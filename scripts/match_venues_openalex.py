#!/usr/bin/env python3
"""Match the combined venue list to OpenAlex sources by ISSN.

Input   data/raw/venues/venue_levels.csv    (from build_venue_levels.py)
Output  data/raw/venues/venue_openalex.csv  same rows + OpenAlex source id, name, type, works count
Cache   data/raw/venues/openalex_issn_cache.json  (ISSN -> source; re-runs only query new ISSNs)

Queries /sources?filter=issn:A|B|... in batches of 50. Needs OPENALEX_API_KEY in .env
(about 1,600 list requests in total).
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

from fetch_openalex_hierarchy import get_json, short_id
from wikiapi import load_env

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "venues"
IN_FILE, OUT_FILE = RAW / "venue_levels.csv", RAW / "venue_openalex.csv"
CACHE = RAW / "openalex_issn_cache.json"
BATCH = 50
FIELDS = "id,display_name,issn_l,issn,type,works_count,host_organization_name"


def main() -> None:
    load_env(ROOT / ".env")
    key = os.environ.get("OPENALEX_API_KEY")
    if not key:
        raise SystemExit("OPENALEX_API_KEY missing in .env")

    with IN_FILE.open(newline="", encoding="utf-8") as f:
        venues = list(csv.DictReader(f))
    wanted = sorted({code for v in venues for code in v["issns"].split()})
    cache: dict[str, dict | None] = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [c for c in wanted if c not in cache]
    print(f"{len(wanted)} ISSNs, {len(todo)} to query", file=sys.stderr)

    started = time.time()
    for n, start in enumerate(range(0, len(todo), BATCH), 1):
        batch = todo[start:start + BATCH]
        params = {"filter": "issn:" + "|".join(batch), "per-page": "200", "select": FIELDS, "api_key": key}
        page = get_json("https://api.openalex.org/sources?" + urllib.parse.urlencode(params))
        for code in batch:
            cache.setdefault(code, None)
        for src in page["results"]:
            record = {"id": short_id(src["id"]), "name": src["display_name"], "type": src.get("type"),
                      "works_count": src.get("works_count"), "publisher": src.get("host_organization_name")}
            for code in (src.get("issn") or []) + [src.get("issn_l")]:
                if code in batch and cache.get(code) is None:
                    cache[code] = record
        if n % 20 == 0 or start + BATCH >= len(todo):
            CACHE.write_text(json.dumps(cache))
            print(f"  {min(start + BATCH, len(todo))}/{len(todo)} ISSNs ({time.time() - started:.0f}s)", file=sys.stderr)
    CACHE.write_text(json.dumps(cache))

    matched = 0
    for v in venues:
        hit = next((cache[c] for c in v["issns"].split() if cache.get(c)), None)
        v["openalex_id"] = hit["id"] if hit else ""
        v["openalex_name"] = hit["name"] if hit else ""
        v["openalex_type"] = hit["type"] if hit else ""
        v["openalex_works"] = hit["works_count"] if hit else ""
        matched += bool(hit)
    with OUT_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(venues[0]))
        writer.writeheader()
        writer.writerows(venues)
    with_issn = sum(1 for v in venues if v["issns"])
    print(f"matched {matched} of {with_issn} venues with an ISSN ({len(venues)} venues in total)", file=sys.stderr)
    print(f"wrote {OUT_FILE.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
