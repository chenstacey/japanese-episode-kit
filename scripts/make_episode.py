#!/usr/bin/env python3
"""One command: audio source in, study material out.

    python scripts/make_episode.py <input> --slug ep02 --title "第2集"

Writes out/<slug>/ containing audio.m4a, subtitles.srt, furigana.json and
episode.json. Stages are deliberately not separate commands -- the ordering and
the audio normalisation are easy to get wrong, and getting them wrong produces
subtitles that drift on a phone but look fine on a desktop.
"""
# `X | None` annotations would otherwise need Python 3.10; macOS still ships 3.9
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VENV_ASR = ROOT / ".venv-asr"
VENV_NLP = ROOT / ".venv-nlp"
DICT_DIR = ROOT / "dict"

AUDIO_SUFFIXES = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus",
                  ".mp4", ".mkv", ".mov", ".webm"}


def run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, **kwargs)


def venv_python(venv: Path) -> str:
    python = venv / "bin" / "python"
    if not python.exists():
        sys.exit(f"missing {python}\n  run: bash scripts/setup.sh")
    return str(python)


# ---------------------------------------------------------------- input

def is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def site_args(source: str, cookies_browser: str | None) -> list:
    """Per-site flags that decide whether extraction works at all.

    YouTube: the default web client is refused outright ("The page needs to be
    reloaded") since YouTube began forcing SABR streaming; the android client
    still resolves.

    Bilibili: returns 412 Precondition Failed to anonymous requests no matter
    what User-Agent is sent. Only real browser cookies get through, so pass
    --cookies-from-browser and stay logged in there.
    """
    args = []
    if "youtube.com" in source or "youtu.be" in source:
        args += ["--extractor-args", "youtube:player_client=android"]
    if cookies_browser:
        args += ["--cookies-from-browser", cookies_browser]
    elif "bilibili.com" in source:
        print("      note: bilibili blocks anonymous requests — "
              "pass --cookies-from-browser chrome if this fails")
    return args


def fetch_existing_subtitles(source: str, workdir: Path, langs: str,
                             cookies_browser: str | None) -> Path | None:
    """Grab a caption track the site already has, if there is one.

    This is why browser tools produce subtitles instantly while a local
    transcription takes minutes: on YouTube and similar they are not
    recognising speech at all, just downloading the existing track.

    It only helps when a real caption track exists. Reuploaded or fansubbed
    video usually carries its subtitles burned into the picture, and Bilibili
    in particular often advertises only a `danmaku` track — comments, not
    dialogue — which is useless here. Those all fall through to transcription.

    DRM-protected services (Netflix and similar) are out of reach: their
    subtitles need an authenticated, decrypted session.
    """
    if not shutil.which("yt-dlp"):
        return None

    print(f"      looking for existing {langs} subtitles…")
    result = subprocess.run(
        ["yt-dlp", "--skip-download", "--write-subs", "--write-auto-subs",
         "--sub-langs", langs, "--convert-subs", "srt",
         "--no-playlist", "--quiet", "--no-warnings",
         *site_args(source, cookies_browser),
         "-o", str(workdir / "subs.%(ext)s"), source],
        capture_output=True, text=True)

    # danmaku is a comment stream, not dialogue
    found = [f for f in sorted(workdir.glob("subs*.srt"))
             if "danmaku" not in f.name.lower()]
    if found:
        # a human-made track beats an auto-generated one
        manual = [f for f in found if "auto" not in f.name.lower()]
        return (manual or found)[0]
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        if detail:
            print(f"      (no usable track: {detail[-1][:90]})")
    return None


def download_audio(source: str, workdir: Path,
                   cookies_browser: str | None, part: int | None) -> Path:
    if not shutil.which("yt-dlp"):
        sys.exit("yt-dlp is needed for URLs\n  run: bash scripts/setup.sh")

    print(f"      downloading audio")
    target = workdir / "download.%(ext)s"
    # a bilibili page is often several parts; without --part take just the first
    selection = ["--playlist-items", str(part)] if part else ["--no-playlist"]
    run(["yt-dlp", "-f", "bestaudio/best", "-o", str(target),
         *selection, "--quiet", "--progress",
         *site_args(source, cookies_browser), source])

    downloaded = sorted(workdir.glob("download.*"))
    if not downloaded:
        sys.exit("download produced no file")
    return downloaded[0]


