"""Before/after DNA experiment: clean pre-simulation export and reproducible damage simulations.

Step 1 (clean export): the approved vault order files (`vaults/vault-N/order.fasta`) are the
source of truth. They are concatenated, in vault order and without reordering, into
`exports/pre_simulation.fasta` with ids `vault-N|{pool}|{index}` (unique across vaults, since
every vault holds its own copy of the manifest). Checksums, counts and the encoder configuration
go to `exports/export_metadata.json`; everything is also bundled in `exports/clean_dna.zip`.
`exports/recovery_bundle.json` is the portable, non-secret metadata a decoder needs besides the
DNA and the keys.

Step 2 (simulation): a run copies the clean export byte-for-byte into its own folder, then sends
every (vault, pool) tube through the bundled codec’s channel simulator with a seed derived from the run seed.
The resulting reads are shuffled and written to `post_simulation_reads.fasta` as
`>read_000001 sample={pool}`. Strand identities and per-read error alignments go to a separate
`ground_truth.tsv`, which the decoder never reads. Runs are immutable: a new run never overwrites
an earlier one or any archive artifact.

These are digital sequences and simulated reads. No DNA is synthesized or sequenced.
"""

from __future__ import annotations

import csv
import io
import json
import math
import secrets
import threading
import time
import traceback
import uuid
import zipfile
from collections import Counter
from dataclasses import replace

import numpy as np
from rapidfuzz.distance import Levenshtein

from . import artifacts, crypto, dna, fasta, manifest, store, vaults
from dna_codec.seeds import is_heldout

EXPORT = "exports"
PRE_FASTA = f"{EXPORT}/pre_simulation.fasta"
EXPORT_META = f"{EXPORT}/export_metadata.json"
BUNDLE = f"{EXPORT}/recovery_bundle.json"
CLEAN_ZIP = f"{EXPORT}/clean_dna.zip"
SIM_FILES = ("input_snapshot.fasta", "post_simulation_reads.fasta", "simulation_metadata.json", "ground_truth.tsv")
DIGITAL_NOTICE = ("Digital DNA sequences designed by the encoder. They have not been physically "
                  "synthesized, stored or sequenced.")
SIM_NOTICE = ("Reads produced by the bundled codec’s sequencing/storage channel simulator, not by a laboratory. "
              "A single simulated trial is not proof of long-term physical recoverability.")
FAR_READ = 0.35  # normalized edit distance above which a read is counted as malformed/chimeric
MAX_SIM_READS = 600_000


# ------------------------------------------------------------------ clean export


def _vault_fastas(job: dict) -> list[tuple[int, str]]:
    paths = sorted(
        (p for p in job["order"]["order_files"] if p.endswith("/order.fasta")),
        key=lambda p: int(p.split("/")[1].removeprefix("vault-")),
    )
    return [(int(p.split("/")[1].removeprefix("vault-")), p) for p in paths]


