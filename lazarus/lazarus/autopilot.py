"""Scripted run of the same tools, no LLM. Used by tests and as a labeled offline fallback.

It is NOT the deep agent: it follows a fixed recipe. The deep agent (agent.py) decides for itself.
"""

from __future__ import annotations

from . import store, tools


def run(job_id: str, approve=lambda tool, args: True, trials: int = 4) -> dict:
    store.emit(job_id, "message", "supervisor", {"text": "AUTOPILOT (scripted, no LLM) run started."})
    inv = tools.inventory_files(job_id=job_id)
    cold = [f["name"] for f in inv["files"]]
    if not cold:
        return {"error": "No cold archive files selected; upload a PDF, CSV, or image."}
    prep = tools.prepare_archive(job_id=job_id, file_names=cold, tier_notes="Records explicitly selected by the user")
    pool = prep["reference_pool"]
    cov = float(inv["policy"]["coverage"])
    n_v = int(inv["policy"]["n_vaults"])
    tools.build_profile(job_id=job_id, coverage=cov)
    sweep = tools.run_codec_sweep(job_id=job_id, pool_id=pool, redundancies=[0.3, 0.6, 1.0], coverages=[cov], trials=trials)
    ok = [p for p in sweep["points"] if p["recovery_rate"] >= inv["policy"]["target"]]
    best = min(ok, key=lambda p: (p["write_usd"], p["redundancy"])) if ok else None
    red = best["redundancy"] if best else 1.0
    rules = {k: best[k] for k in ("homopolymer_rule", "gc_rule")} if best else {"homopolymer_rule": True, "gc_rule": True}
    while True:
        results = [tools.stress_test(job_id=job_id, pool_id="all", redundancy=red, coverage=cov,
                    scenario=scenario, n_vaults=n_v, trials=trials, target=inv["policy"]["target"], **rules)
                   for scenario in ("vault_loss", "simulator_b", "decay_x2", "low_coverage")]
        cost = tools.estimate_cost(job_id=job_id, redundancy=red, coverage=cov, n_vaults=n_v, **rules)
        if cost.get("error") or not cost.get("within_budget"):
            return {"error": "No tested design within the modeled budget; increase the budget and start a new archive."}
        if all(r.get("passed") for r in results):
            break
        if red >= 2.2:
            return {"error": "Stress tests failed; increase coverage and start a new archive."}
        red = round(red + 0.3, 2)
    args = {"redundancy": red, "coverage": cov, "n_vaults": n_v, **rules}
    if not approve("place_synthesis_order", args):
        return {"stopped": "order rejected"}
    order = tools.place_synthesis_order(job_id=job_id, **args)
    if "error" in order:
        return order
    if not approve("destroy_primary", {}):
        return {"stopped": "destroy rejected"}
    tools.destroy_primary(job_id=job_id)
    drill = tools.recover_archive(job_id=job_id)
    for attempt in (1, 2):
        if drill.get("all_verified"):
            break
        drill = tools.recover_archive(job_id=job_id, attempt=attempt, coverage=cov * 1.5 ** attempt)
    tools.write_certificate(job_id=job_id, summary="Autopilot run (scripted recipe, no LLM).")
    return drill
