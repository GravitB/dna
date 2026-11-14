"""Business-facing state and evidence derived from persisted measurements."""

SCENARIOS = {
    "vault_loss": "Loss of one location",
    "simulator_b": "Different DNA reader",
    "decay_x2": "Twice the storage period",
    "low_coverage": "Fewer reads",
}


def evidence(job, args):
    rows = []
    for scenario, label in SCENARIOS.items():
        matches = [
            s
            for s in job["stress"]
            if s.get("scenario") == scenario
            and s.get("design") == design(job, args)
            and s.get("pool_id") == "all"
        ]
        last = matches[-1] if matches else None
        rows.append(
            {
                "scenario": scenario,
                "label": label,
                "state": "missing"
                if last is None
                else "passed"
                if last["recovery_rate"] >= job["policy"]["target"]
                else "failed",
                "recovered": last.get("n_recovered") if last else None,
                "trials": last.get("n_trials") if last else None,
            }
        )
    return rows


def design(job, args):
    return {
        "redundancy": args.get("redundancy", 1.0),
        "coverage": args.get("coverage", 10),
        "strand_length": args.get("strand_length", 110),
        "n_vaults": args.get("n_vaults", 3),
        "decoder": args.get("decoder", "polish"),
        "homopolymer_rule": args.get("homopolymer_rule", True),
        "gc_rule": args.get("gc_rule", True),
        "tech": job["policy"]["tech"],
        "retention_years": job["policy"]["retention_years"],
        "files": {
            n: {"sha256": f["sha256"], "nonce": f.get("nonce")}
            for n, f in job["sealed"].items()
        },
    }


def proposal(job, args, cost):
    rows = evidence(job, args)
    return {
        **cost,
        "evidence": rows,
        "can_approve": bool(job["sealed"])
        and set(job["sealed"]) == set(job.get("selected_files", job["sealed"]))
        and all(r["state"] == "passed" for r in rows)
        and args.get("n_vaults", 3) == job["policy"]["n_vaults"]
        and cost.get("within_budget", False),
    }


def view(job, pending=None):
    status = job["status"]
    latest = job["drills"][-1] if job["drills"] else None
    if pending:
        phase = "review" if pending["tool"] == "place_synthesis_order" else "recovery"
        label = "Review proposal" if phase == "review" else "Ready for recovery test"
    elif status == "recovering":
        phase, label = "recovery", "Recovery test in progress"
    elif status in ("interrupted", "error", "stopped"):
        phase, label = (
            "attention",
            {
                "interrupted": "Interrupted",
                "error": "Needs attention",
                "stopped": "Analysis stopped",
            }[status],
        )
    elif latest:
        phase, label = (
            "results",
            "Recovery verified" if latest["all_verified"] else "Recovery incomplete",
        )
    elif job.get("finished"):
        phase, label = "attention", "No recovery evidence"
    elif job.get("order"):
        phase, label = "recovery", "Archive prepared"
    else:
        phase, label = "analysis", "Analyzing records"
    if job.get("needs_retest") and not pending and status != "recovering":
        label = "Recovery test needed"
    return {
        "needs_retest": job.get("needs_retest", False),
        "phase": phase,
        "label": label,
        "pending_action": label if pending else None,
        "latest_test": latest.get("tested_at") if latest else None,
        "restored_count": sum(f.get("sha256_match", False) for f in latest["files"])
        if latest
        else None,
        "verified": latest["all_verified"] if latest else None,
    }


def summary(job, pending=None):
    return {
        "id": job["id"],
        "name": job.get("name") or job["company"],
        "company": job["company"],
        "created": job["created"],
        "status": job["status"],
        "retention_years": job["policy"]["retention_years"],
        "file_count": len(job["selected_files"])
        if "selected_files" in job
        else len(job["sealed"]) or None,
        "presentation": view(job, pending),
    }
