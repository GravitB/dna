"""HTTP API + server-sent events (contract: LAZARUS_TEAM_PLAN.md section 8).

Run: uv run uvicorn lazarus.api:app --port 8000
Serves the built web UI from ../web/dist when present.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from . import agent, store, tools, vaults  # noqa: E402

MAX_UPLOAD_BYTES = 200_000
SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data" / "northstar_bio"
WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"

app = FastAPI(title="Lazarus")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"ok": True, "llm": bool(os.environ.get("ANTHROPIC_API_KEY")), "model": agent.MODEL}


@app.get("/api/samples")
def samples():
    return [{"name": f.name, "bytes": f.stat().st_size} for f in sorted(SAMPLE_DIR.iterdir())] if SAMPLE_DIR.exists() else []


@app.get("/api/jobs")
def jobs():
    return store.list_jobs()


@app.post("/api/jobs")
async def create_job(
    company: str = Form("Northstar Bio"),
    policy: str = Form(...),
    use_samples: bool = Form(False),
    mode: str = Form("agent"),
    files: list[UploadFile] | None = File(None),
):
    pol = json.loads(policy)
    pol = {"retention_years": float(pol.get("retention_years", 50)), "tech": pol.get("tech", "nanopore"),
           "coverage": float(pol.get("coverage", 10)), "budget_usd": float(pol.get("budget_usd", 50)),
           "target": float(pol.get("target", 1.0)), "n_vaults": int(pol.get("n_vaults", 3)), "notes": pol.get("notes", "")}
    if pol["tech"] not in ("nanopore", "illumina"):
        raise HTTPException(400, "tech must be nanopore or illumina")
    if mode == "agent" and not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(400, "ANTHROPIC_API_KEY is not set; put it in .env or use mode=autopilot")
    job_id = store.new_job(company, pol)
    up = store.job_dir(job_id) / "uploads"
    total = 0
    if use_samples:
        for f in SAMPLE_DIR.iterdir():
            shutil.copy(f, up / f.name)
    for f in files or []:
        data = await f.read()
        total += len(data)
        if total > MAX_UPLOAD_BYTES:
            shutil.rmtree(store.job_dir(job_id))
            raise HTTPException(400, f"demo limit is {MAX_UPLOAD_BYTES // 1000} KB total")
        (up / Path(f.filename or "file").name).write_bytes(data)
    if not any(up.iterdir()):
        shutil.rmtree(store.job_dir(job_id))
        raise HTTPException(400, "no files")
    store.emit(job_id, "message", "human", {"text": f"Job created for {company}. Mode: {mode}."})
    agent.start(job_id, mode)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    try:
        j = store.load(job_id)
    except FileNotFoundError:
        raise HTTPException(404)
    j["vaults"] = vaults.list_vaults(store.job_dir(job_id))
    r = agent.RUNS.get(job_id)
    j["pending"] = r.pending if r else None
    return j


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

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/jobs/{job_id}/approve")
async def approve(job_id: str, body: dict):
    r = agent.RUNS.get(job_id)
    if not r or not r.decide(body):
        raise HTTPException(409, "nothing is waiting for approval")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/vaults/{vault_id}/destroy")
def destroy_vault(job_id: str, vault_id: int):
    ok = vaults.destroy_vault(store.job_dir(job_id), vault_id)
    store.emit(job_id, "vault_event", "human", {"vault_id": vault_id, "status": "destroyed"})
    store.emit(job_id, "message", "human", {"text": f"Vault {vault_id} destroyed (flood/fire scenario)."})
    return {"destroyed": ok}


@app.post("/api/jobs/{job_id}/drill")
async def drill(job_id: str, body: dict | None = None):
    """Re-run the recovery drill directly (e.g. after destroying a vault)."""
    body = body or {}
    res = await asyncio.to_thread(tools.recover_archive, job_id=job_id, attempt=int(body.get("attempt", 1)),
                                  coverage=body.get("coverage"))
    return res


@app.get("/api/jobs/{job_id}/files/{name:path}")
def job_file(job_id: str, name: str):
    base = store.job_dir(job_id).resolve()
    p = (base / name).resolve()
    if not str(p).startswith(str(base)) or not p.is_file() or p.parts[len(base.parts)] in ("kms",):
        raise HTTPException(404)
    return FileResponse(p)


if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = WEB_DIST / path
        if path and f.is_file() and WEB_DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(WEB_DIST / "index.html")
else:
    @app.get("/")
    def root():
        return JSONResponse({"msg": "Lazarus API. Build the UI with: cd web && npm run build"})
