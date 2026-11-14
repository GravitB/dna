"""Standalone DNA decoder: FASTA/FASTQ reads in, SHA-256-verified files out.

The decoder receives only:
  * the uploaded (or explicitly selected) read file,
  * non-secret recovery metadata (a recovery bundle; optional, the manifest is read from DNA first),
  * a key lookup (the archive's key store in Mode A, a passphrase-protected key file in Mode B).
It never opens an archive's uploads, staging pools, restored files, the clean export (unless that is
the file the user chose to decode) or simulator ground truth.

Pipeline: parse -> group reads by sample label (tube/pool) -> decode the bootstrap manifest from the
MANIFEST reads -> per pool: reference-free clustering -> consensus (majority vote and/or Erbgut's CNN
PolishDecoder) -> Fountain recovery -> reassemble the encrypted stream -> AES-256-GCM decrypt ->
zstd decompress -> SHA-256 check against the manifest (and the recovery bundle if supplied).

Laboratory reads: several files may be supplied, each optionally assigned to a sample (tube) by
the user's sample sheet; sample ids resolve to pools through the Recovery Package's sample sheet.
FASTQ reads below a mean Phred threshold are filtered out; consensus itself ignores per-base
qualities (majority vote and the CNN take bases only). Reads sequenced from the reverse strand are
handled by checking each consensus strand's CRC in both orientations.

Verdicts: PASS (every expected file hash matches), PARTIAL (some do), FAIL (none do),
INCOMPLETE (metadata or keys needed to finish were unavailable).

Importable without any server state: sessions (which use the job store) import it lazily.
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import threading
import time
import traceback
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import clustering, crypto, dna, fasta, manifest
from dnacodec.encoder import _Layout  # strand CRC check only, for reporting valid consensus strands

DECODERS = ("baseline", "polish")
KEYFILE_FORMAT = "lazarus-keyfile-v1"
MIN_PASSPHRASE = 10
VERDICT_TEXT = {
    "PASS": "All expected file hashes match.",
    "PARTIAL": "Some files were recovered with matching hashes; others were not.",
    "FAIL": "No file was recovered with a matching hash.",
    "INCOMPLETE": "Required metadata or keys were unavailable, so recovery could not be completed.",
}
DISCLAIMER = ("This report describes one decoding attempt of digital/simulated DNA reads. A single passing "
              "trial is not an estimate of reliability and not proof of long-term physical DNA recoverability. "
              "No DNA was synthesized or sequenced.")
LAB_DISCLAIMER = ("This report describes one decoding attempt of reads supplied as laboratory-format FASTA/FASTQ. "
                  "Lazarus cannot verify where the reads came from. Physical DNA recovery is only demonstrated "
                  "when the reads come from sequencing synthesized, Lazarus-encoded DNA, which this report "
                  "does not establish on its own.")
EVIDENCE = {
    "clean_design": "Clean design FASTA (no damage): checks metadata, keys and decoding only.",
    "simulated_reads": "Simulated sequencing reads (Erbgut channel model): a digital experiment, not a lab result.",
    "lab_format_reads": "Laboratory-format reads (demultiplexed FASTA/FASTQ supplied by the user): format "
                        "compatibility; physical recovery is validated only for reads from synthesized DNA.",
    "unknown": "Reads of unstated origin.",
}
DEFAULT_MIN_QUALITY = 7.0
_COMP = str.maketrans("ACGT", "TGCA")


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def revcomp(s: str) -> str:
    return s.translate(_COMP)[::-1]


# ------------------------------------------------------------------ key file


def _kdf(salt: bytes) -> Scrypt:
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1)


def make_keyfile(archive_id: str, keys: dict[str, bytes], passphrase: str) -> bytes:
    """Passphrase-protected key file (scrypt + AES-256-GCM). Raw keys never leave in clear text."""
    if len(passphrase or "") < MIN_PASSPHRASE:
        raise ValueError(f"Use a passphrase of at least {MIN_PASSPHRASE} characters.")
    salt, nonce = os.urandom(16), os.urandom(12)
    body = json.dumps({k: base64.b64encode(v).decode() for k, v in keys.items()}).encode()
    aad = f"{KEYFILE_FORMAT}:{archive_id}".encode()
    ct = AESGCM(_kdf(salt).derive(passphrase.encode())).encrypt(nonce, body, aad)
    return json.dumps({
        "format": KEYFILE_FORMAT, "archive_id": archive_id, "key_ids": sorted(keys),
        "kdf": {"name": "scrypt", "n": 2**15, "r": 8, "p": 1, "salt": base64.b64encode(salt).decode()},
        "cipher": "AES-256-GCM", "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ct).decode(),
    }, indent=2).encode()


def open_keyfile(data: bytes, passphrase: str) -> tuple[str, dict[str, bytes]]:
    try:
        doc = json.loads(data)
        if doc.get("format") != KEYFILE_FORMAT:
            raise ValueError()
        salt = base64.b64decode(doc["kdf"]["salt"])
        aad = f"{KEYFILE_FORMAT}:{doc['archive_id']}".encode()
        ct, nonce = base64.b64decode(doc["ciphertext"]), base64.b64decode(doc["nonce"])
    except (ValueError, KeyError, TypeError):
        raise ValueError("Not a Lazarus key file.") from None
    try:
        body = AESGCM(_kdf(salt).derive((passphrase or "").encode())).decrypt(nonce, ct, aad)
    except InvalidTag:
        raise ValueError("Wrong passphrase for this key file.") from None
    keys = {k: base64.b64decode(v) for k, v in json.loads(body).items()}
    return doc["archive_id"], keys


# ------------------------------------------------------------------ capabilities


def polish_status() -> tuple[bool, str | None]:
    if not Path(dna.POLISH_CHECKPOINT).exists():
        return False, "CNN checkpoint (checkpoints/polish/polish.pt) not found"
    try:
        import torch  # noqa: F401
    except ImportError:
        return False, "PyTorch is not installed"
    return True, None


# ------------------------------------------------------------------ pipeline


@dataclass
class ReadInput:
    """One sequencing file. `sample` assigns every read in it to a sample/tube (from the user's
    lab sample sheet); otherwise each read's own `sample=` header label is used."""

    name: str
    data: bytes
    sample: str | None = None