def build_clean_export(job_id: str, man: dict | None = None) -> dict:
    """Write the immutable clean export of an approved order. Idempotent: an existing export is
    returned unchanged. Requires every vault order file to still be readable."""
    job = store.load(job_id)
    if not job.get("order"):
        raise FileNotFoundError("No approved archive order")
    if (job["order"].get("export") or {}).get("files"):
        return job["order"]["export"]
    records: list[tuple[str, str]] = []
    vault_counts, vault_files = {}, {}
    for v, path in _vault_fastas(job):
        try:
            raw = artifacts.download(job_id, path)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Vault {v} order file is unavailable, so the clean export cannot be rebuilt.") from None
        _, recs = fasta.parse(raw)
        vault_counts[v] = len(recs)
        vault_files[path] = {"sha256": crypto.sha256(raw), "bytes": len(raw)}
        records += [(f"vault-{v}|{r.id}", r.sequence) for r in recs]
    pre = fasta.write(records).encode()

    # Manifest: decode it from the clean manifest strands of the first vault (exact strands, no noise).
    if man is None:
        first = [s for h, s in records if h.split("|")[1] == vaults.MANIFEST_POOL and h.startswith("vault-")]
        n_man = job["order"]["manifest_strands"]
        man = manifest.decode_manifest(first[:n_man])
        if man is None:
            raise ValueError("Manifest could not be decoded from the clean strands")
    settings = job["order"]["settings"]
    lengths = {len(s) for _, s in records}
    gc = [gc_fraction(s) for _, s in records]
    bundle = {
        "format": "lazarus-recovery-bundle-v1",
        "archive_id": job_id,
        "company": job["company"],
        "created": store.now(),
        "bootstrap": {
            "spec": "docs/BOOTSTRAP.md",
            "strand_length": manifest.BOOTSTRAP.strand_length,
            "seed_bases": manifest.BOOTSTRAP.seed_bases,
            "redundancy": manifest.BOOTSTRAP.redundancy,
            "manifest_bytes": manifest.MANIFEST_BYTES,
            "sample_label": vaults.MANIFEST_POOL,
        },
        "manifest": man,
        "manifest_sha256": crypto.sha256(manifest.pack(man)),
        "expected_files": {n: {"sha256": f["sha256"], "bytes": f["bytes"]} for n, f in man["files"].items()},
        "keys_included": False,
        "note": "Contains no encryption keys. Keys are supplied separately as a passphrase-protected key file.",
    }
    bundle_bytes = json.dumps(bundle, indent=2, sort_keys=True).encode()
    meta = {
        "format": "lazarus-clean-export-v1",
        "archive_id": job_id,
        "created": store.now(),
        "notice": DIGITAL_NOTICE,
        "source": "approved vault order files (vaults/vault-N/order.fasta)",
        "header_format": "vault-{N}|{pool}|{index}; identical to the vault files apart from the vault prefix",
        "ordering": "vault 1..N; within a vault the order of its order.fasta (manifest, then pools by id, index order)",
        "encoder_configuration": {
            "approved_settings": settings,
            "pools": {pid: {k: m[k] for k in ("settings", "n_bytes", "n_chunks")} for pid, m in man["pools"].items()},
            "bootstrap_manifest": bundle["bootstrap"],
            "codec": "the bundled codec DNA Fountain encoder (dna_codec.encoder)",
        },
        "counts": {
            "sequences": len(records),
            "per_vault": {str(v): n for v, n in vault_counts.items()},
            "data_strands": job["order"]["data_strands"],
            "manifest_strands_per_vault": job["order"]["manifest_strands"],
            "n_vaults": settings["n_vaults"],
            "strand_lengths": sorted(lengths),
            "total_nucleotides": sum(len(s) for _, s in records),
            "redundancy": settings["redundancy"],
            "gc_mean": round(float(np.mean(gc)), 4) if gc else None,
        },
        "files": {
            PRE_FASTA: {"sha256": crypto.sha256(pre), "bytes": len(pre)},
            BUNDLE: {"sha256": crypto.sha256(bundle_bytes), "bytes": len(bundle_bytes)},
            **vault_files,
        },
    }
    meta_bytes = json.dumps(meta, indent=2, sort_keys=True).encode()
    sums = "".join(f"{v['sha256']}  {p}\n" for p, v in sorted(meta["files"].items()))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("pre_simulation.fasta", pre)
        z.writestr("export_metadata.json", meta_bytes)
        z.writestr("recovery_bundle.json", bundle_bytes)
        z.writestr("SHA256SUMS", sums)
        z.writestr("README.txt", DIGITAL_NOTICE + "\nThis is the clean synthesis design, not sequencing data.\n")
        for path in vault_files:
            z.writestr(path, artifacts.download(job_id, path))
            csv_path = path.replace("order.fasta", "order.csv")
            if csv_path in job["order"]["order_files"]:
                z.writestr(csv_path, artifacts.download(job_id, csv_path))
    zip_bytes = buf.getvalue()
    for path, data in ((PRE_FASTA, pre), (BUNDLE, bundle_bytes), (EXPORT_META, meta_bytes), (CLEAN_ZIP, zip_bytes)):
        artifacts.publish(job_id, path, data)
    export = {
        "created": meta["created"],
        "files": {PRE_FASTA: meta["files"][PRE_FASTA], BUNDLE: meta["files"][BUNDLE],
                  EXPORT_META: {"sha256": crypto.sha256(meta_bytes), "bytes": len(meta_bytes)},
                  CLEAN_ZIP: {"sha256": crypto.sha256(zip_bytes), "bytes": len(zip_bytes)}},
        "counts": meta["counts"],
        "encoder_configuration": meta["encoder_configuration"],
    }
    store.update(job_id, lambda j: j["order"].update(export=export))
    return export


