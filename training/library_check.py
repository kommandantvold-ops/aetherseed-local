#!/usr/bin/env python3
"""Does the library show the right passage - and nothing when it has nothing?

    python3 training/library_check.py [--dir /var/lib/aetherseed/library] [-v]

No model is involved and nothing is written: it asks logic/library.py the
questions in training/library-probes.json and compares. Two numbers matter:
how many of the questions a collection should answer got a passage from it
(and from the right document), and how many of the questions it should leave
alone it left alone. The second is the one that must be whole: a passage shown
for a question it does not answer takes the question away from her.
Build logs 57-59.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from logic import library as L  # noqa: E402


def check(lib, probes, verbose=False, out=print):
    keys = ("right", "wrong_passage", "wrong_doc", "missed", "left_alone", "intruded",
            "missed_line", "alone_line", "unanswered")
    kinds = [k for k in ("unasked", "asked", "held_out", "unasked2", "held_out2", "held_out3", "everyday") if probes.get(k)]
    res = {k: dict.fromkeys(keys, 0) for k in kinds}
    for kind in kinds:
        for p in probes[kind]:
            if kind == "asked":
                q = L.lookup_query(p["ask"])
                hit = lib.look_up(q) if q else None
            else:
                hit = lib.find(p["ask"])
            got = hit["collection_id"] if hit else None
            if p.get("any"):
                key = "right" if hit else "left_alone"
            elif p["expect"] is None:
                key = "left_alone" if hit is None else "intruded"
            elif got not in (p["expect"] if isinstance(p["expect"], list) else [p["expect"]]):
                key = "missed"
            elif (p.get("title") or "").lower() not in hit["title"].lower():
                key = "wrong_doc"
            elif p.get("text") and not any(t in hit["text"] for t in p["text"]):
                key = "wrong_passage"
            else:
                key = "right"
            res[kind][key] += 1
            # She answers this one herself. Does it get the line "not from the
            # library - say 'look it up'" (build log 59)? Wanted where the
            # library holds it, not elsewhere.
            if hit is None and kind != "asked":
                wanted = p["expect"] is not None and not p.get("any")
                res[kind]["unanswered"] += wanted
                if lib.says_it_all(p["ask"]):
                    res[kind]["missed_line" if wanted else "alone_line"] += 1
                    if verbose:
                        out("%-8s %-10s %s" % (kind, "line", p["ask"]))
            if verbose or key in ("intruded", "wrong_doc", "wrong_passage", "missed"):
                out("%-8s %-10s %s" % (kind, key.upper() if key != "right" and key != "left_alone" else key,
                                       p["ask"]))
                if hit:
                    out("           -> %s | %s | %s %s | %s"
                        % (hit["collection_id"], hit["title"][:50], hit["heading"][:30],
                           hit["place"], hit["text"][:90].replace("\n", " ")))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default=L.LIBRARY_DIR)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    lib = L.Library(a.dir)
    if not lib:
        print("no collection in %s" % a.dir)
        return 1
    with open(os.path.join(HERE, "library-probes.json"), encoding="utf-8") as f:
        probes = json.load(f)
    print("collections: %s" % "; ".join(lib.holds()))
    res = check(lib, probes, a.verbose)
    for kind in res:
        r = res[kind]
        should = r["right"] + r["wrong_passage"] + r["wrong_doc"] + r["missed"]
        alone = r["left_alone"] + r["intruded"]
        print("%-9s should answer: %d of %d right (%d right document but another passage, "
              "%d wrong document, %d missed); should leave alone: %d of %d left alone "
              "(%d intruded)"
              % (kind, r["right"], should, r["wrong_passage"], r["wrong_doc"], r["missed"],
                 r["left_alone"], alone, r["intruded"]))
        if kind != "asked":
            print("%-9s   the line under her own answer: %d of the %d she should have answered "
                  "from it and did not; %d of the %d left alone"
                  % ("", r["missed_line"], r["unanswered"], r["alone_line"], r["left_alone"]))
    return 0 if not any(r["intruded"] for r in res.values()) else 2


if __name__ == "__main__":
    sys.exit(main())
