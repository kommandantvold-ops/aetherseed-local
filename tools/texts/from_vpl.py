#!/usr/bin/env python3
"""Make the two reading texts from the World English Bible's verse-per-line file.

    python3 tools/texts/from_vpl.py eng-web_vpl.txt tools/texts/

eng-web_vpl.txt is in eng-web_vpl.zip from eBible.org (see README.md here).
One JSON object per verse, in order, the text exactly as the source line has it
after the book code and reference:

    {"ref": "Genesis 1:1", "chapter": 1, "verse": 1, "text": "In the beginning, ..."}

Run it again and compare SHA256SUMS: the output is deterministic.
"""

import json
import os
import re
import sys

BOOKS = {"GEN": ("Genesis", "genesis.web.jsonl"),
         "SOL": ("Song of Songs", "song-of-songs.web.jsonl")}
_LINE = re.compile(r"^(\w+) (\d+):(\d+) (.*)$")


def convert(vpl_path, out_dir):
    out = {code: [] for code in BOOKS}
    with open(vpl_path, encoding="utf-8") as f:
        for line in f:
            m = _LINE.match(line.rstrip("\r\n"))
            if not m or m.group(1) not in BOOKS:
                continue
            code, ch, vs, text = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
            name = BOOKS[code][0]
            out[code].append({"ref": f"{name} {ch}:{vs}", "chapter": ch, "verse": vs,
                              "text": text.strip()})
    for code, (name, filename) in BOOKS.items():
        with open(os.path.join(out_dir, filename), "w", encoding="utf-8") as f:
            for row in out[code]:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{filename}: {len(out[code])} verses of {name}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    convert(sys.argv[1], sys.argv[2])
