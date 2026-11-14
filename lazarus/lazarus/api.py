"""HTTP API + server-sent events (contract: LAZARUS_TEAM_PLAN.md section 8).

Run: uv run uvicorn lazarus.api:app --port 8000
Serves the built web UI from ../web/dist when present.
"""

from __future__ import annotations

import asyncio
import json
import math
import mimetypes
import os
import threading
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from . import agent, store, tools, vaults, presentation, artifacts
from .persistence import get_cloud, StorageError  # noqa: E402

MAX_UPLOAD_BYTES = 200_000
SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data" / "northstar_bio"
WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"

from contextlib import asynccontextmanager, contextmanager


@asynccontextmanager
async def lifespan(app):
    cloud = get_cloud()
    if cloud:
        await asyncio.to_thread(cloud.check)
    # Persisted artifacts remain readable, but in-memory agent execution cannot survive a restart.
    for saved in store.list_jobs():
        current = store.load(saved['id'])
        if current.get('learning_state', {}).get('status') in ('running', 'canceling'):
            store.update(saved['id'], lambda j: j['learning_state'].update(status='interrupted', message='Server restarted during learning. Retry fresh learning or use standard encoding.'))
        if saved["status"] in (
            "created",
            "running",
            "inventoried",
            "prepared",
            "ordered",
            "primary_destroyed",
            "recovering",
        ) or saved["status"].startswith("awaiting_approval:"):
            store.update(
                saved["id"],
                lambda j: j.update(
                    status="interrupted",
                    error="Server restarted. Start a new archive, or run a recovery drill if vaults exist.",
                ),
            )
    yield


_operations: dict[str, threading.Lock] = {}


@contextmanager
def job_operation(job_id):
    lock = _operations.setdefault(job_id, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(
            409, "A recovery operation is already running. Wait for it to finish."
        )
    try:
        yield
    finally:
        lock.release()


app = FastAPI(title="Lazarus", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


@app.exception_handler(StorageError)
async def storage_error(request, exc):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(FileNotFoundError)
async def missing_archive(request, exc):
    return JSONResponse(
        status_code=404, content={"detail": "Archive or artifact not found."}
    )


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "llm": agent.has_model_key(),
        "model": agent.MODEL,
        "storage_backend": "supabase" if get_cloud() else "local",
    }


@app.get("/api/samples")
def samples(preset: str = "standard"):
    from .experience import QUICK_SAMPLE
    return (
        [
            {"name": f.name, "bytes": f.stat().st_size}
            for f in sorted(SAMPLE_DIR.iterdir())
            if (f.name == QUICK_SAMPLE) == (preset == "quick_demo")
        ]
        if SAMPLE_DIR.exists()
        else []
    )


@app.get("/api/samples/{name}/preview")
def sample_preview(name: str):
    from .experience import QUICK_SAMPLE, preview_type
    if name != QUICK_SAMPLE:
        raise HTTPException(404)
    data = (SAMPLE_DIR / name).read_bytes()
    return Response(data, media_type=preview_type(name, data), headers={"X-Content-Type-Options": "nosniff"})


@app.get("/api/jobs")
def jobs():
    return [
        presentation.summary(
            store.load(j["id"]),
            agent.RUNS[j["id"]].pending if j["id"] in agent.RUNS else None,
        )
        for j in store.list_jobs()
    ]


@app.post("/api/jobs")
async def create_job(
    company: str = Form("Northstar Bio"),
    name: str = Form(""),
    selected_files: str | None = Form(None),
    policy: str = Form(...),
    use_samples: bool = Form(False),
    analysis_preset: str = Form("standard"),
    mode: str = Form("agent"),
    encoding_mode: str | None = Form(None),
    files: list[UploadFile] | None = File(None),
):
    from .experience import QUICK_SAMPLE
    if analysis_preset not in ("standard", "quick_demo"):
        raise HTTPException(400, "Unknown analysis preset")
    if encoding_mode not in (None, "standard", "evaluated", "fresh"):
        raise HTTPException(400, "Choose standard, evaluated or fresh encoding")
    if mode not in ("agent", "autopilot"):
        raise HTTPException(400, "mode must be agent or autopilot")
    try:
        raw = json.loads(policy)
        pol = {
            "retention_years": float(raw.get("retention_years", 50)),
            "tech": raw.get("tech", "nanopore"),
            "coverage": float(raw.get("coverage", 10)),
            "budget_usd": float(raw.get("budget_usd", 50)),
            "target": float(raw.get("target", 1.0)),
            "n_vaults": int(raw.get("n_vaults", 3)),
            "notes": str(raw.get("notes", "")),
        }
        for key in ("retention_years", "coverage", "budget_usd", "target"):
            if not math.isfinite(pol[key]):
                raise ValueError("policy numbers must be finite")
        if not (
            0 <= pol["retention_years"] <= 1000
            and 1 <= pol["coverage"] <= 100
            and pol["budget_usd"] > 0
            and 0 < pol["target"] <= 1
            and 1 <= pol["n_vaults"] <= 6
        ):
            raise ValueError(
                "invalid policy range: years 0–1000, coverage 1–100, positive budget, target (0,1], vaults 1–6"
            )
    except (ValueError, TypeError, AttributeError, OverflowError) as exc:
        raise HTTPException(400, str(exc)) from exc
    if pol["tech"] not in ("nanopore", "illumina"):
        raise HTTPException(400, "tech must be nanopore or illumina")
    if analysis_preset == "quick_demo":
        pol.update(retention_years=50, coverage=16, n_vaults=3, tech="nanopore", target=1.0)
        if not use_samples or files:
            raise HTTPException(400, "The picture demo uses the bundled sample only.")
    if mode == "agent" and not agent.has_model_key():
        raise HTTPException(400, "API key for the selected model is not set; configure .env or use autopilot")
    incoming = {}
    if use_samples:
        incoming = {f.name: f.read_bytes() for f in SAMPLE_DIR.iterdir() if f.is_file()}
        if analysis_preset == "quick_demo":
            incoming = {QUICK_SAMPLE: incoming[QUICK_SAMPLE]}
    total = sum(len(data) for data in incoming.values())
    for f in files or []:
        filename = Path(f.filename or "file").name
        if filename in incoming:
            raise HTTPException(
                400, f"Duplicate filename: {filename}. Rename the file and try again."
            )
        data = await f.read(MAX_UPLOAD_BYTES + 1)
        total += len(data)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(400, "Upload limit is 200 KB including sample files.")
        incoming[filename] = data
    if total > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "Upload limit is 200 KB including sample files.")
    try:
        selected = (
            json.loads(selected_files) if selected_files is not None else list(incoming)
        )
        if (
            not isinstance(selected, list)
            or not selected
            or any(not isinstance(n, str) for n in selected)
        ):
            raise ValueError("Select at least one file.")
        if len(set(selected)) != len(selected) or not set(selected) <= incoming.keys():
            raise ValueError("Selected files must be unique uploaded filenames.")
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    if analysis_preset == 'quick_demo':
        encoding_mode = 'standard'
    elif encoding_mode == 'evaluated':
        from . import model_registry
        if model_registry.find(pol) is None:
            raise HTTPException(409, 'No compatible evaluated model. Choose fresh learning or standard encoding.')
    job_id = store.new_job(company, pol)
    store.update(
        job_id,
        lambda j: j.update(
            name=name.strip() or company,
            analysis_preset=analysis_preset,
            encoding_mode=encoding_mode,
            selected_files=selected,
            intake_files=[
                {"name": n, "bytes": len(d), "included": n in selected}
                for n, d in incoming.items()
            ],
        ),
    )
    up = store.job_dir(job_id) / "uploads"
    for filename in selected:
        (up / filename).write_bytes(incoming[filename])
    store.emit(
        job_id,
        "message",
        "human",
        {"text": f"Job created for {company}. Mode: {mode}."},
    )
    agent.start(job_id, mode)
    return {"job_id": job_id}


