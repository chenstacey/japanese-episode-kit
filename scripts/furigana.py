#!/usr/bin/env python3
"""SRT -> furigana + dictionary pack. Run with the NLP virtualenv.

Output shape:

    {"furigana": {"<japanese line>": [{surface, reading, base}, ...]},
     "dict":     {"<base form>": {reading, pos, glosses, glosses_en, lang}}}

Keyed by line text rather than by index so the pack survives a re-timed or
lightly edited subtitle file.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from furigana_core import build_pack  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("srt")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--dict-dir", default="dict")
    args = ap.parse_args()

    srt = Path(args.srt)
    if not srt.exists():
        sys.exit(f"not found: {srt}")

    dict_dir = Path(args.dict_dir)
    jmdict = dict_dir / "jmdict.sqlite"
    ja_zh = dict_dir / "ja_zh.sqlite"

    if not jmdict.exists() and not ja_zh.exists():
        print("      note: no dictionaries found — readings only, no definitions")
        print("            run: bash scripts/setup.sh")

    pack, total_words = build_pack(srt.read_text(encoding="utf-8-sig"), jmdict, ja_zh)
    Path(args.out).write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")

    chinese = sum(1 for e in pack["dict"].values() if e.get("lang") == "zh")
    english = len(pack["dict"]) - chinese
    size = Path(args.out).stat().st_size / 1e6
    print(f"      {len(pack['furigana'])} lines, "
          f"{len(pack['dict'])}/{total_words} words defined "
          f"({chinese} zh, {english} en), {size:.1f} MB")


if __name__ == "__main__":
    main()
