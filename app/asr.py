"""Speech recognition backends. Each returns a list of segments:
[{"start": float, "end": float, "text": str}]

Pick one with DARIJA_ASR = elevenlabs | openai | local (default: first one with a key).
"""

from __future__ import annotations

import os
import re

import httpx

TIMEOUT = httpx.Timeout(600.0, connect=20.0)


def available() -> list[str]:
    out = []
    if os.environ.get("ELEVENLABS_API_KEY"):
        out.append("elevenlabs")
    if os.environ.get("OPENAI_API_KEY"):
        out.append("openai")
    try:
        import faster_whisper  # noqa: F401
        out.append("local")
    except ImportError:
        pass
    return out


def default_backend() -> str | None:
    choice = os.environ.get("DARIJA_ASR")
    if choice:
        return choice
    av = available()
    return av[0] if av else None


def transcribe(audio: bytes, filename: str, backend: str | None = None, language: str | None = None) -> list[dict]:
    """language: None = server default, "auto" = let the engine detect (better when a clip is
    mostly French), or an ISO code such as "ara" / "fra"."""
    backend = backend or default_backend()
    if backend == "elevenlabs":
        return _elevenlabs(audio, filename, language)
    if backend == "openai":
        return _openai(audio, filename)
    if backend == "local":
        return _local(audio, filename, language)
    raise RuntimeError(
        "No speech recognition backend configured. Set ELEVENLABS_API_KEY or OPENAI_API_KEY, "
        "or install faster-whisper (see README)."
    )


# --- ElevenLabs Scribe: word timestamps, handles Arabic/French code-switching well ---

def _elevenlabs(audio: bytes, filename: str, language: str | None = None) -> list[dict]:
    data = {
        "model_id": os.environ.get("ELEVENLABS_MODEL", "scribe_v1"),
        "timestamps_granularity": "word",
        "tag_audio_events": "true",
        "diarize": "true",
    }
    lang = os.environ.get("ELEVENLABS_LANGUAGE", "ara") if language is None else language  # empty = auto-detect
    if lang == "auto":
        lang = ""
    if lang:
        data["language_code"] = lang
    r = httpx.post(
        "https://api.elevenlabs.io/v1/speech-to-text",
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        data=data,
        files={"file": (filename, audio)},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    words = [
        {"start": w.get("start", 0.0), "end": w.get("end", 0.0), "text": w["text"], "speaker": w.get("speaker_id")}
        for w in r.json().get("words", [])
        if w.get("type") in ("word", "audio_event")
    ]
    return group_words(words)


# --- OpenAI transcription: segment timestamps with whisper-1 verbose_json ---

def _openai(audio: bytes, filename: str) -> list[dict]:
    model = os.environ.get("OPENAI_ASR_MODEL", "whisper-1")
    data = {"model": model}
    if model == "whisper-1":
        data["response_format"] = "verbose_json"
        data["timestamp_granularities[]"] = "segment"
    if os.environ.get("OPENAI_ASR_PROMPT", "1"):
        # A prompt in the target style nudges Whisper toward Darija + French.
        data["prompt"] = os.environ.get(
            "OPENAI_ASR_PROMPT_TEXT",
            "واش راك؟ لاباس، الحمد لله. ça va, normal. شنو كاتدير دابا؟ c'est bon.",
        )
    r = httpx.post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        data=data,
        files={"file": (filename, audio)},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    js = r.json()
    if js.get("segments"):
        return [{"start": s["start"], "end": s["end"], "text": s["text"].strip()} for s in js["segments"]]
    return split_plain_text(js.get("text", ""))


# --- Local: faster-whisper, optionally with a Darija fine-tune converted to CTranslate2 ---

_local_model = None


def _local(audio: bytes, filename: str, language: str | None = None) -> list[dict]:
    global _local_model
    import io

    from faster_whisper import WhisperModel

    if _local_model is None:
        _local_model = WhisperModel(
            os.environ.get("LOCAL_WHISPER_MODEL", "large-v3"),
            device=os.environ.get("LOCAL_WHISPER_DEVICE", "auto"),
            compute_type=os.environ.get("LOCAL_WHISPER_COMPUTE", "int8"),
        )
    segs, _ = _local_model.transcribe(io.BytesIO(audio), language=None if language == "auto" else "ar", vad_filter=True)
    return [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segs]


# --- helpers ---

def group_words(words: list[dict], max_len: float = 12.0, gap: float = 0.7) -> list[dict]:
    """Group word timestamps into caption-sized segments on pauses, speaker changes,
    sentence punctuation, or a maximum length."""
    segs: list[dict] = []
    cur: list[dict] = []
    for w in words:
        if cur:
            pause = w["start"] - cur[-1]["end"]
            too_long = w["end"] - cur[0]["start"] > max_len
            new_speaker = w.get("speaker") != cur[-1].get("speaker")
            if pause > gap or too_long or new_speaker:
                segs.append(_join(cur))
                cur = []
        cur.append(w)
        if re.search(r"[.?!؟]$", w["text"]) and w["end"] - cur[0]["start"] > 3:
            segs.append(_join(cur))
            cur = []
    if cur:
        segs.append(_join(cur))
    return segs


def _join(ws: list[dict]) -> dict:
    text = "".join(w["text"] for w in ws) if any(w["text"].startswith(" ") for w in ws) else " ".join(w["text"] for w in ws)
    return {"start": ws[0]["start"], "end": ws[-1]["end"], "text": re.sub(r"\s+", " ", text).strip(),
            "speaker": ws[0].get("speaker")}


def split_plain_text(text: str) -> list[dict]:
    parts = [p.strip() for p in re.split(r"(?<=[.?!؟])\s+", text) if p.strip()]
    return [{"start": 0.0, "end": 0.0, "text": p} for p in parts]
