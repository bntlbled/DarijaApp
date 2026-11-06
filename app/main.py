"""FastAPI server. Run: uvicorn app.main:app --reload"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import asr, instagram, pipeline
from .export import to_markdown

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Darija transcriber")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

MAX_BYTES = 100 * 1024 * 1024


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(ROOT / "static" / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    # Served from the root so its scope covers the share target.
    return FileResponse(ROOT / "static" / "sw.js", media_type="text/javascript")


@app.get("/api/status")
def status():
    return {
        "asr_backends": asr.available(),
        "asr_default": asr.default_backend(),
        "claude": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
        "instagram": instagram.configured(),
        "ffmpeg": instagram.ffmpeg_available(),
    }


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...), backend: str = Form(""), context: str = Form(""),
                     language: str = Form("")):
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large (100 MB max).")
    name = file.filename or "audio.webm"
    if instagram.is_video(name, file.content_type):
        data, name = _extract(data, name)
    return _transcribe_audio(data, name, backend, language, context)


def _extract(video: bytes, name: str) -> tuple[bytes, str]:
    try:
        return instagram.extract_audio(video, name)
    except instagram.InstagramError as e:
        raise HTTPException(422, str(e))


def _transcribe_audio(audio: bytes, name: str, backend: str, language: str, context: str) -> dict:
    try:
        segments = asr.transcribe(audio, name, backend or None, language or None)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # provider HTTP errors etc.
        raise HTTPException(502, f"Speech recognition failed: {e}")
    if not segments:
        raise HTTPException(422, "No speech was recognised in that audio.")
    return _run(segments, context)


# ---------- Instagram ----------

def _ig(fn, *a):
    try:
        return fn(*a)
    except instagram.InstagramError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Couldn't reach Instagram: {e}")


@app.get("/api/instagram/media")
def instagram_media(limit: int = 30):
    """The connected account's own videos and reels."""
    acct = _ig(instagram.account)
    return {"account": acct, "videos": _ig(instagram.list_videos, max(1, min(limit, 100)))}


class InstagramIn(BaseModel):
    media_id: str = ""
    url: str = ""
    context: str = ""
    backend: str = ""
    language: str = ""


@app.post("/api/instagram/transcribe")
def instagram_transcribe(body: InstagramIn):
    if body.media_id:
        media = _ig(instagram.get_media, body.media_id)
    elif body.url:
        media = _ig(instagram.find_own_by_url, body.url)
    else:
        raise HTTPException(422, "Send a media_id or a reel link.")
    video = _ig(instagram.download_video, media)
    audio, name = _extract(video, f"reel-{media['id']}.mp4")
    context = " ".join(x for x in [body.context, f"Instagram caption: {(media.get('caption') or '')[:300]}"
                                   if media.get("caption") else ""] if x)
    out = _transcribe_audio(audio, name, body.backend, body.language, context)
    out["source"] = {"kind": "instagram", "permalink": media.get("permalink"), "id": media["id"]}
    return out


# ---------- share target (Android: Share > Darija Transcriber) ----------

SHARE_DIR = Path(tempfile.gettempdir()) / "darija-shared"
SHARE_TTL = 3600


@app.post("/share")
async def share_target(media: UploadFile | None = File(None), title: str = Form(""), text: str = Form(""),
                       url: str = Form("")):
    if media is not None and media.filename:
        data = await media.read()
        if len(data) > MAX_BYTES:
            return RedirectResponse("/?share_error=too_large", status_code=303)
        SHARE_DIR.mkdir(exist_ok=True)
        for old in SHARE_DIR.iterdir():
            if time.time() - old.stat().st_mtime > SHARE_TTL:
                old.unlink(missing_ok=True)
        ext = os.path.splitext(media.filename)[1][:6] or ".mp4"
        sid = uuid.uuid4().hex
        (SHARE_DIR / f"{sid}{ext}").write_bytes(data)
        return RedirectResponse(f"/?shared={sid}{ext}", status_code=303)
    link = url or next(iter(re.findall(r"https?://\S+", f"{text} {title}")), "")
    return RedirectResponse(f"/?ig={quote(link)}" if link else "/", status_code=303)


@app.get("/api/shared/{name}")
def shared_file(name: str):
    if not re.fullmatch(r"[0-9a-f]{32}\.[A-Za-z0-9]{1,5}", name):
        raise HTTPException(404, "Not found")
    p = SHARE_DIR / name
    if not p.exists():
        raise HTTPException(404, "That shared file has expired. Share it again.")
    return Response(p.read_bytes(), media_type="application/octet-stream")


class TextIn(BaseModel):
    text: str
    context: str = ""


@app.post("/api/process-text")
def process_text(body: TextIn):
    """Skip ASR: paste a transcript (Arabic script, Arabizi or mixed), one line per segment."""
    segs = [{"start": 0.0, "end": 0.0, "text": l.strip()} for l in body.text.splitlines() if l.strip()]
    if not segs:
        raise HTTPException(422, "Paste at least one line.")
    return _run(segs, body.context)


def _run(segments, context):
    try:
        return pipeline.run(segments, context)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    except Exception as e:
        raise HTTPException(502, f"Language pass failed: {type(e).__name__}: {e}")


@app.get("/api/demo")
def demo():
    p = ROOT / "static" / "demo.json"
    return JSONResponse(json.loads(p.read_text(encoding="utf-8")))


class ExportIn(BaseModel):
    result: dict
    title: str = "Transcript"


@app.post("/api/export.md", response_class=PlainTextResponse)
def export_md(body: ExportIn):
    return to_markdown(body.result, body.title)
