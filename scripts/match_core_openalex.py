#!/usr/bin/env python3
"""Match CORE/ICORE conference rankings to OpenAlex sources.

Inputs
  core_table.csv (path as argument)   ID, Name, Acronym (';'-separated), YearsListed ("CORE2023_A*, ICORE2026_A*")
                                      from https://github.com/jtapolcai/corePaperList (inputs/core_table.csv)
  data/topic_venues.jsonl             venue names that appear in the topic tables
  data/core_openalex_manual.csv       hand-made links for venues the rules miss (e.g. AAAI, PVLDB, PACMMOD)
Cache
  data/raw/venues/openalex_conferences.json   all OpenAlex sources of type 'conference' (~20,000; ~100 requests)
Output
  data/core_openalex.csv              one row per matched OpenAlex source: CORE id, acronym, latest rank, edition, how matched

Matching (in this order; a source keeps its first match):
  0. the manual list
  1. normalised full name equals the normalised OpenAlex name or one of its alternate titles
  2. the CORE acronym appears in brackets in the OpenAlex name / alternate title, or an alternate title
     equals the acronym, and at least half of the CORE name's significant words occur in the OpenAlex name
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

from fetch_openalex_hierarchy import get_json, short_id
from wikiapi import load_env

ROOT = Path(__file__).resolve().parent.parent
CONFS = ROOT / "data" / "raw" / "venues" / "openalex_conferences.json"
TOPIC_VENUES = ROOT / "data" / "topic_venues.jsonl"
OUT = ROOT / "data" / "core_openalex.csv"
MANUAL = ROOT / "data" / "core_openalex_manual.csv"
STOP = {"proceedings", "of", "the", "on", "in", "and", "for", "international", "conference", "symposium",
        "workshop", "annual", "acm", "ieee", "ifip", "usenix", "siam", "joint", "a", "an", "to", "at",
        "meeting", "forum", "proc", "series", "edition", "intl", "conf", "european", "european"}
EDITION_ORDER = ["ERA2010", "CORE2008", "CORE2013", "CORE2014", "CORE2017", "CORE2018",
                 "CORE2020", "CORE2021", "CORE2023", "ICORE2026"]


def words(text: str) -> list[str]:
    text = re.sub(r"\b(19|20)\d\d\b|\b\d+(st|nd|rd|th)\b|'\d\d", " ", text.lower().replace("&", " and "))
    return re.findall(r"[a-z0-9]+", text)


def norm(text: str) -> str:
    return " ".join(w for w in words(text) if w not in STOP)


def latest_rank(years_listed: str) -> tuple[str, str]:
    best = ("", "")
    for item in years_listed.split(","):
        edition, _, rank = item.strip().partition("_")
        if edition in EDITION_ORDER and (not best[0] or EDITION_ORDER.index(edition) > EDITION_ORDER.index(best[0])):
            best = (edition, rank)
    return best


def conferences() -> list[dict]:
    if CONFS.exists():
        return json.loads(CONFS.read_text())
    load_env(ROOT / ".env")
    key = os.environ.get("OPENALEX_API_KEY")
    if not key:
        raise SystemExit("OPENALEX_API_KEY missing in .env")
    result, cursor = [], "*"
    while cursor:
        params = {"filter": "type:conference", "per-page": "200", "cursor": cursor, "api_key": key,
                  "select": "id,display_name,alternate_titles,abbreviated_title,works_count"}
        page = get_json("https://api.openalex.org/sources?" + urllib.parse.urlencode(params))
        result += [{"id": short_id(s["id"]), "name": s["display_name"],
                    "alt": [t for t in (s.get("alternate_titles") or []) + [s.get("abbreviated_title")] if t],
                    "works": s.get("works_count") or 0} for s in page["results"]]
        cursor = page["meta"].get("next_cursor")
        print(f"  {len(result)} conference sources", file=sys.stderr)
    CONFS.write_text(json.dumps(result))
    return result


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: match_core_openalex.py path/to/core_table.csv")
    with open(sys.argv[1], newline="", encoding="utf-8") as f:
        core = [r for r in csv.DictReader(f)]

    # Candidate OpenAlex sources: all conferences, plus journal-type venues from the topic tables
    # whose names look like proceedings (e.g. "Proceedings of the AAAI Conference ...").
    sources: dict[str, dict] = {c["id"]: c for c in conferences()}
    for line in TOPIC_VENUES.read_text(encoding="utf-8").splitlines():
        for sid, name, _ in json.loads(line)["venues"]:
            if name and sid not in sources and re.search(r"proceedings|conference|symposium", name, re.I):
                sources[sid] = {"id": sid, "name": name, "alt": [], "works": 0}

    by_name: dict[str, list[str]] = {}
    for s in sources.values():
        for title in [s["name"], *s["alt"]]:
            if (key := norm(title)):
                by_name.setdefault(key, []).append(s["id"])

    matches: dict[str, dict] = {}

    side = re.compile(r"workshop|extended abstract|companion|adjunct|poster|demo|doctoral|tutorial", re.I)

    def add(sid: str, row: dict, how: str) -> None:
        if sid in matches:
            return
        if how != "manual" and side.search(sources[sid]["name"]) and not side.search(row["Name"]):
            return  # a workshop or companion volume does not inherit the main conference's rank
        own = re.findall(r"\(([A-Z][A-Za-z0-9-]{1,15})\)", sources[sid]["name"])
        if how not in ("acronym", "manual") and own and not set(own) & {a.strip() for a in row["Acronym"].split(";")}:
            return  # OpenAlex names a different acronym
        edition, rank = latest_rank(row["YearsListed"])
        if rank not in ("A*", "A", "B", "C"):
            return
        matches[sid] = {"openalex_id": sid, "openalex_name": sources[sid]["name"], "core_id": row["ID"],
                        "core_name": row["Name"], "acronym": row["Acronym"].split(";")[0],
                        "core_rank": rank, "core_edition": edition, "matched_by": how}

    core_by_id = {row["ID"]: row for row in core}
    with MANUAL.open(newline="", encoding="utf-8") as f:  # 0. manual links
        for link in csv.DictReader(f):
            sources.setdefault(link["openalex_id"], {"id": link["openalex_id"], "name": link["note"], "alt": [], "works": 0})
            add(link["openalex_id"], core_by_id[link["core_id"]], "manual")
    for row in core:  # 1. full name
        for sid in by_name.get(norm(row["Name"]), []):
            add(sid, row, "name")
    def jaccard(a: set, b: set) -> float:
        return len(a & b) / len(a | b) if a and b else 0.0

    # 2. acronym in brackets, as the whole title, or as a "ACR 2019"-style prefix, plus similar names.
    # Only acronym-like strings count (two capitals or digits), so 'Networking' or 'Interaction' do not.
    source_words = {sid: set(norm(" ".join([s["name"], *s["alt"]])).split()) for sid, s in sources.items()}
    by_acronym: dict[str, set[str]] = {}
    for s in sources.values():
        for t in [s["name"], *s["alt"]]:
            for a in re.findall(r"\(([^()]{2,20})\)", t) + [t.strip()] + re.findall(r"^([A-Z][A-Za-z0-9-]+)\s+'?\d", t):
                by_acronym.setdefault(a.strip(), set()).add(s["id"])
    for row in core:
        acronyms = {a.strip() for a in row["Acronym"].split(";")
                    if len(re.findall(r"[A-Z0-9]", a)) >= 2 and len(a.strip()) <= 20}
        core_words = set(norm(row["Name"]).split())
        for a in acronyms:
            for sid in by_acronym.get(a, ()):
                if len(core_words & source_words[sid]) >= max(1, 2 * len(core_words) / 3):
                    add(sid, row, "acronym")
    # 3. nearly the same significant words (Jaccard >= 0.8, at least three words)
    for row in core:
        core_words = set(norm(row["Name"]).split())
        if len(core_words) < 3:
            continue
        for sid, s in sources.items():
            if sid not in matches and jaccard(core_words, set(norm(s["name"]).split())) >= 0.8:
                add(sid, row, "similar name")

    rows = sorted(matches.values(), key=lambda r: (r["core_rank"], r["acronym"]))
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    from collections import Counter
    print(f"{len(core)} CORE entries, {len({r['core_id'] for r in rows})} matched to {len(rows)} OpenAlex sources",
          file=sys.stderr)
    print("by rank:", Counter(r["core_rank"] for r in rows).most_common(), file=sys.stderr)
    print("by method:", Counter(r["matched_by"] for r in rows).most_common(), file=sys.stderr)
    print(f"wrote {OUT.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
