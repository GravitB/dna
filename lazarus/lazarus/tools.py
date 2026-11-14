"""Agent tools (contract: LAZARUS_TEAM_PLAN.md section 7).

Plain Python functions with type hints and docstrings; agent.py turns them into LangChain tools.
Every call is logged to the job's event stream (tool_call / tool_result) and to its custody log.
Nothing here asks an LLM anything: all numbers come from real Erbgut encode/simulate/decode runs.
"""

from __future__ import annotations

import functools
import html
import mimetypes
import shutil
import time
from pathlib import Path
from typing import Literal

Decoder = Literal["baseline", "polish"]  # 'polish' = Erbgut's CNN PolishDecoder

from . import crypto, dna, manifest, store, vaults, presentation, artifacts, experiment
from .persistence import get_cloud

TOOL_AGENT = {
    "prepare_learned_model": "codec-researcher",
    "compare_archive_candidates": "codec-engineer",
    "validate_archive_candidate": "adversary",
    "run_quick_design": "codec-engineer",
    "inventory_files": "supervisor",
    "prepare_archive": "supervisor",
    "build_profile": "codec-engineer",
    "run_codec_experiment": "codec-engineer",
    "run_codec_sweep": "codec-engineer",
    "run_learning_experiment": "codec-researcher",
    "estimate_cost": "codec-engineer",
    "stress_test": "adversary",
    "place_synthesis_order": "supervisor",
    "destroy_primary": "supervisor",
    "recover_archive": "recovery-engineer",
    "write_certificate": "compliance",
    "read_job_log": "compliance",
}

MAX_TRIALS = 20


def logged(fn):
    """Emit tool_call/tool_result events and append to the chain-of-custody log."""

    @functools.wraps(fn)
    def wrapper(job_id: str, *args, **kwargs):
        agent = TOOL_AGENT.get(fn.__name__, "supervisor")
        store.emit(job_id, "tool_call", agent, {"tool": fn.__name__, "args": kwargs})
        t0 = time.time()
        try:
            result = fn(job_id, *args, **kwargs)
        except Exception as e:  # noqa: BLE001  errors go back to the agent as data
            result = {"error": f"{type(e).__name__}: {e}"}
            if fn.__name__ == "recover_archive":
                result.update(
                    tested_at=store.now(),
                    all_verified=False,
                    files=[],
                    pools={},
                    vaults_available=[],
                    n_vaults=0,
                    coverage=kwargs.get("coverage"),
                    attempt=kwargs.get("attempt", 0),
                )
                store.update(
                    job_id,
                    lambda j: (
                        j["drills"].append(result),
                        j.update(status="recovery_failed"),
                    ),
                )
                store.emit(job_id, "drill_result", agent, result)
        store.emit(
            job_id, "tool_result", agent, {"tool": fn.__name__, "result": result}
        )
        store.update(
            job_id,
            lambda j: j["custody"].append(
                {
                    "ts": store.now(),
                    "agent": agent,
                    "tool": fn.__name__,
                    "args": kwargs,
                    "ok": "error" not in result,
                    "seconds": round(time.time() - t0, 2),
                }
            ),
        )
        return result

    return wrapper


# ---------------------------------------------------------------- helpers


def _policy(job_id: str) -> dict:
    return store.load(job_id)["policy"]


def _profile(job_id: str, coverage: float | None, years_factor: float = 1.0):
    p = _policy(job_id)
    cov = float(coverage if coverage is not None else p["coverage"])
    return dna.make_profile(p["tech"], float(p["retention_years"]) * years_factor, cov)


def _settings(
    redundancy: float, strand_length: int, homopolymer_rule: bool, gc_rule: bool
):
    return dna.settings_from_dict(
        {
            "redundancy": redundancy,
            "strand_length": strand_length,
            "max_homopolymer": 3 if homopolymer_rule else None,
            "gc_min": 0.4 if gc_rule else None,
            "gc_max": 0.6 if gc_rule else None,
        }
    )


def _pool_bytes(job_id: str, pool_id: str) -> bytes:
    path = store.job_dir(job_id) / "staging" / f"{pool_id}.bin"
    if not path.exists():
        raise FileNotFoundError(
            f"pool {pool_id} not found (run prepare_archive first, or primary was destroyed)"
        )
    return path.read_bytes()


def _trials(n: int) -> int:
    return max(1, min(int(n), MAX_TRIALS))


# ---------------------------------------------------------------- intake


@logged
def inventory_files(job_id: str) -> dict:
    """List the uploaded files with size, type and SHA-256, plus the customer's retention policy."""
    job = store.load(job_id)
    out = []
    for f in sorted((store.job_dir(job_id) / "uploads").iterdir()):
        data = f.read_bytes()
        out.append(
            {
                "name": f.name,
                "bytes": len(data),
                "mime": mimetypes.guess_type(f.name)[0] or "application/octet-stream",
                "sha256": crypto.sha256(data),
                "compressed_bytes": crypto.compressed_size(data),
            }
        )
    store.update(job_id, lambda j: j.update(files=out, status="inventoried"))
    return {"company": job["company"], "policy": job["policy"], "files": out, "analysis_preset": job.get("analysis_preset", "standard"), "encoding_mode": job.get("encoding_mode")}