@dataclass
class DecodeRequest:
    fasta_bytes: bytes
    fasta_name: str
    decoders: list[str]
    key_for: Callable[[str], bytes | None]
    key_source: str
    mode: str  # "existing_archive" | "independent_import" | "package_recovery" | ...
    bundle: dict | None = None
    expected_archive_id: str | None = None
    simulation: dict | None = None
    archive_context: dict = field(default_factory=dict)
    inputs: list[ReadInput] | None = None  # several files (lab runs); overrides fasta_bytes
    sample_map: dict[str, str] = field(default_factory=dict)  # lab sample id -> pool id
    lab: bool = False  # lenient laboratory parsing (gzip, N reads dropped, long reads dropped)
    min_mean_quality: float | None = None  # FASTQ read filter; None -> DEFAULT_MIN_QUALITY in lab mode
    evidence: str | None = None  # key of EVIDENCE; inferred when None


def _valid_strands(strands, settings) -> int:
    try:
        layout = _Layout(settings)
    except ValueError:
        return 0
    return sum(layout.parse(s) is not None for s in strands if s)


def orient(strands: list, settings) -> tuple[list, int]:
    """Real sequencers read either strand of the duplex. A consensus built from reverse-strand
    reads fails the strand CRC as-is but passes after reverse-complementing; nothing else is
    changed. Returns (strands, number flipped)."""
    try:
        layout = _Layout(settings)
    except ValueError:
        return strands, 0
    out, flipped = [], 0
    for s in strands:
        if s and layout.parse(s) is None:
            rc = revcomp(s)
            if layout.parse(rc) is not None:
                out.append(rc)
                flipped += 1
                continue
        out.append(s)
    return out, flipped


UNLABELED_HELP = (
    "Reads carry no sample (tube) assignment. Lazarus archives so far are synthesized without "
    "in-molecule primers or barcodes, so reads of different pools cannot be told apart by sequence, "
    "and Lazarus will not guess. Supply the sequencing facility's demultiplexed files, one per physical "
    "sample, with a sample sheet (file, sample_id) whose sample ids appear in the Recovery Package's "
    "sequencing/sample_sheet.csv, or label each read 'sample=<pool>' in its header.")


