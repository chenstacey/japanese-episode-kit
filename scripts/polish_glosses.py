#!/usr/bin/env python3
"""Rewrite the definitions that do not work as study cards.

Two dictionaries feed an episode: Chinese Wiktionary where it has the word,
JMdict's English where it does not. Both leave work behind.

The English fallback is not spread evenly — the rarer a word is, the less
likely Wiktionary has it, so it lands hardest on exactly the words picked out
as worth studying: on one episode, a quarter of all entries but a third of the
study keywords.

The Chinese is not uniformly usable either. Wiktionary writes for a page, not a
card, so entries arrive carrying grammar labels, bracketed usage notes, worked
examples and romaji cross-references. A few are the wrong word outright —
しゃべる, "to chat", came through glossed as シャベル, a shovel.

The writing is done by whoever runs this; the script only takes the entries out
and puts them back.

    python scripts/polish_glosses.py export out/ep06
    #  → out/ep06/glosses.todo/part1.txt … write partN.zh.txt beside each
    python scripts/polish_glosses.py import out/ep06

Importing rewrites furigana.json and re-runs the segment proposals, since the
study cards carry a copy of each definition.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV_NLP = HERE.parent / ".venv-nlp"
PER_PART = 60

PROMPT = """请为下面这些日语单词写简短的中文释义。

这些词现有的释义不适合直接放在单词卡上:有的只有英文(中文词典查不到),
有的中文释义带着词性标注、括号说明或例句,还有的干脆匹配错了词。
下面给出的是它们现有的释义,仅供参考 —— 如果和例句对不上,以例句为准。

【输出格式】必须严格遵守
- 每行输出:`编号. 中文释义`(编号后面是英文句点加一个空格)
- 编号必须与输入一一对应,不要合并、拆分、跳过或重新编号
- 输入有多少行,就输出多少行(本次共 {count} 行)
- 只输出编号和释义,不要解释、标题、前言、空行

【释义要求】
- 简短,10 个字以内最好,这是要显示在单词卡片上的
- 多个义项用「,」分开,最多两个,先写最常用的
- 只写词义本身,不要写词性、不要举例、不要加括号说明
- 参考给出的例句判断这个词在剧里的实际用法,优先写贴合的义项

【输入格式】每行是:编号. 单词(读音) — 现有释义 ‖ 剧中例句
"""

REPLY_LINE = re.compile(r"^\s*(\d+)\s*(?:[.、:：．)\]]\s*|\s+)(.+?)\s*$")


def todo_dir(directory: Path) -> Path:
    return directory / "glosses.todo"


KANA = re.compile(r"[ぁ-んァ-ヶ]")

# Wiktionary's Chinese entries are written for a page, not a card: grammar
# labels, bracketed usage notes, worked examples, cross-references in romaji.
# Some are also simply the wrong word — しゃべる ("to chat") arrived glossed as
# シャベル, a shovel.
CRUFT = re.compile(r"[【（(]|\d\.\s|[；;]\s*\S+\s+\(")


def needs_work(base: str, entry: dict) -> bool:
    glosses = entry.get("glosses") or []
    if not glosses:
        return False
    # A single kana is a particle or an interjection. It never becomes a study
    # keyword, and Wiktionary answers it with an essay about the syllable —
    # writing those is effort spent on cards nobody will see.
    if len(base) < 2:
        return False
    if entry.get("lang") != "zh":
        return True                       # English fallback
    if entry.get("gloss_source") == "written":
        return False                      # already rewritten
    first = glosses[0]
    if len(first) > 24 or CRUFT.search(first):
        return True
    # kana in the definition of a word that has none is usually a cross
    # reference or a mismatched entry rather than a meaning
    return bool(KANA.search(first) and not KANA.search(base))


def entries_to_write(pack: dict) -> list:
    """Everything whose definition is unusable as a study card, ordered by the
    word so batches stay stable across runs."""
    return sorted(base for base, entry in pack.get("dict", {}).items()
                  if needs_work(base, entry))


def example_for(base: str, pack: dict, limit: int = 28) -> str:
    """A line the word actually appears in, so the sense can be chosen to fit
    the drama rather than the dictionary's first listing."""
    for line, tokens in pack.get("furigana", {}).items():
        if any(token.get("base") == base for token in tokens):
            return line[:limit]
    return ""


