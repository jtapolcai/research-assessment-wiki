#!/usr/bin/env python3
"""Download the OpenAlex topic hierarchy (domains, fields, subfields, topics).

Writes
  data/raw/<entity>.json          full API records (not committed)
  data/openalex_hierarchy.json    cleaned snapshot used by the wiki generator

Uses only the standard library. An OpenAlex API key is optional for this
volume (~30 list requests); set OPENALEX_API_KEY to use one.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

API = "https://api.openalex.org"
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUT_FILE = ROOT / "data" / "openalex_hierarchy.json"
USER_AGENT = "research-assessment-wiki/0.1 (+https://github.com/jtapolcai/research-assessment-wiki)"


def short_id(openalex_id: str | None) -> str | None:
    """'https://openalex.org/T10101' -> 'T10101'; '.../subfields/2208' -> '2208'."""
    if not openalex_id:
        return None
    return openalex_id.rstrip("/").rsplit("/", 1)[-1]


def get_json(url: str, retries: int = 5) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            body = error.read().decode("utf-8", "replace")[:500]
            raise SystemExit(f"HTTP {error.code} for {url}\n{body}") from error
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError("unreachable")


def fetch_all(entity: str) -> list[dict]:
    """Fetch every record of an entity type.

    Uses basic page= paging (allowed without an API key up to 10,000 results;
    cursor paging needs a key). The largest set, topics, is ~4,500 records.
    """
    params = {"per-page": "200", "page": "1"}
    api_key = os.environ.get("OPENALEX_API_KEY")
    if api_key:
        params["api_key"] = api_key
    records: list[dict] = []
    page_number = 1
    while True:
        params["page"] = str(page_number)
        url = f"{API}/{entity}?{urllib.parse.urlencode(params)}"
        page = get_json(url)
        records.extend(page["results"])
        total = page.get("meta", {}).get("count", 0)
        if not page["results"] or len(records) >= total:
            break
        page_number += 1
    if total > 10_000:
        raise SystemExit(f"{entity}: {total} records exceed basic paging; set OPENALEX_API_KEY")
    print(f"{entity}: {len(records)} of {total} records", file=sys.stderr)
    return records


def ref(obj: dict | None) -> str | None:
    return short_id(obj.get("id")) if obj else None


def clean_level(record: dict) -> dict:
    return {
        "id": short_id(record["id"]),
        "name": record["display_name"],
        "description": record.get("description"),
        "wikidata": short_id((record.get("ids") or {}).get("wikidata")),
        "wikipedia": (record.get("ids") or {}).get("wikipedia"),
        "works_count": record.get("works_count"),
        "cited_by_count": record.get("cited_by_count"),
    }


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw = {}
    for entity in ("domains", "fields", "subfields", "topics"):
        raw[entity] = fetch_all(entity)
        (RAW_DIR / f"{entity}.json").write_text(
            json.dumps(raw[entity], ensure_ascii=False, indent=1), encoding="utf-8"
        )

    domains = [clean_level(d) for d in raw["domains"]]
    fields = [{**clean_level(f), "domain": ref(f.get("domain"))} for f in raw["fields"]]
    subfields = [
        {**clean_level(s), "field": ref(s.get("field")), "domain": ref(s.get("domain"))}
        for s in raw["subfields"]
    ]
    topics = [
        {
            **clean_level(t),
            "keywords": [k["display_name"] for k in (t.get("keywords") or [])],
            "subfield": ref(t.get("subfield")),
            "field": ref(t.get("field")),
            "domain": ref(t.get("domain")),
        }
        for t in raw["topics"]
    ]

    for collection in (domains, fields, subfields, topics):
        collection.sort(key=lambda item: (len(item["id"]), item["id"]))

    snapshot = {
        "source": "OpenAlex API (https://api.openalex.org), CC0",
        "retrieved": date.today().isoformat(),
        "counts": {
            "domains": len(domains),
            "fields": len(fields),
            "subfields": len(subfields),
            "topics": len(topics),
        },
        "domains": domains,
        "fields": fields,
        "subfields": subfields,
        "topics": topics,
    }
    OUT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT_FILE.relative_to(ROOT)}: {snapshot['counts']}", file=sys.stderr)


if __name__ == "__main__":
    main()
