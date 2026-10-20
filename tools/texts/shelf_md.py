#!/usr/bin/env python3
"""A book of verses (one JSON object per line: ref, chapter, verse, text) as a
document for the steward's shelf, in the shape the shelf already holds
Ecclesiastes and Luke in.

    python3 tools/texts/shelf_md.py tools/texts/genesis.web.jsonl Genesis > Genesis.md

the 1,533 Genesis verses kept as facts he told her:
"move to shelf". As facts, any verse that shared one word with a question came
back as something her steward told her - "And what day is that happening?"
brought Genesis 50:20 ("... as is happening today"), on copies of a unit the
same day. On the shelf a verse answers when it is looked up, word for word,
with its place, and not otherwise.

Every verse is checked against its own reference; the text is not changed.
"""
import collections
import json
import sys


def shelf_md(rows, book: str) -> str:
    by = collections.OrderedDict()
    for r in rows:
        if r["ref"] != "%s %d:%d" % (book, r["chapter"], r["verse"]):
            raise ValueError("verse %r is not %s %d:%d" % (r["ref"], book, r["chapter"], r["verse"]))
        by.setdefault(r["chapter"], []).append(r)
    out = ["# %s" % book, "", "World English Bible (public domain).", "", ""]
    for chapter, verses in by.items():
        out += ["## %s %d" % (book, chapter), ""]
        out += ["%d:%d %s" % (v["chapter"], v["verse"], v["text"]) for v in verses]
        out += ["", ""]
    return "\n".join(out).rstrip() + "\n"


def main(argv):
    if len(argv) != 3:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    sys.stdout.write(shelf_md(rows, argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
