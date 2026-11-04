"""Claude language pass: Arabizi transliteration, word-level language tags,
English translation and a per-line dialect verdict, in one structured call."""

from __future__ import annotations

import json
import os
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

MODEL = os.environ.get("DARIJA_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("DARIJA_EFFORT", "medium")

Lang = Literal["darija", "fr", "en", "msa", "other"]
Dialect = Literal["moroccan", "algerian", "mixed", "unknown"]


class Token(BaseModel):
    t: str = Field(description="The word as it should appear in the Arabizi line, with any attached punctuation.")
    lang: Lang = Field(description="darija, fr (French), en (English), msa (Modern Standard Arabic), other")


class LineOut(BaseModel):
    id: int
    tokens: list[Token] = Field(description="The full Arabizi line, word by word, in order.")
    english: str
    dialect: Dialect
    dialect_confidence: float = Field(description="0 to 1, confidence in `dialect` for this line alone.")
    dialect_cues: list[str] = Field(description="Words or features that point to the dialect, e.g. 'ta3', 'ka- prefix'.")
    unclear: bool = Field(description="True when the transcription looks misheard and the reading is a best guess.")


class BatchOut(BaseModel):
    lines: list[LineOut]
    overall_dialect: Dialect
    overall_confidence: float
    overall_reasoning: str = Field(description="One or two sentences on why.")


SYSTEM = """You turn speech-recognition output of North African Arabic (Darija) into a clean line-by-line transcript.

For each input line, produce:
1. **tokens**: the line in Arabizi (Latin-script Arabic), word by word, each tagged with its language.
2. **english**: a natural English translation of the whole line.
3. **dialect**: moroccan, algerian, mixed (both cues present, or code-switching between speakers) or unknown (too short / no cues), with a confidence and the cues you used.

## Arabizi conventions (follow exactly)
- 3 = ع, 7 = ح, 9 = ق, gh = غ, kh = خ, ch = ش, 2 = ء (hamza). Emphatic letters may use a dot (ṣ, ṭ, ḍ) only where the source clearly has them; otherwise plain s, t, d.
- Write qaf as **9** for both dialects, even when Algerians pronounce it g.
- Definite article attached with a hyphen and assimilated: l-far9, d-densité, s-sa3a, r-r9a9, n-nhar.
- Long vowels as ou / i / a (kifach, mazal, ykounou). Keep spellings readable, not academic.
- **French words and phrases stay in French spelling**, as spoken (problème, la société, est-ce que, normal), tagged fr. Same for English (input, podcast, stand up), tagged en. Darija morphology glued to a French word stays glued (yrépondiw, l-agence) and is tagged by the stem's language.
- Keep sound cues in brackets, translated in the English line: [ḍ7ak] → [laughter], [mousi9a] → [music].
- If a stretch is unintelligible write […]. Do not invent content; set unclear=true when your reading is a guess.
- Do NOT translate the Darija into MSA. Write what was said, in the speaker's dialect.

## Dialect cues
Moroccan: dyal (of), daba (now), joj (two), ka-/ta- present prefix (kandir, katgoul), ghadi/gha (future), wakha, 3afak, chno/ach (what), fin (where), imta (when), bzaf, drari, 7it (because), khass (must), bgha (want).
Algerian: ta3/nta3 (of), rah/rani/rak (is, now), dork/dorka (now), zouj (two), no present prefix (ndir, tgoul), kima (like), ki (when), 3la khater (because), win (where), wa9tach (when), bezzaf, najem (can), mli7 (good), barka (enough), yaser, 7ab (want), khatra (time), wesh.
Shared or weak: kan/kanet (was), wach, kifach, chwiya, safi, mzyan, bach, hadchi.
Judge each line on its own words; the overall verdict uses all lines. The ASR may render Algerian g-qaf as ڨ or ق: either way write 9.

The input lines may be in Arabic script, Latin script or a mix, and may contain recognition errors. Fix obvious mis-recognitions when the intended word is clear from context. Return exactly one output line per input line, with the same id."""


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def process_lines(lines: list[dict], context_hint: str = "") -> BatchOut:
    """lines: [{"id": int, "text": str}]. Returns validated BatchOut."""
    user = (
        (f"Context about the recording: {context_hint}\n\n" if context_hint else "")
        + "Input lines (JSON):\n"
        + json.dumps([{"id": l["id"], "text": l["text"]} for l in lines], ensure_ascii=False, indent=1)
    )
    client = _client()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        cache_control={"type": "ephemeral"},
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_format=BatchOut,
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError("The model declined to process this transcript.")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("Output was cut off; try a shorter clip.")
    parsed = getattr(msg, "parsed_output", None)
    if parsed is None:
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        parsed = BatchOut.model_validate_json(text)
    return parsed
