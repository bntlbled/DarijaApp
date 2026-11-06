import subprocess

import pytest
from fastapi.testclient import TestClient

from app import asr, instagram, language
from app.main import app
from tests.test_app import fake_process

client = TestClient(app)
needs_ffmpeg = pytest.mark.skipif(not instagram.ffmpeg_available(), reason="ffmpeg not installed")


def make_video(tmp_path, audio=True) -> bytes:
    out = tmp_path / "v.mp4"
    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1"]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-shortest"]
    subprocess.run(cmd + ["-pix_fmt", "yuv420p", str(out)], check=True)
    return out.read_bytes()


def test_shortcode():
    assert instagram.shortcode("https://www.instagram.com/reel/C9xYz_1-ab/?igsh=xx") == "C9xYz_1-ab"
    assert instagram.shortcode("https://instagram.com/someone/p/ABC123/") == "ABC123"
    assert instagram.shortcode("https://example.com/reel/abc") is None


@needs_ffmpeg
def test_extract_audio(tmp_path):
    audio, name = instagram.extract_audio(make_video(tmp_path), "clip.mp4")
    assert name == "clip.mp3" and len(audio) > 1000
    assert audio[:3] == b"ID3" or audio[0] == 0xFF  # ID3 tag or MPEG frame sync


@needs_ffmpeg
def test_video_without_audio_is_clear_error(tmp_path):
    with pytest.raises(instagram.InstagramError, match="no audio"):
        instagram.extract_audio(make_video(tmp_path, audio=False), "silent.mp4")


@needs_ffmpeg
def test_video_upload_is_converted_before_asr(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(language, "process_lines", fake_process)
    def fake_asr(a, n, b=None, l=None):
        seen.update(name=n, size=len(a), lang=l)
        return [{"start": 0.0, "end": 1.0, "text": "راني"}]
    monkeypatch.setattr(asr, "transcribe", fake_asr)
    r = client.post("/api/transcribe", files={"file": ("reel.mp4", make_video(tmp_path), "video/mp4")},
                    data={"language": "auto"})
    assert r.status_code == 200, r.text
    assert seen["name"] == "reel.mp3" and seen["lang"] == "auto"


def test_other_peoples_links_are_refused(monkeypatch):
    monkeypatch.delenv("INSTAGRAM_ACCESS_TOKEN", raising=False)
    r = client.post("/api/instagram/transcribe", json={"url": "https://www.instagram.com/reel/XYZ/"})
    assert r.status_code == 400 and "own connected Instagram account" in r.json()["detail"]


def test_own_reel_by_link(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "t")
    calls = []
    def fake_get(path, params):
        calls.append(path)
        return {"data": [
            {"id": "111111", "media_type": "IMAGE", "permalink": "https://www.instagram.com/p/AAA/"},
            {"id": "222222", "media_type": "VIDEO", "media_url": "https://cdn/x.mp4", "caption": "Oran vlog",
             "permalink": "https://www.instagram.com/reel/BBB/"},
        ]}
    monkeypatch.setattr(instagram, "_get", fake_get)
    monkeypatch.setattr(instagram, "download_video", lambda m: b"video")
    monkeypatch.setattr(instagram, "extract_audio", lambda v, n: (b"audio", "reel.mp3"))
    ctx = {}
    monkeypatch.setattr(asr, "transcribe", lambda a, n, b=None, l=None: [{"start": 0.0, "end": 1.0, "text": "x"}])
    def proc(lines, hint=""):
        ctx["hint"] = hint
        return fake_process(lines)
    monkeypatch.setattr(language, "process_lines", proc)
    r = client.post("/api/instagram/transcribe", json={"url": "https://instagram.com/reel/BBB/?igsh=1"})
    assert r.status_code == 200, r.text
    assert r.json()["source"]["id"] == "222222"
    assert "Oran vlog" in ctx["hint"]


def test_music_locked_reel():
    with pytest.raises(instagram.InstagramError, match="licensed music"):
        instagram.download_video({"id": "1", "media_type": "VIDEO"})


def test_media_list_keeps_only_videos(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "t")
    def fake_get(path, params):
        if path == "me":
            return {"username": "me_dz", "account_type": "MEDIA_CREATOR"}
        return {"data": [{"id": "1", "media_type": "IMAGE"},
                         {"id": "2", "media_type": "VIDEO", "media_product_type": "REELS", "media_url": "u"},
                         {"id": "3", "media_type": "VIDEO"}]}
    monkeypatch.setattr(instagram, "_get", fake_get)
    js = client.get("/api/instagram/media").json()
    assert [v["id"] for v in js["videos"]] == ["2", "3"]
    assert [v["has_video_url"] for v in js["videos"]] == [True, False]


def test_share_target_file_roundtrip():
    r = client.post("/share", files={"media": ("vid.mp4", b"abc", "video/mp4")}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/?shared=")
    name = r.headers["location"].split("=", 1)[1]
    assert client.get(f"/api/shared/{name}").content == b"abc"
    assert client.get("/api/shared/..%2Fetc").status_code == 404


def test_share_target_link():
    r = client.post("/share", data={"text": "Look https://www.instagram.com/reel/ABC/?igsh=z"}, follow_redirects=False)
    assert r.status_code == 303 and "ig=https" in r.headers["location"]


def test_manifest_has_share_target():
    js = client.get("/manifest.webmanifest").json()
    assert js["share_target"]["action"] == "/share"
