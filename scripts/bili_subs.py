#!/usr/bin/env python3
"""Inspect Bilibili's CC subtitle tracks. Diagnostic only — do not trust output.

yt-dlp reports only the `danmaku` comment stream for many Bilibili uploads,
while the player API separately advertises CC tracks. That sounded promising.

It is not. In testing this endpoint was unreliable in two separate ways:

  * it answers intermittently — roughly one request in three returns the track
    list at all, the rest come back empty;
  * worse, twice out of two attempts the track it returned belonged to a
    *different video*. A 15-minute Japanese drama got 26 minutes of Korean
    variety-show captions, then a handful of video-game lines.

A duration check catches the first kind of mismatch and is applied below, but it
cannot catch a wrong track that happens to be short enough. Treat anything this
produces as suspect and read it before using it. For real work, transcribe.

    python scripts/bili_subs.py BV1Dege6VEoD --cookies /tmp/bili_cookies.txt
    python scripts/bili_subs.py BV1Dege6VEoD --part 2 --out subs.zh.srt

Export cookies first (Bilibili refuses anonymous requests with 412):

    yt-dlp --cookies-from-browser chrome --cookies /tmp/bili_cookies.txt \\
           --skip-download --simulate "https://www.bilibili.com/video/BVxxxx"
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

API = "https://api.bilibili.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
REFERER = "https://www.bilibili.com/"


def get_json(url: str, cookies: Path | None) -> dict:
    cmd = ["curl", "-s", "-A", UA, "-e", REFERER]
    if cookies:
        cmd += ["-b", str(cookies)]
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        sys.exit(f"unexpected response from {url[:60]}: {result.stdout[:120]}")


def parts(bvid: str, cookies: Path | None) -> list:
    data = get_json(f"{API}/x/player/pagelist?bvid={bvid}", cookies)
    if data.get("code") != 0:
        sys.exit(f"pagelist failed: {data.get('message')} "
                 f"(412/-403 usually means the cookies are missing or stale)")
    return data.get("data") or []


def tracks(bvid: str, cid: int, cookies: Path | None, attempts: int = 6) -> list:
    """The subtitle list is returned intermittently; ask a few times."""
    for attempt in range(attempts):
        data = get_json(f"{API}/x/player/v2?bvid={bvid}&cid={cid}", cookies)
        found = ((data.get("data") or {}).get("subtitle") or {}).get("subtitles") or []
        if found:
            return found
        if attempt < attempts - 1:
            time.sleep(1.5)
    return []


def to_srt(entries: list) -> str:
    def stamp(t: float) -> str:
        h, rem = divmod(max(0.0, t), 3600)
        m, s = divmod(rem, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"

    lines = []
    for i, item in enumerate(entries, 1):
        lines += [str(i),
                  f"{stamp(item['from'])} --> {stamp(item['to'])}",
                  item.get("content", ""), ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bvid", help="e.g. BV1Dege6VEoD")
    ap.add_argument("--cookies", type=Path, help="netscape cookie file")
    ap.add_argument("--part", type=int, help="1-based part; omit to list all")
    ap.add_argument("--lang", help="preferred track language, e.g. ai-zh")
    ap.add_argument("--out", help="write the chosen track here as .srt")
    args = ap.parse_args()

    pages = parts(args.bvid, args.cookies)
    if not pages:
        sys.exit("no parts found")

    selected = [pages[args.part - 1]] if args.part else pages
    for page in selected:
        print(f"p{page['page']}  cid={page['cid']}  {page['part']}")
        found = tracks(args.bvid, page["cid"], args.cookies)
        if not found:
            print("    no CC track")
            continue
        for track in found:
            print(f"    {track.get('lan')}  {track.get('lan_doc')}")

        if not args.out:
            continue
        chosen = next((t for t in found if t.get("lan") == args.lang), found[0])
        url = chosen["subtitle_url"]
        if url.startswith("//"):
            url = "https:" + url
        payload = get_json(url, None)
        body = payload.get("body") or []
        if not body:
            print("    track was empty")
            continue

        # The flaky endpoint sometimes answers with another video's track
        # entirely — once it returned 26 minutes of Korean variety-show captions
        # for a 15-minute Japanese drama. Compare against the part's duration
        # before trusting anything it hands back.
        last = max(item.get("to", 0) for item in body)
        expected = page.get("duration") or 0
        if expected and last > expected * 1.15:
            print(f"    REJECTED: subtitle runs to {last/60:.1f} min but the part "
                  f"is {expected/60:.1f} min — the API returned another video's track")
            continue

        Path(args.out).write_text(to_srt(body), encoding="utf-8")
        print(f"    wrote {args.out}  ({len(body)} cues, {chosen.get('lan')})")
        print("    note: this is usually a translation, not the Japanese source —"
              " it cannot feed furigana")


if __name__ == "__main__":
    main()
