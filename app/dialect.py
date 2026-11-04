"""Marker-based Moroccan vs Algerian Darija scorer.

Works on Arabizi (Latin-script) text, the format the language pass produces.
It is deliberately transparent: every point comes from a named cue, so the UI
can show *why* a line was labelled one way. Claude's own judgement is blended
in by `combine()`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# (pattern, weight, explanation). Patterns match whole lowercase tokens with
# leading "l-"/"d-"/"s-" style article prefixes stripped.
MOROCCAN: list[tuple[str, float, str]] = [
    (r"d[iy]a?l(i|ek|ak|o|ou|ha|na|kom|hom)?", 3.0, "dyal (possessive 'of')"),
    (r"daba", 3.0, "daba ('now')"),
    (r"j(o|ou)j", 2.5, "joj ('two')"),
    (r"bzaf", 1.0, "bzaf ('a lot')"),
    (r"ghadi|ghad", 2.0, "ghadi (future marker)"),
    (r"wakha|wakhkha", 2.5, "wakha ('ok')"),
    (r"3afak|3afakom", 2.5, "3afak ('please')"),
    (r"a?chno|a?chnou|chnu", 1.0, "chno ('what')"),
    (r"ach", 1.5, "ach ('what')"),
    (r"fin|fayn|fine", 1.5, "fin ('where')"),
    (r"imta|fo9ach", 2.0, "imta / fo9ach ('when')"),
    (r"mzyan|mzyana|mezyan", 1.0, "mzyan ('good')"),
    (r"bghit|bgha|bghina|kanbghi|bghiti", 1.5, "bgha ('want')"),
    (r"drari", 2.5, "drari ('kids/guys')"),
    (r"7it", 1.5, "7it ('because')"),
    (r"chi", 1.0, "chi ('some')"),
    (r"hadchi", 1.0, "hadchi ('this')"),
    (r"ma[a-z]+ch?", 0.0, ""),  # placeholder: negation is shared, keeps index stable
    (r"khass(ni|ek|ak|o|ha|na|kom|hom)?|khassek", 2.0, "khass ('must')"),
    (r"mrat|merrat", 0.8, "mrat ('times')"),
    (r"bezaf", 0.0, ""),
]

ALGERIAN: list[tuple[str, float, str]] = [
    (r"n?ta3(i|ek|ak|o|ou|ha|na|kom|hom|hem)?", 3.0, "ta3 / nta3 (possessive 'of')"),
    (r"ra(h|ni|k|ki|hi|ho|hou|na|kom|hom|hem)", 2.5, "rah / rani / rak ('is now')"),
    (r"dork|dorka|drk|dorek", 3.0, "dork ('now')"),
    (r"z(o|ou)dj?|zouj", 2.5, "zouj ('two')"),
    (r"bezzaf|bezaf", 1.5, "bezzaf ('a lot')"),
    (r"kima", 1.5, "kima ('like')"),
    (r"ki", 1.0, "ki ('when')"),
    (r"3la ?khater|3lakhater|khater", 2.0, "3la khater ('because')"),
    (r"win|winta|winek", 1.5, "win ('where')"),
    (r"wa9tach|wa9teh", 2.0, "wa9tach ('when')"),
    (r"t?najem|nnajem|ynajem|tnajmou|najmou", 2.5, "najem ('can')"),
    (r"mli7|mlih|mli7a", 1.5, "mli7 ('good')"),
    (r"barka", 1.5, "barka ('enough')"),
    (r"yaser|yasser", 2.0, "yaser ('a lot')"),
    (r"khatrat|khatra", 2.0, "khatra ('time/once')"),
    (r"lazem|lazmek|lazmni", 1.0, "lazem ('must')"),
    (r"kifech|kifeh", 1.5, "kifech ('how')"),
    (r"(n|t|y)?7ab(it|iti|ina|ou)?|n7eb|t7eb|y7eb", 1.0, "7ab ('want')"),
    (r"rfed|yrfed|nrfed", 2.0, "rfed ('lift')"),
    (r"wesh|wech", 1.0, "wesh ('what')"),
    (r"bark", 1.0, "bark ('only')"),
    (r"chwiya|chwia", 0.0, ""),
]

# Moroccan present-tense ka-/ta- prefix on verbs: kandir, katdir, kaydir, tandir.
KA_PREFIX = re.compile(r"^(ka|ta)(n|t|y)[a-z0-9]{2,}$")
KA_EXCLUDE = {
    "kayn", "kayna", "kaynin", "kaynch", "kayen", "kayna", "kaynine",
    "tani", "tanya", "tanta", "kaynou", "kaytouni",
}
# Past tense of "to be" (kan, kanet, kanou, kanouch...) is shared by both dialects.
KAN_PAST = re.compile(r"^kan(et|t|ou|o|u|at)?(ch|chi)?$|^kont(i|ou|o)?$")

_ARTICLE = re.compile(r"^(l|d|s|t|n|r|z|ch|ss|sh)-")
_WORD = re.compile(r"[a-z0-9']+(?:-[a-z0-9']+)*")


@dataclass
class Cue:
    token: str
    dialect: str  # "moroccan" | "algerian"
    weight: float
    reason: str


@dataclass
class MarkerScore:
    moroccan: float = 0.0
    algerian: float = 0.0
    cues: list[Cue] = field(default_factory=list)

    @property
    def total(self) -> float:
        return self.moroccan + self.algerian

    @property
    def p_moroccan(self) -> float:
        """Probability-like score, smoothed so a single cue isn't decisive."""
        k = 2.0
        return (self.moroccan + k) / (self.total + 2 * k)

    def label(self, margin: float = 0.12) -> str:
        if self.total == 0:
            return "unknown"
        p = self.p_moroccan
        if p > 0.5 + margin:
            return "moroccan"
        if p < 0.5 - margin:
            return "algerian"
        # Too little evidence to call it, vs genuine cues on both sides.
        return "mixed" if self.moroccan >= 1.5 and self.algerian >= 1.5 else "unknown"


