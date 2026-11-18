#!/usr/bin/env python3
"""Build the wiki page with the DFG publication-type survey (2018).

Reads   data/dfg_publication_types_2018.csv  (Figure 3 of the DFG position paper)
        data/dfg_board_subfields.csv         (our mapping: OpenAlex subfield -> DFG review board)
Writes  wiki/Main/DFG publication type survey (2018).wiki

Upload afterwards with:  python3 scripts/upload_hierarchy.py --only fixed
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from upload_hierarchy import page_titles

ROOT = Path(__file__).resolve().parent.parent
TYPES_CSV = ROOT / "data" / "dfg_publication_types_2018.csv"
MAP_CSV = ROOT / "data" / "dfg_board_subfields.csv"
OUT = ROOT / "wiki" / "Main" / "DFG publication type survey (2018).wiki"

HEADERS = [
    "Monographs / books", "Contributions to edited volumes", "Journal articles", "Preprints",
    "Non-publisher publications", "Data publications", "Software / code", "Patents",
    "Audio-visual media", "Images / graphs", "Alternative types", "Other",
]

INTRO = """The [https://www.dfg.de DFG] (German Research Foundation) asked the Head Office staff of its
48 review boards in August 2018 how common the various publication types are in their subject
areas. The answers are shown in Figure 3 of the DFG position paper
''Academic Publishing as a Foundation and Area of Leverage for Research Assessment'' (2022).
We use them as a first, field-specific indication of which kinds of output matter in a field.

'''Scale:''' share of the publication type in the field: 5 = very high (&gt;90 %), 4 = high (75–90 %),
3 = medium (25–75 %), 2 = low (5–25 %), 1 = minimal (&lt;5 %), – = no response.
These are '''shares, not evaluation weights'''.

'''Mapping to OpenAlex:''' each OpenAlex subfield was assigned to the closest DFG review board
(last column). This assignment is our own approximation and open to correction; the subfield and
topic pages show the profile of the assigned board.

'''Note:''' in the source figure the rows for ''Computer Science'' and ''Construction Engineering and
Architecture'' are identical, which may be an error in the figure; the values are reproduced as
published.
"""

SOURCE = """== Source ==
Deutsche Forschungsgemeinschaft (2022). ''Academic Publishing as a Foundation and Area of Leverage
for Research Assessment. Challenges and Fields of Action.'' Position paper. Bonn: DFG.
Appendix (section 6), Figure 3, p. 74.
[https://www.dfg.de/resource/blob/175776/positionspapier-publikationswesen-en.pdf PDF]

[[Category:Sources]]"""


def main() -> None:
    data = json.loads((ROOT / "data" / "openalex_hierarchy.json").read_text(encoding="utf-8"))
    titles = page_titles(data)

    subfields_of: dict[str, list[str]] = defaultdict(list)
    with MAP_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            subfields_of[row["review_board"]].append(row["subfield_id"])

    lines = [INTRO, "== Survey results ==",
             '{| class="wikitable sortable" style="font-size:90%;"',
             "! DFG review board !! " + " !! ".join(HEADERS) + " !! OpenAlex subfields"]
    with TYPES_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ids = subfields_of.get(row["review_board"], [])
            links = ", ".join(f"[[{titles[('subfields', i)]}]]" for i in ids) or "–"
            params = {k: v for k, v in row.items()}
            params["subfield_ids"] = ",".join(ids)
            params["subfields"] = links
            lines.append("{{DFG publication types\n" +
                         "\n".join(f"|{k}={v}" for k, v in params.items()) + "\n}}")
    lines += ["|}", "", SOURCE]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
