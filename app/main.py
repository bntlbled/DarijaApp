"""FastAPI server. Run: uvicorn app.main:app --reload"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import asr, pipeline
from .export import to_markdown

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Darija transcriber")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

MAX_BYTES = 100 * 1024 * 1024


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/status")
def status():
    return {
        "asr_backends": asr.available(),
        "asr_default": asr.default_backend(),
        "claude": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
    }


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...), backend: str = Form(""), context: str = Form("")):
    audio = await file.read()
    if len(audio) > MAX_BYTES:
        raise HTTPException(413, "File too large (100 MB max).")
    try:
        segments = asr.transcribe(audio, file.filename or "audio.webm", backend or None)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # provider HTTP errors etc.
        raise HTTPException(502, f"Speech recognition failed: {e}")
    if not segments:
        raise HTTPException(422, "No speech was recognised in that audio.")
    return _run(segments, context)


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
