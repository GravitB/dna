from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from lazarus import agent, api, presentation, store, tools


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "JOBS_DIR", tmp_path)
    monkeypatch.setattr(agent, "RUNS", {})
    monkeypatch.setattr(agent, "start", lambda *a: None)
    with TestClient(api.app) as c:
        yield c


def create(client, **kwargs):
    return client.post(
        "/api/jobs",
        data={"mode": "autopilot", "policy": "{}", **kwargs},
        files=[
            ("files", ("final.txt", b"Final record")),
            ("files", ("draft.txt", b"draft")),
        ],
    )


def test_selected_text_and_exclusions_are_explicit(client):
    r = create(
        client, name="Final records", company="Example", selected_files='["final.txt"]'
    )
    assert r.status_code == 200
    jid = r.json()["job_id"]
    j = client.get("/api/jobs/" + jid).json()
    assert j["name"] == "Final records" and j["selected_files"] == ["final.txt"]
    assert not (store.job_dir(jid) / "uploads/draft.txt").exists()
    assert "error" in tools.prepare_archive(job_id=jid, file_names=["draft.txt"])
    assert "error" not in tools.prepare_archive(job_id=jid, file_names=["final.txt"])
    row = client.get("/api/jobs").json()[0]
    assert row["file_count"] == 1 and row["presentation"]["latest_test"] is None


@pytest.mark.parametrize(
    "selection", ["[]", '["missing.txt"]', '["final.txt", "final.txt"]', "{}"]
)
def test_invalid_selection_is_rejected(client, selection):
    assert create(client, selected_files=selection).status_code == 400
    assert store.list_jobs() == []


def test_duplicate_and_total_sample_limit(client):
    assert (
        client.post(
            "/api/jobs",
            data={"mode": "autopilot", "policy": "{}"},
            files=[("files", ("same.txt", b"a")), ("files", ("same.txt", b"b"))],
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/jobs",
            data={"mode": "autopilot", "policy": "{}", "use_samples": "true"},
            files={"files": ("large.bin", bytes(175000))},
        ).status_code
        == 400
    )
    assert store.list_jobs() == []


def measured_job(client):
    jid = create(client, selected_files='["final.txt"]').json()["job_id"]
    tools.prepare_archive(job_id=jid, file_names=["final.txt"])
    job = store.load(jid)
    args = {"redundancy": 1.6, "coverage": 10, "n_vaults": 3}
    rows = [
        {
            "scenario": scenario,
            "design": presentation.design(job, args),
            "pool_id": "all",
            "recovery_rate": 1,
            "n_recovered": 4,
            "n_trials": 4,
        }
        for scenario in presentation.SCENARIOS
    ]
    store.update(jid, lambda j: j.update(stress=rows))
    return jid, args


def test_approval_requires_exact_current_design(client):
    jid, args = measured_job(client)
    job = store.load(jid)
    cost = {"within_budget": True}
    assert presentation.proposal(job, args, cost)["can_approve"]
    for key, value in [
        ("coverage", 15),
        ("redundancy", 1.9),
        ("n_vaults", 4),
        ("decoder", "baseline"),
    ]:
        assert not presentation.proposal(job, {**args, key: value}, cost)["can_approve"]
    changed = deepcopy(job)
    changed["sealed"]["final.txt"]["nonce"] = "different encryption"
    assert not presentation.proposal(changed, args, cost)["can_approve"]
    assert not presentation.proposal(job, args, {"within_budget": False})["can_approve"]
    job["stress"].append({**job["stress"][0], "recovery_rate": 0, "n_recovered": 0})
    assert not presentation.proposal(job, args, cost)["can_approve"]


def test_api_blocks_unmeasured_approval_and_duplicate_decisions(client, monkeypatch):
    jid, args = measured_job(client)
    run = agent.Run(jid)
    run.pending = {"tool": "place_synthesis_order", "args": {**args, "coverage": 15}}
    agent.RUNS[jid] = run
    assert (
        client.post(
            f"/api/jobs/{jid}/approve", json={"decision": "approve"}
        ).status_code
        == 409
    )
    run.pending["args"] = args
    assert (
        client.post(
            f"/api/jobs/{jid}/approve", json={"decision": "approve"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/jobs/{jid}/approve", json={"decision": "approve"}
        ).status_code
        == 409
    )


def test_recovery_cannot_omit_selected_records(client, monkeypatch):
    jid = create(client, selected_files='["final.txt"]').json()["job_id"]
    monkeypatch.setattr(
        tools, "_read_vaults", lambda d: ([1], {"MANIFEST": {1: {0: "ACGT"}}})
    )
    monkeypatch.setattr(tools.dna, "sequence", lambda *a: [])
    monkeypatch.setattr(tools.dna, "decode_clusters", lambda *a: [])
    monkeypatch.setattr(
        tools.manifest,
        "decode_manifest",
        lambda *a: {
            "pools": {},
            "files": {},
            "n_vaults": 3,
            "channel": {
                "tech": "nanopore",
                "retention_years": 50,
                "planned_coverage": 10,
            },
        },
    )
    result = tools.recover_archive(job_id=jid)
    assert not result["all_verified"]
    assert (
        result["files"][0]["name"] == "final.txt"
        and not result["files"][0]["sha256_match"]
    )
    assert result["tested_at"]


def test_failed_exception_is_recorded(client, monkeypatch):
    jid = create(client).json()["job_id"]
    monkeypatch.setattr(
        tools,
        "_read_vaults",
        lambda d: (_ for _ in ()).throw(ValueError("corrupt vault")),
    )
    result = tools.recover_archive(job_id=jid)
    assert not result["all_verified"]
    assert store.load(jid)["drills"][-1]["tested_at"]
    assert store.load(jid)["status"] == "recovery_failed"


def test_active_workflow_blocks_overlapping_recovery(client):
    jid = create(client).json()["job_id"]
    store.update(
        jid,
        lambda j: j.update(order={"settings": {"coverage": 10}}, status="recovering"),
    )
    assert client.post(f"/api/jobs/{jid}/drill", json={}).status_code == 409
    assert client.post(f"/api/jobs/{jid}/vaults/1/destroy").status_code == 409


def test_legacy_summary_and_interrupted_state(client):
    jid = store.new_job("Legacy org", {"retention_years": 50})
    store.update(jid, lambda j: j.update(status="interrupted"))
    row = client.get("/api/jobs").json()[0]
    assert row["name"] == "Legacy org" and row["file_count"] is None
    assert row["presentation"]["phase"] == "attention"


def test_location_change_requests_a_new_test(client):
    jid = create(client).json()["job_id"]
    job = store.load(jid)
    job.update(
        status="certified",
        needs_retest=True,
        drills=[
            {"all_verified": True, "files": [], "tested_at": "2026-11-14T00:00:00Z"}
        ],
    )
    assert presentation.view(job)["label"] == "Recovery test needed"
    assert presentation.view(job)["needs_retest"]