@logged
def prepare_archive(job_id: str, file_names: list[str], tier_notes: str = "") -> dict:
    """Compress (zstd), encrypt (AES-256-GCM, key kept in customer KMS, never in DNA) and split the
    chosen DNA-tier files into oligo pools of at most ~12 KB. Returns pool ids and the reference pool
    (the largest one) to run codec experiments on. tier_notes: why other files stay off DNA."""
    d = store.job_dir(job_id)
    job = store.load(job_id)
    if job.get("order") or job.get("candidate_comparison"):
        return {"error": "Archive inputs are frozen. Create a revised archive to change files or rerun design selection."}
    if not file_names or len(file_names) != len(set(file_names)):
        return {"error": "Select unique archive files."}
    if "selected_files" in job and set(file_names) != set(job["selected_files"]):
        return {
            "error": "Archive must include every user-selected record. Do not exclude selected files."
        }
    if job.get("order"):
        return {"error": "This archive is already ordered. Create a revised archive."}
    uploads = d / "uploads"
    sealed, stream = {}, b""
    for name in file_names:
        src = uploads / Path(name).name
        if not src.exists():
            return {"error": f"no uploaded file named {name}"}
        data = src.read_bytes()
        key = crypto.new_key()
        key_id = f"kms-{job_id}-{len(sealed):02d}"
        artifacts.put_key(job_id, key_id, key)
        nonce, ct = crypto.seal(data, key)
        sealed[src.name] = {
            "key_id": key_id,
            "nonce": nonce.hex(),
            "sha256": crypto.sha256(data),
            "bytes": len(data),
            "cipher_bytes": len(ct),
            "offset": len(stream),
        }
        stream += ct
    # One archive stream split into balanced pools: no tiny pools (small Fountain codes have a
    # much larger recovery variance than large ones).
    n_pools = max(1, -(-len(stream) // crypto.POOL_BYTES))
    size = -(-len(stream) // n_pools)
    pools = {}
    for i in range(n_pools):
        part = stream[i * size : (i + 1) * size]
        pid = f"pool-{i:04d}"
        (d / "staging" / f"{pid}.bin").write_bytes(part)
        pools[pid] = {"offset": i * size, "bytes": len(part)}
    for f in sealed.values():
        a, b = f["offset"], f["offset"] + f["cipher_bytes"]
        f["pools"] = [
            p
            for p, v in pools.items()
            if v["offset"] < b and v["offset"] + v["bytes"] > a
        ]
    for p, v in pools.items():
        v["files"] = [n for n, f in sealed.items() if p in f["pools"]]
    ref = max(pools, key=lambda p: pools[p]["bytes"]) if pools else None
    store.update(
        job_id,
        lambda j: j.update(
            pools=pools, sealed=sealed, tier_notes=tier_notes, status="prepared"
        ),
    )
    return {
        "pools": [{"pool_id": k, **v} for k, v in pools.items()],
        "reference_pool": ref,
        "archive_bytes": len(stream),
        "files": {
            k: {
                "bytes": v["bytes"],
                "cipher_bytes": v["cipher_bytes"],
                "pools": v["pools"],
            }
            for k, v in sealed.items()
        },
    }


# ---------------------------------------------------------------- codec design


@logged
def build_profile(job_id: str, coverage: float | None = None) -> dict:
    """Build the Erbgut channel profile for this customer: the vendor's read technology (calibrated on
    real reads) stretched to the retention horizon. coverage = planned reads per strand at read-back."""
    p = _profile(job_id, coverage)
    return {
        "name": p.name,
        "technology": p.technology,
        "sub_rate": p.sub_rate,
        "ins_rate": p.ins_rate,
        "del_rate": p.del_rate,
        "storage_years": p.storage_years,
        "strand_loss_after_storage": round(p.total_dropout, 4),
        "coverage_mean": p.coverage_mean,
        "calibrated_from": p.calibrated_from,
        "decay_note": "decay is extrapolated (modeled), not measured",
    }


def _experiment(
    job_id,
    pool_id,
    redundancy,
    strand_length,
    coverage,
    decoder,
    trials,
    homopolymer_rule,
    gc_rule,
    channel="a",
    lost_vaults=0,
    n_vaults=1,
    years_factor=1.0,
):
    from .experience import QUICK_REDUNDANCIES
    job = store.load(job_id)
    if job.get("analysis_preset") == "quick_demo":
        if redundancy not in QUICK_REDUNDANCIES or strand_length != 110 or not homopolymer_rule or not gc_rule:
            raise ValueError("Quick demo uses the four bounded redundancy candidates and default DNA rules.")
        trials = 3
        pool_id = "all"
        if coverage not in (16, 9.6) or n_vaults not in (1, 3):
            raise ValueError("Quick demo uses 16 planned reads and three locations.")
    s = _settings(redundancy, strand_length, homopolymer_rule, gc_rule)
    prof = _profile(job_id, coverage, years_factor)
    if pool_id == "all":
        data = [_pool_bytes(job_id, p) for p in store.load(job_id)["pools"]]
    else:
        data = _pool_bytes(job_id, pool_id)
    r = dna.run_trials(
        data,
        s,
        prof,
        _trials(trials),
        decoder,
        channel=channel,
        lost_vaults=lost_vaults,
        n_vaults=n_vaults,
    )
    r["settings"] = {
        "redundancy": redundancy,
        "strand_length": strand_length,
        "coverage": prof.coverage_mean,
        "homopolymer_rule": homopolymer_rule,
        "gc_rule": gc_rule,
    }
    return r


@logged
def run_codec_experiment(
    job_id: str,
    pool_id: str,
    redundancy: float,
    coverage: float,
    strand_length: int = 110,
    decoder: Decoder = "baseline",
    trials: int = 8,
    homopolymer_rule: bool = True,
    gc_rule: bool = True,
) -> dict:
    """pool_id: one pool, or 'all' for the whole archive. Encode with Erbgut's Fountain encoder, then run `trials` simulated sequencing passes and
    decode each one. Returns recovery_rate (fraction of exact file recoveries), strand accuracy,
    bits per base and modeled costs. decoder: 'baseline' (majority vote, fast) or 'polish' (CNN)."""
    r = _experiment(
        job_id,
        pool_id,
        redundancy,
        strand_length,
        coverage,
        decoder,
        trials,
        homopolymer_rule,
        gc_rule,
    )
    store.emit(job_id, "experiment_result", "codec-engineer", r)
    store.update(job_id, lambda j: j["experiments"].append(r))
    return r


@logged
def run_codec_sweep(job_id: str, pool_id: str, redundancies: list[float], coverages: list[float],
                    decoder: Decoder = "baseline", trials: int = 6, strand_length: int = 110,
                    compare_rules: bool = True) -> dict:
    """Grid search: run an experiment for every (redundancy, coverage) pair and rule combination. Use it to map the
    recovery / cost frontier quickly before confirming the best point with more trials."""
    rows = []
    for c in coverages[:5]:
        for red in redundancies[:6]:
            rules = [(True, True), (True, False), (False, True), (False, False)] if compare_rules else [(True, True)]
            for homopolymer_rule, gc_rule in rules:
                r = _experiment(job_id, pool_id, red, strand_length, c, decoder, trials, homopolymer_rule, gc_rule)
                store.emit(job_id, "experiment_result", "codec-engineer", r)
                rows.append(r)
    store.update(job_id, lambda j: j["experiments"].extend(rows))
    return {
        "points": [
            {
                **r["settings"],
                "recovery_rate": r["recovery_rate"],
                "strand_accuracy": r["strand_accuracy"],
                "write_usd": r["write_usd"],
                "read_usd": r["read_usd"],
                "bits_per_base": r["bits_per_base"],
                "n_trials": r["n_trials"],
            }
            for r in rows
        ],
        "decoder": decoder,
    }


@logged
def stress_test(job_id: str, pool_id: str, redundancy: float, coverage: float, scenario: str,
                n_vaults: int = 3, strand_length: int = 110, decoder: Decoder = "polish", trials: int = 6,
                target: float = 1.0, homopolymer_rule: bool = True, gc_rule: bool = True) -> dict:
    """Red-team a design under a condition it was NOT tuned on. pool_id='all' (recommended) attacks the
    whole archive: a trial only passes if every pool is recovered. scenario:
    'simulator_b' (structurally different sequencing channel), 'decay_x2' (twice the storage time),
    'low_coverage' (only 60% of the planned reads), 'vault_loss' (one of n_vaults sites destroyed).
    passed = recovery_rate >= target."""
    job = store.load(job_id)
    if n_vaults != int(job["policy"].get("n_vaults", n_vaults)):
        raise ValueError("Use the customer's fixed storage location count.")
    target = job["policy"].get("target", target)
    kw = dict(channel="a", lost_vaults=0, n_vaults=n_vaults, years_factor=1.0)
    cov = coverage
    if scenario == "simulator_b":
        kw["channel"] = "b"
    elif scenario == "decay_x2":
        kw["years_factor"] = 2.0
    elif scenario == "low_coverage":
        cov = max(1.0, round(coverage * 0.6, 1))
    elif scenario == "vault_loss":
        kw["lost_vaults"] = 1
    else:
        return {"error": "scenario must be simulator_b, decay_x2, low_coverage or vault_loss"}
    r = _experiment(job_id, pool_id, redundancy, strand_length, cov, decoder, trials, homopolymer_rule, gc_rule, **kw)
    r['design'] = presentation.design(store.load(job_id), dict(redundancy=redundancy, coverage=coverage,
                strand_length=strand_length, n_vaults=n_vaults, decoder=decoder,
                homopolymer_rule=homopolymer_rule, gc_rule=gc_rule))
    r.update(scenario=scenario, n_vaults=n_vaults, target=target, passed=r["recovery_rate"] >= target, pool_id=pool_id)
    store.emit(job_id, "stress_result", "adversary", r)
    store.update(job_id, lambda j: j["stress"].append(r))
    return r


@logged
def estimate_cost(job_id: str, redundancy: float, coverage: float, strand_length: int = 110, n_vaults: int = 3,
                  homopolymer_rule: bool = True, gc_rule: bool = True) -> dict:
    """Modeled total cost to write every pool at this setting and read it back once, against the budget.
    Prices are Erbgut placeholder prices, not vendor quotes."""
    job = store.load(job_id)
    s = _settings(redundancy, strand_length, homopolymer_rule, gc_rule)
    prof = _profile(job_id, coverage)
    bases = write = read = 0.0
    for pid in job["pools"]:
        meta = dna.encode_bytes(_pool_bytes(job_id, pid), s).meta
        n = int(-(-meta.n_chunks * (1 + redundancy) // 1))
        c = dna.costs(meta, n, prof)
        bases += c["bases"]
        write += c["write_usd"]
        read += c["read_usd"]
    # Every site also receives a full bootstrap manifest pool.
    meta = manifest.bootstrap_meta()
    n = int(-(-meta.n_chunks * (1 + meta.settings.redundancy) // 1))
    c = dna.costs(meta, n, prof)
    bases += n_vaults * c["bases"]
    write += n_vaults * c["write_usd"]
    read += n_vaults * c["read_usd"]
    budget = float(job["policy"].get("budget_usd") or 0)
    return {
        "bases": int(bases),
        "write_usd": round(write, 2),
        "read_usd": round(read, 2),
        "budget_usd": budget,
        "within_budget": budget <= 0 or write <= budget,
        "prices": "modeled placeholders",
    }


# ---------------------------------------------------------------- order (needs human approval)


@logged
def place_synthesis_order(job_id: str, redundancy: float, coverage: float, n_vaults: int = 3,
                          strand_length: int = 110, decoder: Decoder = "polish", design_notes: str = "",
                          homopolymer_rule: bool = True, gc_rule: bool = True, candidate_id: str | None = None) -> dict:
    """REQUIRES HUMAN APPROVAL. Encode every pool with the approved setting, spread strands across
    n_vaults sites (strand i -> vault i mod n), write vendor-ready order.fasta/order.csv per vault, and
    write the self-describing bootstrap manifest (DNA-encoded, full copy in every vault)."""
    job = store.load(job_id)
    if job.get('order'):
        return job['order'] if candidate_id and job['order'].get('candidate_id') == candidate_id else {'error': 'Archive already ordered; create a new archive to change its design.'}
    if not 1 <= n_vaults <= 6 or not job["sealed"]:
        return {"error": "choose 1–6 vaults and prepare at least one archive file"}
    if n_vaults != int(job["policy"]["n_vaults"]):
        return {"error": "vault count must match the customer's policy; start a new job to change it"}
    if job.get("encoding_mode") and job.get("analysis_preset") != "quick_demo" and not candidate_id:
        return {"error": "Use the exact tested candidate_id for this archive."}
    s = _settings(redundancy, strand_length, homopolymer_rule, gc_rule)
    if 'selected_files' in job and not candidate_id:
        cost = estimate_cost.__wrapped__(job_id, redundancy, coverage, strand_length, n_vaults, homopolymer_rule, gc_rule)
        args = dict(redundancy=redundancy, coverage=coverage, strand_length=strand_length, n_vaults=n_vaults, decoder=decoder, homopolymer_rule=homopolymer_rule, gc_rule=gc_rule)
        if not presentation.proposal(job, args, cost)['can_approve']:
            return {'error': 'Passing whole-archive tests for this design within budget are required.'}
    if candidate_id:
        from . import candidates
        args = dict(candidate_id=candidate_id, redundancy=redundancy, coverage=coverage,
                    n_vaults=n_vaults, strand_length=strand_length, decoder=decoder,
                    homopolymer_rule=homopolymer_rule, gc_rule=gc_rule)
        checked = candidates.approval(job_id, args)
        if not checked['can_approve']:
            return {'error': 'Candidate evidence, settings, decoder and budget must match the approved archive.'}
        frozen = candidates.load(job_id, candidate_id)
        pools_out = {pid: p['strands'] for pid, p in frozen['pools'].items()}
        man = candidates.archive_manifest(job, candidate_id, frozen)
    else:
        pools_out, man_pools = {}, {}
        for pid in job["pools"]:
            enc = dna.encode_bytes(_pool_bytes(job_id, pid), s)
            pools_out[pid] = enc.strands
            man_pools[pid] = {**dna.meta_to_dict(enc.meta), "offset": job["pools"][pid]["offset"]}
        files = {name: {k: v[k] for k in ("key_id", "nonce", "sha256", "bytes", "pools", "offset", "cipher_bytes")}
                 for name, v in job["sealed"].items()}
        man = {"format": "lazarus-manifest-v1", "archive_id": job_id, "company": job["company"], "created": store.now(),
               "channel": {"tech": job["policy"]["tech"], "retention_years": job["policy"]["retention_years"],
                           "planned_coverage": coverage, "recommended_decoder": decoder},
               "n_vaults": n_vaults, "placement": "strand i of each pool -> vault (i mod n_vaults) + 1",
               "crypto": "zstd then AES-256-GCM, aad=lazarus-v1, key in local demo keystore by key_id",
               "stream": "pools concatenated in pool-id order form one stream; each file is stream[offset:offset+cipher_bytes]",
               "pools": man_pools, "files": files}
    man_strands = manifest.encode_manifest(man)
    written = vaults.write_vaults(
        store.job_dir(job_id), n_vaults, pools_out, man_strands
    )
    if get_cloud():
        store.update(
            job_id,
            lambda j: j.update(storage={"backend": "supabase", "state": "uploading"}),
        )
        try:
            for path in written:
                artifacts.publish(
                    job_id, path, (store.job_dir(job_id) / path).read_bytes()
                )
            for f in job["sealed"].values():
                artifacts.get_key(job_id, f["key_id"])
        except Exception:
            store.update(
                job_id,
                lambda j: j.update(storage={"backend": "supabase", "state": "failed"}),
            )
            raise
    total_strands = sum(len(v) for v in pools_out.values())
    cost = candidates.cost(job_id, candidate_id) if candidate_id else estimate_cost.__wrapped__(job_id, redundancy, coverage, strand_length, n_vaults, homopolymer_rule, gc_rule)
    order = {"candidate_id": candidate_id, "settings": {"redundancy": redundancy, "strand_length": strand_length, "coverage": coverage,
                          "n_vaults": n_vaults, "decoder": decoder, "homopolymer_rule": homopolymer_rule,
                          "gc_rule": gc_rule}, "design_notes": design_notes,
             "order_files": written, "data_strands": total_strands, "manifest_strands": len(man_strands),
             "total_bases": (total_strands + n_vaults * len(man_strands)) * strand_length, "cost": cost,
             "placed": store.now()}
    if candidate_id:
        order['settings'].update(frozen['settings'])
        order['validation_path'] = job['candidates'][candidate_id]['validation_path']
        order['model'] = man['model']
    store.update(
        job_id,
        lambda j: j.update(
            order=order,
            status="ordered",
            vault_locations={str(v): "healthy" for v in range(1, n_vaults + 1)},
            storage={
                "backend": "supabase" if get_cloud() else "local",
                "state": "saved",
            },
        ),
    )
    from .experience import dna_summary
    summary = dna_summary(store.load(job_id))
    store.update(job_id, lambda j: j.update(dna_summary=summary))
    for v in range(1, n_vaults + 1):
        store.emit(
            job_id, "vault_event", "supervisor", {"vault_id": v, "status": "healthy"}
        )
    # Step 1 of the before/after experiment: immutable clean (pre-simulation) export of this order.
    order["export"] = experiment.build_clean_export(job_id, man)
    return order


@logged
def destroy_primary(job_id: str) -> dict:
    """REQUIRES HUMAN APPROVAL. Disaster drill: delete the original uploads and every staging copy, so
    only the DNA vaults, the one-page bootstrap spec and the customer's KMS keys remain."""
    d = store.job_dir(job_id)
    if not store.load(job_id).get("order"):
        return {"error": "place a successful order before destroying primary data"}
    artifacts.verify_order(job_id)
    deleted = []
    for sub in ("uploads", "staging"):
        for f in (d / sub).iterdir():
            deleted.append(f"{sub}/{f.name}")
            f.unlink()
    store.update(job_id, lambda j: j.update(status="primary_destroyed"))
    return {"deleted": deleted}


# ---------------------------------------------------------------- recovery


def _read_vaults(d: Path, n_max: int = 16):
    available, merged = [], {}
    for location in vaults.list_vaults(d):
        v = location["vault_id"]
        data = vaults.read_vault(d, v)
        if data is None:
            continue
        available.append(v)
        for pool_id, strands in data.items():
            if pool_id == vaults.MANIFEST_POOL:
                merged.setdefault(pool_id, {})[v] = strands
            else:
                merged.setdefault(pool_id, {}).update(strands)
    return available, merged


@logged
def recover_archive(
    job_id: str, attempt: int = 0, coverage: float | None = None
) -> dict:
    """Year-2076 recovery using ONLY the surviving vaults, the bootstrap spec and the KMS keys:
    sequence (simulated), decode the manifest with the fixed bootstrap setting, then decode every pool
    with BOTH the majority-vote baseline and Erbgut's CNN polisher on the same reads, Fountain-recover,
    decrypt, decompress and check SHA-256. attempt = re-sequencing attempt number (new reads).
    coverage overrides the planned reads per strand (e.g. sequence deeper on a retry)."""
    d = store.job_dir(job_id)
    t0 = time.time()
    # A new drill supersedes prior restored artifacts and certification.
    reset_restored(job_id)
    (d / "certificate.html").unlink(missing_ok=True)
    store.update(
        job_id,
        lambda j: (
            j.pop("certificate", None),
            j.update(status="recovering", needs_retest=False),
            j.pop("error", None),
        ),
    )

    def fail(message):
        result = {
            "tested_at": store.now(),
            "error": message,
            "files": [],
            "pools": {},
            "all_verified": False,
            "vaults_available": available,
            "n_vaults": (store.load(job_id).get("order") or {})
            .get("settings", {})
            .get("n_vaults", 0),
            "coverage": coverage,
            "attempt": attempt,
            "seconds": round(time.time() - t0, 2),
        }
        store.update(
            job_id,
            lambda j: (j["drills"].append(result), j.update(status="recovery_failed")),
        )
        store.emit(job_id, "drill_result", "recovery-engineer", result)
        return result

    available, merged = _read_vaults(d)
    for v in available:
        store.emit(
            job_id,
            "vault_event",
            "recovery-engineer",
            {"vault_id": v, "status": "reading"},
        )
    if not available:
        return fail("no vault survived")
    seed0 = 50_000 + 1000 * int(attempt)

    # 1. bootstrap manifest: merge decodes of every vault's copy
    man = None
    base_prof = None
    decoded_man = []
    for i, v in enumerate(available):
        copy = merged[vaults.MANIFEST_POOL][v]
        strands = [copy[k] for k in sorted(copy)]
        if base_prof is None:
            # The bootstrap spec fixes the read plan for the manifest: nanopore-class channel, 10 reads.
            base_prof = dna.make_profile("nanopore", 50, 10)
        clusters = dna.sequence(strands, base_prof, seed0 + i)
        decoded_man += dna.decode_clusters(
            clusters, manifest.BOOTSTRAP.strand_length, "polish"
        )
        man = manifest.decode_manifest(decoded_man)
        if man:
            break
    if man is None:
        return fail("manifest unreadable from surviving vaults")
    store.emit(
        job_id,
        "message",
        "recovery-engineer",
        {
            "text": f"Manifest decoded from DNA using only the bootstrap spec ({len(man['pools'])} pools, {len(man['files'])} files)."
        },
    )

    ch = man["channel"]
    cov = float(coverage if coverage is not None else ch["planned_coverage"])
    prof = dna.make_profile(ch["tech"], ch["retention_years"], cov)

    # 2. every pool, both decoders on the same reads
    pool_results, pool_bytes = {}, {}
    for j, (pid, meta_d) in enumerate(sorted(man["pools"].items())):
        meta = dna.meta_from_dict(meta_d)
        have = merged.get(pid, {})
        n_total = int(-(-meta.n_chunks * (1 + meta.settings.redundancy) // 1))
        strands = [have.get(i) for i in range(max(n_total, max(have, default=-1) + 1))]
        present = [s for s in strands if s]
        clusters = dna.sequence(present, prof, seed0 + 100 + j)
        res = {"strands_present": len(present), "strands_written": len(strands)}
        for dec in ("baseline", "polish"):
            out = dna.decode_clusters(clusters, meta.settings.strand_length, dec)
            data = dna.recover_bytes(out, meta)
            res[f"{dec}_ok"] = data is not None
            res[f"{dec}_strand_accuracy"] = round(
                sum(a == b for a, b in zip(out, present)) / max(1, len(present)), 4
            )
            if data is not None and pid not in pool_bytes:
                pool_bytes[pid] = data
        pool_results[pid] = res

    # 3. files: cut each file's ciphertext out of the archive stream, decrypt with KMS key, verify hash
    offsets = {pid: int(m.get("offset", 0)) for pid, m in man["pools"].items()}
    files_out = []
    restored = d / "restored"
    restored.mkdir(exist_ok=True)
    for name, f in man["files"].items():
        entry = {
            "name": name,
            "recovered": False,
            "sha256_match": False,
            "baseline_would_recover": all(
                pool_results[p]["baseline_ok"] for p in f["pools"]
            ),
            "polish_would_recover": all(
                pool_results[p]["polish_ok"] for p in f["pools"]
            ),
        }
        if all(p in pool_bytes for p in f["pools"]):
            try:
                start = offsets[f["pools"][0]]
                span = b"".join(pool_bytes[p] for p in f["pools"])
                ct = span[f["offset"] - start : f["offset"] - start + f["cipher_bytes"]]
                key = artifacts.get_key(job_id, f["key_id"])
                plain = crypto.unseal(bytes.fromhex(f["nonce"]), ct, key)
                entry["recovered"] = True
                entry["sha256"] = crypto.sha256(plain)
                entry["sha256_match"] = entry["sha256"] == f["sha256"]
                if entry["sha256_match"]:
                    artifacts.publish(job_id, f"restored/{name}", plain)
            except Exception as e:  # noqa: BLE001
                entry.update(
                    recovered=False,
                    sha256_match=False,
                    error=f"{type(e).__name__}: file could not be verified or saved",
                )
        files_out.append(entry)

    expected = store.load(job_id).get("selected_files", list(man["files"]))
    for missing in set(expected) - set(man["files"]):
        files_out.append(
            {
                "name": missing,
                "recovered": False,
                "sha256_match": False,
                "baseline_would_recover": False,
                "polish_would_recover": False,
                "error": "Missing from archive",
            }
        )
    result = {
        "tested_at": store.now(),
        "vaults_available": available,
        "n_vaults": man["n_vaults"],
        "candidate_id": man.get("candidate_id"),
        "coverage": cov,
        "attempt": attempt,
        "files": files_out,
        "pools": pool_results,
        "all_verified": bool(files_out) and all(f["sha256_match"] for f in files_out),
        "seconds": round(time.time() - t0, 2),
    }
    for v in available:
        store.emit(
            job_id,
            "vault_event",
            "recovery-engineer",
            {"vault_id": v, "status": "healthy"},
        )
    store.emit(job_id, "drill_result", "recovery-engineer", result)
    store.update(
        job_id,
        lambda j: (
            j["drills"].append(result),
            j.update(
                status="recovered" if result["all_verified"] else "recovery_failed"
            ),
        ),
    )
    return result


# ---------------------------------------------------------------- compliance


@logged
def read_job_log(job_id: str) -> dict:
    """Summary of everything measured so far: experiments, stress tests, order, drills, custody log size."""
    j = store.load(job_id)
    return {
        "policy": j["policy"],
        "candidate_comparison": j.get("candidate_comparison"),
        "candidate_validation": {cid: c.get("validation") for cid, c in j.get("candidates", {}).items() if c.get("validation")},
        "n_experiments": len(j["experiments"]),
        "stress": [
            {
                k: s[k]
                for k in ("scenario", "recovery_rate", "n_trials", "passed", "settings")
            }
            for s in j["stress"]
        ],
        "order": j["order"],
        "drills": [
            {
                k: d[k]
                for k in ("vaults_available", "all_verified", "attempt", "coverage")
            }
            for d in j["drills"]
        ],
        "custody_entries": len(j["custody"]),
    }


@logged
def write_certificate(job_id: str, summary: str = "") -> dict:
    """Write the Recoverability Certificate (HTML) from measured data only. summary: 2-4 sentence
    plain-English conclusion written by the compliance agent."""
    j = store.load(job_id)
    artifacts.publish(
        job_id, "certificate.html", render_certificate(j, summary).encode()
    )
    store.update(
        job_id,
        lambda x: x.update(
            status="certified" if x["status"] == "recovered" else x["status"],
            certificate="certificate.html",
        ),
    )
    store.emit(
        job_id,
        "done",
        "compliance",
        {"certificate_path": f"/api/jobs/{job_id}/files/certificate.html"},
    )
    return {"path": "certificate.html"}


def render_certificate(j: dict, summary: str) -> str:
    e = html.escape
    o = j.get("order") or {}
    last = j["drills"][-1] if j["drills"] else None
    verdict = (
        "VERIFIED RECOVERABLE" if last and last["all_verified"] else "NOT VERIFIED"
    )
    rows_stress = "".join(
        f"<tr><td>{e(s['scenario'])}</td><td>{s['settings']['redundancy']:.2f}</td><td>{s['settings']['coverage']:g}</td>"
        f"<td>{s['n_recovered']}/{s['n_trials']}</td><td>{'PASS' if s['passed'] else 'FAIL'}</td></tr>"
        for s in j["stress"]
    )
    if o.get('candidate_id'):
        selected = j.get('candidates', {}).get(o['candidate_id'], {})
        for r in selected.get('validation', {}).get('scenarios', []):
            rows_stress += (f"<tr><td>{e(r['scenario'])} (held-out)</td><td>{o['settings']['redundancy']:.2f}</td>"
                            f"<td>{o['settings']['coverage']:g}</td><td>{r['n_recovered']}/{r['n_trials']}</td>"
                            f"<td>{'PASS' if r['recovery_rate'] >= j['policy']['target'] else 'FAIL'}</td></tr>")
    rows_files = "".join(
        f"<tr><td>{e(f['name'])}</td><td>{'yes' if f['sha256_match'] else 'no'}</td><td>{'yes' if f['baseline_would_recover'] else 'no'}</td>"
        f"<td>{'yes' if f['polish_would_recover'] else 'no'}</td><td><code>{e(f.get('sha256', '')[:16])}…</code></td></tr>"
        for f in (last["files"] if last else [])
    )
    rows_custody = "".join(
        f"<tr><td>{e(c['ts'][11:23])}</td><td>{e(c['agent'])}</td><td>{e(c['tool'])}</td><td>{'ok' if c['ok'] else 'error'}</td></tr>"
        for c in j["custody"]
    )
    st = o.get("settings", {})
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Recovery Report</title>
<style>body{{font:14px/1.5 -apple-system,Segoe UI,sans-serif;max-width:860px;margin:40px auto;padding:0 16px;color:#111;background:#fff}}
h1{{font-size:22px}}table{{border-collapse:collapse;width:100%;margin:8px 0 20px}}td,th{{border:1px solid #ddd;padding:4px 8px;text-align:left}}
.v{{font-size:20px;font-weight:700;color:{"#0a7a3a" if verdict.startswith("VERIFIED") else "#b00020"}}}small{{color:#666}}</style></head><body>
<h1>Lazarus Recovery Report</h1><p>Simulation evidence. This report is not regulatory certification.</p>
<p><b>{e(j.get("name") or j["company"])}</b> · {e(j["company"])} · job {e(j["id"])} · issued {e(store.now())}</p>
<p class="v">{verdict}</p>
<p>{e(summary)}</p>
<h3>Policy</h3><p>Retention {j["policy"]["retention_years"]} years · read technology {e(j["policy"]["tech"])} · {st.get("n_vaults", "?")} vault sites</p>
<h3>Approved archive design</h3>
<p>Redundancy {st.get("redundancy")} · strand length {st.get("strand_length")} · planned reads/strand {st.get("coverage")} ·
decoder {e(str(st.get("decoder")))} · {o.get("data_strands")} data strands + {o.get("manifest_strands")} manifest strands per vault ·
{o.get("total_bases")} bases · modeled write cost ${(o.get("cost") or {}).get("write_usd")}</p>
<p>Frozen candidate: {e(str(o.get("candidate_id") or "Legacy archive"))}. Learned model: {e(str((o.get("model") or {}).get("id") or "Standard rules"))}. Small trial counts are exploratory.</p>
<h3>Experiment history (includes earlier designs)</h3><table><tr><th>Scenario</th><th>Redundancy</th><th>Reads</th><th>Recovered</th><th>Result</th></tr>{rows_stress}</table>
<h3>Recovery test</h3><p>Tested: {e(str(last.get("tested_at", "Not recorded"))) if last else "Not recorded"}</p>
<p>Vaults available: {last["vaults_available"] if last else "-"} of {last["n_vaults"] if last else "-"} · reads/strand {last["coverage"] if last else "-"}</p>
<table><tr><th>File</th><th>SHA-256 match</th><th>Baseline decoder alone</th><th>CNN decoder alone</th><th>SHA-256</th></tr>{rows_files}</table>
<h3>Chain of custody</h3><table><tr><th>Time (UTC)</th><th>Agent</th><th>Action</th><th>Status</th></tr>{rows_custody}</table>
<p><small>Demo report, not a regulatory certification or guarantee of future recovery. DNA synthesis and sequencing are simulated
with the Erbgut channel model (calibrated on real Nanopore reads; storage decay extrapolated). Costs are modeled placeholders.
Keys are stored separately from DNA: locally in demo mode, or as encrypted key records in Supabase. Codec, simulators and CNN decoder: Erbgut (HackMIT 2026).</small></p>
</body></html>"""


@logged
def run_quick_design(job_id: str) -> dict:
    """Bounded real picture demo: three trials per point, baseline then CNN and four stress tests. Returns exact measured settings or an honest failure."""
    from .experience import QUICK_REDUNDANCIES
    job = store.load(job_id)
    if job.get("analysis_preset") != "quick_demo":
        return {"error": "This tool is for the quick picture demo only."}
    if job.get("quick_design_result"):
        return job["quick_design_result"]
    for red in QUICK_REDUNDANCIES:
        args = dict(job_id=job_id, pool_id="all", redundancy=red, coverage=16, trials=3)
        normal = run_codec_experiment(**args, decoder="baseline")
        if normal.get("recovery_rate", 0) < job["policy"]["target"]:
            continue
        cost = estimate_cost(job_id=job_id, redundancy=red, coverage=16, n_vaults=3)
        if not cost.get("within_budget"):
            continue
        confirmed = run_codec_experiment(**args, decoder="polish")
        if confirmed.get("recovery_rate", 0) < job["policy"]["target"]:
            continue
        tests = [stress_test(**args, n_vaults=3, decoder="polish", scenario=s) for s in presentation.SCENARIOS]
        if all(t.get("passed") for t in tests):
            result = {"settings": dict(redundancy=red, coverage=16, n_vaults=3, strand_length=110,
                       decoder="polish", homopolymer_rule=True, gc_rule=True), "cost": cost,
                       "trials_per_point": 3, "stress": tests}
            store.update(job_id, lambda j: j.update(quick_design_result=result))
            return result
    result = {"error": "No quick-demo design passed every measured test within budget. Create a standard archive to explore further."}
    store.update(job_id, lambda j: j.update(quick_design_result=result))
    return result



@logged
def run_learning_experiment(job_id: str, quick: bool = True) -> dict:
    """Run Erbgut's real risk-learning loop with the fixed CNN decoder in an isolated process.

    Quick mode is exploratory, not benchmark evidence. Full mode uses upstream trial budgets.
    This tests Erbgut's fixed research file, not the customer's archive; no codec is deployed.
    Reports and model checkpoints stay associated with this job. May take several minutes.
    """
    import json
    import subprocess
    import sys
    import uuid

    root = store.job_dir(job_id) / "learning" / uuid.uuid4().hex
    root.mkdir(parents=True)
    policy = _policy(job_id)
    request = root / "request.json"
    request.write_text(json.dumps({"profile": dna.profile_to_dict(_profile(job_id, None)),
                                   "target": policy["target"], "quick": quick}))
    report = None
    with (root / "worker.log").open("w") as log:
        try:
            subprocess.run([sys.executable, "-m", "lazarus.learning", str(request.resolve()),
                            str(root.resolve())], check=True, stdout=log, stderr=log,
                           timeout=600 if quick else 7200)
        except subprocess.TimeoutExpired:
            report = {"status": "timed_out", "quick": quick,
                      "message": "Learning exceeded its time budget; no success or improvement established."}
        except subprocess.CalledProcessError:
            report = {"status": "failed", "quick": quick,
                      "message": "Erbgut learning failed. Inspect worker.log; no improvement established."}
    if report is None:
        report = json.loads((root / "report.json").read_text())
    else:
        (root / "report.json").write_text(json.dumps(report, indent=2))
    for path in root.rglob("*"):
        if path.is_file():
            artifacts.publish(job_id, path.relative_to(store.job_dir(job_id)).as_posix(), path.read_bytes())
    store.update(job_id, lambda j: j.setdefault("learning_experiments", []).append(report))
    return report

@logged
def prepare_learned_model(job_id: str) -> dict:
    """Respect the upload's encoding choice. Reuse a compatible evaluated model or run cancelable fresh learning. Standard mode never trains."""
    from . import learned, model_registry
    job = store.load(job_id)
    mode = job.get('encoding_mode', 'standard')
    if mode == 'fresh' and job.get('learning_state', {}).get('status') in ('canceled', 'failed', 'interrupted'):
        message = 'Fresh learning stopped. Create a revised archive to retry or choose standard encoding.'
        store.update(job_id, lambda j: j.update(error=message, candidate_rejected=True))
        return {'error': message}
    if mode == 'standard':
        return {'mode': mode, 'message': 'Standard encoding selected; no learned model is used.'}
    row = job.get('prepared_model')
    if not row:
        row = learned.train(job_id) if mode == 'fresh' else model_registry.find(job['policy'])
    if row is None:
        message = 'No evaluated compatible model is available. Create a revised archive and choose fresh learning or standard encoding explicitly.'
        store.update(job_id, lambda j: j.update(error=message, candidate_rejected=True))
        return {'error': message}
    model_registry.load(row, job['policy'])
    store.update(job_id, lambda j: j.update(prepared_model=row))
    return {'mode': mode, 'model': model_registry.summary(row)}


@logged
def compare_archive_candidates(job_id: str, redundancy: float = 0.8, trials: int = 3) -> dict:
    """Freeze actual encrypted customer DNA and compare standard and learned encoding under matched train-seed tests. Does not approve or order."""
    from . import learned
    result = learned.compare(job_id, redundancy, trials)
    if result.get('error') or not result.get('selected_id'):
        message = result.get('error') or 'No candidate passed selection within budget. Create a revised archive with more reads or a larger modeled budget.'
        store.update(job_id, lambda j: j.update(error=message, candidate_rejected=True))
    return result


@logged
def validate_archive_candidate(job_id: str) -> dict:
    """Adversary: validate the train-selected frozen candidate once on held-out normal and four stress scenarios, including bootstrap recovery. Return exact order settings or honest failure."""
    from . import learned
    result = learned.finalize(job_id)
    if result.get('error'):
        store.update(job_id, lambda j: j.update(error=result['error'], candidate_rejected=True))
    return result


ALL_TOOLS = [
    prepare_learned_model,
    compare_archive_candidates,
    validate_archive_candidate,
    run_quick_design,
    run_learning_experiment,
    inventory_files,
    prepare_archive,
    build_profile,
    run_codec_experiment,
    run_codec_sweep,
    stress_test,
    estimate_cost,
    place_synthesis_order,
    destroy_primary,
    recover_archive,
    read_job_log,
    write_certificate,
]


def reset_restored(job_id: str) -> None:
    shutil.rmtree(store.job_dir(job_id) / "restored", ignore_errors=True)