def gc_fraction(s: str) -> float:
    return (s.count("G") + s.count("C")) / max(1, len(s))


def clean_records(job_id: str) -> list[fasta.Record]:
    build_clean_export(job_id)
    return fasta.parse(artifacts.download(job_id, PRE_FASTA))[1]


def inspect(job_id: str, offset: int = 0, limit: int = 50, sample: str | None = None) -> dict:
    every = clean_records(job_id)
    recs = [r for r in every if r.sample == sample] if sample else every
    page = recs[offset : offset + limit]
    return {
        "total": len(recs),
        "offset": offset,
        "samples": sorted({r.sample for r in every}),
        "sequences": [
            {"id": r.id, "vault": fasta.vault_of_id(r.id), "sample": r.sample, "index": int(r.id.rsplit("|", 1)[1]),
             "length": len(r.sequence), "gc": round(gc_fraction(r.sequence), 3), "sequence": r.sequence}
            for r in page
        ],
    }


# ------------------------------------------------------------------ simulation parameters


def _num(params, key, default, lo, hi, cast=float):
    v = params.get(key, default)
    if v is None or v == "":
        return None if default is None else cast(default)
    try:
        v = cast(v)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number") from None
    if isinstance(v, float) and not math.isfinite(v):
        raise ValueError(f"{key} must be finite")
    if not lo <= v <= hi:
        raise ValueError(f"{key} must be between {lo} and {hi}")
    return v


def normalize_params(job: dict, params: dict) -> dict:
    """Validated, fully explicit simulation settings (defaults from the approved design)."""
    order, policy = job["order"], job["policy"]
    tech = params.get("tech") or policy["tech"]
    if tech not in dna.BASE_PROFILES:
        raise ValueError("tech must be nanopore or illumina")
    channel = params.get("channel") or "a"
    if channel not in ("a", "b"):
        raise ValueError("channel must be 'a' (calibrated simulator) or 'b' (red-team simulator)")
    n_vaults = int(order["settings"]["n_vaults"])
    lost = params.get("lost_vaults") or []
    if not isinstance(lost, list) or any(not isinstance(v, int) or not 1 <= v <= n_vaults for v in lost):
        raise ValueError(f"lost_vaults must list vault numbers 1–{n_vaults}")
    seed = params.get("seed")
    seed = secrets.randbelow(10**6) if seed in (None, "") else _num(params, "seed", None, 0, 2**31 - 1, int)
    out = {
        "tech": tech,
        "channel": channel,
        "coverage": _num(params, "coverage", order["settings"]["coverage"], 1, 100),
        "storage_years": _num(params, "storage_years", policy["retention_years"], 0, 1000),
        "seed": seed,
        "lost_vaults": sorted(set(lost)),
    }
    for key in ("sub_rate", "ins_rate", "del_rate"):
        out[key] = _num(params, key, None, 0, 0.3)
    out["dropout_rate"] = _num(params, "dropout_rate", None, 0, 0.95)
    out["decay_per_year"] = _num(params, "decay_per_year", None, 0, 0.05)
    return out