def resolve_local(source: str) -> Path:
    path = Path(source).expanduser()
    if not path.exists():
        sys.exit(f"not found: {path}")
    return path


# ---------------------------------------------------------------- audio

def probe(path: Path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name",
         "-show_entries", "format=format_name,duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    parts = [p for p in out.stdout.strip().splitlines() if p]
    codec = parts[0] if parts else ""
    container = parts[1] if len(parts) > 1 else ""
    duration = float(parts[2]) if len(parts) > 2 else 0.0
    return codec, container, duration


def normalize_audio(src: Path, dest: Path, bitrate: str,
                    start: str | None, end: str | None) -> float:
    """Re-encode to mono AAC in a plain MP4 container.

    Not optional. An episode once arrived as a VBR MP3 inside a QuickTime
    container: desktop browsers played it correctly, but iOS extrapolated seek
    positions from the average bitrate and the subtitles drifted further out the
    deeper you scrubbed. Re-encoding removes the container quirks and the VBR
    seek tables; +faststart lets playback begin before the whole file arrives.
    """
    cmd = ["ffmpeg", "-y", "-i", str(src)]
    if start:
        cmd += ["-ss", start]
    if end:
        cmd += ["-to", end]
    cmd += ["-vn", "-ac", "1", "-c:a", "aac", "-b:a", bitrate,
            "-movflags", "+faststart", str(dest)]
    run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    codec, container, duration = probe(dest)
    if codec != "aac" or "mp4" not in container:
        sys.exit(f"normalisation produced {codec} in {container}; expected aac in mp4")
    return duration


# ---------------------------------------------------------------- transcript

def transcribe(audio: Path, out_srt: Path, engine: str,
               chunk_sec: float, overlap: float):
    script = HERE / "transcribe.py"
    run([venv_python(VENV_ASR), str(script), str(audio),
         "-o", str(out_srt), "--engine", engine,
         "--chunk-sec", str(chunk_sec), "--overlap", str(overlap)])


def build_pack(srt: Path, out_json: Path):
    script = HERE / "furigana.py"
    run([venv_python(VENV_NLP), str(script), str(srt),
         "-o", str(out_json), "--dict-dir", str(DICT_DIR)])


# ---------------------------------------------------------------- checks

def warn_about_loose_cues(srt: Path):
    """Flag cues whose window is far wider than their text.

    These are usually dialogue the recogniser missed: the speech is there, the
    words are not, and the neighbouring cue's window stretched to cover it. On
    playback the highlight sits still while different dialogue plays, which
    reads as the subtitles being out of sync.
    """
    sys.path.insert(0, str(HERE))
    from furigana_core import TS  # noqa: E402

    import re
    text = srt.read_text(encoding="utf-8")
    blocks = re.split(r"\n{2,}", text.strip())
    loose = []
    for block in blocks:
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        idx = next((i for i, l in enumerate(lines) if TS.search(l)), None)
        if idx is None:
            continue
        m = re.search(r"(\d+):(\d+):([\d.]+)[,.](\d+)\s*-->\s*(\d+):(\d+):([\d.]+)[,.](\d+)",
                      lines[idx])
        if not m:
            continue
        g = [float(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        body = "".join(lines[idx + 1:])
        span = end - start
        if span > 8 and body and len(body) / span < 2.0:
            loose.append((start, span, body[:24]))
    return loose


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="audio -> srt + furigana pack")
    ap.add_argument("input", help="local media file or URL")
    ap.add_argument("--slug", help="short id; defaults to the file name")
    ap.add_argument("--title", help="display title; defaults to the file name")
    ap.add_argument("--out", default="out", help="output root (default: out)")
    ap.add_argument("--engine", choices=["reazon", "whisper"], default="reazon")
    ap.add_argument("--srt", help="use this transcript instead of transcribing")
    ap.add_argument("--force-asr", action="store_true",
                    help="transcribe even if the source has a subtitle track")
    ap.add_argument("--sub-langs", default="ja,ja-*",
                    help="subtitle languages to look for (default: ja,ja-*)")
    ap.add_argument("--cookies-from-browser", dest="cookies_browser",
                    help="read cookies from this browser (chrome, firefox…); "
                         "bilibili refuses anonymous requests without it")
    ap.add_argument("--part", type=int,
                    help="which part of a multi-part video (1-based)")
    ap.add_argument("--no-furigana", action="store_true")
    ap.add_argument("--bitrate", default="96k")
    ap.add_argument("--start", help="ffmpeg -ss, e.g. 00:01:30")
    ap.add_argument("--end", help="ffmpeg -to, e.g. 00:41:00")
    ap.add_argument("--chunk-sec", type=float, default=600.0)
    ap.add_argument("--overlap", type=float, default=15.0)
    args = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not found\n  run: bash scripts/setup.sh")

    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        # Look for a ready-made caption track before doing anything expensive.
        existing_subs = None
        if is_url(args.input) and not args.srt and not args.force_asr:
            print("[1/3] resolving source")
            existing_subs = fetch_existing_subtitles(
                args.input, tmpdir, args.sub_langs, args.cookies_browser)
            if existing_subs:
                print(f"      found a subtitle track — skipping transcription")

        source = download_audio(args.input, tmpdir, args.cookies_browser, args.part) \
            if is_url(args.input) else resolve_local(args.input)

        slug = args.slug or source.stem.replace(" ", "-").lower()
        title = args.title or source.stem
        dest = Path(args.out) / slug
        dest.mkdir(parents=True, exist_ok=True)

        print(f"[2/3] normalising audio -> mono AAC {args.bitrate}")
        audio = dest / "audio.m4a"
        duration = normalize_audio(source, audio, args.bitrate, args.start, args.end)
        print(f"      {duration/60:.1f} min, {audio.stat().st_size/1e6:.1f} MB")

        srt = dest / "subtitles.srt"
        transcript_source = args.engine
        if args.srt:
            shutil.copy(Path(args.srt).expanduser(), srt)
            transcript_source = "supplied"
            print(f"      using supplied transcript {args.srt}")
        elif existing_subs:
            shutil.copy(existing_subs, srt)
            transcript_source = "existing-track"
        else:
            print(f"      transcribing with {args.engine} "
                  f"(expect ~{duration/60*0.3:.0f} min)")
            transcribe(audio, srt, args.engine, args.chunk_sec, args.overlap)

        pack = dest / "furigana.json"
        if args.no_furigana:
            pack = None
            print("[3/3] skipping furigana pack")
        else:
            print("[3/3] building furigana + dictionary pack")
            build_pack(srt, pack)

    cue_count = sum(1 for line in srt.read_text(encoding="utf-8").splitlines()
                    if "-->" in line)
    defined = 0
    if pack and pack.exists():
        data = json.loads(pack.read_text(encoding="utf-8"))
        defined = len(data.get("dict", {}))

    manifest = {
        "slug": slug,
        "title": title,
        "duration": round(duration, 2),
        "cues": cue_count,
        "defined_words": defined,
        "audio": audio.name,
        "srt": srt.name,
        "pack": pack.name if pack else None,
        "transcript_source": transcript_source,
    }
    (dest / "episode.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    loose = warn_about_loose_cues(srt)

    print(f"\ndone in {(time.time()-started)/60:.1f} min -> {dest}")
    print(f"  {cue_count} cues, {defined} words with definitions")
    if loose:
        print(f"\n  note: {len(loose)} cues are much longer than their text.")
        print("  That usually means speech the recogniser missed; those stretches")
        print("  will feel out of sync during playback. Worst offenders:")
        for start, span, body in sorted(loose, key=lambda x: -x[1])[:5]:
            print(f"    {int(start//60)}:{int(start%60):02d}  {span:4.1f}s  {body}")


if __name__ == "__main__":
    main()