def run(req: DecodeRequest, progress: Callable[[str, str, str], None] = lambda *a: None):
    """Returns (report, recovered) where recovered = {file name: verified plaintext bytes}."""
    t0 = time.time()
    missing: list[str] = []
    warnings: list[str] = []
    progress("parse", "running", "Parsing and validating reads")
    inputs = req.inputs or [ReadInput(req.fasta_name, req.fasta_bytes)]
    min_q = req.min_mean_quality if req.min_mean_quality is not None else DEFAULT_MIN_QUALITY  # FASTQ only
    by_sample: dict[str, list[str]] = defaultdict(list)
    unlabeled = low_quality = 0
    unknown_samples: set[str] = set()
    files_info, lengths, formats = [], [], set()
    lab_stats = fasta.ReadStats()
    total_records = 0
    for inp in inputs:
        fmt, records = fasta.parse(inp.data, lenient=req.lab, stats=lab_stats if req.lab else None)
        formats.add(fmt)
        total_records += len(records)
        kept = 0
        for r in records:
            if min_q is not None and r.quality is not None and r.mean_quality < min_q:
                low_quality += 1
                continue
            label = inp.sample or r.sample
            if label is None:
                unlabeled += 1
                continue
            pool = req.sample_map.get(label, label)
            if req.sample_map and label not in req.sample_map and label not in req.sample_map.values():
                unknown_samples.add(label)
            by_sample[pool].append(r.sequence)
            lengths.append(len(r.sequence))
            kept += 1
        files_info.append({"filename": inp.name, "format": fmt, "sha256": crypto.sha256(inp.data),
                           "bytes": len(inp.data), "records": len(records), "used": kept,
                           "assigned_sample": inp.sample})
    fmt = formats.pop() if len(formats) == 1 else "mixed"
    first = files_info[0]
    input_info = {
        "filename": first["filename"] if len(files_info) == 1 else f"{len(files_info)} files",
        "format": fmt, "sha256": first["sha256"] if len(files_info) == 1 else None,
        "bytes": sum(f["bytes"] for f in files_info), "records": total_records,
        "files": files_info,
        "samples": {k: len(v) for k, v in sorted(by_sample.items())}, "unlabeled_records": unlabeled,
        "length": ({"min": min(lengths), "max": max(lengths), "mean": round(sum(lengths) / len(lengths), 2)}
                   if lengths else None),
        "quality_scores": (
            "none (FASTA)" if fmt == "fasta" else
            f"used for read filtering only: reads with mean Phred < {min_q:g} dropped ({low_quality}); "
            "consensus ignores per-base qualities" if min_q is not None else
            "preserved but not used (no quality filter set); consensus ignores per-base qualities"),
        "low_quality_reads_dropped": low_quality,
        **(lab_stats.as_dict() if req.lab else {}),
        "lab_mode": req.lab,
    }
    if unknown_samples:
        warnings.append(f"Sample ids not in the sample sheet were used as pool names: {', '.join(sorted(unknown_samples))}.")
    if unlabeled and not by_sample:
        missing.append("sample assignment: " + UNLABELED_HELP)
    elif unlabeled:
        warnings.append(f"{unlabeled} reads carry no sample (pool) label and were not used. " + UNLABELED_HELP)
    progress("parse", "done", f"{total_records} {fmt.upper()} records in {len(files_info)} file(s), "
                              f"{len(by_sample)} samples")

    ok_polish, why_polish = polish_status()
    decoders = []
    unavailable = {}
    for d in req.decoders:
        if d == "polish" and not ok_polish:
            unavailable[d] = why_polish
        else:
            decoders.append(d)
    if not decoders:
        missing.append(f"decoder: {'; '.join(f'{k}: {v}' for k, v in unavailable.items())}")
    per_dec = {d: {"available": True, "pools": {}, "files": {}, "seconds": 0.0} for d in decoders}
    per_dec.update({d: {"available": False, "reason": why} for d, why in unavailable.items()})

    # ---- 1. manifest via the bootstrap spec
    progress("manifest", "running", "Decoding the DNA bootstrap manifest")
    man, man_source = None, None
    man_reads = by_sample.get(manifest.MANIFEST_POOL, [])
    m_clusters, m_stats = clustering.cluster_reads(man_reads, manifest.BOOTSTRAP.strand_length)
    for d in decoders:
        t = time.time()
        cons = dna.decode_clusters(m_clusters, manifest.BOOTSTRAP.strand_length, d) if m_clusters else []
        cons, flipped = orient(cons, manifest.BOOTSTRAP)
        got = manifest.decode_manifest(cons) if cons else None
        per_dec[d]["manifest"] = {"recovered": got is not None, "clusters": len(m_clusters),
                                  "valid_strands": _valid_strands(cons, manifest.BOOTSTRAP),
                                  "reverse_complement_strands": flipped}
        per_dec[d]["seconds"] += time.time() - t
        if got is not None and man is None:
            man, man_source = got, "dna"
    bundle_man = (req.bundle or {}).get("manifest")
    if man is not None and bundle_man is not None and man != bundle_man:
        warnings.append("The manifest decoded from DNA differs from the supplied recovery bundle; "
                        "expected hashes from both are enforced.")
    if man is None and bundle_man is not None:
        man, man_source = bundle_man, "bundle"
        warnings.append("Manifest could not be decoded from DNA; using the recovery bundle's copy.")
    if man is None:
        missing.append("archive manifest: not decodable from the MANIFEST reads"
                       + ("" if man_reads else " (no reads labeled sample=MANIFEST)")
                       + " and no recovery bundle was supplied")
    progress("manifest", "done" if man else "failed",
             f"Manifest from {man_source}" if man else "Manifest unavailable")

    archive_id = (man or {}).get("archive_id") or (req.bundle or {}).get("archive_id")
    if man and req.expected_archive_id and archive_id and archive_id != req.expected_archive_id:
        missing.append(f"matching archive: these reads belong to archive {archive_id}, "
                       f"not the selected archive {req.expected_archive_id}")
        man = None

    # ---- 2. pools
    pool_bytes: dict[str, dict[str, bytes | None]] = {d: {} for d in decoders}
    cluster_stats = {manifest.MANIFEST_POOL: m_stats}
    if man and decoders:
        pools = sorted(man["pools"].items())
        for n, (pid, meta_d) in enumerate(pools, 1):
            progress("pools", "running", f"Clustering and decoding pool {n} of {len(pools)} ({pid})")
            meta = dna.meta_from_dict(meta_d)
            L = meta.settings.strand_length
            written = int(-(-meta.n_chunks * (1 + meta.settings.redundancy) // 1))
            clusters, st = clustering.cluster_reads(by_sample.get(pid, []), L)
            cluster_stats[pid] = st
            for d in decoders:
                t = time.time()
                cons = dna.decode_clusters(clusters, L, d) if clusters else []
                cons, flipped = orient(cons, meta.settings)
                data = dna.recover_bytes(cons, meta) if cons else None
                pool_bytes[d][pid] = data
                per_dec[d]["pools"][pid] = {
                    "reads": len(by_sample.get(pid, [])), "clusters": len(clusters),
                    "strands_written": written, "reconstructed_strands": len(cons),
                    "valid_strands": _valid_strands(cons, meta.settings),
                    "reverse_complement_strands": flipped,
                    "chunks_needed": meta.n_chunks, "recovered": data is not None,
                }
                per_dec[d]["seconds"] += time.time() - t
            if not by_sample.get(pid):
                warnings.append(f"No reads labeled sample={pid}.")
        progress("pools", "done", f"{len(pools)} pools processed")

    # ---- 3. files
    progress("files", "running", "Decrypting, decompressing and verifying SHA-256")
    expected_extra = (req.bundle or {}).get("expected_files") or {}
    files_out, recovered = [], {}
    if man:
        offsets = {pid: int(m.get("offset", 0)) for pid, m in man["pools"].items()}
        for name, f in sorted(man["files"].items()):
            expected = f["sha256"]
            extra = expected_extra.get(name, {}).get("sha256")
            entry = {"name": name, "expected_sha256": expected, "expected_bytes": f["bytes"],
                     "key_id": f["key_id"], "pools": f["pools"], "verified": False, "decoders": {}}
            if extra and extra != expected:
                entry["bundle_sha256"] = extra
            key, key_error = None, None
            try:
                key = req.key_for(f["key_id"])
            except Exception:  # noqa: BLE001  never surface key material or store internals
                key = None
            if key is None:
                key_error = f"key {f['key_id']} was not supplied ({req.key_source})"
            for d in decoders:
                res = {"status": "dna_failed", "reason": None}
                if not all(pool_bytes[d].get(p) is not None for p in f["pools"]):
                    lost = [p for p in f["pools"] if pool_bytes[d].get(p) is None]
                    res["reason"] = f"pool(s) not recovered from DNA: {', '.join(lost)}"
                else:
                    start = offsets[f["pools"][0]]
                    span = b"".join(pool_bytes[d][p] for p in f["pools"])
                    ct = span[f["offset"] - start : f["offset"] - start + f["cipher_bytes"]]
                    res["ciphertext_recovered"] = len(ct) == f["cipher_bytes"]
                    if key is None:
                        res.update(status="key_missing", reason=key_error)
                    else:
                        try:
                            plain = crypto.unseal(bytes.fromhex(f["nonce"]), ct, key)
                        except InvalidTag:
                            res.update(status="decryption_failed",
                                       reason="AES-GCM authentication failed (wrong key or corrupted ciphertext)")
                        except Exception:  # noqa: BLE001
                            res.update(status="decompression_failed", reason="zstd decompression failed")
                        else:
                            actual = crypto.sha256(plain)
                            ok = actual == expected and (not extra or extra == actual)
                            res.update(status="verified" if ok else "hash_mismatch", actual_sha256=actual,
                                       actual_bytes=len(plain),
                                       reason=None if ok else "SHA-256 does not match the expected hash")
                            if ok and name not in recovered:
                                recovered[name] = plain
                                entry.update(verified=True, decoder=d, actual_sha256=actual,
                                             actual_bytes=len(plain))
                entry["decoders"][d] = res
                per_dec[d]["files"][name] = res["status"]
            if not entry["verified"]:
                statuses = [r["status"] for r in entry["decoders"].values()]
                entry["status"] = ("key_missing" if "key_missing" in statuses else
                                   next((s for s in ("hash_mismatch", "decryption_failed", "decompression_failed")
                                         if s in statuses), "dna_failed"))
                entry["reason"] = next((r["reason"] for r in entry["decoders"].values() if r["reason"]), None)
                last = next(iter(entry["decoders"].values()), {})
                if "actual_sha256" in last:
                    entry["actual_sha256"] = last["actual_sha256"]
            else:
                entry["status"] = "verified"
            if key_error:
                missing.append(key_error)
            files_out.append(entry)
        for name in sorted(set(expected_extra) - set(man["files"])):
            files_out.append({"name": name, "expected_sha256": expected_extra[name]["sha256"],
                              "verified": False, "status": "not_in_manifest",
                              "reason": "listed in the recovery bundle but not in the manifest", "decoders": {}})
    progress("files", "done", f"{len(recovered)} of {len(files_out)} files verified")

    n_ok = sum(f["verified"] for f in files_out)
    if files_out and n_ok == len(files_out):
        verdict = "PASS"
    elif missing:
        verdict = "INCOMPLETE"
    elif n_ok:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    for d in decoders:
        per_dec[d]["seconds"] = round(per_dec[d]["seconds"], 2)
        fs = per_dec[d]["files"]
        per_dec[d]["verdict"] = ("PASS" if fs and all(v == "verified" for v in fs.values()) else
                                 "PARTIAL" if any(v == "verified" for v in fs.values()) else
                                 "INCOMPLETE" if not man or any(v == "key_missing" for v in fs.values()) else "FAIL")
    pools_meta = (man or {}).get("pools", {})
    evidence = _evidence(req)
    report = {
        "format": "lazarus-verification-report-v1",
        "mode": req.mode,
        "verdict": verdict,
        "verdict_text": VERDICT_TEXT[verdict],
        "missing": sorted(set(missing)),
        "warnings": warnings,
        "archive": {
            "archive_id": archive_id,
            "company": (man or {}).get("company"),
            "files": [{"name": n, "bytes": f["bytes"], "sha256": f["sha256"]} for n, f in sorted((man or {}).get("files", {}).items())],
            "encoder_configuration": {pid: m["settings"] for pid, m in pools_meta.items()},
            "data_strands_written": sum(int(-(-m["n_chunks"] * (1 + m["settings"]["redundancy"]) // 1)) for m in pools_meta.values()),
            "n_vaults": (man or {}).get("n_vaults"),
            "channel": (man or {}).get("channel"),
            **req.archive_context,
        },
        "input": input_info,
        "simulation": req.simulation,
        "recovery": {
            "decoders_requested": req.decoders,
            "key_source": req.key_source,
            "manifest_recovered_from_dna": man_source == "dna",
            "manifest_source": man_source,
            "clustering": {"method": "reference-free k-mer + edit-distance clustering (lazarus.clustering)",
                           "per_sample": cluster_stats},
            "decoders": per_dec,
            "reconstructed_strands": {d: sum(p["reconstructed_strands"] for p in per_dec[d]["pools"].values())
                                      for d in decoders},
            "seconds": round(time.time() - t0, 2),
        },
        "files": files_out,
        "trial_scope": "single decoding trial",
        "evidence": {"level": evidence, "text": EVIDENCE[evidence], "physical_dna_validated": False},
        "disclaimer": LAB_DISCLAIMER if evidence == "lab_format_reads" else DISCLAIMER,
    }
    return report, recovered


def _evidence(req: DecodeRequest) -> str:
    if req.evidence in EVIDENCE:
        return req.evidence
    if req.simulation:
        return "simulated_reads"
    if req.lab:
        return "lab_format_reads"
    return "unknown"


# ------------------------------------------------------------------ report rendering


def render_html(r: dict) -> str:
    e = lambda v: html.escape(str(v))  # noqa: E731
    color = {"PASS": "#0a7a3a", "PARTIAL": "#a86400", "FAIL": "#b00020", "INCOMPLETE": "#555"}[r["verdict"]]
    a, rec, sim = r["archive"], r["recovery"], r.get("simulation") or {}
    files = "".join(
        f"<tr><td>{e(f['name'])}</td><td>{e(f.get('expected_bytes', ''))}</td><td><code>{e(f.get('expected_sha256', ''))}</code></td>"
        f"<td><code>{e(f.get('actual_sha256', '—'))}</code></td><td>{e(f.get('decoder', '—'))}</td>"
        f"<td><b>{'MATCH' if f['verified'] else 'NO MATCH'}</b> {e(f.get('reason') or '')}</td></tr>" for f in r["files"])
    decs = ""
    for d, v in rec["decoders"].items():
        if not v.get("available"):
            decs += f"<tr><td>{e(d)}</td><td colspan=5>unavailable: {e(v.get('reason'))}</td></tr>"
            continue
        pools = v["pools"]
        decs += (f"<tr><td>{e(d)}</td><td>{e(v['verdict'])}</td><td>{'yes' if v.get('manifest', {}).get('recovered') else 'no'}</td>"
                 f"<td>{sum(p['recovered'] for p in pools.values())}/{len(pools)}</td>"
                 f"<td>{sum(p['valid_strands'] for p in pools.values())}</td><td>{v['seconds']}s</td></tr>")
    m = sim.get("metrics") or {}
    rates = m.get("observed_error_rates_per_base") or {}
    sim_html = (
        f"<p>Simulation <code>{e(sim.get('simulation_id'))}</code> · profile {e(sim.get('settings', {}).get('tech'))} · "
        f"channel {e(sim.get('settings', {}).get('channel'))} · seed {e(sim.get('settings', {}).get('seed'))} · "
        f"coverage {e(sim.get('settings', {}).get('coverage'))} · storage {e(sim.get('settings', {}).get('storage_years'))} years</p>"
        f"<p>Clean sequences {e(m.get('clean_sequences'))} · damaged reads {e(m.get('reads'))} · missing sequences "
        f"{e(m.get('missing_sequences'))} · observed errors/base: sub {e(rates.get('substitution'))}, ins "
        f"{e(rates.get('insertion'))}, del {e(rates.get('deletion'))}</p>"
        f"<pre>{e(json.dumps(sim.get('settings'), indent=1))}</pre>"
    ) if sim else "<p>No linked simulation. The reads were decoded without simulator context.</p>"
    trials = a.get("trial_history")
    trial_html = (f"<p>Independent decoded simulation trials for this archive: {trials['passed']} PASS of {trials['trials']} "
                  f"(distinct simulation runs). This is a small-sample estimate, not a guarantee.</p>") if trials else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>DNA Verification Report</title>
<style>body{{font:14px/1.5 -apple-system,Segoe UI,sans-serif;max-width:960px;margin:40px auto;padding:0 16px;color:#111;background:#fff}}
table{{border-collapse:collapse;width:100%;margin:8px 0 20px}}td,th{{border:1px solid #ddd;padding:4px 8px;text-align:left;vertical-align:top}}
code{{font-size:11px;word-break:break-all}}.v{{font-size:24px;font-weight:700;color:{color}}}small{{color:#666}}</style></head><body>
<h1>Lazarus DNA Verification Report</h1>
<p><b>Evidence: {e((r.get('evidence') or {}).get('text', 'digital experiment'))}</b> {e(r['disclaimer'])}</p>
<p class="v">{e(r['verdict'])}</p><p>{e(r['verdict_text'])}</p>
{''.join(f'<p>Missing: {e(x)}</p>' for x in r['missing'])}{''.join(f'<p><small>Note: {e(x)}</small></p>' for x in r['warnings'])}
<h2>Archive details</h2>
<p>Archive {e(a.get('archive_id'))} · {e(a.get('company'))} · {e(a.get('n_vaults'))} vaults ·
{e(a.get('data_strands_written'))} data strands written · session {e(r.get('session_id'))} · {e(r.get('created'))}</p>
<pre>{e(json.dumps(a.get('encoder_configuration'), indent=1))}</pre>
<h2>Input</h2><p>{e(r['input']['filename'])} · {e(r['input']['format'])} · {e(r['input']['records'])} records ·
quality: {e(r['input'].get('quality_scores'))}</p>
<ul>{''.join(f"<li>{e(f['filename'])} · {e(f['format'])} · {e(f['records'])} records ({e(f['used'])} used)"
             f"{' · sample ' + e(f['assigned_sample']) if f.get('assigned_sample') else ''} · SHA-256 <code>{e(f['sha256'])}</code></li>"
             for f in r['input'].get('files', []))}</ul>
<h2>DNA simulation results</h2>{sim_html}
<h2>Recovery results</h2>
<p>Decoders requested: {e(', '.join(rec['decoders_requested']))} · manifest recovered from DNA:
{'yes' if rec['manifest_recovered_from_dna'] else 'no'} (source: {e(rec['manifest_source'])}) · keys: {e(rec['key_source'])} ·
processing time {e(rec['seconds'])}s</p>
<table><tr><th>Decoder</th><th>Verdict</th><th>Manifest</th><th>Pools recovered</th><th>Valid strands</th><th>Time</th></tr>{decs}</table>
<table><tr><th>File</th><th>Bytes</th><th>Expected SHA-256</th><th>Actual SHA-256</th><th>Decoder</th><th>Result</th></tr>{files}</table>
<h2>Final verdict: {e(r['verdict'])}</h2>{trial_html}
<p><small>Codec, simulators, majority-vote and CNN decoders: Erbgut (HackMIT 2026). Read clustering: Lazarus.
Success requires byte-exact SHA-256 equality of reconstructed files; similar-looking DNA is never counted as recovery.</small></p>
</body></html>"""


# ------------------------------------------------------------------ sessions (local)


_SID = re.compile(r"^dec-\d{8}-\d{6}-[0-9a-f]{6}$")
_lock = threading.RLock()
_slots = threading.BoundedSemaphore(1)


def sessions_dir() -> Path:
    from . import store

    return store.JOBS_DIR / "_decoder_sessions"


def session_dir(sid: str) -> Path:
    if not _SID.match(sid or ""):
        raise FileNotFoundError("Decoder session not found")
    return sessions_dir() / sid


def load_session(sid: str) -> dict:
    p = session_dir(sid) / "session.json"
    if not p.exists():
        raise FileNotFoundError("Decoder session not found")
    with _lock:
        return json.loads(p.read_text())


def _save(sid: str, doc: dict) -> None:
    with _lock:
        p = session_dir(sid) / "session.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=2))
        tmp.replace(p)


def _update(sid: str, fn) -> dict:
    with _lock:
        doc = load_session(sid)
        fn(doc)
        _save(sid, doc)
        return doc


def list_sessions(limit: int = 30) -> list[dict]:
    d = sessions_dir()
    if not d.exists():
        return []
    out = []
    for p in sorted(d.iterdir(), reverse=True)[:limit]:
        try:
            s = load_session(p.name)
        except (FileNotFoundError, ValueError):
            continue
        out.append({k: s.get(k) for k in ("id", "created", "status", "mode", "archive_id", "simulation_id",
                                         "verdict", "fasta_name")})
    return out


def start(req: DecodeRequest, *, job_id: str | None = None, background: bool = True,
          on_done: Callable[[dict, dict], None] | None = None) -> dict:
    sid = time.strftime("dec-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    d = session_dir(sid)
    d.mkdir(parents=True)
    _save(sid, {
        "id": sid, "created": _now(), "status": "queued", "mode": req.mode, "job_id": job_id,
        "archive_id": req.expected_archive_id, "simulation_id": (req.simulation or {}).get("simulation_id"),
        "fasta_name": req.fasta_name, "decoders": req.decoders, "steps": [], "verdict": None,
        "error": None, "files": [],
    })
    if background:
        threading.Thread(target=_execute, args=(sid, req, on_done), daemon=True).start()
    else:
        _execute(sid, req, on_done)
    return load_session(sid)


def _execute(sid: str, req: DecodeRequest, on_done) -> None:
    def progress(step, status, detail):
        def fn(doc):
            doc["status"] = "running"
            for s in doc["steps"]:
                if s["step"] == step:
                    s.update(status=status, detail=detail)
                    return
            doc["steps"].append({"step": step, "status": status, "detail": detail})
        _update(sid, fn)

    try:
        with _slots:
            report, recovered = run(req, progress)
        report.update(session_id=sid, created=load_session(sid)["created"])
        d = session_dir(sid)
        (d / "recovered").mkdir(exist_ok=True)
        stored = []
        for i, (name, data) in enumerate(sorted(recovered.items())):
            (d / "recovered" / f"{i:03d}").write_bytes(data)
            stored.append({"index": i, "name": name, "bytes": len(data), "sha256": crypto.sha256(data)})
        (d / "verification_report.json").write_text(json.dumps(report, indent=2))
        (d / "verification_report.html").write_text(render_html(report), encoding="utf-8")
        _update(sid, lambda doc: doc.update(status="complete", verdict=report["verdict"], files=stored,
                                            summary=summarize(report)))
        if on_done:
            try:
                on_done(load_session(sid), {"report": report, "recovered": recovered})
            except Exception as e:  # noqa: BLE001  the decode itself finished; record the storage problem
                traceback.print_exc()
                _update(sid, lambda doc: doc.update(storage_error=f"{type(e).__name__}: archive record not updated"))
    except fasta.FastaError as e:
        _update(sid, lambda doc: doc.update(status="failed", error=str(e)))
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        _update(sid, lambda doc: doc.update(status="failed", error=f"{type(e).__name__}: decoding stopped"))


def mark_interrupted() -> None:
    d = sessions_dir()
    if not d.exists():
        return
    for p in d.iterdir():
        try:
            s = load_session(p.name)
        except (FileNotFoundError, ValueError):
            continue
        if s["status"] in ("queued", "running"):
            _update(p.name, lambda doc: doc.update(status="failed", error="Interrupted by a server restart; run it again."))


def summarize(report: dict) -> dict:
    return {
        "verdict": report["verdict"],
        "verdict_text": report["verdict_text"],
        "missing": report["missing"],
        "warnings": report["warnings"],
        "manifest_source": report["recovery"]["manifest_source"],
        "seconds": report["recovery"]["seconds"],
        "files": [{k: f.get(k) for k in ("name", "verified", "status", "reason", "expected_sha256",
                                         "actual_sha256", "expected_bytes", "decoder")} for f in report["files"]],
        "decoders": {d: ({k: v.get(k) for k in ("verdict", "seconds")} |
                         {"pools_recovered": sum(p["recovered"] for p in v["pools"].values()),
                          "pools": len(v["pools"]),
                          "manifest_recovered": v.get("manifest", {}).get("recovered")})
                     if v.get("available") else {"available": False, "reason": v.get("reason")}
                     for d, v in report["recovery"]["decoders"].items()},
        "input": {k: v for k, v in report["input"].items() if k != "files"},
        "simulation_id": (report.get("simulation") or {}).get("simulation_id"),
        "evidence": report.get("evidence"),
    }


def session_file(sid: str, name: str) -> tuple[bytes, str]:
    """(bytes, download filename). name: report.json | report.html | recovered/<index>."""
    s = load_session(sid)
    d = session_dir(sid)
    if s["status"] != "complete":
        raise FileNotFoundError("Decoding is not complete")
    if name == "report.json":
        return (d / "verification_report.json").read_bytes(), f"{sid}_verification_report.json"
    if name == "report.html":
        return (d / "verification_report.html").read_bytes(), f"{sid}_verification_report.html"
    if name.startswith("recovered/") and name[10:].isdigit():
        i = int(name[10:])
        entry = next((f for f in s["files"] if f["index"] == i), None)
        if entry:
            return (d / "recovered" / f"{i:03d}").read_bytes(), safe_name(entry["name"])
    raise FileNotFoundError("Decoder file not found")


def safe_name(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(str(name).replace("\\", "/")).name).strip(" .")
    return base or "recovered.bin"