def profile_for(p: dict):
    prof = dna.make_profile(p["tech"], p["storage_years"], p["coverage"])
    overrides = {k: p[k] for k in ("sub_rate", "ins_rate", "del_rate", "dropout_rate", "decay_per_year")
                 if p.get(k) is not None}
    return replace(prof, **overrides) if overrides else prof


def subseed(seed: int, k: int) -> int:
    """Deterministic per-tube seed. Skips the bundled codec’s held-out evaluation range."""
    s = int(np.random.SeedSequence([seed, k]).generate_state(1)[0]) & 0x7FFFFFFF
    return s + 1000 if is_heldout(s) else s


# ------------------------------------------------------------------ simulation


def simulate_reads(records: list[fasta.Record], p: dict):
    """Pure function: clean records + settings -> (fasta_text, truth_rows, metrics).
    Deterministic for a given input and seed."""
    prof = profile_for(p)
    tubes: dict[tuple[int, str], list[tuple[int, fasta.Record]]] = {}
    for i, r in enumerate(records):
        v = fasta.vault_of_id(r.id)
        if v is None or r.sample is None:
            raise ValueError(f"Clean record '{r.id}' is not in vault-N|pool|index form")
        tubes.setdefault((v, r.sample), []).append((i, r))
    reads: list[tuple[str, str, int]] = []  # (sequence, sample, source record index)
    for k, ((v, sample), items) in enumerate(tubes.items()):
        if v in p["lost_vaults"]:
            continue
        clusters = dna.sequence([r.sequence for _, r in items], prof, subseed(p["seed"], k), p["channel"])
        for (i, _), cl in zip(items, clusters):
            reads += [(seq, sample, i) for seq in cl]
        if len(reads) > MAX_SIM_READS:
            raise ValueError(f"Simulation would produce more than {MAX_SIM_READS} reads; lower the coverage.")
    order = np.random.default_rng([p["seed"], 0x5EED]).permutation(len(reads))
    reads = [reads[j] for j in order]

    lines, truth = [], []
    subs = ins = dels = aligned = exact = far = 0
    per_record = np.zeros(len(records), dtype=np.int64)
    for n, (seq, sample, i) in enumerate(reads, start=1):
        rid = f"read_{n:06d}"
        lines.append((f"{rid} sample={sample}", seq))
        ref = records[i].sequence
        per_record[i] += 1
        ops = Levenshtein.editops(ref, seq)
        s = sum(op.tag == "replace" for op in ops)
        a = sum(op.tag == "insert" for op in ops)
        d = sum(op.tag == "delete" for op in ops)
        dist = s + a + d
        is_far = dist > FAR_READ * len(ref)
        far += is_far
        exact += dist == 0
        if not is_far:
            subs, ins, dels, aligned = subs + s, ins + a, dels + d, aligned + len(ref)
        truth.append((rid, records[i].id, sample, dist, s, a, d, int(is_far)))

    logical: dict[tuple[str, str], bool] = {}
    for i, r in enumerate(records):
        key = (r.sample, r.id.rsplit("|", 1)[1])
        logical[key] = logical.get(key, False) or per_record[i] > 0
    surviving = int((per_record > 0).sum())
    lost_by_vault = sum(1 for r in records if fasta.vault_of_id(r.id) in p["lost_vaults"])
    metrics = {
        "clean_sequences": len(records),
        "surviving_sequences": surviving,
        "missing_sequences": len(records) - surviving,
        "missing_from_lost_vaults": lost_by_vault,
        "observed_dropout_rate": round(1 - surviving / max(1, len(records)), 5),
        "logical_strands": len(logical),
        "logical_strands_missing": sum(not v for v in logical.values()),
        "reads": len(reads),
        "duplicate_reads_kept": len(reads) - len({r[0] for r in reads}),
        "mean_reads_per_surviving_sequence": round(len(reads) / max(1, surviving), 3),
        "exact_reads": exact,
        "malformed_or_chimeric_reads": far,
        "observed_error_counts": {"substitutions": subs, "insertions": ins, "deletions": dels,
                                  "aligned_reference_bases": aligned},
        "observed_error_rates_per_base": {
            "substitution": round(subs / max(1, aligned), 6),
            "insertion": round(ins / max(1, aligned), 6),
            "deletion": round(dels / max(1, aligned), 6),
            "total": round((subs + ins + dels) / max(1, aligned), 6),
        },
        "error_measurement": "minimal edit alignment of each read to its source strand (ground truth; "
                             "not available to the decoder). Malformed reads are excluded from the rates.",
        "per_sample_reads": dict(sorted(Counter(r[1] for r in reads).items())),
    }
    return fasta.write(lines), truth, metrics, prof


