# Darija Transcriber

Web app: record or upload Darija audio and get back

- a line-by-line **Arabizi** transcript (3 = ع, 7 = ح, 9 = ق, gh = غ, kh = خ, ch = ش, 2 = ء),
- the **English translation** under each line,
- **French and English words highlighted** where speakers code-switch,
- a **Moroccan vs Algerian** verdict for the whole clip and for each line, with the cues behind it,
- export to Markdown in the same layout as the hand-made podcast transcripts, or JSON.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env      # add your keys
./run.sh                  # http://localhost:8000
```

Without keys you can still open the app and press **Try the demo**, which renders the first 60 lines of the Mina podcast transcript in the app's format.

You need:
- `ANTHROPIC_API_KEY` for the language pass.
- One speech engine: `ELEVENLABS_API_KEY` (Scribe; recommended to try first for Arabic + French mixing), `OPENAI_API_KEY` (Whisper), or `pip install faster-whisper` and `DARIJA_ASR=local` for offline use (slow without a GPU).

The **Paste transcript** tab skips speech recognition, so you can test the language pass on text you already have (Arabic script, Arabizi or mixed, one line per segment).

## How it works

```
audio ──► speech engine ──► segments with timestamps (Arabic script / French)
                                │
                                ▼
                 Claude, one structured call per 40 lines
         Arabizi tokens + language tag per word + English + dialect per line
                                │
                                ▼
       marker scorer (dyal/ta3, daba/dork, ka- prefix, joj/zouj, rah…) 
       blended with Claude's verdict, per line and for the whole clip
```

| File | What it does |
|---|---|
| `app/asr.py` | ElevenLabs / OpenAI / local Whisper backends, groups word timestamps into caption lines |
| `app/language.py` | Prompt with your Arabizi conventions, Pydantic schema, Claude call |
| `app/dialect.py` | Transparent marker scorer and the blend with Claude's verdict |
| `app/pipeline.py` | Batching and assembly of the result |
| `app/export.py` | Markdown export in the podcast-file layout |
| `app/static/` | The single-page UI |
| `scripts/eval_dialect.py` | Scores the marker model on the labelled files in `samples/` |
| `scripts/build_demo.py` | Rebuilds the demo data from a hand-made transcript |

## Dialect scorer accuracy

`python scripts/eval_dialect.py` on the six transcripts in `samples/` (685 lines):

- Lines where the scorer made a call (260): **99.6% correct** (1 error: *bghit* in an Algerian line).
- Every file classified correctly at file level.
- 421 lines (mostly short or garbled podcast fragments) had no cues, so the scorer says "unknown" and Claude's judgement decides.

Caveats: the cue weights were tuned on these same files, all three podcasts are Algerian, and the Moroccan data is only two translated texts. Real Moroccan speech recordings are the most useful next test set.

## Tests

```bash
python -m pytest -q
```

## Ideas for later

- An audio-based dialect classifier (accent and prosody, e.g. fine-tuned on the ADI-17 dataset) for clips with few lexical cues.
- Speaker labels in the transcript (ElevenLabs already returns them).
- A Darija fine-tuned Whisper model for the offline backend.
