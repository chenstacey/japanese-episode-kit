#!/usr/bin/env python3
"""Preflight check. Prints what is missing and the command that fixes it.

Run this first when make_episode.py fails — most failures are an incomplete
install rather than a bug.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

OK, WARN, BAD = "ok  ", "warn", "MISS"
problems = []
warnings = []


def report(status: str, label: str, detail: str = ""):
    print(f"  [{status}] {label}" + (f"  {detail}" if detail else ""))


def check_tool(name: str, fix: str, required: bool = True):
    if shutil.which(name):
        report(OK, name)
        return True
    report(BAD if required else WARN, name, f"-> {fix}")
    (problems if required else warnings).append(f"{name}: {fix}")
    return False


def check_venv(path: Path, module: str, label: str):
    python = path / "bin" / "python"
    if not python.exists():
        report(BAD, label, "-> bash scripts/setup.sh")
        problems.append(f"{label} missing")
        return
    result = subprocess.run([str(python), "-c", f"import {module}"],
                            capture_output=True)
    if result.returncode == 0:
        report(OK, label)
    else:
        report(BAD, label, f"cannot import {module} -> bash scripts/setup.sh")
        problems.append(f"{label} broken")


def check_file(path: Path, label: str, fix: str, required: bool = True):
    if path.exists():
        report(OK, label, f"{path.stat().st_size / 1e6:.0f} MB")
    else:
        report(BAD if required else WARN, label, f"-> {fix}")
        (problems if required else warnings).append(f"{label}: {fix}")


print("system tools")
check_tool("ffmpeg", "brew install ffmpeg")
check_tool("ffprobe", "brew install ffmpeg")
check_tool("yt-dlp", "bash scripts/setup.sh  (only needed for URL inputs)",
           required=False)

print("\nenvironments")
check_venv(ROOT / ".venv-asr", "reazonspeech.espnet.asr", ".venv-asr")
check_venv(ROOT / ".venv-nlp", "fugashi", ".venv-nlp")

print("\ndictionaries")
check_file(ROOT / "dict" / "jmdict.sqlite", "jmdict.sqlite (English)",
           "bash scripts/setup.sh")
check_file(ROOT / "dict" / "ja_zh.sqlite", "ja_zh.sqlite (Chinese)",
           "bash scripts/setup.sh", required=False)

print()
if problems:
    print(f"{len(problems)} problem(s) — the pipeline will not run:")
    for problem in problems:
        print(f"  - {problem}")
    sys.exit(1)

if warnings:
    print("ready, with limitations:")
    for warning in warnings:
        print(f"  - {warning}")
else:
    print("ready")