def _truth_tsv(rows) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter="\t", lineterminator="\n")
    w.writerow(["read_id", "source_sequence_id", "sample", "edit_distance", "substitutions",
                "insertions", "deletions", "malformed"])
    w.writerows(rows)
    return buf.getvalue().encode()


_running: dict[str, threading.Thread] = {}
_sim_slots = threading.BoundedSemaphore(2)


def start_simulation(job_id: str, params: dict, *, background: bool = True) -> dict:
    job = store.load(job_id)
    if not job.get("order"):
        raise FileNotFoundError("Approve an archive order before running a DNA simulation")
    p = normalize_params(job, params)
    profile_for(p)  # validate overrides early (the bundled codec checks rate ranges)
    build_clean_export(job_id)
    sim_id = time.strftime("sim-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    rec = {"id": sim_id, "created": store.now(), "status": "running", "settings": p,
           "notice": SIM_NOTICE, "files": {}, "metrics": None, "error": None}
    store.update(job_id, lambda j: j.setdefault("simulations", []).append(rec))
    store.emit(job_id, "message", "simulator", {"text": f"DNA damage simulation {sim_id} started (seed {p['seed']})."})
    if background:
        t = threading.Thread(target=_run_simulation, args=(job_id, sim_id, p), daemon=True)
        _running[sim_id] = t
        t.start()
    else:
        _run_simulation(job_id, sim_id, p)
    return get_simulation(job_id, sim_id)


def _run_simulation(job_id: str, sim_id: str, p: dict) -> None:
    t0 = time.time()
    try:
        with _sim_slots:
            snapshot = artifacts.download(job_id, PRE_FASTA)
            _, records = fasta.parse(snapshot)
            text, truth, metrics, prof = simulate_reads(records, p)
            reads = text.encode()
            truth_bytes = _truth_tsv(truth)
            job = store.load(job_id)
            meta = {
                "format": "lazarus-simulation-v1",
                "simulation_id": sim_id,
                "archive_id": job_id,
                "created": next(s["created"] for s in job["simulations"] if s["id"] == sim_id),
                "notice": SIM_NOTICE,
                "settings": p,
                "profile": dna.profile_to_dict(prof),
                "simulator": "the bundled codec simulator A (calibrated)" if p["channel"] == "a" else "the bundled codec simulator B (red team)",
                "seed_scheme": "tube k uses numpy SeedSequence([seed, k]); tubes = (vault, pool) in clean FASTA order; "
                               "reads shuffled with default_rng([seed, 0x5EED])",
                "encoder_configuration": job["order"]["export"]["encoder_configuration"],
                "input": {"path": PRE_FASTA, "sha256": crypto.sha256(snapshot), "bytes": len(snapshot)},
                "output": {"path": "post_simulation_reads.fasta", "sha256": crypto.sha256(reads),
                           "bytes": len(reads), "format": "FASTA (no quality scores: the simulator does not model them)"},
                "ground_truth": {"path": "ground_truth.tsv", "sha256": crypto.sha256(truth_bytes),
                                 "note": "simulator-only labels; never given to the decoder"},
                "metrics": metrics,
                "seconds": round(time.time() - t0, 2),
            }
            meta_bytes = json.dumps(meta, indent=2, sort_keys=True).encode()
            files = {}
            for name, data in (("input_snapshot.fasta", snapshot), ("post_simulation_reads.fasta", reads),
                               ("ground_truth.tsv", truth_bytes), ("simulation_metadata.json", meta_bytes)):
                path = f"simulations/{sim_id}/{name}"
                artifacts.publish(job_id, path, data)
                files[name] = {"path": path, "sha256": crypto.sha256(data), "bytes": len(data)}

        def done(j):
            s = next(s for s in j["simulations"] if s["id"] == sim_id)
            s.update(status="complete", files=files, metrics=metrics, seconds=meta["seconds"],
                     profile=meta["profile"], input_sha256=meta["input"]["sha256"],
                     output_sha256=meta["output"]["sha256"])

        store.update(job_id, done)
        store.emit(job_id, "message", "simulator", {"text": f"Simulation {sim_id}: {metrics['reads']} reads, "
                                                    f"{metrics['missing_sequences']} of {metrics['clean_sequences']} sequences missing."})
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        traceback.print_exc()

        def failed(j):
            s = next(s for s in j["simulations"] if s["id"] == sim_id)
            s.update(status="failed", error=msg)

        store.update(job_id, failed)
    finally:
        _running.pop(sim_id, None)


