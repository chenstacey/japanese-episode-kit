#!/usr/bin/env python3
"""Add Chinese translations to a Japanese-only .srt, in two steps.

An episode transcribed from audio has no translations — speech recognition
produces one language. Viewers read a *bilingual* srt, where each cue carries
the Japanese line followed by the Chinese in <i> tags, so nothing bilingual
appears until those are filled in.

The translating is done by whoever runs this — a person or an assistant. This
script only handles the two mechanical ends: getting the lines out in a form
that is safe to translate, and putting the results back without disturbing the
timings.

    python scripts/translate.py export out/ep03/subtitles.srt
    #  → out/ep03/subtitles.parts/part1.txt, part2.txt …
    #    translate each, writing the reply beside it as part1.zh.txt
    python scripts/translate.py import out/ep03/subtitles.srt

Split into parts of 150 lines so one bad batch costs one part rather than the
episode. Importing is idempotent: existing translations are replaced, missing
ones are left alone, and a cue with no translation simply shows nothing rather
than blocking the rest.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TS = re.compile(r"\d+:\d+:\d+(?:\.\d+)?[,.]\d+(?:\.\d+)?\s*-->")
LINES_PER_PART = 150

PROMPT = """请把下面这部日剧的台词逐句翻译成中文。

【输出格式】必须严格遵守
- 每行输出:`编号. 中文翻译`(编号后面是英文句点加一个空格)
- 编号必须与原文一一对应,不要合并、拆分、跳过或重新编号
- 输入有多少行,就输出多少行(本次共 {count} 行)
- 只输出编号和译文,不要任何解释、标题、前言、空行

【翻译要求】
- 口语化,保留说话人的语气;这是生活剧,不要书面语
- 一句话没说完就断开的,译文也保持没说完的样子
- 保留原文的省略和语气词感觉,不要补全成完整句子

【原文】
"""

# what a pasted numbered list looks like across chat clients
REPLY_LINE = re.compile(r"^\s*(\d+)\s*(?:[.、:：．)\]]\s*|\s+)(.+?)\s*$")


class Cue:
    __slots__ = ("index", "timing", "jp", "zh")

    def __init__(self, index: str, timing: str, jp: list, zh: list):
        self.index, self.timing, self.jp, self.zh = index, timing, jp, zh


def parse(path: Path) -> list:
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    cues = []
    for block in re.split(r"\n{2,}", text.strip()):
        lines = [l for l in block.split("\n") if l.strip()]
        at = next((i for i, l in enumerate(lines) if TS.search(l)), None)
        if at is None:
            continue
        jp, zh = [], []
        for line in lines[at + 1:]:
            stripped = re.sub(r"</?i>", "", line).strip()
            if not stripped:
                continue
            (zh if "<i>" in line.lower() else jp).append(stripped)
        cues.append(Cue(lines[at - 1].strip() if at else str(len(cues) + 1),
                        lines[at].strip(), jp, zh))
    return cues


def write(path: Path, cues: list):
    blocks = []
    for number, cue in enumerate(cues, 1):
        body = list(cue.jp) + [f"<i>{line}</i>" for line in cue.zh]
        blocks.append("\n".join([str(number), cue.timing, *body]))
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def parts_dir(srt: Path) -> Path:
    return srt.with_suffix(".parts")


def do_export(srt: Path):
    cues = parse(srt)
    if not cues:
        sys.exit(f"no cues in {srt}")
    translatable = [(i, c) for i, c in enumerate(cues) if c.jp]
    out = parts_dir(srt)
    out.mkdir(exist_ok=True)

    written = []
    for start in range(0, len(translatable), LINES_PER_PART):
        chunk = translatable[start:start + LINES_PER_PART]
        number = start // LINES_PER_PART + 1
        # numbering restarts per part so the model counts a short list, not a
        # long one; the import maps it back by position within the same part
        body = "\n".join(f"{n}. {' '.join(cue.jp)}"
                         for n, (_, cue) in enumerate(chunk, 1))
        target = out / f"part{number}.txt"
        target.write_text(PROMPT.format(count=len(chunk)) + body + "\n",
                          encoding="utf-8")
        written.append((target, len(chunk)))

    print(f"{len(translatable)} lines -> {len(written)} part(s) in {out}/")
    for target, count in written:
        print(f"  {target.name}  ({count} lines)")
    print("\nTranslate each part, writing the result beside it as partN.zh.txt "
          "(one\nline per input line, `编号. 中文翻译`). Then run:")
    print(f"  python scripts/translate.py import {srt}")


def do_import(srt: Path):
    cues = parse(srt)
    translatable = [(i, c) for i, c in enumerate(cues) if c.jp]
    source = parts_dir(srt)
    replies = sorted(source.glob("part*.zh.txt"),
                     key=lambda p: int(re.search(r"\d+", p.name).group()))
    if not replies:
        sys.exit(f"no part*.zh.txt in {source}/ — export first, then save the "
                 f"replies there")

    filled = 0
    for reply in replies:
        number = int(re.search(r"\d+", reply.name).group())
        offset = (number - 1) * LINES_PER_PART
        chunk = translatable[offset:offset + LINES_PER_PART]

        found = {}
        for line in reply.read_text(encoding="utf-8-sig").splitlines():
            match = REPLY_LINE.match(line)
            if match:
                found[int(match.group(1))] = match.group(2)

        missing = len(chunk) - len(found)
        print(f"  {reply.name}: {len(found)}/{len(chunk)} lines"
              + (f"  ({missing} missing)" if missing > 0 else ""))
        for position, (_, cue) in enumerate(chunk, 1):
            text = found.get(position)
            if text:
                cue.zh = [text]
                filled += 1

    write(srt, cues)
    print(f"\nwrote {srt} — {filled}/{len(translatable)} lines now bilingual")
    if filled < len(translatable):
        print("Missing lines just show no translation; rerun after fixing a part.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("export", "import"))
    ap.add_argument("srt", type=Path)
    args = ap.parse_args()

    if not args.srt.exists():
        sys.exit(f"not found: {args.srt}")
    (do_export if args.action == "export" else do_import)(args.srt)


if __name__ == "__main__":
    main()
