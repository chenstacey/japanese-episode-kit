---
name: japanese-episode-kit
description: Turn a Japanese audio source into complete study material — a timed transcript, kana readings, Chinese/English definitions, proposed segments for close listening, and Chinese translations of every line. Use when the user provides an audio file, an audio URL, a podcast episode, or a video link (Bilibili, YouTube) and wants it "processed", or asks for a transcript, subtitles, furigana readings, translations, or vocabulary data for Japanese listening practice.
---

# Japanese Episode Kit

Produces, from one audio source:

- `subtitles.srt` — Japanese transcript with timings (Chinese too, once translated)
- `furigana.json` — kana readings per word, plus Chinese/English definitions
- `audio.m4a` — normalized audio (mono AAC), safe to play on iOS
- `segments.json` — three proposed stretches for close study, and the words in them
- `episode.json` — a manifest tying them together

## The whole job, in order

When asked to "process this episode" from a link or a file, run all of this —
the transcript on its own is half a deliverable, because the reading view stays
blank without the Chinese.

**1. Catch the tools up.** Always, not just the first time.

```bash
cd <kit> && git pull && bash scripts/setup.sh && python3 scripts/doctor.py
```

`doctor.py` must come back clean before going on. `setup.sh` is cheap when
there is nothing to do and is the fix for most "it worked last time" failures.

**2. Find out what the link actually contains** — only for a multi-part page
(Bilibili 分集, a playlist). Run the command from step 3 without `--part`, read
the list it prints, and pick the number matching the episode asked for. Getting
this wrong transcribes the wrong episode and costs the full ASR time.

**3. Build it.**

```bash
python3 scripts/make_episode.py "<url or file>" \
  --slug ep06 --title "第6集" \
  --end 00:44:00 \
  --cookies-from-browser chrome --force-asr
```

- `--slug` / `--title` — always pass both. Left to itself the kit takes the name
  from the file, and some sites hand `yt-dlp` nothing usable.
- `--end` (and `--start`) — trim before transcribing, so credits and trailing
  filler do not cost ASR time. Ask for these if the user mentioned a length.
- `--cookies-from-browser chrome` — required for Bilibili; see below.
- `--force-asr` — **use it on Bilibili.** See below.

Expect **10–15 minutes of CPU per 40 minutes of audio**. It is not hung.

**4. Translate it** — see *Adding Chinese translations*. Not optional: this is
what the reading view shows under each line.

**5. Report** — see *What to tell the user when it finishes*.

Output lands in `out/<slug>/`, ready to publish.

## Input

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

  Also pass **`--force-asr`**. Bilibili advertises CC subtitle tracks that are
  not reliably its own: on two separate attempts the API returned *another
  video's* subtitles — a 15-minute drama came back with 26 minutes of Korean
  variety-show captions. Without `--force-asr` the kit may take that track and
  skip transcription, producing an episode whose subtitles belong to something
  else entirely. Transcribing costs ten minutes; this costs the whole episode.
- **YouTube** needs a non-default player client, which the kit passes on its own.

Most drama uploads carry their subtitles burned into the picture, or expose only
a `danmaku` comment track. Both mean no usable subtitles, and the kit falls back
to transcription — say so rather than reporting a failure.

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

Report all of this, without being asked — each line is something they cannot
see from the output directory:

1. **Cue count, defined words, segments proposed**, and the output path.
2. **Which part of a multi-part page was used**, if the source had several. This
   is the one mistake that silently produces a perfectly good episode of the
   wrong content.
3. **Loose cues.** The script warns when cues are far longer than their text.
   Pass the warning on with its timestamps: it means dialogue the recognizer
   missed, and during playback the highlight sits still while other lines are
   spoken — which reads as broken sync even though the timings are right.
   Those stretches are poor choices for close study.
4. **Translation coverage** — lines filled per part, and any part that came
   back short.
5. **The title**, as it will appear in the library.

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
- **Transcription produces Japanese only.** The Chinese is a separate step you
  do yourself (*Adding Chinese translations*). If the source already has a
  bilingual SRT, pass it with `--srt` and both steps are skipped.
- **Downloading**: `yt-dlp` fetches from many sites. Only download material you
  have the right to use; that judgement is the user's, not this script's.