def do_export(directory: Path):
    pack = json.loads((directory / "furigana.json").read_text(encoding="utf-8"))
    bases = entries_to_write(pack)
    if not bases:
        print("nothing to do — every definition already reads as a study card")
        return

    out = todo_dir(directory)
    out.mkdir(exist_ok=True)
    for stale in out.glob("part*.txt"):
        stale.unlink()

    written = []
    for start in range(0, len(bases), PER_PART):
        chunk = bases[start:start + PER_PART]
        number = start // PER_PART + 1
        lines = []
        for n, base in enumerate(chunk, 1):
            entry = pack["dict"][base]
            reading = entry.get("reading") or ""
            current = "; ".join(entry.get("glosses", [])[:3])[:120]
            example = example_for(base, pack)
            lines.append(f"{n}. {base}({reading}) — {current}"
                         + (f" ‖ {example}" if example else ""))
        target = out / f"part{number}.txt"
        target.write_text(PROMPT.format(count=len(chunk)) + "\n" + "\n".join(lines) + "\n",
                          encoding="utf-8")
        written.append((target, len(chunk)))

    print(f"{len(bases)} definitions need writing -> {len(written)} part(s) in {out}/")
    for target, count in written:
        print(f"  {target.name}  ({count} entries)")
    print("\nWrite each part's Chinese beside it as partN.zh.txt, then run:")
    print(f"  python scripts/polish_glosses.py import {directory}")


def do_import(directory: Path, minutes: float):
    pack_path = directory / "furigana.json"
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    bases = entries_to_write(pack)
    source = todo_dir(directory)
    replies = sorted(source.glob("part*.zh.txt"),
                     key=lambda p: int(re.search(r"\d+", p.name).group()))
    if not replies:
        sys.exit(f"no part*.zh.txt in {source}/ — export first, then write the replies there")

    replaced = 0
    for reply in replies:
        number = int(re.search(r"\d+", reply.name).group())
        chunk = bases[(number - 1) * PER_PART:(number - 1) * PER_PART + PER_PART]

        found = {}
        for line in reply.read_text(encoding="utf-8-sig").splitlines():
            match = REPLY_LINE.match(line)
            if match:
                found[int(match.group(1))] = match.group(2)

        missing = len(chunk) - len(found)
        print(f"  {reply.name}: {len(found)}/{len(chunk)} entries"
              + (f"  ({missing} missing)" if missing > 0 else ""))

        for position, base in enumerate(chunk, 1):
            text = found.get(position)
            if not text:
                continue
            entry = pack["dict"][base]
            # keep the English: it is what the Chinese was written from, and
            # the lookup sheet still shows it underneath
            entry.setdefault("glosses_en", entry.get("glosses", []))
            entry["glosses"] = [g.strip() for g in text.split("；") if g.strip()] or [text]
            entry["lang"] = "zh"
            entry["gloss_source"] = "written"
            replaced += 1

    pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
    total = len(pack["dict"])
    zh = sum(1 for e in pack["dict"].values() if e.get("lang") == "zh")
    print(f"\nrewrote {replaced} definitions — {zh}/{total} entries now Chinese "
          f"({zh / total * 100:.0f}%)")

    # study cards carry their own copy of each definition
    if (directory / "segments.json").exists():
        print("re-running the segment proposals so the cards pick these up…")
        # study_segments needs wordfreq, which lives in the NLP virtualenv —
        # sys.executable is whatever interpreter launched this and usually has
        # no such thing
        python = VENV_NLP / "bin" / "python"
        result = subprocess.run(
            [str(python) if python.exists() else sys.executable,
             str(HERE / "study_segments.py"), str(directory), "--minutes", str(minutes)],
            capture_output=True, text=True)
        if result.returncode != 0:
            print("  could not regenerate segments.json:")
            for line in (result.stderr or result.stdout).strip().splitlines()[-3:]:
                print(f"    {line}")
        else:
            print("  done")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("export", "import"))
    ap.add_argument("episode_dir", type=Path)
    ap.add_argument("--minutes", type=float, default=3.0,
                    help="segment length to use when regenerating (default 3)")
    args = ap.parse_args()

    if not (args.episode_dir / "furigana.json").exists():
        sys.exit(f"no furigana.json in {args.episode_dir}")
    if args.action == "export":
        do_export(args.episode_dir)
    else:
        do_import(args.episode_dir, args.minutes)


if __name__ == "__main__":
    main()
