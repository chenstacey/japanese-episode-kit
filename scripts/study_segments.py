#!/usr/bin/env python3
"""Propose three-minute stretches worth studying closely, and the vocabulary in
each. Run with the NLP virtualenv.

    python scripts/study_segments.py out/ep01 --minutes 3

Writes out/ep01/segments.json.

Two findings shaped this:

* **Cut on silence.** A stretch that starts mid-sentence is useless for blind
  listening. This episode had 311 gaps of 2.5s or more, so there is always a
  natural boundary within a few seconds of any target length.

* **Rarity alone picks transcription errors.** The rarest "words" in the first
  episode were フィニャンシュ, 掃持, 瀋尾 — mis-heard fragments, not vocabulary.
  A word therefore has to be rare *and* carry a dictionary entry *and* not be an
  interjection before it counts as worth annotating.

There is a real tension in the scoring: the stretches with the densest, easiest
dialogue also carry the fewest new words. Rather than average that away, three
different candidates are offered — easiest, richest, and balanced — and the
choice is left to the listener.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TS = re.compile(r"(\d+):(\d+):([\d.]+)[,.](\d+)\s*-->\s*(\d+):(\d+):([\d.]+)[,.](\d+)")

# fillers and interjections are rare by frequency but not worth studying
SKIP_POS = {"感動詞", "補助記号", "記号", "助詞", "助動詞", "接頭辞", "接尾辞", "フィラー"}

GAP = 2.5          # a silence this long reads as a scene break
RARE = 4.0         # zipf below this counts as worth annotating


def parse_srt(path: Path) -> list:
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    cues = []
    for block in re.split(r"\n{2,}", text.strip()):
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        idx = next((i for i, l in enumerate(lines) if TS.search(l)), None)
        if idx is None:
            continue
        m = TS.search(lines[idx])
        g = [float(x) for x in m.groups()]
        jp, zh = [], []
        for line in lines[idx + 1:]:
            stripped = re.sub(r"<[^>]*>", "", line).strip()
            if not stripped:
                continue
            (zh if "<i>" in line.lower() else jp).append(stripped)
        cues.append({
            "start": g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000,
            "end": g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000,
            "jp": " ".join(jp), "zh": " ".join(zh),
        })
    return sorted(cues, key=lambda c: c["start"])


def snap_points(cues: list) -> list:
    """Times where a segment may begin or end without cutting a sentence."""
    points = [cues[0]["start"]] if cues else []
    for i in range(len(cues) - 1):
        if cues[i + 1]["start"] - cues[i]["end"] >= GAP:
            points.append(cues[i + 1]["start"])
    return points


# A leading part-of-speech label: 形, 名·形动, 他上一, 自五, サ変 …
POS_LABEL = re.compile(
    r"^(?:[名動动形副助代数量連连介嘆叹接自他]|サ変|形动|形動)"
    r"[\w·・、]{0,4}\s+")


def shorten_gloss(text: str) -> str:
    """Trim a dictionary gloss down to something that fits on a card.

    Wiktionary entries arrive with a grammar label and worked examples attached
    ("他上一 1. 借。 本を借りる 借书。 2. 租。 …"). The full text still belongs in
    the lookup sheet; a study card needs the first sense and nothing else.

    Order matters: the label has to come off before the numbered senses are
    split, or a gloss like "形 1. 可惜，遗憾。 …" cuts at " 1. " and leaves the
    card reading just "形".
    """
    text = POS_LABEL.sub("", text.strip())
    text = re.sub(r"^\d+\.\s*", "", text)          # the first sense's marker
    text = re.split(r"\s+\d+\.\s", text)[0]        # stop before the second
    # stop at the first example sentence — they start with Japanese script
    text = re.split(r"\s+(?=[ぁ-んァ-ヶ一-鿿]{2,}[はがをにでへ])", text)[0]
    return text.strip(" ；;，,。")[:40]


def best_gloss(glosses) -> str:
    """The first gloss that survives trimming with something left to read.

    Some entries are a bare grammar label with the meaning only in a later
    sense; keeping an empty card would be worse than showing nothing.
    """
    for gloss in glosses or []:
        short = shorten_gloss(gloss)
        if short:
            return short
    return ""


def analyse(cues: list, pack: dict, start: float, end: float, zipf) -> dict:
    inside = [c for c in cues if c["start"] >= start - 0.01 and c["end"] <= end + 0.01]
    if len(inside) < 8:
        return None

    speech = sum(c["end"] - c["start"] for c in inside)
    chars = sum(len(c["jp"]) for c in inside)
    biggest_gap = max((inside[i + 1]["start"] - inside[i]["end"]
                       for i in range(len(inside) - 1)), default=0.0)

    words = {}
    for cue in inside:
        for token in pack["furigana"].get(cue["jp"], []):
            base = token.get("base")
            if not base or len(base) < 2 or token.get("pos") in SKIP_POS:
                continue
            entry = pack["dict"].get(base)
            if not entry or base in words:
                continue
            if zipf(base) >= RARE:
                continue
            gloss = best_gloss(entry.get("glosses"))
            if not gloss:
                continue          # nothing readable to put on a card
            words[base] = {
                "base": base,
                "reading": entry.get("reading") or token.get("reading"),
                "gloss": gloss,
                "lang": entry.get("lang", "en"),
                "at": round(cue["start"], 2),
            }

    return {
        "start": round(start, 2), "end": round(end, 2),
        "cues": len(inside),
        "speechRatio": round(speech / (end - start), 3),
        "charsPerSecond": round(chars / speech, 2) if speech else 0,
        "biggestGap": round(biggest_gap, 1),
        "keywords": sorted(words.values(), key=lambda w: w["at"]),
        "preview": inside[0]["jp"][:30],
    }


def pick_diverse(candidates: list, count: int = 3) -> list:
    """Offer genuinely different options rather than three overlapping windows."""
    def take(ranked, chosen):
        for candidate in ranked:
            if all(candidate["end"] <= c["start"] or candidate["start"] >= c["end"]
                   for c in chosen):
                return candidate
        return None

    chosen = []
    easiest = sorted(candidates, key=lambda c: -c["speechRatio"])
    richest = sorted(candidates, key=lambda c: -len(c["keywords"]))
    balanced = sorted(candidates,
                      key=lambda c: -(c["speechRatio"] * 2 + min(len(c["keywords"]), 12) * 0.06))

    for label, ranked in (("dense", easiest), ("vocabulary", richest), ("balanced", balanced)):
        pick = take(ranked, chosen)
        if pick:
            pick = dict(pick, character=label)
            chosen.append(pick)
    return chosen[:count]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episode_dir", help="a directory produced by make_episode.py")
    ap.add_argument("--minutes", type=float, default=3.0)
    ap.add_argument("--tolerance", type=float, default=45.0,
                    help="how far the length may stretch to land on a silence")
    args = ap.parse_args()

    try:
        from wordfreq import zipf_frequency
    except ImportError:
        sys.exit("wordfreq is needed\n  run: bash scripts/setup.sh")

    def zipf(word: str) -> float:
        return zipf_frequency(word, "ja")

    directory = Path(args.episode_dir)
    cues = parse_srt(directory / "subtitles.srt")
    if not cues:
        sys.exit("no cues in subtitles.srt")
    pack_path = directory / "furigana.json"
    if not pack_path.exists():
        sys.exit("furigana.json is required — rerun make_episode.py without --no-furigana")
    pack = json.loads(pack_path.read_text(encoding="utf-8"))

    points = snap_points(cues)
    target = args.minutes * 60
    print(f"{len(cues)} cues, {len(points)} natural break points")

    candidates = []
    for start in points:
        # end on the break nearest the target length
        options = [p for p in points
                   if abs((p - start) - target) <= args.tolerance and p > start]
        for end in options:
            result = analyse(cues, pack, start, end, zipf)
            if result:
                candidates.append(result)

    if not candidates:
        sys.exit("no candidate segments — try a different --minutes or --tolerance")

    chosen = pick_diverse(candidates)
    (directory / "segments.json").write_text(
        json.dumps({"segments": chosen}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{len(candidates)} candidates considered; offering {len(chosen)}:\n")
    for segment in chosen:
        minutes = lambda t: f"{int(t // 60)}:{int(t % 60):02d}"
        print(f"  [{segment['character']}]  {minutes(segment['start'])}–{minutes(segment['end'])}"
              f"   {segment['cues']} cues"
              f"   speech {segment['speechRatio']*100:.0f}%"
              f"   {len(segment['keywords'])} key words")
        print(f"      {segment['preview']}")
        if segment["keywords"]:
            sample = "、".join(w["base"] for w in segment["keywords"][:8])
            print(f"      {sample}")
        print()
    print(f"wrote {directory / 'segments.json'}")


if __name__ == "__main__":
    main()
