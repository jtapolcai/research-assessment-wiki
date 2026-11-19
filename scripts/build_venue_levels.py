#!/usr/bin/env python3
"""Combine the Finnish (JUFO) and Norwegian venue lists into one 0-3 level proposal.

Inputs (downloaded into data/raw/venues/, not committed):
  jufo/.../massa.json     https://jufo-rest.csc.fi/v1.1/massa.json.zip   (JUFO bulk file)
  norway_journals.csv     https://kanalregister.hkdir.no/publiseringskanaler/csvliste/tidsskrift
Output:
  data/raw/venues/venue_levels.csv   one row per journal/series or conference

Proposed level (our own 0-3 scale, to be reviewed by experts):
  3  JUFO level 3
  2  JUFO level 2, or Norwegian level 2
  1  JUFO level 1 or Norwegian level 1 (recognised scientific venue)
  0  listed by JUFO or Norway, but at level 0 in both
The 'flag' column marks disagreements worth an expert's look.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "venues"
OUT = RAW / "venue_levels.csv"


def issn(value: str | None) -> str | None:
    value = (value or "").strip().upper()
    return value if len(value) == 9 and value[4] == "-" else None


def level(value) -> int | None:
    return int(value) if str(value).strip() in {"0", "1", "2", "3"} else None


def propose(jufo: int | None, norway: int | None) -> tuple[int, str]:
    flags = []
    if jufo == 3:
        result = 3
        if norway is not None and norway < 2:
            flags.append("JUFO 3 but Norway below 2")
    elif jufo == 2 or norway == 2:
        result = 2
        if jufo is not None and jufo < 2 and norway == 2:
            flags.append("Norway 2 but JUFO below 2")
    elif jufo == 1 or norway == 1:
        result = 1
        if jufo == 0 and norway == 1:
            flags.append("Norway 1 but JUFO 0")
    else:
        result = 0
    return result, "; ".join(flags)


def main() -> None:
    jufo_file = next(RAW.glob("jufo/**/massa.json"))
    jufo = json.loads(jufo_file.read_text(encoding="utf-8"))
    with (RAW / "norway_journals.csv").open(encoding="utf-8-sig", newline="") as f:
        norway = list(csv.DictReader(f, delimiter=";"))

    # Index Norwegian journals by every ISSN they carry.
    norway_by_issn: dict[str, dict] = {}
    for row in norway:
        for key in ("Print ISSN", "Online ISSN"):
            if (code := issn(row[key])):
                norway_by_issn.setdefault(code, row)

    rows, used_norway = [], set()
    for rec in jufo:
        kind = (rec.get("Type") or "").lower()
        if kind == "kirjakustantaja":  # book publishers: handled separately later
            continue
        codes = [c for c in (issn(rec.get(k)) for k in ("ISSNL", "ISSN1", "ISSN2")) if c]
        nrow = next((norway_by_issn[c] for c in codes if c in norway_by_issn), None)
        if nrow:
            used_norway.add(nrow["journal_id"])
        jl, nl = level(rec.get("Level")), level(nrow["Level 2026"]) if nrow else None
        proposed, flag = propose(jl, nl)
        rows.append({
            "name": rec.get("Name"), "type": "conference" if kind == "konferenssi" else "journal/series",
            "abbreviation": rec.get("Abbreviation") or "", "issn_l": issn(rec.get("ISSNL")) or "",
            "issns": " ".join(dict.fromkeys(
                c for c in codes + ([issn(nrow["Print ISSN"]), issn(nrow["Online ISSN"])] if nrow else []) if c)),
            "jufo_id": rec.get("Jufo_ID"), "jufo_level": "" if jl is None else jl,
            "norway_id": nrow["journal_id"] if nrow else "", "norway_level": "" if nl is None else nl,
            "norway_discipline": nrow["NPI Academic Discipline"] if nrow else "",
            "proposed_level": proposed, "flag": flag,
        })
    for nrow in norway:  # Norwegian journals that JUFO does not list
        if nrow["journal_id"] in used_norway:
            continue
        nl = level(nrow["Level 2026"])
        if nl is None:
            continue
        proposed, flag = propose(None, nl)
        codes = [c for c in (issn(nrow["Print ISSN"]), issn(nrow["Online ISSN"])) if c]
        rows.append({
            "name": nrow["International Title"] or nrow["Original Title"], "type": "journal/series",
            "abbreviation": "", "issn_l": "", "issns": " ".join(codes), "jufo_id": "", "jufo_level": "",
            "norway_id": nrow["journal_id"], "norway_level": nl,
            "norway_discipline": nrow["NPI Academic Discipline"], "proposed_level": proposed, "flag": flag,
        })

    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    from collections import Counter
    print(f"wrote {OUT.relative_to(ROOT)}: {len(rows)} venues")
    print("proposed level:", sorted(Counter(r["proposed_level"] for r in rows).items(), reverse=True))
    print("conferences by level:", sorted(Counter(r["proposed_level"] for r in rows if r["type"] == "conference").items(), reverse=True))
    print("flags:", Counter(r["flag"] for r in rows if r["flag"]).most_common())


if __name__ == "__main__":
    main()
