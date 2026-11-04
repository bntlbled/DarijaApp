"""Build app/static/demo.json from one of the hand-made podcast transcripts, so the
UI can be tried without API keys. Language tags here come from a simple word
list (the real app gets them from Claude); dialect comes from the marker scorer.

Usage: python scripts/build_demo.py samples/podcast-mina-transcript.md [max_lines]
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import pipeline  # noqa: E402
from app.language import LineOut, Token  # noqa: E402

FR = set("""
le la les de des du un une et est c'est ce ça qui que quoi pour pas mais avec dans sur par plus très bon bien
voilà donc alors je tu il elle nous vous ils elles mon mes ton tes son ses notre votre leur moi toi
normal jamais toujours chaque épisode domaine expérience officiel déjà problème société est-ce oui non parce
genre vraiment surtout comme même aussi enfin bref après avant juste trop peu beaucoup rien tout tous toute
école fac université travail langue langues français anglais niveau question exemple personne gens fois
""".split())
EN = set("input output stand up podcast queen of language content creator the and you is it okay ok yes".split())


def tag(tok: str) -> str:
    w = tok.lower().strip(".,!?;:…()\"«»—")
    if not w or w.startswith("["):
        return "other"
    if w in EN:
        return "en"
    if w in FR or re.search(r"[éèêàçùâîôû]", w) or re.match(r"^(l|d|qu|j|n|c|s)'[a-zé]", w):
        # Darija words with emphatic dots (ṣ ṭ ḍ) are not French
        return "darija" if re.search(r"[ṣṭḍ]", w) else "fr"
    return "darija"


def parse(path: Path):
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for i, line in enumerate(lines):
        m = re.fullmatch(r"\*\*(\d+):(\d{2})\*\*", line.strip())
        if m and i + 2 < len(lines):
            start = int(m[1]) * 60 + int(m[2])
            arabizi = lines[i + 1].strip()
            eng = lines[i + 2].strip()
            unclear = "[unclear]" in eng
            eng = re.sub(r"\s*\*\*\[unclear\]\*\*", "", eng).strip().strip("*")
            out.append((start, arabizi, eng, unclear))
    return out


def main(src: Path, max_lines: int):
    rows = parse(src)[:max_lines]
    segs, outs = [], {}
    for i, (start, arabizi, eng, unclear) in enumerate(rows):
        end = rows[i + 1][0] if i + 1 < len(rows) else start + 5
        segs.append({"id": i, "start": start, "end": end, "text": arabizi})
        outs[i] = LineOut(
            id=i, tokens=[Token(t=t, lang=tag(t)) for t in arabizi.split()], english=eng,
            dialect="unknown", dialect_confidence=0.0, dialect_cues=[], unclear=unclear,
        )
    res = pipeline.assemble(segs, outs, [("unknown", 0.0, len(segs), "")])
    res["dialect"]["reasoning"] = (
        "Demo built from your hand-made transcript: dialect comes from the marker scorer only, "
        "and language tags from a word list."
    )
    res["demo"] = {"source": src.name}
    dest = ROOT / "app" / "static" / "demo.json"
    dest.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {dest} with {len(segs)} lines; dialect={res['dialect']['label']} {res['dialect']['confidence']}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 60)
