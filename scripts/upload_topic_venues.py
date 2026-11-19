#!/usr/bin/env python3
"""Add a "Leading venues" table to every topic page.

Reads   data/topic_venues.jsonl                 (from fetch_topic_venues.py)
        data/openalex_hierarchy.json            (topic page titles)
        data/raw/venues/venue_openalex.csv      (Norwegian level per OpenAlex source; optional)
        data/openalex_sources.json              (source types; fetched here and cached, CC0)

The table is written between <!-- BOT:BEGIN venues --> and <!-- BOT:END venues -->, right after
the OpenAlex block; the rest of the page is kept. Only the Norwegian level (CC BY 4.0) is
published; the combined JUFO-based level stays local until the JUFO licence is clarified.

Examples
  scripts/upload_topic_venues.py --dry-run out/ --limit 5
  scripts/upload_topic_venues.py --subfield 1702
  scripts/upload_topic_venues.py
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

from fetch_openalex_hierarchy import get_json, short_id
from upload_hierarchy import END as OPENALEX_END, clean, page_titles
from wikiapi import Wiki, WikiError, load_env

ROOT = Path(__file__).resolve().parent.parent
VENUES = ROOT / "data" / "topic_venues.jsonl"
HIERARCHY = ROOT / "data" / "openalex_hierarchy.json"
LEVELS_CSV = ROOT / "data" / "raw" / "venues" / "venue_openalex.csv"
SOURCES = ROOT / "data" / "openalex_sources.json"
BEGIN, END = "<!-- BOT:BEGIN venues -->", "<!-- BOT:END venues -->"
BLOCK_RE = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
YEARS = "2015–2025"
MAX_VENUES, MIN_SHARE = 25, 0.5  # list at most 25 venues, each with at least 0.5 % of the topic's works


def norway_levels() -> dict[str, str]:
    if not LEVELS_CSV.exists():
        print(f"note: {LEVELS_CSV.relative_to(ROOT)} missing, no Norwegian levels", file=sys.stderr)
        return {}
    levels: dict[str, str] = {}
    with LEVELS_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["openalex_id"] and row["norway_level"] != "":
                levels.setdefault(row["openalex_id"], row["norway_level"])
    return levels


def source_types(ids: set[str]) -> dict[str, str]:
    cache: dict[str, str] = json.loads(SOURCES.read_text()) if SOURCES.exists() else {}
    todo = sorted(ids - set(cache))
    if todo:
        load_env(ROOT / ".env")
        key = os.environ.get("OPENALEX_API_KEY", "")
        print(f"looking up {len(todo)} source types", file=sys.stderr)
        for start in range(0, len(todo), 50):
            batch = todo[start:start + 50]
            params = {"filter": "openalex:" + "|".join(batch), "select": "id,type", "per-page": "200"}
            if key:
                params["api_key"] = key
            page = get_json("https://api.openalex.org/sources?" + urllib.parse.urlencode(params))
            for code in batch:
                cache.setdefault(code, "")
            for src in page["results"]:
                cache[short_id(src["id"])] = src.get("type") or ""
        SOURCES.write_text(json.dumps(cache, sort_keys=True, indent=0))
    return cache


def selected(record: dict) -> list[tuple[int, list, float]]:
    total = record["total"] or 1
    rows = []
    for rank, venue in enumerate(record["venues"][:MAX_VENUES], 1):
        share = 100 * venue[2] / total
        if share < MIN_SHARE and rank > 3:  # always show the top three
            break
        rows.append((rank, venue, share))
    return rows


def venue_block(record: dict, types: dict, norway: dict) -> str:
    if not selected(record):
        return "\n".join([BEGIN, "== Leading venues ==",
                          f"''OpenAlex lists no journal, proceedings or book-series works for this topic "
                          f"in {YEARS}.''", END])
    lines = [BEGIN, "== Leading venues ==", '{| class="wikitable sortable"',
             "! # !! Venue !! Type !! Share of the topic's works (%) !! Norwegian level"]
    for rank, (source, name, works), share in selected(record):
        lines.append(
            f"{{{{Topic venue|topic_id={record['topic']}|rank={rank}|source={source}|name={clean(name)}"
            f"|type={types.get(source, '')}|share={share:.1f}|works={works}|norway={norway.get(source, '')}}}}}")
    lines += ["|}", f"{{{{Topic venues note|years={YEARS}|total={record['total']}"
                    f"|min_share={MIN_SHARE}|max={MAX_VENUES}}}}}", END]
    return "\n".join(lines)


def merge(existing: str, block: str) -> str:
    if BLOCK_RE.search(existing):
        return BLOCK_RE.sub(lambda _m: block, existing, count=1)
    if OPENALEX_END in existing:
        head, tail = existing.split(OPENALEX_END, 1)
        return head + OPENALEX_END + "\n" + block + tail
    return existing.rstrip() + "\n\n" + block + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", metavar="DIR", type=Path, help="write the venue blocks to DIR, no upload")
    parser.add_argument("--subfield", metavar="ID", help="only the topics of this subfield")
    parser.add_argument("--limit", type=int, help="at most this many topics")
    args = parser.parse_args()

    data = json.loads(HIERARCHY.read_text(encoding="utf-8"))
    titles = page_titles(data)
    subfield_of = {t["id"]: t.get("subfield") for t in data["topics"]}
    records = [json.loads(line) for line in VENUES.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.subfield:
        records = [r for r in records if subfield_of.get(r["topic"]) == args.subfield]
    records = records[: args.limit]
    types = source_types({v[0] for r in records for _, v, _ in selected(r)})
    norway = norway_levels()
    blocks = {titles[("topics", r["topic"])]: venue_block(r, types, norway) for r in records}
    print(f"{len(blocks)} topic pages prepared", file=sys.stderr)

    if args.dry_run:
        args.dry_run.mkdir(parents=True, exist_ok=True)
        for title, block in blocks.items():
            (args.dry_run / f"{title.replace('/', '_')}.venues.wiki").write_text(block + "\n", encoding="utf-8")
        print(f"wrote {len(blocks)} files to {args.dry_run}", file=sys.stderr)
        return

    load_env(ROOT / ".env")
    wiki = Wiki(os.environ["WIKI_API_URL"])
    try:
        wiki.login(os.environ["WIKI_BOT_USER"], os.environ["WIKI_BOT_PASSWORD"])
    except WikiError as error:
        raise SystemExit(f"{error}\nIs the tunnel open (scripts/upload_channel.sh)?")

    current = wiki.read_pages(list(blocks))
    updated = unchanged = 0
    failures: list[tuple[str, str]] = []
    started = time.time()
    for number, (title, block) in enumerate(blocks.items(), 1):
        existing = current.get(title)
        if existing is None:
            failures.append((title, "topic page does not exist"))
            continue
        new_text = merge(existing, block)
        if new_text.rstrip() == existing.rstrip():
            unchanged += 1
        else:
            try:
                wiki.edit(title, new_text, "Bot: leading venues from OpenAlex")
                updated += 1
            except WikiError as error:
                failures.append((title, str(error)))
        if number % 100 == 0 or number == len(blocks):
            print(f"  {number}/{len(blocks)}  updated {updated}, unchanged {unchanged}, "
                  f"failed {len(failures)}  ({time.time() - started:.0f}s)", file=sys.stderr)
    for title, error in failures[:20]:
        print(f"FAILED {title}: {error}", file=sys.stderr)
    if failures:
        raise SystemExit(f"{len(failures)} pages failed")


if __name__ == "__main__":
    main()