def _compile(table):
    return [(re.compile(rf"^(?:{p})$"), w, why) for p, w, why in table if w > 0]


_MA = _compile(MOROCCAN)
_DZ = _compile(ALGERIAN)


def _normalise(tok: str) -> str:
    tok = tok.lower().replace("’", "'")
    tok = _ARTICLE.sub("", tok)
    return tok.strip("'-")


def score_tokens(tokens: list[str]) -> MarkerScore:
    """Score already-split Darija tokens (French/English tokens should be removed first)."""
    s = MarkerScore()
    # Two-word cue: "3la khater"
    joined = " ".join(t.lower() for t in tokens)
    if re.search(r"\b3la khater\b", joined):
        s.algerian += 2.0
        s.cues.append(Cue("3la khater", "algerian", 2.0, "3la khater ('because')"))
    for raw in tokens:
        for part in _WORD.findall(raw.lower()):
            tok = _normalise(part)
            if not tok or tok in ("khater",):
                continue
            hit = False
            for rx, w, why in _MA:
                if rx.match(tok):
                    s.moroccan += w
                    s.cues.append(Cue(tok, "moroccan", w, why))
                    hit = True
                    break
            if hit:
                continue
            for rx, w, why in _DZ:
                if rx.match(tok):
                    s.algerian += w
                    s.cues.append(Cue(tok, "algerian", w, why))
                    hit = True
                    break
            if hit:
                continue
            if KA_PREFIX.match(tok) and tok not in KA_EXCLUDE and not KAN_PAST.match(tok):
                s.moroccan += 2.0
                s.cues.append(Cue(tok, "moroccan", 2.0, "ka-/ta- present-tense prefix"))
    return s


def score_text(text: str) -> MarkerScore:
    """Score raw Arabizi text. Strips obvious French words using a small stoplist."""
    text = re.sub(r"\[[^\]]*\]", " ", text)  # drop [laughter], [unclear] etc.
    text = re.sub(r"\*[^*]+\*", " ", text)    # drop *italic* asides
    toks = [t for t in re.split(r"\s+", text) if t]
    toks = [t for t in toks if _normalise(t) not in FRENCH_STOP]
    return score_tokens(toks)


def combine(claude_label: str, claude_conf: float, markers: MarkerScore) -> tuple[str, float]:
    """Blend Claude's verdict with the marker score.

    Returns (label, confidence in [0,1]) where confidence is for the returned label.
    The marker score's influence grows with how much evidence it found; with no
    verdict from Claude the markers decide alone.
    """
    if claude_label == "unknown" or claude_conf <= 0:
        if markers.total == 0:
            return "unknown", 0.0
        lab = markers.label()
        p = markers.p_moroccan
        return lab, round(p if lab == "moroccan" else 1 - p if lab == "algerian" else 1 - abs(p - 0.5) * 2, 3)
    if claude_label == "moroccan":
        p_claude = 0.5 + 0.5 * claude_conf
    elif claude_label == "algerian":
        p_claude = 0.5 - 0.5 * claude_conf
    else:
        p_claude = 0.5
    evidence = min(markers.total / 8.0, 1.0)  # ~8 points of cues = full weight
    w_markers = 0.5 * evidence
    p = (1 - w_markers) * p_claude + w_markers * markers.p_moroccan
    if abs(p - 0.5) < 0.1:
        return "mixed", round(1 - abs(p - 0.5) * 2, 3)
    return ("moroccan", round(p, 3)) if p > 0.5 else ("algerian", round(1 - p, 3))


# French words that collide with Darija cue patterns ("fin", "ki"...) when
# scoring free text without language tags.
FRENCH_STOP = {
    "fin", "la", "le", "les", "de", "des", "du", "et", "est", "un", "une", "en",
    "ce", "ça", "qui", "que", "pour", "pas", "mais", "avec", "dans", "sur",
    "bon", "voilà", "donc", "alors", "c'est", "très", "plus", "on", "je",
}
