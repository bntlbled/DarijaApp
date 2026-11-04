from fastapi.testclient import TestClient

from app import asr, dialect, language, pipeline
from app.export import to_markdown
from app.language import BatchOut, LineOut, Token
from app.main import app

client = TestClient(app)


def test_moroccan_markers():
    s = dialect.score_text("Chno l-far9 bin l-lyaf dyal l3adalat dyal wa7ed kayjri daba")
    assert s.label() == "moroccan"
    assert {c.token for c in s.cues} >= {"dyal", "daba", "kayjri"}


def test_algerian_markers():
    s = dialect.score_text("Wach howa l-far9 ta3 l3adalat, rani nkhdem dork bezzaf")
    assert s.label() == "algerian"


def test_shared_words_are_not_evidence():
    assert dialect.score_text("kanet kanou kayn kifach chwiya").label() == "unknown"


def test_combine_prefers_markers_without_claude():
    m = dialect.score_text("ta3 rani dork zouj")
    assert dialect.combine("unknown", 0.0, m)[0] == "algerian"


def test_combine_markers_can_overrule_weak_claude():
    m = dialect.score_text("dyal daba kandir joj ghadi wakha 3afak")
    lab, conf = dialect.combine("algerian", 0.2, m)
    assert lab == "moroccan"


def test_group_words_splits_on_pause_and_speaker():
    words = [
        {"start": 0.0, "end": 0.3, "text": "salam", "speaker": "a"},
        {"start": 0.35, "end": 0.6, "text": "khoya", "speaker": "a"},
        {"start": 2.0, "end": 2.3, "text": "ça", "speaker": "a"},
        {"start": 2.35, "end": 2.6, "text": "va", "speaker": "b"},
    ]
    segs = asr.group_words(words)
    assert [s["text"] for s in segs] == ["salam khoya", "ça", "va"]


def fake_process(lines, context_hint=""):
    out = []
    for l in lines:
        out.append(LineOut(
            id=l["id"],
            tokens=[Token(t="rani", lang="darija"), Token(t="fatigué", lang="fr"), Token(t="dork", lang="darija")],
            english="I'm tired now", dialect="algerian", dialect_confidence=0.7,
            dialect_cues=["rani"], unclear=False,
        ))
    return BatchOut(lines=out, overall_dialect="algerian", overall_confidence=0.8, overall_reasoning="rani, dork")


def test_pipeline_and_api(monkeypatch):
    monkeypatch.setattr(language, "process_lines", fake_process)
    r = client.post("/api/process-text", json={"text": "راني fatigué دورك\nline two"})
    assert r.status_code == 200, r.text
    js = r.json()
    assert js["dialect"]["label"] == "algerian"
    assert len(js["lines"]) == 2
    assert js["languages"]["fr"] > 0.3
    md = to_markdown(js, "Test")
    assert "rani fatigué dork" in md and "*I'm tired now*" in md


def test_transcribe_endpoint_uses_asr(monkeypatch):
    monkeypatch.setattr(language, "process_lines", fake_process)
    monkeypatch.setattr(asr, "transcribe", lambda a, n, b=None: [{"start": 1.0, "end": 2.0, "text": "راني"}])
    r = client.post("/api/transcribe", files={"file": ("a.webm", b"xx", "audio/webm")})
    assert r.status_code == 200, r.text
    assert r.json()["lines"][0]["start"] == 1.0


def test_no_backend_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(asr, "default_backend", lambda: None)
    r = client.post("/api/transcribe", files={"file": ("a.webm", b"xx", "audio/webm")})
    assert r.status_code == 400 and "No speech recognition backend" in r.json()["detail"]


def test_demo_loads():
    r = client.get("/api/demo")
    assert r.status_code == 200 and r.json()["dialect"]["label"] == "algerian"


def test_batching(monkeypatch):
    calls = []
    def proc(lines, h=""):
        calls.append(len(lines)); return fake_process(lines)
    monkeypatch.setattr(language, "process_lines", proc)
    pipeline.run([{"text": f"l{i}"} for i in range(95)])
    assert calls == [40, 40, 15]
