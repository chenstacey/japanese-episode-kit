#!/usr/bin/env python3
"""Audio -> Japanese SRT. Run with the ASR virtualenv.

Called by make_episode.py; usable directly for a one-off transcript.
"""
import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def duration_of(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def to_timestamp(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


def transcribe_reazon(wav: Path, tmpdir: Path, chunk_sec: float, overlap: float):
    """ReazonSpeech, chunked so memory stays flat on feature-length audio.

    The model is loaded once and reused: loading costs about a minute, and
    reloading per chunk would dominate the run.
    """
    from reazonspeech.espnet.asr import load_model, transcribe, audio_from_path

    started = time.time()
    model = load_model()
    print(f"      model loaded in {time.time()-started:.0f}s", flush=True)

    total = duration_of(wav)
    cues = []
    index, position = 0, 0.0
    while position < total:
        chunk_start = max(0.0, position - (overlap if index else 0.0))
        chunk_end = min(total, position + chunk_sec)
        piece = tmpdir / f"chunk{index}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav), "-ss", f"{chunk_start:.3f}",
             "-to", f"{chunk_end:.3f}", "-c", "copy", str(piece)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        started = time.time()
        result = transcribe(model, audio_from_path(str(piece)))
        kept = 0
        for segment in result.segments:
            # the previous chunk's tail already covered this
            if index and segment.start_seconds < overlap:
                continue
            text = segment.text.strip()
            if not text:
                continue
            cues.append((chunk_start + segment.start_seconds,
                         chunk_start + segment.end_seconds, text))
            kept += 1
        print(f"      chunk {index + 1}: {kept} cues in {time.time()-started:.0f}s",
              flush=True)
        index += 1
        position += chunk_sec
    return cues


def transcribe_whisper(wav: Path):
    from faster_whisper import WhisperModel

    model = WhisperModel("large-v3", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(wav), language="ja",
                                   vad_filter=True, beam_size=5)
    cues = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            cues.append((segment.start, segment.end, text))
    return cues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--engine", choices=["reazon", "whisper"], default="reazon")
    ap.add_argument("--chunk-sec", type=float, default=600.0)
    ap.add_argument("--overlap", type=float, default=15.0)
    args = ap.parse_args()

    audio = Path(args.audio)
    if not audio.exists():
        sys.exit(f"not found: {audio}")

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        # every engine here wants 16 kHz mono
        wav = tmpdir / "audio16k.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio), "-vn", "-ac", "1", "-ar", "16000",
             "-c:a", "pcm_s16le", str(wav)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if args.engine == "reazon":
            cues = transcribe_reazon(wav, tmpdir, args.chunk_sec, args.overlap)
        else:
            cues = transcribe_whisper(wav)

    cues.sort(key=lambda c: c[0])
    # a cue must never run into the next one
    for i in range(len(cues) - 1):
        if cues[i][1] > cues[i + 1][0]:
            cues[i] = (cues[i][0], cues[i + 1][0] - 0.01, cues[i][2])

    lines = []
    for i, (start, end, text) in enumerate(cues, 1):
        lines += [str(i), f"{to_timestamp(start)} --> {to_timestamp(end)}", text, ""]
    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"      {len(cues)} cues -> {args.out}")


if __name__ == "__main__":
    main()