def get_simulation(job_id: str, sim_id: str) -> dict:
    for s in store.load(job_id).get("simulations", []):
        if s["id"] == sim_id:
            return s
    raise FileNotFoundError("Simulation not found")


def compare(job_id: str, sim_id: str, limit: int = 8, reads_per_strand: int = 3) -> dict:
    """Side-by-side clean vs damaged reads, from the run's own snapshot and ground truth."""
    sim = get_simulation(job_id, sim_id)
    if sim["status"] != "complete":
        raise FileNotFoundError("Simulation is not complete")
    base = f"simulations/{sim_id}"
    _, clean = fasta.parse(artifacts.download(job_id, f"{base}/input_snapshot.fasta"))
    _, reads = fasta.parse(artifacts.download(job_id, f"{base}/post_simulation_reads.fasta"))
    by_id = {r.id: r.sequence for r in reads}
    rows = list(csv.DictReader(io.StringIO(artifacts.download(job_id, f"{base}/ground_truth.tsv").decode()),
                               delimiter="\t"))
    per_source: dict[str, list[dict]] = {}
    for row in rows:
        per_source.setdefault(row["source_sequence_id"], []).append(row)
    clean_by_id = {r.id: r.sequence for r in clean}
    data_ids = [r.id for r in clean if r.sample != vaults.MANIFEST_POOL]
    missing = [i for i in data_ids if i not in per_source]
    present = [i for i in data_ids if i in per_source]
    step = max(1, len(present) // max(1, limit - min(2, len(missing))))
    chosen = present[::step][: limit - min(2, len(missing))] + missing[:2]
    out = []
    for cid in chosen:
        ref = clean_by_id[cid]
        entry = {"id": cid, "clean": ref, "reads": [], "missing": cid not in per_source}
        for row in per_source.get(cid, [])[:reads_per_strand]:
            seq = by_id[row["read_id"]]
            entry["reads"].append({
                "read_id": row["read_id"], "sequence": seq,
                "edit_distance": int(row["edit_distance"]), "substitutions": int(row["substitutions"]),
                "insertions": int(row["insertions"]), "deletions": int(row["deletions"]),
                "malformed": row["malformed"] == "1",
                "segments": [{"op": t, "clean": ref[a:b], "read": seq[c:d]}
                             for t, a, b, c, d in Levenshtein.opcodes(ref, seq)],
            })
        entry["reads_total"] = len(per_source.get(cid, []))
        out.append(entry)
    return {"simulation_id": sim_id, "metrics": sim["metrics"], "strands": out, "notice": SIM_NOTICE}


def mark_interrupted(job_id: str) -> None:
    def fix(j):
        for s in j.get("simulations", []):
            if s["status"] == "running":
                s.update(status="failed", error="Interrupted by a server restart; start a new simulation.")
    store.update(job_id, fix)
