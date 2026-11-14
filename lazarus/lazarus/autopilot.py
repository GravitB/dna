"""Scripted run of the same tools, no LLM. Used by tests and as a labeled offline fallback.

It is NOT the deep agent: it follows a fixed recipe. The deep agent (agent.py) decides for itself.
"""

from __future__ import annotations

from . import store, tools


def run(job_id: str, approve=lambda tool, args: True, trials: int = 4) -> dict:
    store.emit(job_id, "message", "supervisor", {"text": "AUTOPILOT (scripted, no LLM) run started."})
    inv = tools.inventory_files(job_id=job_id)
    cold = [f["name"] for f in inv["files"] if not f["name"].endswith(".txt")]
    prep = tools.prepare_archive(job_id=job_id, file_names=cold, tier_notes="*.txt treated as hot working files")
    pool = prep["reference_pool"]
    cov = float(inv["policy"]["coverage"])
    n_v = int(inv["policy"]["n_vaults"])
    tools.build_profile(job_id=job_id, coverage=cov)
    sweep = tools.run_codec_sweep(job_id=job_id, pool_id=pool, redundancies=[0.3, 0.6, 1.0], coverages=[cov], trials=trials)
    ok = [p for p in sweep["points"] if p["recovery_rate"] >= 1.0]
    red = min(p["redundancy"] for p in ok) if ok else 1.0
    while True:
        st = tools.stress_test(job_id=job_id, pool_id="all", redundancy=red, coverage=cov, scenario="vault_loss",
                               n_vaults=n_v, trials=trials)
        if st.get("passed") or red >= 1.6:
            break
        red = round(red + 0.3, 2)
    args = {"redundancy": red, "coverage": cov, "n_vaults": n_v}
    if not approve("place_synthesis_order", args):
        return {"stopped": "order rejected"}
    tools.place_synthesis_order(job_id=job_id, **args)
    if not approve("destroy_primary", {}):
        return {"stopped": "destroy rejected"}
    tools.destroy_primary(job_id=job_id)
    drill = tools.recover_archive(job_id=job_id)
    tools.write_certificate(job_id=job_id, summary="Autopilot run (scripted recipe, no LLM).")
    return drill
