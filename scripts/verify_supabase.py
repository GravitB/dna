#!/usr/bin/env python3
"""Run an opt-in, real-backend Supabase archive and portable recovery check.

Creates a fictional sample archive and preserves its cloud evidence for inspection.
Run with the backend active and the lazarus Python environment.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv


def verify(base_url, timeout):
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    load_dotenv(root / "lazarus" / ".env")
    with httpx.Client(base_url=base_url, timeout=60) as client:
        health = client.get("/api/health")
        health.raise_for_status()
        assert health.json().get("storage_backend") == "supabase", (
            "Backend is not in Supabase mode"
        )
        samples = client.get("/api/samples")
        samples.raise_for_status()
        names = [f["name"] for f in samples.json()]
        response = client.post(
            "/api/jobs",
            data={
                "name": "Supabase live verification",
                "company": "Northstar Bio",
                "mode": "autopilot",
                "use_samples": "true",
                "selected_files": json.dumps(names),
                "policy": json.dumps({"budget_usd": 100}),
            },
        )
        response.raise_for_status()
        jid = response.json()["job_id"]
        print("Created cloud archive:", jid, flush=True)
        deadline = time.monotonic() + timeout
        decisions = set()
        while time.monotonic() < deadline:
            response = client.get(f"/api/jobs/{jid}")
            response.raise_for_status()
            job = response.json()
            pending = job.get("pending")
            if pending and pending["tool"] not in decisions:
                if pending["tool"] == "place_synthesis_order":
                    assert pending["summary"]["can_approve"], (
                        "Proposal evidence is incomplete"
                    )
                    assert all(
                        e["state"] == "passed" for e in pending["summary"]["evidence"]
                    )
                    print(
                        "All four design scenarios passed; approving simulated archive.",
                        flush=True,
                    )
                else:
                    print(
                        "Approving deletion of this sample job’s working copies.",
                        flush=True,
                    )
                decision = client.post(
                    f"/api/jobs/{jid}/approve", json={"decision": "approve"}
                )
                decision.raise_for_status()
                decisions.add(pending["tool"])
            if job.get("finished") or job["status"] == "error":
                assert job["status"] == "certified", job.get(
                    "error", "Archive did not complete"
                )
                break
            time.sleep(1)
        else:
            raise RuntimeError(
                "Archive verification timed out; inspect the saved job in the UI."
            )
        assert len(decisions) == 2
        assert job["storage"]["state"] == "saved"
        assert job["order"]["cost"]["bases"] == job["order"]["total_bases"]
        assert job["drills"][-1]["all_verified"]
        assert {f["name"] for f in job["drills"][-1]["files"]} == set(names)
        report = client.get(f"/api/jobs/{jid}/files/certificate.html")
        report.raise_for_status()
        assert "not regulatory certification" in report.text
        print(
            "Live API workflow verified:",
            len(names),
            "files restored; report downloaded.",
            flush=True,
        )
        loss = client.post(f"/api/jobs/{jid}/vaults/2/destroy")
        loss.raise_for_status()
        assert loss.json()["destroyed"]
        response = client.post(
            f"/api/jobs/{jid}/drill", json={"attempt": 1, "coverage": 20}, timeout=180
        )
        response.raise_for_status()
        assert response.json()["all_verified"], response.json()
        assert response.json()["vaults_available"] == [1, 3]
        print("Live API recovery from two of three locations verified.", flush=True)
    # A separate working directory proves recovery is not reading original jobs or keys.
    from lazarus import store, tools, artifacts
    from lazarus.persistence import get_cloud

    previous = store.JOBS_DIR
    with tempfile.TemporaryDirectory(prefix="lazarus-portable-") as directory:
        store.JOBS_DIR = Path(directory)
        store._versions.clear()
        store._events.clear()
        try:
            assert not list(Path(directory).iterdir())
            cloud = get_cloud()
            assert cloud is not None
            loaded = store.load(jid)
            assert loaded["storage"]["state"] == "saved"
            assert not list((store.job_dir(jid) / "kms").iterdir())
            result = tools.recover_archive(job_id=jid, attempt=2, coverage=25)
            assert result["all_verified"], result
            assert {f["name"] for f in result["files"]} == set(names)
            for f in result["files"]:
                data = artifacts.download(jid, f"restored/{f['name']}")
                from lazarus.crypto import sha256

                assert sha256(data) == f["sha256"]
            certificate = tools.write_certificate(
                job_id=jid,
                summary="Live Supabase recovery verified from an empty local jobs directory.",
            )
            assert "error" not in certificate
            assert artifacts.download(jid, "certificate.html")
            print(
                "Portable recovery verified with no local DNA, metadata, or key files.",
                flush=True,
            )
        finally:
            store.JOBS_DIR = previous
    print("PASS: live Supabase backend integration.", flush=True)
    return jid


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    verify(args.base_url, args.timeout)
