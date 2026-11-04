"""Export a result in the same Markdown layout as the hand-made podcast files."""


def fmt_ts(sec: float) -> str:
    sec = int(sec or 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def to_markdown(result: dict, title: str = "Transcript") -> str:
    d = result.get("dialect", {})
    langs = ", ".join(f"{k} {v:.0%}" for k, v in result.get("languages", {}).items())
    out = [
        f"# {title}: transliteration and translation",
        "",
        "Line-by-line Arabizi transliteration with the English translation directly below each line. "
        "Conventions: 3 = ع, 7 = ح, 9 = ق, gh = غ, kh = خ, ch = ش, 2 = ء.",
        "",
        f"**Dialect**: {d.get('label', 'unknown').title()} ({d.get('confidence', 0):.0%} confidence). "
        f"{d.get('reasoning', '')}",
        f"**Languages**: {langs}",
        "",
        "---",
        "",
    ]
    for line in result.get("lines", []):
        arabizi = " ".join(t["t"] for t in line["tokens"])
        flag = " **[unclear]**" if line.get("unclear") else ""
        out += [f"**{fmt_ts(line.get('start', 0))}**", arabizi, f"*{line.get('english', '')}*{flag}", ""]
    return "\n".join(out)