@app.post('/api/encoding-options')
def encoding_options(policy: dict):
    from . import model_registry
    try:
        row = model_registry.find(policy)
        return {'evaluated_model': model_registry.summary(row), 'available': row is not None}
    except (KeyError, ValueError, TypeError):
        raise HTTPException(400, 'Invalid channel settings')


@app.post('/api/jobs/{job_id}/learning/cancel')
def cancel_learning(job_id: str):
    from . import learned
    try:
        learned.cancel(job_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {'ok': True}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    try:
        j = store.load(job_id)
    except FileNotFoundError:
        raise HTTPException(404)
    j["vaults"] = vaults.list_vaults(store.job_dir(job_id))
    r = agent.RUNS.get(job_id)
    j["pending"] = r.pending if r else None
    j["presentation"] = presentation.view(j, j["pending"])
    from .experience import dna_summary
    j["dna_summary"] = dna_summary(j)
    j["originals_available"] = any((store.job_dir(job_id) / "uploads").iterdir())
    j["storage"] = j.get("storage") or {
        "backend": "supabase" if get_cloud() else "local",
        "state": "pending" if get_cloud() else "local",
    }
    return j


@app.get("/api/jobs/{job_id}/preview/{name}")
def preview(job_id: str, name: str, stage: str = "original"):
    from .experience import preview_type
    job = store.load(job_id)
    if name not in job.get("selected_files", job.get("sealed", {})) or Path(name).name != name:
        raise HTTPException(404)
    if stage == "original":
        path = store.job_dir(job_id) / "uploads" / name
        if not path.is_file():
            raise HTTPException(404, "Working copy has been removed")
        data = path.read_bytes()
    elif stage == "restored":
        data = artifacts.download(job_id, f"restored/{name}")
    else:
        raise HTTPException(400, "Invalid preview stage")
    media = preview_type(name, data)
    if not media:
        raise HTTPException(415, "Download this file to view it safely")
    return Response(data, media_type=media, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@app.get("/api/jobs/{job_id}/eventlog")
def eventlog(job_id: str):
    return store.events_since(job_id, 0, 0)


@app.get("/api/jobs/{job_id}/events")
async def events(job_id: str, since: int = 0):
    store.job_dir(job_id)

    async def gen():
        seq = since
        while True:
            evs = await asyncio.to_thread(store.events_since, job_id, seq, 10.0)
            if not evs:
                yield ": keepalive\n\n"
                continue
            for ev in evs:
                seq = ev["seq"] + 1
                yield f"id: {ev['seq']}\ndata: {json.dumps(ev)}\n\n"

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


@app.post("/api/jobs/{job_id}/approve")
async def approve(job_id: str, body: dict):
    r = agent.RUNS.get(job_id)
    if body.get("decision") not in ("approve", "reject", "edit"):
        raise HTTPException(400, "invalid approval decision")
    if body.get("args") is not None and not isinstance(body["args"], dict):
        raise HTTPException(400, "Edited settings must be an object.")
    if body["decision"] == "edit" and r and r.mode == "autopilot":
        raise HTTPException(
            400,
            "Reject the proposal and create a revised archive to change scripted settings.",
        )
    if (
        r
        and r.pending
        and r.pending["tool"] == "place_synthesis_order"
        and body["decision"] != "reject"
    ):
        args = (
            {**r.pending["args"], **(body.get("args") or {})}
            if body["decision"] == "edit"
            else r.pending["args"]
        )
        cost = {} if args.get("candidate_id") else tools.estimate_cost.__wrapped__(
            job_id,
            args.get("redundancy", 1),
            args.get("coverage", 10),
            args.get("strand_length", 110),
            args.get("n_vaults", 3),
            args.get("homopolymer_rule", True),
            args.get("gc_rule", True),
        )
        if not presentation.proposal(store.load(job_id), args, cost)["can_approve"]:
            raise HTTPException(
                409,
                "This proposal needs passing tests for the selected design within budget.",
            )
    if not r or not r.decide(body):
        raise HTTPException(409, "nothing is waiting for approval")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/vaults/{vault_id}/destroy")
def destroy_vault(job_id: str, vault_id: int):
    with job_operation(job_id):
        job = store.load(job_id)
        run = agent.RUNS.get(job_id)
        if job["status"] == "recovering" or (run and run.thread.is_alive()):
            raise HTTPException(409, "Wait for the current archive workflow to finish.")
        if vault_id not in [
            v["vault_id"] for v in vaults.list_vaults(store.job_dir(job_id))
        ]:
            raise HTTPException(404, "Storage location not found")
        ok = vaults.destroy_vault(store.job_dir(job_id), vault_id)
        if ok:
            store.update(job_id, lambda j: j.update(needs_retest=True))
        store.emit(
            job_id,
            "vault_event",
            "human",
            {"vault_id": vault_id, "status": "destroyed"},
        )
        store.emit(
            job_id,
            "message",
            "human",
            {"text": f"Vault {vault_id} destroyed (flood/fire scenario)."},
        )
        return {"destroyed": ok}


@app.post("/api/jobs/{job_id}/drill")
async def drill(job_id: str, body: dict | None = None):
    """Re-run recovery from the remaining simulated locations."""
    with job_operation(job_id):
        body = body or {}
        job = store.load(job_id)
        run = agent.RUNS.get(job_id)
        if (
            not job.get("order")
            or job["status"] == "recovering"
            or (run and run.thread.is_alive())
        ):
            raise HTTPException(
                409,
                "Wait for the archive workflow to finish before starting another recovery test.",
            )
        try:
            attempt = int(body.get("attempt", len(job["drills"])))
            coverage = float(
                body.get("coverage") or job["order"]["settings"]["coverage"]
            )
            if attempt < 0 or not math.isfinite(coverage) or not 1 <= coverage <= 100:
                raise ValueError()
        except (TypeError, ValueError, OverflowError):
            raise HTTPException(
                400, "Use a nonnegative attempt and coverage from 1 to 100."
            )
        store.update(job_id, lambda j: j.update(status="recovering"))
        res = await asyncio.to_thread(
            tools.recover_archive, job_id=job_id, attempt=attempt, coverage=coverage
        )
        if "all_verified" in res:
            await asyncio.to_thread(
                tools.write_certificate,
                job_id=job_id,
                summary="Recovery drill updated from measured results.",
            )
        return res


@app.get("/api/jobs/{job_id}/files/{name:path}")
def job_file(job_id: str, name: str):
    from .experience import preview_type
    try:
        content = artifacts.download(job_id, name)
    except ValueError:
        raise HTTPException(404, "Archive artifact not found")
    return Response(
        content,
        media_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
        headers={
            "Content-Disposition": f"{'inline' if name == 'certificate.html' or preview_type(name, content) else 'attachment'}; filename*=UTF-8''{quote(Path(name).name, safe='')}",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = WEB_DIST / path
        if path and f.is_file() and WEB_DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(
            WEB_DIST / "index.html", headers={"Cache-Control": "no-cache"}
        )
else:

    @app.get("/")
    def root():
        return JSONResponse(
            {"msg": "Lazarus API. Build the UI with: cd web && npm run build"}
        )
