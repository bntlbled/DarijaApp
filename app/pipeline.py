"""Glue: ASR segments -> Claude language pass -> dialect blending -> result JSON."""

from __future__ import annotations

from collections import Counter

from . import dialect as dz
from . import language

BATCH = 40  # lines per Claude call


def run(segments: list[dict], context_hint: str = "") -> dict:
    segments = [s for s in segments if s.get("text", "").strip()]
    for i, s in enumerate(segments):
        s["id"] = i
    outs: dict[int, language.LineOut] = {}
    overall_votes = []
    for k in range(0, len(segments), BATCH):
        batch = segments[k : k + BATCH]
        res = language.process_lines(batch, context_hint)
        for line in res.lines:
            outs[line.id] = line
        overall_votes.append((res.overall_dialect, res.overall_confidence, len(batch), res.overall_reasoning))
    return assemble(segments, outs, overall_votes)


def assemble(segments: list[dict], outs: dict, overall_votes: list) -> dict:
    lines = []
    all_darija_tokens: list[str] = []
    lang_counts: Counter = Counter()
    for s in segments:
        o = outs.get(s["id"])
        if o is None:
            lines.append({**s, "tokens": [{"t": s["text"], "lang": "other"}], "english": "",
                          "dialect": "unknown", "confidence": 0.0, "cues": [], "unclear": True})
            continue
        toks = [t.model_dump() if hasattr(t, "model_dump") else t for t in o.tokens]
        darija = [t["t"] for t in toks if t["lang"] == "darija"]
        all_darija_tokens += darija
        lang_counts.update(t["lang"] for t in toks)
        m = dz.score_tokens(darija)
        label, conf = dz.combine(o.dialect, o.dialect_confidence, m)
        cues = list(dict.fromkeys(o.dialect_cues + [f"{c.token} ({c.dialect[:2].upper()})" for c in m.cues]))
        lines.append({
            "id": s["id"], "start": s.get("start", 0.0), "end": s.get("end", 0.0), "speaker": s.get("speaker"),
            "source": s["text"], "tokens": toks, "english": o.english,
            "dialect": label, "confidence": round(conf, 2), "cues": cues[:8], "unclear": o.unclear,
            "claude_dialect": o.dialect, "markers": {"moroccan": m.moroccan, "algerian": m.algerian},
        })

    # Overall: Claude's batch verdicts (weighted by lines) blended with markers over the whole clip.
    total = sum(n for *_, n, _ in overall_votes) or 1
    p_ma = 0.0
    for lab, conf, n, _ in overall_votes:
        p = 0.5 + 0.5 * conf if lab == "moroccan" else 0.5 - 0.5 * conf if lab == "algerian" else 0.5
        p_ma += p * n / total
    claude_label = "moroccan" if p_ma > 0.55 else "algerian" if p_ma < 0.45 else "mixed"
    claude_conf = abs(p_ma - 0.5) * 2
    clip_markers = dz.score_tokens(all_darija_tokens)
    label, conf = dz.combine(claude_label, claude_conf, clip_markers)

    n_tok = sum(lang_counts.values()) or 1
    return {
        "dialect": {
            "label": label,
            "confidence": round(conf, 2),
            "reasoning": " ".join(r for *_, r in overall_votes if r),
            "markers": {
                "moroccan": round(clip_markers.moroccan, 1),
                "algerian": round(clip_markers.algerian, 1),
                "top_cues": [c for c, _ in Counter(f"{c.token} ({c.dialect})" for c in clip_markers.cues).most_common(10)],
            },
            "line_votes": dict(Counter(l["dialect"] for l in lines)),
        },
        "languages": {k: round(v / n_tok, 3) for k, v in lang_counts.most_common()},
        "lines": lines,
    }
