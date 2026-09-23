#!/usr/bin/env python3
"""
correct_memory.py — an operator marks a stored answer as not to be used again.

WHY THIS EXISTS
---------------
The owner must not be able to tamper with the node's memory from the console.
That is a security barrier and a design decision (Andreas, 23 Sep), and it
holds. But a wrong answer, once stored `factual`, is retrieved as context and
becomes grounding for its own repetition - measured on this unit the same day
(build log 26e). Something has to be able to say "that one does not come back",
and it has to leave a trail.

So: an operator, on the device, with a written reason, and never silently.

WHAT IT DOES AND DOES NOT DO
----------------------------
It sets an episode's `mode` to `unverified`. Nothing is deleted, and nothing is
rewritten: the episode stays in the database exactly as it was said, and
`visible_modes()` makes `unverified` invisible to retrieval in both factual and
fiction requests. That is the existing mechanism for "this must never come back
as context", used here for a reason slightly wider than the one it was built
for - it was built for an answer carrying an unbacked source, and this also
covers an answer that was plainly wrong about the node itself. The widening is
recorded rather than hidden, and it is visible nowhere in the interface: the
console's badges are computed per turn, and the record summary reads the
provenance log, not episode modes.

Every change appends a line to `corrections.log` beside the provenance log,
with the episode, both modes, the reason and the operator. `--restore` reads
that file and puts a mode back, because an operator tool that only goes one way
is a tool that eventually makes an irreversible mistake.

**It does not write to `provenance.log`.** That file is the node's account of
its own turns, and `summarise_record()` counts its lines as turns - an operator
action in there would make the node miscount its own conversation. A separate
file keeps both honest.

USAGE
-----
    sudo -u aetherseed python3 correct_memory.py --list
    sudo -u aetherseed python3 correct_memory.py --ids 7,9 --reason "..."
    sudo -u aetherseed python3 correct_memory.py --ids 7,9 --reason "..." --apply
    sudo -u aetherseed python3 correct_memory.py --restore --ids 7 --apply

Dry run unless --apply is given. Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time

DEFAULT_DB = os.path.expanduser("~/.aetherseed/aetherroot/memory.db")
DEFAULT_LOG = os.path.expanduser("~/.aetherseed/corrections.log")
UNVERIFIED = "unverified"


def episodes(db):
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(
            "SELECT id, timestamp, mode, user_msg, ai_msg FROM episodes ORDER BY id"
        ).fetchall()
    finally:
        con.close()


def show(rows, ids=None):
    for r in rows:
        if ids and r["id"] not in ids:
            continue
        print("#%-4d %s  mode=%-10s" % (r["id"], r["timestamp"][:19], r["mode"]))
        print("      U: %s" % (r["user_msg"] or "").replace("\n", " ")[:100])
        print("      A: %s" % (r["ai_msg"] or "").replace("\n", " ")[:150])


def log_line(path, entry):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entry = dict(entry)
    entry["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def previous_modes(path, ids):
    """The mode each episode had before the most recent correction to it."""
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("episode") in ids and e.get("action") == "set_mode":
                    out[e["episode"]] = e.get("mode_before")
    except FileNotFoundError:
        pass
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--log", default=DEFAULT_LOG)
    ap.add_argument("--list", action="store_true", help="print every episode")
    ap.add_argument("--ids", default="", help="comma-separated episode ids")
    ap.add_argument("--mode", default=UNVERIFIED, help="mode to set (default unverified)")
    ap.add_argument("--reason", default="", help="why, in one line - required to apply")
    ap.add_argument("--operator", default=os.environ.get("SUDO_USER") or os.environ.get("USER", "?"))
    ap.add_argument("--restore", action="store_true",
                    help="put the modes back, from the corrections log")
    ap.add_argument("--apply", action="store_true", help="actually write")
    a = ap.parse_args(argv)

    rows = episodes(a.db)
    if a.list or not a.ids:
        print("%d episodes in %s\n" % (len(rows), a.db))
        show(rows)
        if not a.ids:
            return 0
        print()

    ids = {int(x) for x in a.ids.split(",") if x.strip()}
    known = {r["id"]: r for r in rows}
    missing = sorted(ids - set(known))
    if missing:
        print("no such episode: %s" % missing, file=sys.stderr)
        return 2

    if a.restore:
        targets = previous_modes(a.log, ids)
        unknown = sorted(ids - set(targets))
        if unknown:
            print("no recorded previous mode for: %s" % unknown, file=sys.stderr)
            return 2
    else:
        targets = {i: a.mode for i in ids}

    print("episodes to change:")
    show(rows, ids)
    print()
    for i in sorted(ids):
        print("  #%d  %s -> %s" % (i, known[i]["mode"], targets[i]))

    if not a.apply:
        print("\nDRY RUN. Nothing written. Add --apply (and --reason) to do it.")
        return 0
    if not a.reason:
        print("\n--reason is required to apply: a correction with no stated "
              "reason is a tamper.", file=sys.stderr)
        return 2

    con = sqlite3.connect(a.db)
    try:
        for i in sorted(ids):
            before = known[i]["mode"]
            con.execute("UPDATE episodes SET mode = ? WHERE id = ?", (targets[i], i))
            log_line(a.log, {
                "action": "set_mode", "episode": i,
                "mode_before": before, "mode_after": targets[i],
                "reason": a.reason, "operator": a.operator,
                "restore": bool(a.restore),
                "user_msg": (known[i]["user_msg"] or "")[:200],
                "ai_msg": (known[i]["ai_msg"] or "")[:400],
            })
        con.commit()
    finally:
        con.close()

    after = {r["id"]: r["mode"] for r in episodes(a.db)}
    print("\napplied:")
    for i in sorted(ids):
        ok = "ok" if after[i] == targets[i] else "FAILED (now %s)" % after[i]
        print("  #%d -> %s  %s" % (i, targets[i], ok))
    print("recorded in %s" % a.log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
