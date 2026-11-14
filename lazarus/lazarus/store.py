"""Job folders and the event stream (contract: LAZARUS_TEAM_PLAN.md section 8)."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .persistence import get_cloud, RevisionConflict

JOBS_DIR = Path(
    os.environ.get("LAZARUS_JOBS_DIR", Path(__file__).resolve().parents[1] / "jobs")
)

_lock = threading.RLock()
_events: dict[str, list[dict]] = {}
_cond = threading.Condition(_lock)
_versions: dict[str, int] = {}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def job_dir(job_id: str) -> Path:
    if not job_id or "/" in job_id or "\\" in job_id or ".." in job_id:
        raise ValueError("bad job id")
    return JOBS_DIR / job_id


def new_job(company: str, policy: dict) -> str:
    job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    d = job_dir(job_id)
    for sub in ("uploads", "staging", "kms", "vaults", "restored"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    save(
        job_id,
        {
            "id": job_id,
            "company": company,
            "policy": policy,
            "created": now(),
            "status": "created",
            "files": [],
            "pools": {},
            "sealed": {},
            "experiments": [],
            "stress": [],
            "order": None,
            "drills": [],
            "custody": [],
        },
    )
    return job_id


def ensure_dirs(job_id: str) -> Path:
    d = job_dir(job_id)
    for sub in ("uploads", "staging", "kms", "vaults", "restored"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def load(job_id: str) -> dict:
    with _lock:
        cloud = get_cloud()
        if cloud:
            job, version = cloud.load(job_id)
            _versions[job_id] = version
            ensure_dirs(job_id)
            return job
        return json.loads((job_dir(job_id) / "job.json").read_text())


def save(job_id: str, job: dict) -> None:
    with _lock:
        cloud = get_cloud()
        if cloud:
            _versions[job_id] = cloud.save(job_id, job, _versions.get(job_id, 0))
            return
        p = job_dir(job_id) / "job.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(job, indent=2))
        tmp.replace(p)


def update(job_id: str, fn) -> dict:
    with _lock:
        for attempt in range(3):
            job = load(job_id)
            fn(job)
            try:
                save(job_id, job)
                return job
            except RevisionConflict:
                if attempt == 2:
                    raise


def list_jobs() -> list[dict]:
    cloud = get_cloud()
    if cloud:
        return [
            {
                "id": j["id"],
                "company": j["company"],
                "status": j["status"],
                "created": j["created"],
            }
            for j in cloud.list_jobs()
        ]
    if not JOBS_DIR.exists():
        return []
    out = []
    for d in sorted(JOBS_DIR.iterdir(), reverse=True):
        if (d / "job.json").exists():
            j = json.loads((d / "job.json").read_text())
            out.append(
                {
                    "id": j["id"],
                    "company": j["company"],
                    "status": j["status"],
                    "created": j["created"],
                }
            )
    return out


# ---------------------------------------------------------------- events


def emit(job_id: str, type_: str, agent: str, data: dict) -> dict:
    ev = {"type": type_, "ts": now(), "agent": agent, "data": data}
    with _cond:
        cloud = get_cloud()
        if cloud:
            ev = cloud.append_event(job_id, ev)
            _cond.notify_all()
            return ev
        evs = _events.setdefault(job_id, _load_events(job_id))
        ev["seq"] = len(evs)
        evs.append(ev)
        with open(job_dir(job_id) / "events.jsonl", "a") as f:
            f.write(json.dumps(ev) + "\n")
        _cond.notify_all()
    return ev


def _load_events(job_id: str) -> list[dict]:
    p = job_dir(job_id) / "events.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def events_since(job_id: str, seq: int, timeout: float = 15.0) -> list[dict]:
    cloud = get_cloud()
    if cloud:
        deadline = time.monotonic() + timeout
        while True:
            events = cloud.events(job_id, seq)
            if events or time.monotonic() >= deadline:
                return events
            with _cond:
                _cond.wait(min(1, max(0, deadline - time.monotonic())))
    with _cond:
        evs = _events.setdefault(job_id, _load_events(job_id))
        if len(evs) <= seq:
            _cond.wait(timeout)
            evs = _events[job_id]
        return evs[seq:]
