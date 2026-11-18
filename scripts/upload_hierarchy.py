#!/usr/bin/env python3
"""Upload the OpenAlex hierarchy and the wiki templates to MediaWiki.

Reads   data/openalex_hierarchy.json  (from fetch_openalex_hierarchy.py)
        wiki/<Namespace>/<Title>.wiki (templates and fixed pages; "Main" = no namespace)
        .env                          (WIKI_API_URL, WIKI_BOT_USER, WIKI_BOT_PASSWORD)

Entity pages hold a bot block between markers. On re-runs only that block is
replaced, so text that curators add outside the markers is kept. Pages whose
content would not change are skipped.

Examples
  scripts/upload_hierarchy.py --dry-run out/            # write wikitext files, no upload
  scripts/upload_hierarchy.py --subfield 1705           # pilot: one subfield's topics
  scripts/upload_hierarchy.py                           # everything (~4,800 pages)

After the first upload, create and fill the Cargo tables on the server (see README):
  docker compose exec mediawiki php maintenance/run.php ./extensions/Cargo/maintenance/cargoRecreateData.php --create-missing-tables-only
  docker compose exec mediawiki php maintenance/run.php ./extensions/Cargo/maintenance/cargoRecreateData.php
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

from wikiapi import Wiki, WikiError, load_env

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "openalex_hierarchy.json"
WIKI_DIR = ROOT / "wiki"
LEVELS = ("domains", "fields", "subfields", "topics")
TEMPLATE_FOR = {"domains": "Domain", "fields": "Field", "subfields": "Subfield", "topics": "Topic"}
BEGIN, END = "<!-- BOT:BEGIN openalex -->", "<!-- BOT:END openalex -->"
BLOCK_RE = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)


# --- wikitext generation ------------------------------------------------------

def clean(value) -> str:
    """Make a value safe as a template parameter."""
    if value is None:
        return ""
    text = " ".join(str(value).split())  # no newlines
    return text.replace("|", "{{!}}").replace("{{", "&#123;&#123;").replace("}}", "&#125;&#125;") \
        .replace("&#123;&#123;!&#125;&#125;", "{{!}}")


def page_titles(data: dict) -> dict[tuple[str, str], str]:
    """(level, id) -> page title. Names used on more than one level get a suffix
    on every level except the lowest one, e.g. 'Social Sciences (domain)'."""
    owners: dict[str, list[str]] = {}
    for level in LEVELS:
        for item in data[level]:
            owners.setdefault(item["name"], []).append(level)
    titles = {}
    for level in LEVELS:
        for item in data[level]:
            name = item["name"]
            levels_with_name = owners[name]
            if len(levels_with_name) > 1 and level != max(levels_with_name, key=LEVELS.index):
                name = f"{name} ({level[:-1]})"
            titles[(level, item["id"])] = name
    if len(set(titles.values())) != len(titles):
        dupes = [t for t, c in Counter(titles.values()).items() if c > 1]
        raise SystemExit(f"duplicate page titles: {dupes[:10]}")
    return titles


PARENT_OF = {"fields": "domain", "subfields": "field", "topics": "subfield"}


def share_tables(data: dict) -> dict[tuple[str, str], dict[str, float]]:
    """(level, id) -> shares, computed among siblings so that every list sums to 100 %.

    works_share / citations_share: percent of the parent (for domains: of all works)
    works_permille: per mille of all works in OpenAlex
    Absolute counts change daily; shares are stable enough to publish.
    """
    shares = {}
    for level in LEVELS:
        items = data[level]
        total_works = sum(i.get("works_count") or 0 for i in items) or 1
        parent_key = PARENT_OF.get(level)
        works_by_parent: dict[str | None, int] = {}
        cites_by_parent: dict[str | None, int] = {}
        for i in items:
            key = i.get(parent_key) if parent_key else None
            works_by_parent[key] = works_by_parent.get(key, 0) + (i.get("works_count") or 0)
            cites_by_parent[key] = cites_by_parent.get(key, 0) + (i.get("cited_by_count") or 0)
        for i in items:
            key = i.get(parent_key) if parent_key else None
            works, cites = i.get("works_count") or 0, i.get("cited_by_count") or 0
            shares[(level, i["id"])] = {
                "works_share": round(100 * works / (works_by_parent[key] or 1), 2),
                "citations_share": round(100 * cites / (cites_by_parent[key] or 1), 2),
                "works_permille": round(1000 * works / total_works, 3),
            }
    return shares


def bot_block(level: str, item: dict, titles: dict, shares: dict) -> str:
    params = {"openalex_id": item["id"], "name": item["name"], "description": item.get("description")}
    for parent in ("domain", "field", "subfield"):
        parent_id = item.get(parent)
        if parent_id:
            params[parent] = titles[(parent + "s", parent_id)]
            params[f"{parent}_id"] = parent_id
    if level == "topics":
        params["keywords"] = "; ".join(k.replace(";", ",") for k in item.get("keywords", []))
    params.update(shares[(level, item["id"])])
    # Raw counts are kept for later calculations but not shown on the pages.
    params["works_count"] = item.get("works_count")
    params["cited_by_count"] = item.get("cited_by_count")
    # Some OpenAlex Wikipedia URLs contain spaces, which would break the external link.
    params["wikipedia"] = (item.get("wikipedia") or "").replace(" ", "_") or None
    if level != "topics":
        params["wikidata"] = item.get("wikidata")
    lines = [f"{{{{{TEMPLATE_FOR[level]}"] + [f"|{k}={clean(v)}" for k, v in params.items()] + ["}}"]
    return "\n".join([BEGIN, *lines, END])


def merge(existing: str | None, block: str) -> str:
    """Replace the bot block in an existing page, or create the page from it."""
    if existing is None:
        return block + "\n"
    if BLOCK_RE.search(existing):
        return BLOCK_RE.sub(lambda _m: block, existing, count=1)
    return block + "\n\n" + existing  # page existed without a block: keep its text below


def fixed_pages() -> dict[str, str]:
    """Templates and other fully bot-owned pages from the wiki/ directory."""
    pages = {}
    for path in sorted(WIKI_DIR.glob("*/*.wiki")):
        namespace = path.parent.name
        title = path.stem if namespace == "Main" else f"{namespace}:{path.stem}"
        pages[title] = path.read_text(encoding="utf-8").rstrip() + "\n"
    return pages


# --- main -----------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", metavar="DIR", type=Path, help="write wikitext files to DIR instead of uploading")
    parser.add_argument("--only", choices=["fixed", *LEVELS], action="append",
                        help="upload only these groups (repeatable); default: all")
    parser.add_argument("--subfield", metavar="ID", help="upload only the topics of this subfield (pilot)")
    parser.add_argument("--limit", type=int, help="upload at most this many entity pages")
    parser.add_argument("--sleep", type=float, default=0.0, help="seconds to wait between edits")
    args = parser.parse_args()

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    titles = page_titles(data)
    shares = share_tables(data)
    groups = args.only or ["fixed", *LEVELS]
    summary = f"Bot: OpenAlex hierarchy import (snapshot {data['retrieved']})"

    # Desired pages: title -> (kind, payload). Fixed pages are written whole.
    wanted: list[tuple[str, str, str]] = []  # (title, kind, text-or-block)
    if "fixed" in groups:
        wanted += [(t, "fixed", text) for t, text in fixed_pages().items()]
    entity_count = 0
    for level in LEVELS:
        if level not in groups:
            continue
        for item in data[level]:
            if level == "topics" and args.subfield and item.get("subfield") != args.subfield:
                continue
            if args.limit is not None and entity_count >= args.limit:
                break
            wanted.append((titles[(level, item["id"])], "block", bot_block(level, item, titles, shares)))
            entity_count += 1

    if args.subfield and not any(i.get("subfield") == args.subfield for i in data["topics"]):
        raise SystemExit(f"no topics with subfield id {args.subfield}")

    print(f"{len(wanted)} pages prepared ({entity_count} entity pages)", file=sys.stderr)

    if args.dry_run:
        args.dry_run.mkdir(parents=True, exist_ok=True)
        for title, kind, text in wanted:
            body = text if kind == "fixed" else merge(None, text)
            safe = title.replace("/", "_").replace(":", "__")
            (args.dry_run / f"{safe}.wiki").write_text(body, encoding="utf-8")
        print(f"wrote {len(wanted)} files to {args.dry_run}", file=sys.stderr)
        return

    load_env(ROOT / ".env")
    try:
        api_url = os.environ["WIKI_API_URL"]
        user, password = os.environ["WIKI_BOT_USER"], os.environ["WIKI_BOT_PASSWORD"]
    except KeyError as missing:
        raise SystemExit(f"missing {missing} in .env (see .env.example)")
    if not password:
        raise SystemExit("WIKI_BOT_PASSWORD is empty in .env")

    wiki = Wiki(api_url)
    try:
        wiki.login(user, password)
    except WikiError as error:
        raise SystemExit(f"{error}\nIs the tunnel open (scripts/upload_channel.sh)?")
    print(f"logged in to {api_url} as {user}", file=sys.stderr)

    current = wiki.read_pages([title for title, _, _ in wanted])
    created = updated = unchanged = 0
    failures: list[tuple[str, str]] = []
    started = time.time()
    for number, (title, kind, text) in enumerate(wanted, 1):
        existing = current.get(title)
        new_text = text if kind == "fixed" else merge(existing, text)
        if existing is not None and existing.rstrip() == new_text.rstrip():
            unchanged += 1
        else:
            try:
                wiki.edit(title, new_text, summary)
                created += existing is None
                updated += existing is not None
            except WikiError as error:
                failures.append((title, str(error)))
            if args.sleep:
                time.sleep(args.sleep)
        if number % 100 == 0 or number == len(wanted):
            elapsed = time.time() - started
            print(f"  {number}/{len(wanted)}  created {created}, updated {updated}, "
                  f"unchanged {unchanged}, failed {len(failures)}  ({elapsed:.0f}s)", file=sys.stderr)

    for title, error in failures[:20]:
        print(f"FAILED {title}: {error}", file=sys.stderr)
    if failures:
        raise SystemExit(f"{len(failures)} pages failed")

    # Pages with Cargo queries cache their rendered lists; refresh them.
    list_pages = [t for t, kind, _ in wanted if kind == "fixed" and ":" not in t] + [
        titles[(level, item["id"])] for level in ("domains", "fields", "subfields") for item in data[level]
    ]
    for start in range(0, len(list_pages), 20):
        wiki.post(action="purge", titles="|".join(list_pages[start:start + 20]), forcelinkupdate="1")
    print(f"refreshed {len(list_pages)} list pages", file=sys.stderr)
    print("done. If templates changed, run cargoRecreateData.php on the server (see docstring).",
          file=sys.stderr)


if __name__ == "__main__":
    main()
