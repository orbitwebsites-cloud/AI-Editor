"""AI Video Editor Backend
Endpoints:
  POST   /api/keys                     Save/update API keys (Fernet-encrypted)
  GET    /api/keys/status              Which keys are configured
  POST   /api/keys/test                Test all providers
  POST   /api/projects/upload          Upload a video file
  GET    /api/projects                 List projects
  GET    /api/projects/{id}            Project details
  DELETE /api/projects/{id}            Delete
  POST   /api/projects/{id}/analyze    Transcribe + LLM analyze (background)
  POST   /api/projects/{id}/broll_search  Fetch Pexels results per moment
  POST   /api/projects/{id}/render     Render final video (background)
  GET    /api/projects/{id}/download   Serve final MP4
  GET    /api/media/original/{id}      Stream original video
  GET    /api/media/output/{id}        Stream output video
"""
from fastapi import FastAPI, APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from cryptography.fernet import Fernet
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
from pathlib import Path
import os
import re
import json
import logging
import uuid
import shutil
import asyncio
import aiofiles
from datetime import datetime, timezone

import ai_services as ai
import video_processor as vp


# ---------- BOOTSTRAP ----------
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
SFX_DIR = os.environ.get("SFX_DIR", "/app/backend/assets/sfx")
LIBRARY_DIR = DATA_DIR / "library"
for sub in ("videos", "audio", "output", "subtitles", "broll", "library"):
    (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)

cipher = Fernet(os.environ["MASTER_ENCRYPTION_KEY"].encode())

USER_ID = "default_user"  # single-user MVP

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("backend")

app = FastAPI(title="AI Video Editor")
api = APIRouter(prefix="/api")


# ---------- KEY MANAGEMENT ----------
def _enc(v: str) -> str:
    return cipher.encrypt(v.encode()).decode()


def _dec(v: str) -> str:
    return cipher.decrypt(v.encode()).decode()


async def get_keys() -> Dict[str, str]:
    doc = await db.settings.find_one({"user_id": USER_ID})
    if not doc:
        return {}
    encrypted = doc.get("keys", {})
    out = {}
    for k, v in encrypted.items():
        try:
            out[k] = _dec(v)
        except Exception:
            pass
    return out


