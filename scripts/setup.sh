#!/bin/bash
# One-time environment setup. Safe to re-run; existing pieces are skipped.
#
# Two virtualenvs rather than one: ReazonSpeech pins numpy<2 (its
# ctc_segmentation wheel is built against 1.x) while other tooling wants 2.x.
# Sharing one environment breaks whichever installs second.
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

say() { printf "\n\033[1m%s\033[0m\n" "$1"; }

say "checking system tools"
for tool in python3 ffmpeg ffprobe; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "  ok   $tool"
  else
    echo "  MISSING  $tool"
    [ "$tool" = "ffmpeg" ] || [ "$tool" = "ffprobe" ] && \
      echo "       install with: brew install ffmpeg"
    exit 1
  fi
done

say "ASR environment (.venv-asr)"
if [ -x ".venv-asr/bin/python" ] && \
   .venv-asr/bin/python -c "import reazonspeech.espnet.asr" 2>/dev/null; then
  echo "  already installed"
else
  python3 -m venv .venv-asr
  .venv-asr/bin/python -m pip install -q --upgrade pip
  echo "  installing (large — espnet and torch, several minutes)…"
  .venv-asr/bin/pip install -q -r requirements/asr.txt
  echo "  done"
fi

say "NLP environment (.venv-nlp)"
if [ -x ".venv-nlp/bin/python" ] && \
   .venv-nlp/bin/python -c "import fugashi" 2>/dev/null; then
  echo "  already installed"
else
  python3 -m venv .venv-nlp
  .venv-nlp/bin/python -m pip install -q --upgrade pip
  .venv-nlp/bin/pip install -q -r requirements/nlp.txt
  echo "  done"
fi

say "yt-dlp (needed only for URL inputs)"
if command -v yt-dlp >/dev/null 2>&1; then
  echo "  already installed"
else
  .venv-nlp/bin/pip install -q yt-dlp
  ln -sf "$ROOT/.venv-nlp/bin/yt-dlp" "$ROOT/scripts/yt-dlp" 2>/dev/null || true
  echo "  installed into .venv-nlp — add it to PATH or use scripts/yt-dlp"
fi

say "dictionaries"
mkdir -p dict
if [ -f "dict/jmdict.sqlite" ] && [ -f "dict/ja_zh.sqlite" ]; then
  echo "  already built"
else
  echo "  building (downloads ~230 MB, keeps ~56 MB)…"
  .venv-nlp/bin/python scripts/build_dicts.py --out-dir dict
fi

say "checking the result"
.venv-nlp/bin/python scripts/doctor.py
