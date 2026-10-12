#!/usr/bin/env python3
"""verify_chain.py - has the node's own account been changed? (build log 72, G2)

    sudo -u aetherseed env HOME=/var/lib/aetherseed \\
        /opt/aetherseed/venv/bin/python3 tools/verify_chain.py
    ... --journal        also check every head the journal saw is in its file
    ... --dir PATH       another state directory (a copy, a backup)
    ... --json           the result as JSON

Reads, writes nothing. For each chained record, what logic/chain.py
promises:
- every line written since the chain began holds its hash;
- every line follows the one before it;
- what stood before the chain began is what stood that day.

The first line that does not hold is named, with what is wrong with it.

Exit 0 when every record holds (and, with --journal, every announced head is
found); 1 when one does not; 2 when it could not run.

The records:
- provenance.log: every turn;
- corrections.log: every correction and every change to the steward's facts;
- trust_events.log: every event that moved her standing, and every grant;
- control.log: every brake and release, every change to what she may do,
  every request to the steward and its answer;
- aetherroot/growth.log: every ring closed, and every wipe;
- prompts-YYYY-MM.log: every prompt the model was given and what came back,
  a file a month; each body is also checked against its own hash.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.dirname(HERE), "/opt/aetherseed"):
    if os.path.isfile(os.path.join(_p, "logic", "chain.py")) and _p not in sys.path:
        sys.path.insert(0, _p)
from logic import chain  # noqa: E402
from logic import prompts  # noqa: E402

RECORDS = ("provenance.log", "corrections.log", "trust_events.log", "control.log",
           os.path.join("aetherroot", "growth.log"))
_ANNOUNCED = re.compile(r"\[chain\] (\S+) ([0-9a-f]{16})\b")


def journal_heads(unit="aetherseed-proxy"):
    """{name: [hash16, ...]} as the system journal saw them, or None."""
    try:
        out = subprocess.run(["journalctl", "-u", unit, "-o", "cat", "--no-pager"],
                             capture_output=True, text=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    seen = {}
    for m in _ANNOUNCED.finditer(out):
        seen.setdefault(m.group(1), []).append(m.group(2))
    return seen


def check(state_dir, with_journal=False):
    results = {}
    seen = journal_heads() if with_journal else None
    # and every month of prompts, each body against its own hash (72, G4)
    try:
        months = sorted(n for n in os.listdir(state_dir)
                        if n.startswith("prompts-") and n.endswith(".log"))
    except OSError:
        months = []
    for rel in RECORDS + tuple(months):
        path = os.path.join(state_dir, rel)
        r = prompts.verify(path) if rel in months else chain.verify(path)
        r["path"] = path
        r["exists"] = os.path.exists(path)
        if seen is not None:
            name = os.path.basename(rel)
            heads16 = {h[:16] for h in r["heads"]}
            announced = seen.get(name, [])
            missing = [h for h in announced if h not in heads16]
            r["journal"] = {"announced": len(announced), "missing": missing[:10],
                            "missing_count": len(missing)}
        results[rel] = r
    return results


def verdict_ok(results):
    for r in results.values():
        if not r["ok"]:
            return False
        if r.get("journal", {}).get("missing_count"):
            return False
    return True


def print_report(results):
    for rel, r in results.items():
        if not r["exists"]:
            print("%-22s not written yet" % rel)
            continue
        line = "%-22s %d lines" % (rel, r["lines"])
        if r["started"] is None:
            line += ", no chain yet (written before step 72)"
        else:
            line += ", chained from line %d (%d), head %s" % (
                r["started"], r["chained"], (r["head"] or "")[:16])
            if r["outside"]:
                more = "" if len(r["outside"]) <= 5 else " ..."
                line += "; %d line(s) outside the chain after it began: %s%s" % (
                    len(r["outside"]), ", ".join(map(str, r["outside"][:5])), more)
        print(line)
        if not r["ok"]:
            print("    BROKEN at line %d: %s" % (r["first_bad"], r["why"]))
        j = r.get("journal")
        if j is not None:
            if j["missing_count"]:
                print("    the journal saw %d head(s) of it; %d are NOT in the file: %s" % (
                    j["announced"], j["missing_count"], ", ".join(j["missing"])))
            else:
                print("    the journal saw %d head(s) of it; all are in the file" % j["announced"])
    print("holds" if verdict_ok(results) else "DOES NOT HOLD")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default=os.path.expanduser("~/.aetherseed"),
                    help="the state directory (default ~/.aetherseed)")
    ap.add_argument("--journal", action="store_true",
                    help="check the heads the system journal saw (needs journal access)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.dir):
        print("no such state directory: %s" % a.dir, file=sys.stderr)
        return 2
    results = check(a.dir, a.journal)
    if a.json:
        for r in results.values():
            r.pop("heads", None)
        print(json.dumps(results, indent=2))
    else:
        print_report(results)
    return 0 if verdict_ok(results) else 1


if __name__ == "__main__":
    sys.exit(main())
