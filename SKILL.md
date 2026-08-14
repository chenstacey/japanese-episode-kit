---
name: japanese-episode-kit
description: Turn a Japanese audio source into study material — a timed SRT transcript plus a furigana/dictionary pack. Use when the user provides an audio file, an audio URL, a podcast episode, or a video link and wants a transcript, subtitles, furigana readings, or vocabulary data for Japanese listening practice.
---

# Japanese Episode Kit

Produces, from one audio source:

- `subtitles.srt` — Japanese transcript with timings (Chinese too, once translated)
- `furigana.json` — kana readings per word, plus Chinese/English definitions
- `audio.m4a` — normalized audio (mono AAC), safe to play on iOS
- `segments.json` — three proposed stretches for close study, and the words in them
- `episode.json` — a manifest tying them together

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

## Study segments

`make_episode.py` writes `segments.json` on its own — there is no separate step
to remember. It proposes three deliberately different stretches — the densest
dialogue, the richest vocabulary, and a balance — each cut on a natural silence
so it never starts mid-sentence, and each carrying the words in it worth
annotating.

Use `--segment-minutes 4` to change the target length, `--no-segments` to skip.
If the proposals fail the episode is still complete and usable; the message
says what to fix.

To regenerate them for an episode that already exists:

```bash
python scripts/study_segments.py out/ep02 --minutes 3
```

Two things about this the numbers do not show: picking words by rarity alone
returns transcription errors and character names, so a word must also carry a
dictionary entry and not be an interjection; and a word that *is* in the
dictionary can still be a name (直人 is glossed "male given name"), which this
does not catch.

## Adding Chinese translations

A transcribed episode is Japanese-only — speech recognition produces one
language. Viewers show the Japanese line with the Chinese underneath, and that
second line stays empty until it is filled in. **You do the translating**; the
script only takes the lines out and puts them back.

```bash
python scripts/translate.py export out/ep03/subtitles.srt
```

That writes `out/ep03/subtitles.parts/part1.txt`, `part2.txt`, … — 150 lines
each, numbered, with the format rules at the top of every file.

For each part: read it, translate every line, and write your translation to
`partN.zh.txt` **in the same directory**, one line per input line, as
`编号. 中文翻译`. Then:

```bash
python scripts/translate.py import out/ep03/subtitles.srt
```

It reports how many lines each part supplied and rewrites the srt with the
Chinese in `<i>` tags. Rerun the import after fixing a part; it replaces rather
than appends.

Rules that matter more than they look:

- **Numbering is the only thing tying a translation to its line.** Do not
  merge, split, skip or renumber. Numbering restarts at 1 in every part.
- **Translate line by line, not scene by scene.** A line cut off mid-sentence
  should stay cut off in Chinese; the viewer shows it against that exact
  moment of audio, and a tidied-up full sentence will not line up.
- **A part that comes back short is not fatal.** The import fills in what it
  has and leaves the rest blank. Say which parts were incomplete.

Nothing else needs rebuilding afterwards: the Japanese is untouched, so the
furigana pack and the study segments stay valid.

## Useful flags

| Flag | Effect |
| --- | --- |
| `--engine whisper` | Use faster-whisper instead of ReazonSpeech. Slower and weaker on noisy Japanese, but handles other languages. |
| `--no-furigana` | Skip the readings/dictionary pack (also skips segments, which read it). |
| `--no-segments` | Skip the study-segment proposals. |
| `--segment-minutes 4` | Target length of a study segment (default 3). |
| `--bitrate 64k` | Smaller audio (default `96k`, about 44 MB/hour). |
| `--start 00:01:30 --end 00:41:00` | Trim before transcribing — useful for cutting opening credits. |
| `--out DIR` | Output root (default `out/`). |

## What to tell the user when it finishes

Report the cue count, the number of words that got definitions, how many study
segments were proposed, and the output path. If many cues are far longer than
their text (the script warns about this), say so — it usually means the source
audio has speech the recognizer dropped, and those stretches will feel out of
sync during playback.

Two things worth flagging, because they are quiet failures:

- **The title.** Some sites hand `yt-dlp` no usable name and the file arrives
  called `download`. The kit refuses to use that as a title and says so — pass
  `--title` and rerun, or set the title when publishing.
- **A missing `segments.json`.** The episode still plays, but a reader gets no
  study proposals. Run `python scripts/doctor.py` and rerun `setup.sh`.

## When the kit was installed a while ago

`setup.sh` is safe to rerun and is the fix for most "it used to work" failures:
it reinstalls the NLP requirements every time, so an environment built against
an older version of this kit catches up. Run it after pulling.

`doctor.py` checks that Japanese word frequencies actually resolve, not merely
that the library imports — importing `wordfreq` succeeds without MeCab and only
fails once it tokenizes Japanese, which is deep inside the segment proposals.

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
