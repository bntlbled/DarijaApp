"""Evaluate the marker scorer on the labelled transcripts in samples/.

Paragraph-level and file-level accuracy. Lines with no cues count as "unknown".
Usage: python scripts/eval_dialect.py [samples_dir]
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.dialect import score_text  # noqa: E402


def parallel_paragraphs(path: Path):
    """Yield (label, paragraph) from files with Moroccan and Algerian sections."""
    label = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            label = "moroccan" if "Moroccan" in line else "algerian" if "Algerian" in line else None
            continue
        line = line.strip()
        if label and line and not line.startswith(("|", "---", "*", ">")):
            yield label, line.lstrip("#- ").strip()


def podcast_lines(path: Path):
    """Arabizi lines follow a **m:ss** timestamp; English lines are in *italics*."""
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if re.fullmatch(r"\*\*\d+:\d{2}(:\d{2})?\*\*", line.strip()) and i + 1 < len(lines):
            yield "algerian", lines[i + 1].strip()


def main(samples: Path):
    data = []
    for p in sorted(samples.glob("*.md")):
        if "side-by-side" in p.name:
            continue
        gen = podcast_lines(p) if p.name.startswith("podcast") else parallel_paragraphs(p)
        for lab, text in gen:
            data.append((p.name, lab, text))

    conf = Counter()
    per_file = {}
    for name, lab, text in data:
        s = score_text(text)
        pred = s.label()
        conf[(lab, pred)] += 1
        f = per_file.setdefault((name, lab), [0.0, 0.0])
        f[0] += s.moroccan
        f[1] += s.algerian

    print(f"{len(data)} labelled lines\n")
    print(f"{'gold':10} {'moroccan':>9} {'algerian':>9} {'mixed':>7} {'unknown':>8}")
    for gold in ("moroccan", "algerian"):
        row = [conf[(gold, p)] for p in ("moroccan", "algerian", "mixed", "unknown")]
        print(f"{gold:10} {row[0]:>9} {row[1]:>9} {row[2]:>7} {row[3]:>8}")
    decided = [(g, p) for (g, p), n in conf.items() for _ in range(n) if p in ("moroccan", "algerian")]
    if decided:
        acc = sum(g == p for g, p in decided) / len(decided)
        print(f"\nAccuracy on lines with a decision: {acc:.1%} ({len(decided)} lines)")
    wrong = [(n, l, t) for n, l, t in data if score_text(t).label() not in (l, "unknown", "mixed")]
    print(f"Wrong calls: {len(wrong)}")
    for n, l, t in wrong[:15]:
        s = score_text(t)
        print(f"  [{n} gold={l}] {t[:90]}  cues={[c.token for c in s.cues]}")

    print("\nFile-level (sum of cue weights):")
    for (name, lab), (m, a) in sorted(per_file.items()):
        pred = "moroccan" if m > a else "algerian"
        print(f"  {name:32} gold={lab:9} MA={m:6.1f} DZ={a:6.1f} -> {pred} {'OK' if pred == lab else 'WRONG'}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "samples")
