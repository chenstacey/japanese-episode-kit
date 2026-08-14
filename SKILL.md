---
name: japanese-episode-kit
description: Turn a Japanese audio source into study material — a timed SRT transcript plus a furigana/dictionary pack. Use when the user provides an audio file, an audio URL, a podcast episode, or a video link and wants a transcript, subtitles, furigana readings, or vocabulary data for Japanese listening practice.
---

# Japanese Episode Kit

Produces, from one audio source:

- `subtitles.srt` — Japanese transcript with timings
- `furigana.json` — kana readings per word, plus Chinese/English definitions
- `audio.m4a` — normalized audio (mono AAC), safe to play on iOS
- `episode.json` — a manifest tying the three together

## Run it

Everything is one command. Do not run the individual stages by hand.

```bash
python scripts/make_episode.py <input> --slug ep02 --title "第2集"
```

`<input>` is any of:

- a local file — `~/Downloads/ep02.mp3`, `.m4a`, `.wav`, `.mp4`
- a direct audio URL — `https://example.com/ep02.mp3`
- a page URL that `yt-dlp` can extract audio from (podcast pages, video sites)

For a URL the kit first looks for a caption track the site already publishes and
skips transcription entirely when it finds one — seconds instead of minutes.

Two sites need extra care, and the failure looks like a broken URL rather than a
permissions problem:

- **Bilibili** answers anonymous requests with `412`. Add
  `--cookies-from-browser chrome` (the user must be logged in there; Safari
  cookies are unreadable). A page with several 分集 needs `--part N`.
- **YouTube** needs a non-default player client, which the kit passes on its own.

Most drama uploads carry their subtitles burned into the picture, or expose only
a `danmaku` comment track. Both mean no usable subtitles, and the kit falls back
to transcription — say so rather than reporting a failure.

Output lands in `out/<slug>/`. Expect **10–15 minutes of CPU per 40 minutes of
audio** — the transcription is the slow part and runs locally, so leave it
running rather than assuming it hung.

## Before the first run

```bash
bash scripts/setup.sh
```

This creates two virtualenvs and downloads the dictionaries (~2 GB total, once).
To check an existing install:

```bash
python scripts/doctor.py
```

`doctor.py` prints exactly what is missing and the command that fixes it. Run it
first whenever `make_episode.py` fails — most failures are a missing dependency,
not a bug.

## Useful flags

| Flag | Effect |
| --- | --- |
| `--engine whisper` | Use faster-whisper instead of ReazonSpeech. Slower and weaker on noisy Japanese, but handles other languages. |
| `--no-furigana` | Skip the readings/dictionary pack. |
| `--bitrate 64k` | Smaller audio (default `96k`, about 44 MB/hour). |
| `--start 00:01:30 --end 00:41:00` | Trim before transcribing — useful for cutting opening credits. |
| `--out DIR` | Output root (default `out/`). |

## What to tell the user when it finishes

Report the cue count, the number of words that got definitions, and the output
path. If many cues are far longer than their text (the script warns about this),
say so — it usually means the source audio has speech the recognizer dropped, and
those stretches will feel out of sync during playback.

## Things worth knowing

- **Audio is always re-encoded to mono AAC in an MP4 container.** This is not
  cosmetic: a VBR MP3 inside a QuickTime container played correctly on desktop
  but drifted progressively out of sync on iPhone. The script refuses to emit
  anything else.
- **ReazonSpeech is the default** because it is markedly more robust than
  Whisper on noisy Japanese dialogue. Demucs vocal separation was tested and
  only helped Whisper, so it is not part of the pipeline.
- **No translation.** The transcript is Japanese only. If the source already has
  a bilingual SRT, pass it with `--srt` and transcription is skipped.
- **Downloading**: `yt-dlp` fetches from many sites. Only download material you
  have the right to use; that judgement is the user's, not this script's.