async def save_keys(new_keys: Dict[str, str]) -> None:
    existing = await db.settings.find_one({"user_id": USER_ID}) or {}
    encrypted = existing.get("keys", {})
    for k, v in new_keys.items():
        if v and v.strip() and not v.startswith("***"):
            encrypted[k] = _enc(v.strip())
    await db.settings.update_one(
        {"user_id": USER_ID},
        {"$set": {"keys": encrypted, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )


@app.on_event("startup")
async def seed_keys_from_env():
    """If DB has no keys yet, seed from env vars (SEED_*_KEY)."""
    existing = await db.settings.find_one({"user_id": USER_ID})
    if existing and existing.get("keys"):
        logger.info("Keys already present in DB; skipping seed.")
        return
    seed = {}
    if os.environ.get("SEED_GROQ_KEY"):
        seed["groq"] = os.environ["SEED_GROQ_KEY"]
    if os.environ.get("SEED_CEREBRAS_KEY"):
        seed["cerebras"] = os.environ["SEED_CEREBRAS_KEY"]
    if os.environ.get("SEED_PEXELS_KEY"):
        seed["pexels"] = os.environ["SEED_PEXELS_KEY"]
    if seed:
        await save_keys(seed)
        logger.info(f"Seeded keys from env: {list(seed.keys())}")


# ---------- MODELS ----------
class KeysBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    groq: Optional[str] = None
    cerebras: Optional[str] = None
    pexels: Optional[str] = None
    pixabay: Optional[str] = None


class RenderOptions(BaseModel):
    model_config = ConfigDict(extra="ignore")
    style: str = "tiktok"           # tiktok | youtube
    aspect: str = "16:9"            # "16:9" | "9:16" | "1:1"
    remove_fillers: bool = True
    captions: bool = True
    sfx: bool = True
    zoom_ins: bool = True
    broll: bool = True
    excluded_filler_indices: List[int] = Field(default_factory=list)
    added_filler_indices: List[int] = Field(default_factory=list)
    selected_broll: List[Dict[str, Any]] = Field(default_factory=list)
    # If set, only render a slice of the source (viral-clip mode)
    clip_start: Optional[float] = None
    clip_end: Optional[float] = None
    clip_label: Optional[str] = None  # used to name the output file


# ---------- HELPERS ----------
async def update_project(pid: str, **fields) -> None:
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.projects.update_one({"id": pid}, {"$set": fields})


async def get_project(pid: str) -> Dict:
    doc = await db.projects.find_one({"id": pid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Project not found")
    return doc


# ---------- ROUTES: KEYS ----------
@api.get("/")
async def root():
    return {"ok": True, "app": "AI Video Editor", "version": "0.1.0"}


@api.get("/keys/status")
async def keys_status():
    keys = await get_keys()
    return {
        "groq": bool(keys.get("groq")),
        "cerebras": bool(keys.get("cerebras")),
        "pexels": bool(keys.get("pexels")),
        "pixabay": bool(keys.get("pixabay")),
    }


@api.post("/keys")
async def set_keys(body: KeysBody):
    payload = {k: v for k, v in body.model_dump().items() if v}
    if not payload:
        raise HTTPException(400, "No keys provided")
    await save_keys(payload)
    return {"ok": True, "updated": list(payload.keys())}


@api.post("/keys/test")
async def test_keys():
    k = await get_keys()
    g, c, p, pb = await asyncio.gather(
        ai.test_groq(k.get("groq", "")),
        ai.test_cerebras(k.get("cerebras", "")),
        ai.test_pexels(k.get("pexels", "")),
        ai.test_pixabay(k.get("pixabay", "")),
    )
    return {"groq": g, "cerebras": c, "pexels": p, "pixabay": pb}


# ---------- ROUTES: PROJECTS ----------
@api.post("/projects/upload")
async def upload_project(file: UploadFile = File(...)):
    pid = str(uuid.uuid4())
    ext = os.path.splitext(file.filename or "video.mp4")[1] or ".mp4"
    ext = ext.lower()
    if ext not in {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".mpeg", ".mpg", ".qt"}:
        raise HTTPException(400, f"Unsupported video type: {ext}")
    dst = DATA_DIR / "videos" / f"{pid}{ext}"

    total = 0
    async with aiofiles.open(dst, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            await out.write(chunk)
            total += len(chunk)

    if total == 0:
        dst.unlink(missing_ok=True)
        raise HTTPException(400, "Empty file uploaded")

    # Probe
    try:
        meta = vp.probe_video(str(dst))
    except Exception as e:
        dst.unlink(missing_ok=True)
        raise HTTPException(400, f"Could not read video file ({ext}): {str(e)[:200]}")

    project = {
        "id": pid,
        "user_id": USER_ID,
        "name": file.filename or f"Project-{pid[:8]}",
        "status": "uploaded",
        "status_message": "Uploaded, ready to analyze",
        "progress": 0,
        "original_path": str(dst),
        "size_bytes": total,
        "duration": meta.get("duration", 0),
        "width": meta.get("width", 0),
        "height": meta.get("height", 0),
        "fps": meta.get("fps", 30),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "transcript": None,
        "analysis": None,
        "output_path": None,
        "render_options": None,
    }
    await db.projects.insert_one(project)
    project.pop("_id", None)
    return project


@api.get("/projects")
async def list_projects():
    items = await db.projects.find(
        {"user_id": USER_ID},
        {"_id": 0, "transcript.words": 0, "transcript.segments": 0},
    ).sort("created_at", -1).to_list(100)
    return items


# ---------- CHUNKED UPLOAD (for large files bypassing ingress 413) ----------
UPLOAD_TMP = DATA_DIR / "uploads_tmp"
UPLOAD_TMP.mkdir(parents=True, exist_ok=True)


class UploadInit(BaseModel):
    model_config = ConfigDict(extra="ignore")
    filename: str
    size: int
    total_chunks: int


@api.post("/uploads/init")
async def upload_init(body: UploadInit):
    ext = os.path.splitext(body.filename or "video.mp4")[1].lower() or ".mp4"
    if ext not in {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".mpeg", ".mpg", ".qt"}:
        raise HTTPException(400, f"Unsupported video type: {ext}")
    if body.size <= 0 or body.total_chunks <= 0:
        raise HTTPException(400, "Invalid size/chunks")
    upload_id = uuid.uuid4().hex
    session_dir = UPLOAD_TMP / upload_id
    session_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "upload_id": upload_id,
        "filename": body.filename,
        "size": body.size,
        "total_chunks": body.total_chunks,
        "ext": ext,
        "received_chunks": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    async with aiofiles.open(session_dir / "manifest.json", "w") as f:
        await f.write(json.dumps(manifest))
    return {"upload_id": upload_id}


@api.post("/uploads/chunk/{upload_id}")
async def upload_chunk(upload_id: str, index: int, file: UploadFile = File(...)):
    session_dir = UPLOAD_TMP / upload_id
    manifest_path = session_dir / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(404, "Upload session not found")
    chunk_path = session_dir / f"chunk_{index:06d}"
    async with aiofiles.open(chunk_path, "wb") as out:
        while True:
            data = await file.read(1024 * 512)
            if not data:
                break
            await out.write(data)
    # Update manifest
    async with aiofiles.open(manifest_path, "r") as f:
        m = json.loads(await f.read())
    if index not in m["received_chunks"]:
        m["received_chunks"].append(index)
    async with aiofiles.open(manifest_path, "w") as f:
        await f.write(json.dumps(m))
    return {"ok": True, "received": len(m["received_chunks"]), "total": m["total_chunks"]}


@api.get("/uploads/status/{upload_id}")
async def upload_status(upload_id: str):
    """Get upload session status — used for resume."""
    manifest_path = UPLOAD_TMP / upload_id / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(404, "Upload session not found")
    async with aiofiles.open(manifest_path, "r") as f:
        m = json.loads(await f.read())
    return {
        "upload_id": upload_id,
        "filename": m.get("filename"),
        "size": m.get("size"),
        "total_chunks": m.get("total_chunks"),
        "received_chunks": sorted(m.get("received_chunks", [])),
    }


@api.post("/uploads/finalize/{upload_id}")
async def upload_finalize(upload_id: str):
    session_dir = UPLOAD_TMP / upload_id
    manifest_path = session_dir / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(404, "Upload session not found")
    async with aiofiles.open(manifest_path, "r") as f:
        m = json.loads(await f.read())
    if len(m["received_chunks"]) != m["total_chunks"]:
        raise HTTPException(400,
            f"Missing chunks: got {len(m['received_chunks'])}/{m['total_chunks']}")

    pid = str(uuid.uuid4())
    ext = m["ext"]
    dst = DATA_DIR / "videos" / f"{pid}{ext}"

    # Concatenate chunks in order
    total = 0
    async with aiofiles.open(dst, "wb") as out:
        for i in range(m["total_chunks"]):
            chunk_path = session_dir / f"chunk_{i:06d}"
            if not chunk_path.exists():
                dst.unlink(missing_ok=True)
                raise HTTPException(400, f"Chunk {i} missing on disk")
            async with aiofiles.open(chunk_path, "rb") as inp:
                while True:
                    data = await inp.read(1024 * 1024)
                    if not data:
                        break
                    await out.write(data)
                    total += len(data)

    # Clean up session dir
    try:
        shutil.rmtree(session_dir)
    except Exception:
        pass

    try:
        meta = vp.probe_video(str(dst))
    except Exception as e:
        dst.unlink(missing_ok=True)
        raise HTTPException(400, f"Could not read assembled video ({ext}): {str(e)[:200]}")

    project = {
        "id": pid,
        "user_id": USER_ID,
        "name": m.get("filename") or f"Project-{pid[:8]}",
        "status": "uploaded",
        "status_message": "Uploaded, ready to analyze",
        "progress": 0,
        "original_path": str(dst),
        "size_bytes": total,
        "duration": meta.get("duration", 0),
        "width": meta.get("width", 0),
        "height": meta.get("height", 0),
        "fps": meta.get("fps", 30),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "transcript": None,
        "analysis": None,
        "output_path": None,
        "render_options": None,
    }
    await db.projects.insert_one(project)
    project.pop("_id", None)
    return project


@api.get("/projects/{pid}")
async def project_detail(pid: str):
    return await get_project(pid)


@api.delete("/projects/{pid}")
async def delete_project(pid: str):
    doc = await db.projects.find_one({"id": pid})
    if not doc:
        raise HTTPException(404)
    # Clean files
    for k in ("original_path", "audio_path", "output_path"):
        p = doc.get(k)
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
    await db.projects.delete_one({"id": pid})
    return {"ok": True}


# ---------- ANALYZE PIPELINE ----------
async def _run_analysis(pid: str):
    try:
        keys = await get_keys()
        if not keys.get("groq"):
            await update_project(pid, status="error",
                                 status_message="Groq API key not configured. Add it in Settings.")
            return

        proj = await get_project(pid)
        await update_project(pid, status="extracting_audio", progress=5,
                             status_message="Extracting audio...")

        audio_path = str(DATA_DIR / "audio" / f"{pid}.mp3")
        await asyncio.to_thread(vp.extract_audio, proj["original_path"], audio_path)
        await update_project(pid, audio_path=audio_path, progress=15,
                             status="transcribing",
                             status_message="Transcribing with Whisper (Groq)...")

        transcript = await ai.transcribe_audio(audio_path, keys["groq"])
        await update_project(pid, transcript=transcript, progress=55,
                             status="analyzing",
                             status_message="AI analyzing for fillers, emphasis, B-roll...")

        analysis = await ai.analyze_transcript(transcript.get("words", []), keys)
        await update_project(pid, analysis=analysis, progress=100, status="ready",
                             status_message="Ready to edit & render")
    except Exception as e:
        logger.exception("Analysis failed")
        await update_project(pid, status="error", status_message=f"Analysis failed: {e}")


@api.post("/projects/{pid}/analyze")
async def analyze(pid: str, bg: BackgroundTasks):
    proj = await get_project(pid)
    if proj["status"] in ("transcribing", "analyzing", "extracting_audio", "rendering"):
        return {"ok": True, "status": proj["status"], "already_running": True}
    await update_project(pid, status="queued", status_message="Queued for analysis...", progress=1)
    bg.add_task(_run_analysis, pid)
    return {"ok": True, "status": "queued"}


# ---------- ASSET LIBRARY (user's own vault) ----------
LIBRARY_EXTS_VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".gif"}
LIBRARY_EXTS_IMAGE = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
LIBRARY_EXTS_ALL = LIBRARY_EXTS_VIDEO | LIBRARY_EXTS_IMAGE


def _asset_kind(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    if ext in LIBRARY_EXTS_VIDEO: return "video"
    if ext in LIBRARY_EXTS_IMAGE: return "image"
    return "other"


@api.get("/library")
async def library_list():
    """List all assets in the user's personal library."""
    items = []
    for p in sorted(LIBRARY_DIR.glob("*")):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext not in LIBRARY_EXTS_ALL:
            continue
        try:
            stat = p.stat()
        except Exception:
            continue
        aid = p.stem
        items.append({
            "id": f"lib_{aid}",
            "name": p.name,
            "kind": _asset_kind(p.name),
            "size": stat.st_size,
            "url": f"/api/library/file/{p.name}",
            "video_url": f"file://{p}",
            "local_path": str(p),
            "thumbnail": f"/api/library/thumb/{p.name}" if _asset_kind(p.name) == "image" else None,
            "is_custom": True,
            "provider": "library",
        })
    return {"items": items}


@api.post("/library/upload")
async def library_upload(file: UploadFile = File(...)):
    """Upload a single asset to the personal library."""
    fname = file.filename or "asset"
    ext = os.path.splitext(fname)[1].lower()
    if ext not in LIBRARY_EXTS_ALL:
        raise HTTPException(400, f"Unsupported asset type: {ext}")
    # Sanitize name
    stem = re.sub(r"[^\w.-]+", "_", os.path.splitext(fname)[0])[:60] or "asset"
    # Ensure unique
    candidate = LIBRARY_DIR / f"{stem}{ext}"
    i = 1
    while candidate.exists():
        candidate = LIBRARY_DIR / f"{stem}_{i}{ext}"
        i += 1
    total = 0
    async with aiofiles.open(candidate, "wb") as out:
        while True:
            chunk = await file.read(1024 * 512)
            if not chunk: break
            await out.write(chunk); total += len(chunk)
    if total == 0:
        candidate.unlink(missing_ok=True)
        raise HTTPException(400, "Empty file")
    return {"ok": True, "name": candidate.name, "size": total, "kind": _asset_kind(candidate.name)}


@api.delete("/library/{name}")
async def library_delete(name: str):
    """Delete an asset from the library (safe against path traversal)."""
    safe = os.path.basename(name)
    p = LIBRARY_DIR / safe
    if not p.exists() or not p.is_file():
        raise HTTPException(404)
    p.unlink()
    return {"ok": True}


@api.get("/library/file/{name}")
async def library_file(name: str):
    """Serve a library file for preview."""
    safe = os.path.basename(name)
    p = LIBRARY_DIR / safe
    if not p.exists() or not p.is_file():
        raise HTTPException(404)
    kind = _asset_kind(safe)
    media_type = "video/mp4" if kind == "video" else "image/jpeg"
    if safe.lower().endswith(".png"): media_type = "image/png"
    elif safe.lower().endswith(".webp"): media_type = "image/webp"
    elif safe.lower().endswith(".gif"): media_type = "image/gif"
    return FileResponse(p, media_type=media_type)


@api.get("/library/thumb/{name}")
async def library_thumb(name: str):
    """Serve image asset as thumbnail (same as file for now)."""
    return await library_file(name)


# ---------- B-ROLL SEARCH ----------
@api.get("/projects/{pid}/broll_search")
async def broll_search(pid: str, query: str, per_page: int = 6, orientation: str = "landscape"):
    """Merges Pexels + Pixabay results (Pixabay first - higher quality)."""
    keys = await get_keys()
    px_orient = "landscape" if orientation != "vertical" else "portrait"
    pb_orient = "vertical" if orientation == "vertical" else "horizontal"
    pexels_task = ai.search_pexels_video(query, keys.get("pexels", ""), per_page=per_page, orientation=px_orient)
    pixabay_task = ai.search_pixabay_video(query, keys.get("pixabay", ""), per_page=per_page, orientation=pb_orient)
    pex, pix = await asyncio.gather(pexels_task, pixabay_task, return_exceptions=True)
    pex = pex if isinstance(pex, list) else []
    pix = pix if isinstance(pix, list) else []
    # Interleave (Pixabay first — better curation) then Pexels
    merged = []
    for i in range(max(len(pix), len(pex))):
        if i < len(pix): merged.append(pix[i])
        if i < len(pex): merged.append(pex[i])
    return {"query": query, "results": merged, "counts": {"pixabay": len(pix), "pexels": len(pex)}}


@api.post("/projects/{pid}/broll_upload")
async def broll_upload(pid: str, file: UploadFile = File(...)):
    """Accept a user-uploaded B-roll clip; return a Pexels-shaped result object."""
    await get_project(pid)  # validate exists
    ext = os.path.splitext(file.filename or "clip.mp4")[1].lower() or ".mp4"
    if ext not in {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}:
        raise HTTPException(400, f"Unsupported B-roll type: {ext}")
    clip_id = f"user_{uuid.uuid4().hex[:8]}"
    dst = DATA_DIR / "broll" / f"{pid}_{clip_id}{ext}"

    total = 0
    async with aiofiles.open(dst, "wb") as out:
        while True:
            chunk = await file.read(1024 * 512)
            if not chunk:
                break
            await out.write(chunk)
            total += len(chunk)
    if total == 0:
        dst.unlink(missing_ok=True)
        raise HTTPException(400, "Empty file uploaded")

    try:
        meta = vp.probe_video(str(dst))
    except Exception as e:
        dst.unlink(missing_ok=True)
        raise HTTPException(400, f"Could not read B-roll: {str(e)[:200]}")

    # Return Pexels-compatible shape; video_url is our own media path
    backend_base = os.environ.get("PUBLIC_BACKEND_URL", "").rstrip("/")
    video_url = f"file://{dst}"  # Backend can read local file:// directly
    return {
        "id": clip_id,
        "duration": meta.get("duration", 0),
        "thumbnail": None,
        "video_url": video_url,
        "local_path": str(dst),
        "width": meta.get("width", 0),
        "height": meta.get("height", 0),
        "user": "You",
        "is_custom": True,
    }


# ---------- VIRAL CLIPS ----------
@api.post("/projects/{pid}/viral_clips")
async def viral_clips(pid: str):
    """Ask LLM to find the 3-5 best viral-worthy short clip moments in this project."""
    proj = await get_project(pid)
    transcript = proj.get("transcript") or {}
    words = transcript.get("words", [])
    if not words:
        raise HTTPException(400, "Project not analyzed yet")
    keys = await get_keys()
    duration = float(proj.get("duration", 0))
    clips = await ai.extract_viral_clips(words, keys, duration)
    await update_project(pid, viral_clips=clips)
    return {"clips": clips}


# ---------- RENDER PIPELINE ----------
async def _run_render(pid: str, opts: RenderOptions):
    try:
        proj = await get_project(pid)
        await update_project(pid, status="rendering", progress=5,
                             status_message="Preparing render...", render_options=opts.model_dump())

        transcript = proj.get("transcript") or {}
        words = transcript.get("words", [])
        analysis = proj.get("analysis") or {}
        duration = float(proj.get("duration", 0))
        src_w = int(proj.get("width") or 1920) or 1920
        src_h = int(proj.get("height") or 1080) or 1080

        # Determine output canvas from aspect
        out_w, out_h = vp.aspect_target_size(opts.aspect, src_w, src_h)

        # Reconcile filler indices
        auto_fillers = set(analysis.get("filler_indices", []))
        auto_fillers -= set(opts.excluded_filler_indices)
        auto_fillers |= set(opts.added_filler_indices)
        filler_indices = list(auto_fillers) if opts.remove_fillers else []

        # Compute keep segments (may be trimmed to viral clip window below)
        keep = vp.build_keep_segments(words, filler_indices, duration)

        # If viral-clip mode: restrict keep to [clip_start, clip_end] range
        clip_start = opts.clip_start
        clip_end = opts.clip_end
        if clip_start is not None and clip_end is not None:
            trimmed = []
            for seg in keep:
                s = max(seg["start"], clip_start)
                e = min(seg["end"], clip_end)
                if e - s > 0.08:
                    trimmed.append({"start": s, "end": e})
            keep = trimmed or [{"start": clip_start, "end": clip_end}]

        await update_project(pid, progress=15, status_message="Cutting segments...")

        cut_path = str(DATA_DIR / "output" / f"{pid}_cut.mp4")
        await asyncio.to_thread(vp.cut_and_concat, proj["original_path"], keep, cut_path,
                                out_w, out_h, src_w, src_h, None, None)
        await update_project(pid, progress=45, status_message="Generating animated captions...")

        # Build ASS captions
        ass_path = None
        if opts.captions and words:
            ass_path = str(DATA_DIR / "subtitles" / f"{pid}.ass")
            emphasis_set = set(analysis.get("emphasis_indices", [])) if opts.zoom_ins else set()
            await asyncio.to_thread(vp.generate_ass, words, ass_path, opts.style, out_w, out_h,
                                    emphasis_set, keep)

        # SFX events (whoosh at each cut boundary in output timeline)
        sfx_events = []
        if opts.sfx:
            t = 0.0
            for seg in keep[:-1]:
                t += (seg["end"] - seg["start"])
                sfx_events.append(t)

        # B-roll events: user-selected
        broll_events = []
        if opts.broll and opts.selected_broll:
            await update_project(pid, progress=55, status_message="Downloading B-roll clips...")
            for i, sel in enumerate(opts.selected_broll):
                url = sel.get("video_url") or ""
                moment_word_idx = int(sel.get("word_index", 0))
                if not url:
                    continue
                # Handle custom (already-local) vs Pexels (needs download)
                if url.startswith("file://") or sel.get("is_custom"):
                    local = sel.get("local_path") or url.replace("file://", "")
                    if not os.path.exists(local):
                        continue
                else:
                    local = str(DATA_DIR / "broll" / f"{pid}_broll_{i}.mp4")
                    ok = await vp.download_broll(url, local)
                    if not ok:
                        continue
                # Compute output time from word index remap
                if moment_word_idx < len(words):
                    orig_t = float(words[moment_word_idx].get("start", 0))
                else:
                    orig_t = 0
                # Simple remap
                offset = 0.0
                out_t = None
                for seg in keep:
                    s, e = seg["start"], seg["end"]
                    if orig_t < s:
                        out_t = offset
                        break
                    if orig_t <= e:
                        out_t = offset + (orig_t - s)
                        break
                    offset += (e - s)
                if out_t is None:
                    out_t = offset
                broll_events.append({
                    "local_path": local,
                    "out_start": max(0, out_t),
                    "out_duration": 3.5,
                })

        await update_project(pid, progress=70, status_message="Rendering final video...")

        # Choose output filename — separate for viral clips so main render is preserved
        if opts.clip_label:
            safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "_", opts.clip_label)[:40]
            output_path = str(DATA_DIR / "output" / f"{pid}_clip_{safe_label}.mp4")
        else:
            output_path = str(DATA_DIR / "output" / f"{pid}_final.mp4")

        await asyncio.to_thread(vp.render_final, cut_path, ass_path, sfx_events,
                                broll_events, SFX_DIR, output_path)

        # Cleanup intermediate
        try:
            os.remove(cut_path)
        except Exception:
            pass

        update_fields = {"status": "done", "progress": 100,
                         "status_message": "Render complete!"}
        if opts.clip_label:
            # Track in viral_renders dict on project
            proj_now = await get_project(pid)
            vr = proj_now.get("viral_renders") or {}
            vr[opts.clip_label] = output_path
            update_fields["viral_renders"] = vr
            update_fields["last_clip_label"] = opts.clip_label
        else:
            update_fields["output_path"] = output_path
        await update_project(pid, **update_fields)
    except Exception as e:
        logger.exception("Render failed")
        await update_project(pid, status="error", status_message=f"Render failed: {e}")


@api.post("/projects/{pid}/render")
async def render(pid: str, opts: RenderOptions, bg: BackgroundTasks):
    proj = await get_project(pid)
    if not proj.get("transcript"):
        raise HTTPException(400, "Project not analyzed yet")
    await update_project(pid, status="queued_render",
                         status_message="Render queued...", progress=1)
    bg.add_task(_run_render, pid, opts)
    return {"ok": True, "status": "queued_render"}


# ---------- MEDIA ----------
def _clean_filename(name: str) -> str:
    """Strip original extension and unsafe chars so downloads are always .mp4"""
    stem = os.path.splitext(name or "video")[0]
    stem = re.sub(r"[^\w\s.-]+", "_", stem).strip() or "video"
    return stem[:80]


@api.get("/projects/{pid}/download")
async def download_final(pid: str, clip: Optional[str] = None):
    """Download the main render, or a viral clip if ?clip=<label> is given."""
    proj = await get_project(pid)
    base = _clean_filename(proj.get("name") or "video")
    if clip:
        out = (proj.get("viral_renders") or {}).get(clip)
        fname = f"{base}_{clip}.mp4"
    else:
        out = proj.get("output_path")
        fname = f"{base}_edited.mp4"
    if not out or not os.path.exists(out):
        raise HTTPException(404, "Output not ready")
    return FileResponse(out, media_type="video/mp4", filename=fname)


@api.get("/media/clip/{pid}/{clip_label}")
async def media_clip(pid: str, clip_label: str):
    """Stream a specific viral clip output."""
    proj = await get_project(pid)
    vr = proj.get("viral_renders") or {}
    out = vr.get(clip_label)
    if not out or not os.path.exists(out):
        raise HTTPException(404)
    return FileResponse(out, media_type="video/mp4")


@api.get("/media/original/{pid}")
async def media_original(pid: str):
    proj = await get_project(pid)
    p = proj.get("original_path")
    if not p or not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p, media_type="video/mp4")


@api.get("/media/output/{pid}")
async def media_output(pid: str):
    proj = await get_project(pid)
    p = proj.get("output_path")
    if not p or not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p, media_type="video/mp4")


# ---------- APP WIRING ----------
app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
