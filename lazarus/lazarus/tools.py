"""Agent tools (contract: LAZARUS_TEAM_PLAN.md section 7).

Plain Python functions with type hints and docstrings; agent.py turns them into LangChain tools.
Every call is logged to the job's event stream (tool_call / tool_result) and to its custody log.
Nothing here asks an LLM anything: all numbers come from real Erbgut encode/simulate/decode runs.
"""

from __future__ import annotations

import functools
import html
import json
import mimetypes
import shutil
import time
from pathlib import Path

from . import crypto, dna, manifest, store, vaults

TOOL_AGENT = {
    "inventory_files": "supervisor",
    "prepare_archive": "supervisor",
    "build_profile": "codec-engineer",
    "run_codec_experiment": "codec-engineer",
    "run_codec_sweep": "codec-engineer",
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
        store.emit(job_id, "tool_result", agent, {"tool": fn.__name__, "result": result})
        store.update(job_id, lambda j: j["custody"].append(
            {"ts": store.now(), "agent": agent, "tool": fn.__name__, "args": kwargs,
             "ok": "error" not in result, "seconds": round(time.time() - t0, 2)}))
        return result

    return wrapper


# ---------------------------------------------------------------- helpers


def _policy(job_id: str) -> dict:
    return store.load(job_id)["policy"]


def _profile(job_id: str, coverage: float | None, years_factor: float = 1.0):
    p = _policy(job_id)
    cov = float(coverage if coverage is not None else p["coverage"])
    return dna.make_profile(p["tech"], float(p["retention_years"]) * years_factor, cov)


def _settings(redundancy: float, strand_length: int, homopolymer_rule: bool, gc_rule: bool):
    return dna.settings_from_dict({
        "redundancy": redundancy,
        "strand_length": strand_length,
        "max_homopolymer": 3 if homopolymer_rule else None,
        "gc_min": 0.4 if gc_rule else None,
        "gc_max": 0.6 if gc_rule else None,
    })


def _pool_bytes(job_id: str, pool_id: str) -> bytes:
    path = store.job_dir(job_id) / "staging" / f"{pool_id}.bin"
    if not path.exists():
        raise FileNotFoundError(f"pool {pool_id} not found (run prepare_archive first, or primary was destroyed)")
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
        out.append({"name": f.name, "bytes": len(data), "mime": mimetypes.guess_type(f.name)[0] or "application/octet-stream",
                    "sha256": crypto.sha256(data), "compressed_bytes": crypto.compressed_size(data)})
    store.update(job_id, lambda j: j.update(files=out, status="inventoried"))
    return {"company": job["company"], "policy": job["policy"], "files": out}


@logged
def prepare_archive(job_id: str, file_names: list[str], tier_notes: str = "") -> dict:
    """Compress (zstd), encrypt (AES-256-GCM, key kept in customer KMS, never in DNA) and split the
    chosen DNA-tier files into oligo pools of at most ~12 KB. Returns pool ids and the reference pool
    (the largest one) to run codec experiments on. tier_notes: why other files stay off DNA."""
    d = store.job_dir(job_id)
    uploads = d / "uploads"
    sealed, stream = {}, b""
    for name in file_names:
        src = uploads / Path(name).name
        if not src.exists():
            return {"error": f"no uploaded file named {name}"}
        data = src.read_bytes()
        key = crypto.new_key()
        key_id = f"kms-{job_id}-{len(sealed):02d}"
        (d / "kms" / f"{key_id}.key").write_bytes(key)
        nonce, ct = crypto.seal(data, key)
        sealed[src.name] = {"key_id": key_id, "nonce": nonce.hex(), "sha256": crypto.sha256(data),
                            "bytes": len(data), "cipher_bytes": len(ct), "offset": len(stream)}
        stream += ct
    # One archive stream split into balanced pools: no tiny pools (small Fountain codes have a
    # much larger recovery variance than large ones).
    n_pools = max(1, -(-len(stream) // crypto.POOL_BYTES))
    size = -(-len(stream) // n_pools)
    pools = {}
    for i in range(n_pools):
        part = stream[i * size:(i + 1) * size]
        pid = f"pool-{i:04d}"
        (d / "staging" / f"{pid}.bin").write_bytes(part)
        pools[pid] = {"offset": i * size, "bytes": len(part)}
    for f in sealed.values():
        a, b = f["offset"], f["offset"] + f["cipher_bytes"]
        f["pools"] = [p for p, v in pools.items() if v["offset"] < b and v["offset"] + v["bytes"] > a]
    for p, v in pools.items():
        v["files"] = [n for n, f in sealed.items() if p in f["pools"]]
    ref = max(pools, key=lambda p: pools[p]["bytes"]) if pools else None
    store.update(job_id, lambda j: j.update(pools=pools, sealed=sealed, tier_notes=tier_notes, status="prepared"))
    return {"pools": [{"pool_id": k, **v} for k, v in pools.items()], "reference_pool": ref,
            "archive_bytes": len(stream),
            "files": {k: {"bytes": v["bytes"], "cipher_bytes": v["cipher_bytes"], "pools": v["pools"]} for k, v in sealed.items()}}


# ---------------------------------------------------------------- codec design


@logged
def build_profile(job_id: str, coverage: float | None = None) -> dict:
    """Build the Erbgut channel profile for this customer: the vendor's read technology (calibrated on
    real reads) stretched to the retention horizon. coverage = planned reads per strand at read-back."""
    p = _profile(job_id, coverage)
    return {"name": p.name, "technology": p.technology, "sub_rate": p.sub_rate, "ins_rate": p.ins_rate,
            "del_rate": p.del_rate, "storage_years": p.storage_years,
            "strand_loss_after_storage": round(p.total_dropout, 4), "coverage_mean": p.coverage_mean,
            "calibrated_from": p.calibrated_from, "decay_note": "decay is extrapolated (modeled), not measured"}


def _experiment(job_id, pool_id, redundancy, strand_length, coverage, decoder, trials, homopolymer_rule, gc_rule,
                channel="a", lost_vaults=0, n_vaults=1, years_factor=1.0):
    s = _settings(redundancy, strand_length, homopolymer_rule, gc_rule)
    prof = _profile(job_id, coverage, years_factor)
    if pool_id == "all":
        data = [_pool_bytes(job_id, p) for p in store.load(job_id)["pools"]]
    else:
        data = _pool_bytes(job_id, pool_id)
    r = dna.run_trials(data, s, prof, _trials(trials), decoder,
                       channel=channel, lost_vaults=lost_vaults, n_vaults=n_vaults)
    r["settings"] = {"redundancy": redundancy, "strand_length": strand_length, "coverage": prof.coverage_mean,
                     "homopolymer_rule": homopolymer_rule, "gc_rule": gc_rule}
    return r


@logged
def run_codec_experiment(job_id: str, pool_id: str, redundancy: float, coverage: float, strand_length: int = 110,
                         decoder: str = "baseline", trials: int = 8, homopolymer_rule: bool = True,
                         gc_rule: bool = True) -> dict:
    """pool_id: one pool, or 'all' for the whole archive. Encode with Erbgut's Fountain encoder, then run `trials` simulated sequencing passes and
    decode each one. Returns recovery_rate (fraction of exact file recoveries), strand accuracy,
    bits per base and modeled costs. decoder: 'baseline' (majority vote, fast) or 'polish' (CNN)."""
    r = _experiment(job_id, pool_id, redundancy, strand_length, coverage, decoder, trials, homopolymer_rule, gc_rule)
    store.emit(job_id, "experiment_result", "codec-engineer", r)
    store.update(job_id, lambda j: j["experiments"].append(r))
    return r


@logged
def run_codec_sweep(job_id: str, pool_id: str, redundancies: list[float], coverages: list[float],
                    decoder: str = "baseline", trials: int = 6, strand_length: int = 110) -> dict:
    """Grid search: run an experiment for every (redundancy, coverage) pair. Use it to map the
    recovery / cost frontier quickly before confirming the best point with more trials."""
    rows = []
    for c in coverages[:5]:
        for red in redundancies[:6]:
            r = _experiment(job_id, pool_id, red, strand_length, c, decoder, trials, True, True)
            store.emit(job_id, "experiment_result", "codec-engineer", r)
            rows.append(r)
    store.update(job_id, lambda j: j["experiments"].extend(rows))
    return {"points": [{**r["settings"], "recovery_rate": r["recovery_rate"], "strand_accuracy": r["strand_accuracy"],
                        "write_usd": r["write_usd"], "read_usd": r["read_usd"], "bits_per_base": r["bits_per_base"],
                        "n_trials": r["n_trials"]} for r in rows], "decoder": decoder}


@logged
def stress_test(job_id: str, pool_id: str, redundancy: float, coverage: float, scenario: str,
                n_vaults: int = 3, strand_length: int = 110, decoder: str = "polish", trials: int = 6,
                target: float = 1.0) -> dict:
    """Red-team a design under a condition it was NOT tuned on. pool_id='all' (recommended) attacks the
    whole archive: a trial only passes if every pool is recovered. scenario:
    'simulator_b' (structurally different sequencing channel), 'decay_x2' (twice the storage time),
    'low_coverage' (only 60% of the planned reads), 'vault_loss' (one of n_vaults sites destroyed).
    passed = recovery_rate >= target."""
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
    r = _experiment(job_id, pool_id, redundancy, strand_length, cov, decoder, trials, True, True, **kw)
    r.update(scenario=scenario, n_vaults=n_vaults, target=target, passed=r["recovery_rate"] >= target, pool_id=pool_id)
    store.emit(job_id, "stress_result", "adversary", r)
    store.update(job_id, lambda j: j["stress"].append(r))
    return r


@logged
def estimate_cost(job_id: str, redundancy: float, coverage: float, strand_length: int = 110) -> dict:
    """Modeled total cost to write every pool at this setting and read it back once, against the budget.
    Prices are Erbgut placeholder prices, not vendor quotes."""
    job = store.load(job_id)
    s = _settings(redundancy, strand_length, True, True)
    prof = _profile(job_id, coverage)
    bases = write = read = 0.0
    for pid in job["pools"]:
        meta = dna.encode_bytes(_pool_bytes(job_id, pid), s).meta
        n = int(-(-meta.n_chunks * (1 + redundancy) // 1))
        c = dna.costs(meta, n, prof)
        bases += c["bases"]; write += c["write_usd"]; read += c["read_usd"]
    budget = float(job["policy"].get("budget_usd") or 0)
    return {"bases": int(bases), "write_usd": round(write, 2), "read_usd": round(read, 2),
            "budget_usd": budget, "within_budget": budget <= 0 or write <= budget, "prices": "modeled placeholders"}


# ---------------------------------------------------------------- order (needs human approval)


@logged
def place_synthesis_order(job_id: str, redundancy: float, coverage: float, n_vaults: int = 3,
                          strand_length: int = 110, decoder: str = "polish", design_notes: str = "") -> dict:
    """REQUIRES HUMAN APPROVAL. Encode every pool with the approved setting, spread strands across
    n_vaults sites (strand i -> vault i mod n), write vendor-ready order.fasta/order.csv per vault, and
    write the self-describing bootstrap manifest (DNA-encoded, full copy in every vault)."""
    job = store.load(job_id)
    s = _settings(redundancy, strand_length, True, True)
    pools_out, man_pools = {}, {}
    for pid in job["pools"]:
        enc = dna.encode_bytes(_pool_bytes(job_id, pid), s)
        pools_out[pid] = enc.strands
        man_pools[pid] = {**dna.meta_to_dict(enc.meta), "offset": job["pools"][pid]["offset"]}
    files = {name: {k: v[k] for k in ("key_id", "nonce", "sha256", "bytes", "pools", "offset", "cipher_bytes")}
             for name, v in job["sealed"].items()}
    man = {"format": "lazarus-manifest-v1", "company": job["company"], "created": store.now(),
           "channel": {"tech": job["policy"]["tech"], "retention_years": job["policy"]["retention_years"],
                       "planned_coverage": coverage, "recommended_decoder": decoder},
           "n_vaults": n_vaults, "placement": "strand i of each pool -> vault (i mod n_vaults) + 1",
           "crypto": "zstd then AES-256-GCM, aad=lazarus-v1, key in customer KMS by key_id",
           "stream": "pools concatenated in pool-id order form one stream; each file is stream[offset:offset+cipher_bytes]",
           "pools": man_pools, "files": files}
    man_strands = manifest.encode_manifest(man)
    written = vaults.write_vaults(store.job_dir(job_id), n_vaults, pools_out, man_strands)
    total_strands = sum(len(v) for v in pools_out.values())
    cost = estimate_cost.__wrapped__(job_id, redundancy, coverage, strand_length)
    order = {"settings": {"redundancy": redundancy, "strand_length": strand_length, "coverage": coverage,
                          "n_vaults": n_vaults, "decoder": decoder}, "design_notes": design_notes,
             "order_files": written, "data_strands": total_strands, "manifest_strands": len(man_strands),
             "total_bases": (total_strands + n_vaults * len(man_strands)) * strand_length, "cost": cost,
             "placed": store.now()}
    store.update(job_id, lambda j: j.update(order=order, status="ordered"))
    for v in range(1, n_vaults + 1):
        store.emit(job_id, "vault_event", "supervisor", {"vault_id": v, "status": "healthy"})
    return order


@logged
def destroy_primary(job_id: str) -> dict:
    """REQUIRES HUMAN APPROVAL. Disaster drill: delete the original uploads and every staging copy, so
    only the DNA vaults, the one-page bootstrap spec and the customer's KMS keys remain."""
    d = store.job_dir(job_id)
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
    for v in range(1, n_max + 1):
        if not vaults.vault_dir(d, v).exists():
            break
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
def recover_archive(job_id: str, attempt: int = 0, coverage: float | None = None) -> dict:
    """Year-2076 recovery using ONLY the surviving vaults, the bootstrap spec and the KMS keys:
    sequence (simulated), decode the manifest with the fixed bootstrap setting, then decode every pool
    with BOTH the majority-vote baseline and Erbgut's CNN polisher on the same reads, Fountain-recover,
    decrypt, decompress and check SHA-256. attempt = re-sequencing attempt number (new reads).
    coverage overrides the planned reads per strand (e.g. sequence deeper on a retry)."""
    d = store.job_dir(job_id)
    t0 = time.time()
    available, merged = _read_vaults(d)
    for v in available:
        store.emit(job_id, "vault_event", "recovery-engineer", {"vault_id": v, "status": "reading"})
    if not available:
        return {"error": "no vault survived", "files": []}
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
        decoded_man += dna.decode_clusters(clusters, manifest.BOOTSTRAP.strand_length, "polish")
        man = manifest.decode_manifest(decoded_man)
        if man:
            break
    if man is None:
        return {"error": "manifest unreadable from surviving vaults", "vaults_available": available}
    store.emit(job_id, "message", "recovery-engineer",
               {"text": f"Manifest decoded from DNA using only the bootstrap spec ({len(man['pools'])} pools, {len(man['files'])} files)."})

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
            res[f"{dec}_strand_accuracy"] = round(sum(a == b for a, b in zip(out, present)) / max(1, len(present)), 4)
            if data is not None and pid not in pool_bytes:
                pool_bytes[pid] = data
        pool_results[pid] = res

    # 3. files: cut each file's ciphertext out of the archive stream, decrypt with KMS key, verify hash
    offsets = {pid: int(m.get("offset", 0)) for pid, m in man["pools"].items()}
    files_out = []
    restored = d / "restored"
    restored.mkdir(exist_ok=True)
    for name, f in man["files"].items():
        entry = {"name": name, "recovered": False, "sha256_match": False,
                 "baseline_would_recover": all(pool_results[p]["baseline_ok"] for p in f["pools"]),
                 "polish_would_recover": all(pool_results[p]["polish_ok"] for p in f["pools"])}
        if all(p in pool_bytes for p in f["pools"]):
            try:
                start = offsets[f["pools"][0]]
                span = b"".join(pool_bytes[p] for p in f["pools"])
                ct = span[f["offset"] - start: f["offset"] - start + f["cipher_bytes"]]
                key = (d / "kms" / f"{f['key_id']}.key").read_bytes()
                plain = crypto.unseal(bytes.fromhex(f["nonce"]), ct, key)
                entry["recovered"] = True
                entry["sha256"] = crypto.sha256(plain)
                entry["sha256_match"] = entry["sha256"] == f["sha256"]
                if entry["sha256_match"]:
                    (restored / name).write_bytes(plain)
            except Exception as e:  # noqa: BLE001
                entry["error"] = f"{type(e).__name__}"
        files_out.append(entry)

    result = {"vaults_available": available, "n_vaults": man["n_vaults"], "coverage": cov, "attempt": attempt,
              "files": files_out, "pools": pool_results, "all_verified": all(f["sha256_match"] for f in files_out),
              "seconds": round(time.time() - t0, 2)}
    for v in available:
        store.emit(job_id, "vault_event", "recovery-engineer", {"vault_id": v, "status": "healthy"})
    store.emit(job_id, "drill_result", "recovery-engineer", result)
    store.update(job_id, lambda j: (j["drills"].append(result),
                                    j.update(status="recovered" if result["all_verified"] else j["status"])))
    return result


# ---------------------------------------------------------------- compliance


@logged
def read_job_log(job_id: str) -> dict:
    """Summary of everything measured so far: experiments, stress tests, order, drills, custody log size."""
    j = store.load(job_id)
    return {"policy": j["policy"], "n_experiments": len(j["experiments"]), "stress": [
        {k: s[k] for k in ("scenario", "recovery_rate", "n_trials", "passed", "settings")} for s in j["stress"]],
        "order": j["order"], "drills": [{k: d[k] for k in ("vaults_available", "all_verified", "attempt", "coverage")} for d in j["drills"]],
        "custody_entries": len(j["custody"])}


@logged
def write_certificate(job_id: str, summary: str = "") -> dict:
    """Write the Recoverability Certificate (HTML) from measured data only. summary: 2-4 sentence
    plain-English conclusion written by the compliance agent."""
    j = store.load(job_id)
    path = store.job_dir(job_id) / "certificate.html"
    path.write_text(render_certificate(j, summary))
    store.update(job_id, lambda x: x.update(status="certified" if x["status"] == "recovered" else x["status"],
                                            certificate="certificate.html"))
    store.emit(job_id, "done", "compliance", {"certificate_path": f"/api/jobs/{job_id}/files/certificate.html"})
    return {"path": "certificate.html"}


def render_certificate(j: dict, summary: str) -> str:
    e = html.escape
    o = j.get("order") or {}
    last = j["drills"][-1] if j["drills"] else None
    verdict = "VERIFIED RECOVERABLE" if last and last["all_verified"] else "NOT VERIFIED"
    rows_stress = "".join(
        f"<tr><td>{e(s['scenario'])}</td><td>{s['settings']['redundancy']:.2f}</td><td>{s['settings']['coverage']:g}</td>"
        f"<td>{s['n_recovered']}/{s['n_trials']}</td><td>{'PASS' if s['passed'] else 'FAIL'}</td></tr>" for s in j["stress"])
    rows_files = "".join(
        f"<tr><td>{e(f['name'])}</td><td>{'yes' if f['sha256_match'] else 'no'}</td><td>{'yes' if f['baseline_would_recover'] else 'no'}</td>"
        f"<td>{'yes' if f['polish_would_recover'] else 'no'}</td><td><code>{e(f.get('sha256', '')[:16])}…</code></td></tr>"
        for f in (last["files"] if last else []))
    rows_custody = "".join(
        f"<tr><td>{e(c['ts'][11:23])}</td><td>{e(c['agent'])}</td><td>{e(c['tool'])}</td><td>{'ok' if c['ok'] else 'error'}</td></tr>"
        for c in j["custody"])
    st = o.get("settings", {})
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Recoverability Certificate</title>
<style>body{{font:14px/1.5 -apple-system,Segoe UI,sans-serif;max-width:860px;margin:40px auto;padding:0 16px;color:#111;background:#fff}}
h1{{font-size:22px}}table{{border-collapse:collapse;width:100%;margin:8px 0 20px}}td,th{{border:1px solid #ddd;padding:4px 8px;text-align:left}}
.v{{font-size:20px;font-weight:700;color:{'#0a7a3a' if verdict.startswith('VERIFIED') else '#b00020'}}}small{{color:#666}}</style></head><body>
<h1>Lazarus Recoverability Certificate</h1>
<p><b>{e(j['company'])}</b> · job {e(j['id'])} · issued {e(store.now())}</p>
<p class="v">{verdict}</p>
<p>{e(summary)}</p>
<h3>Policy</h3><p>Retention {j['policy']['retention_years']} years · read technology {e(j['policy']['tech'])} · {st.get('n_vaults', '?')} vault sites</p>
<h3>Approved archive design</h3>
<p>Redundancy {st.get('redundancy')} · strand length {st.get('strand_length')} · planned reads/strand {st.get('coverage')} ·
decoder {e(str(st.get('decoder')))} · {o.get('data_strands')} data strands + {o.get('manifest_strands')} manifest strands per vault ·
{o.get('total_bases')} bases · modeled write cost ${(o.get('cost') or {}).get('write_usd')}</p>
<h3>Adversarial stress tests</h3><table><tr><th>Scenario</th><th>Redundancy</th><th>Reads</th><th>Recovered</th><th>Result</th></tr>{rows_stress}</table>
<h3>Recovery drill (primary data destroyed)</h3>
<p>Vaults available: {last['vaults_available'] if last else '-'} of {last['n_vaults'] if last else '-'} · reads/strand {last['coverage'] if last else '-'}</p>
<table><tr><th>File</th><th>SHA-256 match</th><th>Baseline decoder alone</th><th>CNN decoder alone</th><th>SHA-256</th></tr>{rows_files}</table>
<h3>Chain of custody</h3><table><tr><th>Time (UTC)</th><th>Agent</th><th>Action</th><th>Status</th></tr>{rows_custody}</table>
<p><small>DNA synthesis and sequencing are simulated with the Erbgut channel model (calibrated on real Nanopore reads;
storage decay extrapolated). Costs are modeled placeholders. Codec, simulators and CNN decoder: Erbgut (HackMIT 2026).</small></p>
</body></html>"""


ALL_TOOLS = [inventory_files, prepare_archive, build_profile, run_codec_experiment, run_codec_sweep, stress_test,
             estimate_cost, place_synthesis_order, destroy_primary, recover_archive, read_job_log, write_certificate]


def reset_restored(job_id: str) -> None:
    shutil.rmtree(store.job_dir(job_id) / "restored", ignore_errors=True)
