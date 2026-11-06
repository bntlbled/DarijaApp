# Darija Transcriber

Web app: record or upload Darija audio, upload or share an Instagram reel, or pick one of your own reels, and get back

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

## Instagram reels

Moroccan Darija, Algerian Darija, French, or any mix of them. The **Instagram** tab and the share sheet both end up in the same pipeline: the app pulls the audio out of the video with ffmpeg, runs speech recognition, then gives you the Arabizi line with the English translation beside it.

There are three ways in, and they follow what Instagram allows. Its Terms of Use forbid collecting content "in an automated way" without permission, and its official API only hands over videos owned by the account that signed in. So the app does **not** download other people's reels from a link.

| Where the reel comes from | How to get it in |
|---|---|
| **Your own account** (Creator or Business) | Set `INSTAGRAM_ACCESS_TOKEN`, then use **Show my reels** or paste the reel's link. Uses the official [Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media). |
| **Someone else's reel** | Save the video first (the reel's **Download** option if the creator allows it, or a screen recording with sound), then pick the file in **Audio / video**. |
| **On an Android phone** | Add the app to your home screen from Chrome. It then appears in the **Share** menu: share a saved video to *Darija Transcriber* and it opens ready to transcribe. (iPhone doesn't support web share targets; use the file picker.) |

Reels that use licensed music come back from the API without a video link. The app marks those as *music-locked*: download that reel from the Instagram app and upload the file.

**Getting a token for your own reels:** switch the account to Creator or Business, create an app at developers.facebook.com, add the *Instagram API with Instagram Login* product, add yourself as an Instagram tester, and generate a token with `instagram_business_basic`. Long-lived tokens last 60 days.

**Spoken language:** for clips that are mostly French, set *Spoken language* to **Auto-detect**. The default (Arabic) suits Darija-led speech with French mixed in.

Needs `ffmpeg` on the server for video files (`apt install ffmpeg` / `brew install ffmpeg`). Without it, videos are sent to the speech engine as is, which ElevenLabs and OpenAI accept but which uploads more data.

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
| `app/instagram.py` | Official Instagram API client for your own reels, ffmpeg audio extraction |
| `app/asr.py` | ElevenLabs / OpenAI / local Whisper backends, groups word timestamps into caption lines |
| `app/language.py` | Prompt with your Arabizi conventions, Pydantic schema, Claude call |
| `app/dialect.py` | Transparent marker scorer and the blend with Claude's verdict |
| `app/pipeline.py` | Batching and assembly of the result |
| `app/export.py` | Markdown export in the podcast-file layout |
| `app/static/` | The single-page UI, web app manifest with the Android share target |
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
