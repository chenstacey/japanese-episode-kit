#!/usr/bin/env python3
"""Build the two lookup databases. Run once, via setup.sh.

Chinese and English come from different projects because JMdict has no Chinese
edition — its multilingual releases are Dutch, French, German, Hungarian,
Russian, Slovenian, Spanish and Swedish. Chinese definitions therefore come from
the Chinese Wiktionary, which covers roughly 70% of an episode's vocabulary
against JMdict's 91%, so both are kept and Chinese is preferred per word.
"""
import argparse
import gzip
import json
import re
import sqlite3
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

JMDICT_RELEASES = "https://api.github.com/repos/scriptin/jmdict-simplified/releases/latest"
ZH_SOURCE = "https://kaikki.org/dictionary/downloads/zh/zh-extract.jsonl.gz"

HEADWORD_PREFIX = re.compile(r"^[^\s]{1,12}【[^】]*】\s*")


def build_jmdict(out_dir: Path):
    db = out_dir / "jmdict.sqlite"
    if db.exists():
        print("  jmdict.sqlite already built")
        return

    with urllib.request.urlopen(JMDICT_RELEASES) as response:
        release = json.load(response)
    asset = next((a for a in release["assets"]
                  if a["name"].startswith("jmdict-eng-")
                  and a["name"].endswith(".json.tgz")), None)
    if not asset:
        sys.exit("could not find jmdict-eng-*.json.tgz in the latest release")

    archive = out_dir / "jmdict-eng.json.tgz"
    print(f"  downloading {asset['name']}")
    subprocess.run(["curl", "-sL", asset["browser_download_url"], "-o", str(archive)],
                   check=True)

    with tarfile.open(archive) as tf:
        name = next(n for n in tf.getnames() if n.endswith(".json"))
        tf.extract(name, out_dir)
    json_path = out_dir / name

    print("  indexing English entries…")
    words = json.loads(json_path.read_text())["words"]
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, kanji_forms TEXT, "
                 "kana_forms TEXT, pos TEXT, glosses TEXT)")
    conn.execute("CREATE TABLE lookup (form TEXT, entry_id INTEGER)")
    for word in words:
        kanji = [k["text"] for k in word.get("kanji", [])]
        kana = [k["text"] for k in word.get("kana", [])]
        pos = sorted({p for s in word["sense"] for p in s.get("partOfSpeech", [])})
        glosses = [g["text"] for s in word["sense"]
                   for g in s.get("gloss", []) if g.get("lang") == "eng"]
        cursor = conn.execute(
            "INSERT INTO entries (kanji_forms, kana_forms, pos, glosses) VALUES (?,?,?,?)",
            tuple(json.dumps(x, ensure_ascii=False) for x in (kanji, kana, pos, glosses)))
        for form in set(kanji + kana):
            conn.execute("INSERT INTO lookup (form, entry_id) VALUES (?,?)",
                         (form, cursor.lastrowid))
    conn.execute("CREATE INDEX idx_lookup_form ON lookup (form)")
    conn.commit()
    conn.close()

    json_path.unlink()
    archive.unlink()
    print(f"  {len(words):,} English entries -> {db.name}")


def clean_gloss(text: str) -> str:
    lines = [l.strip() for l in text.replace("　", " ").split("\n") if l.strip()]
    lines = [HEADWORD_PREFIX.sub("", l) for l in lines]
    lines = [l for l in lines if l and not re.fullmatch(r"[^\s]{1,12}【[^】]*】", l)]
    return " ".join(lines).strip()


def build_chinese(out_dir: Path):
    db = out_dir / "ja_zh.sqlite"
    if db.exists():
        print("  ja_zh.sqlite already built")
        return

    archive = out_dir / "zh-extract.jsonl.gz"
    if not archive.exists():
        print("  downloading zh.wiktionary extract (~215 MB, once)")
        subprocess.run(["curl", "-sL", ZH_SOURCE, "-o", str(archive)], check=True)

    print("  scanning for Japanese entries…")
    entries = {}
    with gzip.open(archive, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("lang_code") != "ja":
                continue
            word = (item.get("word") or "").strip()
            if not word:
                continue
            glosses = []
            for sense in item.get("senses", []):
                for gloss in sense.get("glosses") or []:
                    cleaned = clean_gloss(gloss)
                    if cleaned and cleaned not in glosses:
                        glosses.append(cleaned)
            if glosses:
                entries.setdefault(word, glosses[:5])

    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE zh (form TEXT PRIMARY KEY, glosses TEXT)")
    conn.executemany("INSERT OR REPLACE INTO zh (form, glosses) VALUES (?,?)",
                     ((w, json.dumps(g, ensure_ascii=False)) for w, g in entries.items()))
    conn.commit()
    conn.close()
    archive.unlink()
    print(f"  {len(entries):,} Chinese entries -> {db.name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="dict")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    build_jmdict(out_dir)
    build_chinese(out_dir)


if __name__ == "__main__":
    main()
