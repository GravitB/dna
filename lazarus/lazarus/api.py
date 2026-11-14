"""HTTP API + server-sent events (contract: LAZARUS_TEAM_PLAN.md section 8).

Run: uv run uvicorn lazarus.api:app --port 8000
Serves the homepage from ../site at / and the built web UI from ../web/dist at /app/.
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
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from . import agent, store, tools, vaults, presentation, artifacts, experiment, decoder, fasta, crypto  # noqa: E402
from .persistence import get_cloud, StorageError  # noqa: E402

MAX_UPLOAD_BYTES = 200_000
SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data" / "northstar_bio"
WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
SITE_DIR = Path(__file__).resolve().parents[2] / "site"

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
        if any(s.get("status") == "running" for s in store.load(saved["id"]).get("simulations", [])):
            experiment.mark_interrupted(saved["id"])
    decoder.mark_interrupted()
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
def job_file(job_id: str, name: str, download: bool = False):
    try:
        content = artifacts.download(job_id, name)
    except ValueError:
        raise HTTPException(404, "Archive artifact not found")
    generated = name == "certificate.html" or name.startswith(("exports/", "simulations/", "decodes/"))
    return _file_response(content, Path(name).name, download, generated)


def _file_response(content: bytes, filename: str, download: bool = False, generated: bool = False):
    """Uploaded/restored content opens inline only when it is a verified-safe image or PDF; files
    Lazarus generated itself (certificate, DNA exports, reports) may open inline. ?download=1 always downloads."""
    from .experience import preview_type
    inline = not download and (generated or preview_type(filename, content) is not None)
    media = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    if filename.endswith((".fasta", ".tsv")):
        media = "text/plain; charset=us-ascii"
    return Response(
        content,
        media_type=media,
        headers={
            "Content-Disposition": f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(filename, safe='')}",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---------------------------------------------------------------- DNA experiment (pre/post simulation)


def _ordered(job_id: str) -> dict:
    try:
        job = store.load(job_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "Archive not found")
    if not job.get("order"):
        raise HTTPException(409, "Approve the archive design first; DNA sequences exist only after approval.")
    return job


@app.get("/api/jobs/{job_id}/dna")
def dna_export(job_id: str):
    """Step 1: clean (pre-simulation) DNA export metadata, built from the approved vault files."""
    _ordered(job_id)
    try:
        export = experiment.build_clean_export(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(409, str(exc))
    job = store.load(job_id)
    return {
        "archive_id": job_id,
        "notice": experiment.DIGITAL_NOTICE,
        "export": export,
        "order_settings": job["order"]["settings"],
        "vault_files": [p for p in job["order"]["order_files"]],
        "simulations": job.get("simulations", []),
        "decodes": job.get("decodes", []),
    }


@app.get("/api/jobs/{job_id}/dna/sequences")
def dna_sequences(job_id: str, offset: int = 0, limit: int = 50, sample: str | None = None):
    _ordered(job_id)
    if offset < 0 or not 1 <= limit <= 500:
        raise HTTPException(400, "offset must be >= 0 and limit 1–500")
    return experiment.inspect(job_id, offset, limit, sample)


@app.post("/api/jobs/{job_id}/simulations", status_code=202)
def create_simulation(job_id: str, body: dict | None = None):
    """Step 2: a new, immutable damage simulation of the clean export."""
    _ordered(job_id)
    try:
        return experiment.start_simulation(job_id, body or {})
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/jobs/{job_id}/simulations")
def list_simulations(job_id: str):
    return store.load(job_id).get("simulations", [])


@app.get("/api/jobs/{job_id}/simulations/{sim_id}")
def get_simulation(job_id: str, sim_id: str):
    return experiment.get_simulation(job_id, sim_id)


@app.get("/api/jobs/{job_id}/simulations/{sim_id}/compare")
def compare_simulation(job_id: str, sim_id: str, limit: int = 8):
    if not 1 <= limit <= 40:
        raise HTTPException(400, "limit must be 1–40")
    return experiment.compare(job_id, sim_id, limit)


@app.post("/api/jobs/{job_id}/recovery-keys")
def export_keys(job_id: str, body: dict):
    """Passphrase-protected key file for independent decoding. Keys are never returned in clear."""
    job = _ordered(job_id)
    passphrase = body.get("passphrase") if isinstance(body, dict) else None
    if not isinstance(passphrase, str):
        raise HTTPException(400, "A passphrase is required.")
    keys = {f["key_id"]: artifacts.get_key(job_id, f["key_id"]) for f in job["sealed"].values()}
    try:
        data = decoder.make_keyfile(job_id, keys, passphrase)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    store.emit(job_id, "message", "human", {"text": "Passphrase-protected recovery key file exported."})
    return _file_response(data, f"{job_id}_keys.lazarus-keys.json", download=True)


# ---------------------------------------------------------------- standalone DNA decoder

MAX_BUNDLE_BYTES = 2_000_000
MAX_KEYFILE_BYTES = 64_000


async def _read_upload(f: UploadFile | None, limit: int, what: str) -> bytes | None:
    if f is None or not f.filename:
        return None
    data = await f.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"{what} is larger than {limit // 1_000_000 or limit // 1000} "
                                 f"{'MB' if limit >= 1_000_000 else 'KB'}.")
    return data


def _json_upload(data: bytes | None, what: str) -> dict | None:
    if data is None:
        return None
    try:
        doc = json.loads(data)
        if not isinstance(doc, dict):
            raise ValueError()
        return doc
    except ValueError:
        raise HTTPException(400, f"{what} is not valid JSON.") from None


@app.get("/api/decoder/capabilities")
def decoder_capabilities():
    ok, why = decoder.polish_status()
    return {
        "decoders": {"baseline": {"available": True, "label": "Majority vote (baseline)"},
                     "polish": {"available": ok, "reason": why, "label": "Erbgut CNN PolishDecoder"}},
        "max_fasta_bytes": fasta.MAX_FASTA_BYTES,
        "formats": ["FASTA", "FASTQ (quality scores ignored)"],
        "archives": [
            {"id": j["id"], "name": (s := store.load(j["id"])).get("name") or s["company"],
             "simulations": [{"id": x["id"], "created": x["created"], "seed": x["settings"]["seed"]}
                             for x in s.get("simulations", []) if x["status"] == "complete"]}
            for j in store.list_jobs() if store.load(j["id"]).get("order")
        ],
    }


@app.post("/api/decoder/sessions", status_code=202)
async def create_decode(
    mode: str = Form(...),
    decoders: str = Form("both"),
    archive_id: str = Form(""),
    source: str = Form("upload"),
    simulation_id: str = Form(""),
    key_mode: str = Form(""),
    passphrase: str = Form(""),
    fasta_file: UploadFile | None = File(None),
    bundle_file: UploadFile | None = File(None),
    key_file: UploadFile | None = File(None),
    simulation_metadata: UploadFile | None = File(None),
):
    if mode not in ("existing_archive", "independent_import"):
        raise HTTPException(400, "mode must be existing_archive or independent_import")
    chosen = {"both": ["baseline", "polish"], "baseline": ["baseline"], "polish": ["polish"]}.get(decoders)
    if not chosen:
        raise HTTPException(400, "decoders must be both, baseline or polish")
    fasta_bytes = await _read_upload(fasta_file, fasta.MAX_FASTA_BYTES, "The FASTA file")
    fasta_name = Path(fasta_file.filename).name if fasta_bytes is not None else ""
    keyfile = await _read_upload(key_file, MAX_KEYFILE_BYTES, "The key file")
    key_mode = key_mode or ("archive" if mode == "existing_archive" else "keyfile")
    if key_mode not in ("archive", "keyfile", "none") or (key_mode == "archive" and mode != "existing_archive"):
        raise HTTPException(400, "key_mode must be archive (existing archives only), keyfile or none")

    keys: dict[str, bytes] = {}
    keyfile_archive = None
    if key_mode == "keyfile" and keyfile is not None:
        try:
            keyfile_archive, keys = await asyncio.to_thread(decoder.open_keyfile, keyfile, passphrase)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    simulation, bundle, job_id, context = None, None, None, {}

    if mode == "existing_archive":
        job = _ordered(archive_id)
        job_id = archive_id
        if source == "simulation":
            sim = next((s for s in job.get("simulations", []) if s["id"] == simulation_id), None)
            if not sim or sim["status"] != "complete":
                raise HTTPException(404, "Completed simulation not found for this archive")
            fasta_bytes = artifacts.download(job_id, sim["files"]["post_simulation_reads.fasta"]["path"])
            fasta_name = "post_simulation_reads.fasta"
        elif source == "clean":
            experiment.build_clean_export(job_id)
            fasta_bytes = artifacts.download(job_id, experiment.PRE_FASTA)
            fasta_name = "pre_simulation.fasta"
        elif source != "upload":
            raise HTTPException(400, "source must be upload, simulation or clean")
        if fasta_bytes is None:
            raise HTTPException(400, "Upload a FASTA/FASTQ file or choose a simulation run.")
        digest = crypto.sha256(fasta_bytes)
        sim = next((s for s in job.get("simulations", []) if s.get("output_sha256") == digest), None)
        if sim:
            meta = json.loads(artifacts.download(job_id, sim["files"]["simulation_metadata.json"]["path"]))
            simulation = {"simulation_id": sim["id"], "linked_by": "FASTA SHA-256 matches the simulation output",
                          "settings": meta["settings"], "metrics": meta["metrics"], "profile": meta["profile"]}
        try:
            experiment.build_clean_export(job_id)
            bundle = json.loads(artifacts.download(job_id, experiment.BUNDLE))
        except FileNotFoundError:
            bundle = None  # export could not be rebuilt (a vault was lost first); the DNA manifest still applies
        prior = [d for d in job.get("decodes", []) if d.get("simulation_id")]
        by_sim = {d["simulation_id"]: d["verdict"] for d in prior}
        context = {"trial_history": {"trials": len(by_sim), "passed": sum(v == "PASS" for v in by_sim.values()),
                                     "scope": "earlier decodes of distinct simulation runs of this archive"}} if by_sim else {}
        if key_mode == "archive":
            def key_for(kid):
                try:
                    return artifacts.get_key(job_id, kid)
                except (FileNotFoundError, StorageError, ValueError):
                    return None
            key_source = "archive key store"
        else:
            key_for, key_source = keys.get, ("uploaded key file" if keys else "no keys supplied")
    else:
        if fasta_bytes is None:
            raise HTTPException(400, "Upload the FASTA/FASTQ file to decode.")
        bundle = _json_upload(await _read_upload(bundle_file, MAX_BUNDLE_BYTES, "The recovery bundle"), "The recovery bundle")
        if bundle is not None and bundle.get("format") != "lazarus-recovery-bundle-v1":
            raise HTTPException(400, "The recovery bundle is not a Lazarus recovery bundle.")
        if bundle and keyfile_archive and bundle.get("archive_id") != keyfile_archive:
            raise HTTPException(400, "The key file belongs to a different archive than the recovery bundle.")
        sim_meta = _json_upload(await _read_upload(simulation_metadata, MAX_BUNDLE_BYTES, "Simulation metadata"),
                                "Simulation metadata")
        if sim_meta:
            if (sim_meta.get("output") or {}).get("sha256") != crypto.sha256(fasta_bytes):
                raise HTTPException(400, "The simulation metadata does not describe this FASTA file (SHA-256 differs).")
            simulation = {"simulation_id": sim_meta.get("simulation_id"), "linked_by": "uploaded simulation metadata",
                          "settings": sim_meta.get("settings"), "metrics": sim_meta.get("metrics"),
                          "profile": sim_meta.get("profile")}
        archive_id = (bundle or {}).get("archive_id") or keyfile_archive or ""
        key_for = keys.get
        key_source = "uploaded key file" if keys else "no keys supplied"
    try:
        await asyncio.to_thread(fasta.parse, fasta_bytes)
    except fasta.FastaError as exc:
        raise HTTPException(400, f"Invalid sequence file: {exc}")

    req = decoder.DecodeRequest(
        fasta_bytes=fasta_bytes, fasta_name=fasta_name or "reads.fasta", decoders=chosen, key_for=key_for,
        key_source=key_source, mode=mode, bundle=bundle, expected_archive_id=archive_id or None,
        simulation=simulation, archive_context=context,
    )
    return decoder.start(req, job_id=job_id, on_done=_record_decode if job_id else None)


def _record_decode(session: dict, result: dict) -> None:
    """Mode A: keep the outcome with the archive (and in Supabase when cloud storage is on)."""
    jid, sid = session["job_id"], session["id"]
    report = result["report"]
    artifacts.publish(jid, f"decodes/{sid}/verification_report.json", json.dumps(report, indent=2).encode())
    artifacts.publish(jid, f"decodes/{sid}/verification_report.html", decoder.render_html(report).encode())
    summary = {"id": sid, "created": session["created"], "verdict": report["verdict"],
               "simulation_id": session.get("simulation_id"), "decoders": session["decoders"],
               "files_verified": sum(f["verified"] for f in report["files"]), "files": len(report["files"])}
    store.update(jid, lambda j: j.setdefault("decodes", []).append(summary))
    store.emit(jid, "message", "recovery-engineer",
               {"text": f"Independent decode {sid}: {report['verdict']} ({summary['files_verified']}/{summary['files']} files verified)."})


@app.get("/api/decoder/sessions")
def decode_sessions():
    return decoder.list_sessions()


@app.get("/api/decoder/sessions/{sid}")
def decode_session(sid: str):
    return decoder.load_session(sid)


@app.get("/api/decoder/sessions/{sid}/files/{name:path}")
def decode_file(sid: str, name: str, download: bool = False):
    data, filename = decoder.session_file(sid, name)
    return _file_response(data, filename, download, generated=name in ("report.json", "report.html"))


@app.get("/api")
@app.get("/api/{path:path}")
def unknown_api(path: str = ""):
    raise HTTPException(404, "Unknown API path")


if WEB_DIST.exists():

    @app.get("/app")
    def app_redirect():
        return RedirectResponse("/app/")

    @app.get("/app/{path:path}")
    def spa(path: str):
        f = WEB_DIST / path
        if path and f.is_file() and WEB_DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(
            WEB_DIST / "index.html", headers={"Cache-Control": "no-cache"}
        )
else:

    @app.get("/app/{path:path}")
    def spa_missing(path: str = ""):
        return JSONResponse(
            {"msg": "Lazarus API. Build the UI with: cd web && npm run build"}
        )


if SITE_DIR.exists():
    app.mount("/", StaticFiles(directory=SITE_DIR, html=True), name="site")
else:

    @app.get("/")
    def root():
        return RedirectResponse("/app/")
