# Japanese Episode Kit

Turn a Japanese audio source into intensive-listening material: a timed
transcript, per-word kana readings, and Chinese/English definitions for every
word that appears.

Packaged as an agent skill ([`SKILL.md`](SKILL.md)) so an assistant can drive it,
but it is ordinary Python and runs fine by hand.

```bash
bash scripts/setup.sh                                   # once
python scripts/make_episode.py ~/Downloads/ep02.mp3 --slug ep02
```

Output, in `out/ep02/`:

| File | What it is |
| --- | --- |
| `subtitles.srt` | Japanese transcript with timings |
| `furigana.json` | readings per word + definitions per dictionary form |
| `audio.m4a` | mono AAC, normalised for reliable playback |
| `segments.json` | three proposed stretches for close study, and the words in them |
| `episode.json` | manifest tying them together |

## Input

- a local file — `.mp3 .m4a .wav .flac .mp4 .mkv …`
- a direct audio URL
- a page URL `yt-dlp` can handle

**Existing captions are used when they exist.** For a URL, the kit first asks
whether the site already publishes a Japanese subtitle track and downloads it if
so — seconds instead of minutes. Speech recognition is the fallback, not the
first move. This is the whole reason browser tools like Language Reactor feel
instant on YouTube: they are not transcribing, they are fetching a track that is
already there.

DRM-protected services (Netflix and similar) are out of scope; their subtitles
require an authenticated, decrypted session.

### Site notes, from testing

| Site | State |
| --- | --- |
| YouTube | Works, but needs `--extractor-args "youtube:player_client=android"` — the default client now gets "The page needs to be reloaded". The kit adds this automatically. Verified: a podcast episode yielded a 29 KB human-written Japanese SRT in seconds. |
| Bilibili | Returns **412** to anonymous requests regardless of User-Agent. Pass `--cookies-from-browser chrome` and stay logged in there. Multi-part pages need `--part N`. Verified: parts and audio download fine. Subtitles do not: yt-dlp sees only `danmaku`, and the player API that advertises CC tracks returned **another video's subtitles on both attempts** (a 15-minute drama got 26 minutes of Korean variety-show captions). `scripts/bili_subs.py` can inspect what is advertised, but treat its output as unverified. Transcribe instead. |
| Reuploads / fansubs | Usually burn subtitles into the picture. No track to fetch; transcription is the only route. |

Safari cookies cannot be read (sandbox permissions), so use Chrome for Bilibili.

## Speed

Transcription runs locally on the CPU, so it is not fast:

| Source | Time for 40 minutes of audio |
| --- | --- |
| Existing caption track | seconds |
| ReazonSpeech (default) | ~12 min |
| `--engine whisper` | ~15 min |

Measured on an M4. Budget roughly a third of the audio's length. If a source has
captions, use them.

## Choices behind the defaults

**ReazonSpeech over Whisper.** On noisy Japanese drama dialogue Whisper
large-v3 dropped whole stretches that ReazonSpeech caught. Demucs vocal
separation was tested as a preprocessing step; it only helped Whisper, so it is
not in the pipeline. `--engine whisper` remains for other languages.

**Audio is always re-encoded to mono AAC in MP4.** One source arrived as a VBR
MP3 inside a QuickTime container: desktop browsers played it correctly, but iOS
extrapolated seek positions from the average bitrate and subtitles drifted
further out the deeper you scrubbed — a platform-specific bug that looked like
bad subtitle data. The script refuses to emit anything but AAC-in-MP4, with
`+faststart` so playback can begin before the file finishes downloading.

**Two virtualenvs.** ReazonSpeech pins `numpy<2`; other tooling wants 2.x.
Sharing one environment breaks whichever installs second.

**Chinese definitions come from Wiktionary, not JMdict.** JMdict has no Chinese
edition — its multilingual releases are Dutch, French, German, Hungarian,
Russian, Slovenian, Spanish, Swedish. Chinese covers ~70% of an episode's
vocabulary and JMdict's English covers ~91%, so both are built and Chinese is
preferred per word, with English as the labelled fallback. Combined coverage is
about 92%.

**Function words are not looked up.** Particles and auxiliaries match unrelated
homophones by their kana (the prefix ご hits 五 "five"), so they carry no
dictionary entry and stay unclickable in a viewer.

## Quality warning

After transcribing, the script flags cues whose window is far wider than their
text. Those are usually stretches of speech the recogniser missed entirely: the
audio has dialogue, the transcript does not, and the neighbouring cue's window
stretched to cover the gap. During playback the highlight sits still while
different dialogue plays, which reads as the subtitles being out of sync even
though the timeline is correct.

## Requirements

- macOS or Linux, Python 3.9+
- `ffmpeg` (`brew install ffmpeg`)
- ~2 GB of disk for the environments, ~56 MB for the dictionaries

Run `python scripts/doctor.py` to see what is missing; it prints the fix for
each item.

## Licensing of the data it builds

- [JMdict](https://www.edrdg.org/jmdict/j_jmdict.html) via
  [jmdict-simplified](https://github.com/scriptin/jmdict-simplified) — CC BY-SA 4.0
- Chinese definitions from [Wiktionary](https://zh.wiktionary.org) via
  [kaikki.org](https://kaikki.org) — CC BY-SA 4.0
- [UniDic](https://clrd.ninjal.ac.jp/unidic/) via `unidic-lite` — BSD/GPL/LGPL tri-license
- [ReazonSpeech](https://research.reazon.jp/projects/ReazonSpeech/) — Apache 2.0

You are responsible for having the right to download and process whatever you
feed it.
