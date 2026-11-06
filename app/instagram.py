"""Getting audio out of Instagram, within what Instagram allows.

Instagram's Terms of Use forbid collecting content "in an automated way without our
express permission", and its official API (Instagram API with Instagram Login) only
returns media owned by the *professional* account that signed in. So this module offers:

1. Your own reels, via the official API: set INSTAGRAM_ACCESS_TOKEN (a token from
   Business Login for Instagram with the instagram_business_basic permission). We list
   your videos, fetch `media_url`, and pull the audio out with ffmpeg. Instagram omits
   `media_url` when a reel has copyrighted audio (licensed music); then use option 2.
2. Any video you saved yourself (Instagram's own download, a screen recording, or the
   creator sent it): upload it or share it to the app from your phone. We strip the
   audio with ffmpeg before speech recognition, which keeps uploads small.

A pasted reel link is matched against your own media; links to other people's reels
are not downloaded (that would be scraping), and the user is told how to save it instead.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile

import httpx

GRAPH = "https://graph.instagram.com"
API_VERSION = os.environ.get("INSTAGRAM_API_VERSION", "v25.0")
MEDIA_FIELDS = "id,caption,media_type,media_product_type,media_url,permalink,thumbnail_url,timestamp"
TIMEOUT = httpx.Timeout(120.0, connect=20.0)
MAX_VIDEO_BYTES = 300 * 1024 * 1024

_SHORTCODE = re.compile(r"instagram\.com/(?:[A-Za-z0-9_.]+/)?(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)")


class InstagramError(RuntimeError):
    """A problem the user can act on; the message is shown as is."""


def token() -> str | None:
    return os.environ.get("INSTAGRAM_ACCESS_TOKEN") or None


def configured() -> bool:
    return bool(token())


def shortcode(url: str) -> str | None:
    m = _SHORTCODE.search(url or "")
    return m.group(1) if m else None


# ---------- official API: the signed-in professional account's own media ----------

def _get(path: str, params: dict) -> dict:
    tok = token()
    if not tok:
        raise InstagramError(
            "Instagram isn't connected. Add INSTAGRAM_ACCESS_TOKEN to .env (see README), "
            "or upload the video file instead."
        )
    r = httpx.get(f"{GRAPH}/{API_VERSION}/{path}", params={**params, "access_token": tok}, timeout=TIMEOUT)
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message", r.text)
        except ValueError:
            msg = r.text
        raise InstagramError(f"Instagram API error: {msg}")
    return r.json()


def account() -> dict:
    return _get("me", {"fields": "user_id,username,account_type"})


def list_videos(limit: int = 50) -> list[dict]:
    """The account's own videos and reels, newest first."""
    out: list[dict] = []
    params = {"fields": MEDIA_FIELDS, "limit": min(limit, 50)}
    js = _get("me/media", params)
    while True:
        for m in js.get("data", []):
            if m.get("media_type") == "VIDEO":
                out.append(_slim(m))
        nxt = js.get("paging", {}).get("next")
        if len(out) >= limit or not nxt:
            break
        r = httpx.get(nxt, timeout=TIMEOUT)
        r.raise_for_status()
        js = r.json()
    return out[:limit]


def _slim(m: dict) -> dict:
    return {
        "id": m["id"],
        "caption": (m.get("caption") or "")[:200],
        "kind": m.get("media_product_type") or m.get("media_type"),
        "permalink": m.get("permalink"),
        "thumbnail": m.get("thumbnail_url"),
        "timestamp": m.get("timestamp"),
        "has_video_url": bool(m.get("media_url")),
    }


def get_media(media_id: str) -> dict:
    if not re.fullmatch(r"\d{5,30}", media_id or ""):
        raise InstagramError("That doesn't look like an Instagram media id.")
    return _get(media_id, {"fields": MEDIA_FIELDS})


def find_own_by_url(url: str) -> dict:
    code = shortcode(url)
    if not code:
        raise InstagramError("That isn't an Instagram reel or post link.")
    if configured():
        js = _get("me/media", {"fields": MEDIA_FIELDS, "limit": 50})
        while True:
            for m in js.get("data", []):
                if shortcode(m.get("permalink", "")) == code:
                    return m
            nxt = js.get("paging", {}).get("next")
            if not nxt:
                break
            r = httpx.get(nxt, timeout=TIMEOUT)
            r.raise_for_status()
            js = r.json()
    raise InstagramError(
        "This app can only fetch reels from your own connected Instagram account; Instagram's terms "
        "don't allow downloading other people's reels automatically. To transcribe this one, save the "
        "video (the creator's download option, or a screen recording) and upload or share it here."
    )


def download_video(media: dict) -> bytes:
    if media.get("media_type") != "VIDEO":
        raise InstagramError("That post has no video, so there's no audio to transcribe.")
    url = media.get("media_url")
    if not url:
        raise InstagramError(
            "Instagram won't hand over this video through the API, usually because the reel uses "
            "licensed music. Download it from the Instagram app and upload the file instead."
        )
    with httpx.stream("GET", url, timeout=TIMEOUT, follow_redirects=True) as r:
        r.raise_for_status()
        buf = bytearray()
        for chunk in r.iter_bytes():
            buf += chunk
            if len(buf) > MAX_VIDEO_BYTES:
                raise InstagramError("That video is too large (300 MB max).")
    return bytes(buf)


# ---------- audio extraction ----------

def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def is_video(filename: str, content_type: str | None = None) -> bool:
    if content_type and content_type.startswith("video/"):
        return True
    if content_type and content_type.startswith("audio/"):
        return False
    return bool(re.search(r"\.(mp4|mov|m4v|webm|mkv|3gp)$", filename or "", re.I))


def extract_audio(video: bytes, filename: str = "video.mp4") -> tuple[bytes, str]:
    """Return (audio bytes, filename): mono 16 kHz MP3, which every speech engine accepts and
    keeps a one-minute reel under 1 MB. Without ffmpeg the video goes through unchanged
    (ElevenLabs and OpenAI both accept MP4)."""
    if not ffmpeg_available():
        return video, filename
    suffix = os.path.splitext(filename)[1] or ".mp4"
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "in" + suffix), os.path.join(d, "out.mp3")
        with open(src, "wb") as f:
            f.write(video)
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
             "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", dst],
            capture_output=True, timeout=600,
        )
        if p.returncode != 0 or not os.path.exists(dst):
            err = p.stderr.decode(errors="replace").strip().splitlines()
            if any("does not contain any stream" in l or "Output file #0 does not contain" in l for l in err):
                raise InstagramError("That video has no audio track.")
            raise InstagramError(f"Couldn't read the audio from that video: {err[-1] if err else 'ffmpeg failed'}")
        with open(dst, "rb") as f:
            audio = f.read()
    base = os.path.splitext(os.path.basename(filename))[0] or "audio"
    return audio, base + ".mp3"
