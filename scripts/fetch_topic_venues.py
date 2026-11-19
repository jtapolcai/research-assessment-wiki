#!/usr/bin/env python3
"""Fetch, for every OpenAlex topic, the venues where its works appear.

One /works?group_by=primary_location.source.id request per topic (4,516 in total, about $0.45),
limited to works published 2015-2025 in journals, conference proceedings and book series
(repositories such as arXiv or HAL are left out). OpenAlex returns the 200 largest venues.

Output  data/topic_venues.jsonl   one line per topic:
        {"topic": "T10181", "total": 41215, "venues": [["S106296714", "Lecture notes ...", 1832], ...]}
The file holds OpenAlex data only (CC0) and is committed. Re-runs skip topics already in it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

from fetch_openalex_hierarchy import get_json, short_id
from wikiapi import load_env

ROOT = Path(__file__).resolve().parent.parent
HIERARCHY = ROOT / "data" / "openalex_hierarchy.json"
OUT = ROOT / "data" / "topic_venues.jsonl"
YEARS = "2015-2025"
SOURCE_TYPES = "journal|conference|book series"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="fetch at most this many new topics")
    args = parser.parse_args()

    load_env(ROOT / ".env")
    key = os.environ.get("OPENALEX_API_KEY")
    if not key:
        raise SystemExit("OPENALEX_API_KEY missing in .env")

    topics = [t["id"] for t in json.loads(HIERARCHY.read_text())["topics"]]
    done = set()
    if OUT.exists():
        done = {json.loads(line)["topic"] for line in OUT.read_text().splitlines() if line.strip()}
    todo = [t for t in topics if t not in done][: args.limit]
    print(f"{len(topics)} topics, {len(done)} done, {len(todo)} to fetch", file=sys.stderr)

    started = time.time()
    with OUT.open("a", encoding="utf-8") as out:
        for n, topic in enumerate(todo, 1):
            params = {
                "filter": f"primary_topic.id:{topic},publication_year:{YEARS},"
                          f"primary_location.source.type:{SOURCE_TYPES}",
                "group_by": "primary_location.source.id",
                "api_key": key,
            }
            page = get_json("https://api.openalex.org/works?" + urllib.parse.urlencode(params))
            venues = [[short_id(g["key"]), g["key_display_name"], g["count"]]
                      for g in page["group_by"] if g["key"] and g["key"] != "unknown"]
            out.write(json.dumps({"topic": topic, "total": page["meta"]["count"], "venues": venues},
                                 ensure_ascii=False) + "\n")
            if n % 100 == 0 or n == len(todo):
                out.flush()
                print(f"  {n}/{len(todo)} ({time.time() - started:.0f}s)", file=sys.stderr)


if __name__ == "__main__":
    main()
