#!/usr/bin/env python3
"""Shared furigana + dictionary logic, used by both srt_to_furigana.py (CLI)
and web/serve.py (the viewer's one-click generate button)."""
import json
import re
import sqlite3
from pathlib import Path

KANJI = re.compile(r"[一-鿿]")

# Tolerant timestamp form: "," or "." before ms, and ms may carry a fractional
# part from some subtitle exporters (e.g. "00:03:22,339.9999999999709").
TS = re.compile(r"\d+:\d+:\d+(?:\.\d+)?[,.]\d+(?:\.\d+)?\s*-->")

# Function words get looked up by their kana form and collide with unrelated
# homophones (the prefix ご matches 五 "five", は matches 羽 "feather"), so they
# carry no dictionary entry and stay unclickable. Content words only.
SKIP_POS = {"助詞", "助動詞", "接頭辞", "接尾辞", "補助記号", "記号", "空白", "フィラー"}

_tagger = None


def get_tagger():
    """Lazily build the tagger -- it costs ~1s and loads a large dictionary."""
    global _tagger
    if _tagger is None:
        import fugashi
        _tagger = fugashi.Tagger()
    return _tagger


def kata_to_hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def japanese_lines(srt_text: str):
    """Yield the Japanese line of each cue (the side without <i> tags)."""
    text = srt_text.replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")
    for block in re.split(r"\n{2,}", text):
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        ts_at = next((i for i, l in enumerate(lines) if TS.search(l)), None)
        if ts_at is None:
            continue
        jp = [re.sub(r"<[^>]*>", "", l).strip()
              for l in lines[ts_at + 1:] if "<i>" not in l.lower()]
        jp = " ".join(p for p in jp if p)
        if jp:
            yield jp


def tokenize(text: str):
    """Split one line into {surface, reading, base} tokens.

    reading is filled only when the surface contains kanji; base is None for
    function words so the viewer leaves them unclickable.
    """
    tokens = []
    for word in get_tagger()(text):
        f = word.feature
        surface = word.surface

        reading = None
        if KANJI.search(surface):
            kana = f.kana or f.pron
            if kana:
                reading = kata_to_hira(kana)

        base = (f.orthBase or surface).strip() or surface
        if f.pos1 in SKIP_POS or not any(c.isalnum() for c in base):
            base = None

        # pos travels with the token so downstream steps can tell an
        # interjection from a verb — picking study vocabulary by rarity alone
        # surfaces ううん and うわあ alongside the words worth learning
        tokens.append({"surface": surface, "reading": reading,
                       "base": base, "pos": f.pos1})
    return tokens


def lookup_words(bases, db_path, zh_db_path=None):
    """Look up dictionary entries for a set of base forms.

    Chinese definitions (zh.wiktionary) are preferred when present and English
    (JMdict) is the fallback, because Chinese covers ~70% of a drama's
    vocabulary against JMdict's ~91%. Each entry records which language its
    glosses came from so the UI can label the fallbacks.

    A missing database is not fatal -- callers still get furigana.
    """
    db_path = Path(db_path)
    zh = {}
    if zh_db_path:
        zh_db_path = Path(zh_db_path)
        if zh_db_path.exists():
            conn = sqlite3.connect(str(zh_db_path))
            try:
                for base in bases:
                    row = conn.execute(
                        "SELECT glosses FROM zh WHERE form = ?", (base,)).fetchone()
                    if row:
                        zh[base] = json.loads(row[0])
            finally:
                conn.close()

    entries = {}
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        try:
            for base in bases:
                row = conn.execute(
                    "SELECT entry_id FROM lookup WHERE form = ? LIMIT 1", (base,)).fetchone()
                if not row:
                    continue
                kana_forms, pos, glosses = (json.loads(x) for x in conn.execute(
                    "SELECT kana_forms, pos, glosses FROM entries WHERE id = ?",
                    (row[0],)).fetchone())
                entries[base] = {
                    "reading": kana_forms[0] if kana_forms else None,
                    "pos": pos,
                    "glosses": glosses[:5],
                    "lang": "en",
                }
        finally:
            conn.close()

    for base, glosses in zh.items():
        entry = entries.get(base)
        if entry:
            # keep the English as a secondary reference
            entry["glosses_en"] = entry["glosses"]
            entry["glosses"] = glosses
            entry["lang"] = "zh"
        else:
            entries[base] = {"reading": None, "pos": [], "glosses": glosses, "lang": "zh"}

    return entries


def build_pack(srt_text: str, db_path, zh_db_path=None):
    """Turn raw SRT text into the {furigana, dict} pack the viewer loads."""
    furigana, bases = {}, set()
    for jp in japanese_lines(srt_text):
        if jp in furigana:
            continue
        tokens = tokenize(jp)
        furigana[jp] = tokens
        bases.update(t["base"] for t in tokens if t["base"])

    return {"furigana": furigana,
            "dict": lookup_words(bases, db_path, zh_db_path)}, len(bases)
