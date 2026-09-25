#!/usr/bin/env python3
"""
owner_facts.py — what the owner told the node: add, list, revoke, restore.

WHY THIS EXISTS
---------------
The assertion half of `[fact — entered by user]` (4e, build log step 37). A fact
said in conversation is stored as the model's paraphrase of it, and the
paraphrase is what comes back (31g). A fact entered here is kept WORD FOR WORD
and always comes back ATTRIBUTED - "[Owner told you] ..." - so it can never be
laundered into something the node claims to know itself. What protects it is
in logic/facts.py; the rules for entering it are the ones correct_memory.py
already keeps:

  - by an operator, on the device, on the owner's instruction;
  - a dry run unless --apply, and nothing applied without --reason;
  - every change is a line in corrections.log (action add_fact, revoke_fact,
    restore_fact, set_facts_max) - never in provenance.log, which is the node's
    account of its own turns;
  - nothing is deleted: a revoked fact is kept and never retrieved, and
    --restore brings it back;
  - capped: a unit holds at most `facts_max` active facts (its config.json,
    default logic.facts.DEFAULT_CAP). Raising the cap is itself a recorded
    change (--cap).

The owner cannot do any of this from the console (Andreas, 23 Sep); the console
flow comes with guided correction (4d).

USAGE
-----
    sudo -u aetherseed python3 owner_facts.py --list [--all]
    sudo -u aetherseed python3 owner_facts.py --add "TEXT" --source "WHERE FROM" --reason "..." [--apply]
    sudo -u aetherseed python3 owner_facts.py --add-file FILE.jsonl --reason "..." [--apply]
    sudo -u aetherseed python3 owner_facts.py --revoke 12,13 --reason "..." [--apply]
    sudo -u aetherseed python3 owner_facts.py --restore 12 --reason "..." [--apply]
    sudo -u aetherseed python3 owner_facts.py --cap 2000 --reason "..." [--apply]

A file for --add-file has one JSON object per line with "text" and, optionally,
"source" or "ref" (tools/texts/genesis.web.jsonl is one). Every line is checked
before anything is written: one bad line and nothing is added. A fact that is
already there, word for word with the same source, is skipped, so running the
same file twice adds nothing the second time.

Pure stdlib, plus logic/facts.py from the application.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

for _p in (os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
           os.environ.get("AETHERSEED_APP", "/opt/aetherseed")):
    if os.path.isfile(os.path.join(_p, "logic", "facts.py")) and _p not in sys.path:
        sys.path.insert(0, _p)

from logic.facts import validate_fact, DEFAULT_CAP  # noqa: E402

DEFAULT_DB = os.path.expanduser("~/.aetherseed/aetherroot/memory.db")
DEFAULT_LOG = os.path.expanduser("~/.aetherseed/corrections.log")


def log_line(path, entry):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    entry = dict(entry)
    entry["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def config_path(db):
    return os.path.join(os.path.dirname(os.path.abspath(db)), "config.json")


def read_cap(db):
    try:
        with open(config_path(db), encoding="utf-8") as f:
            return int(json.load(f).get("facts_max", DEFAULT_CAP))
    except FileNotFoundError:
        return DEFAULT_CAP


def has_facts_table(db):
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        return con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' "
                           "AND name = 'facts'").fetchone() is not None
    finally:
        con.close()


def all_facts(db):
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(
            "SELECT id, created_at, text, source, entered_by, revoked_at FROM facts ORDER BY id")]
    finally:
        con.close()


def show(rows):
    for r in rows:
        state = "revoked %s" % r["revoked_at"][:19] if r["revoked_at"] else "active"
        src = " (%s)" % r["source"] if r["source"] else ""
        print("#%-5d %s  %s%s" % (r["id"], state, r["text"][:110], src))


def load_file(path):
    """[(text, source)] from a JSONL file, or raise ValueError naming the line."""
    out = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError("line %d: not JSON (%s)" % (n, e))
            text, source, err = validate_fact(row.get("text"),
                                              row.get("source") or row.get("ref") or "")
            if err:
                raise ValueError("line %d: %s" % (n, err))
            out.append((text, source))
    return out


def refuse(msg):
    print(msg, file=sys.stderr)
    return 2


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--log", default=DEFAULT_LOG)
    ap.add_argument("--list", action="store_true", help="print the active facts")
    ap.add_argument("--all", action="store_true", help="with --list: revoked ones too")
    ap.add_argument("--add", default=None, help="one fact, word for word")
    ap.add_argument("--source", default="", help="with --add: where it is from")
    ap.add_argument("--add-file", default=None, help="a JSONL file of facts")
    ap.add_argument("--revoke", default="", help="comma-separated fact ids")
    ap.add_argument("--restore", default="", help="comma-separated fact ids")
    ap.add_argument("--cap", type=int, default=None, help="set this unit's facts_max")
    ap.add_argument("--reason", default="", help="why, in one line - required to apply")
    ap.add_argument("--operator", default=os.environ.get("SUDO_USER") or os.environ.get("USER", "?"))
    ap.add_argument("--apply", action="store_true", help="actually write")
    a = ap.parse_args(argv)

    if not os.path.exists(a.db):
        return refuse("no memory store at %s" % a.db)
    if not has_facts_table(a.db):
        return refuse("this store has no facts table yet - it is created when the proxy "
                      "next opens it (step 37). Restart the proxy, then retry.")

    rows = all_facts(a.db)
    active = [r for r in rows if not r["revoked_at"]]
    cap = read_cap(a.db)
    actions = sum(bool(x) for x in (a.add is not None, a.add_file, a.revoke, a.restore,
                                    a.cap is not None))
    if a.list or not actions:
        shown = rows if a.all else active
        print("%d active facts (cap %d), %d revoked, in %s\n"
              % (len(active), cap, len(rows) - len(active), a.db))
        show(shown)
        return 0
    if actions > 1:
        return refuse("one change at a time: --add, --add-file, --revoke, --restore or --cap")

    def gate():
        if not a.apply:
            print("\nDRY RUN. Nothing written. Add --apply (and --reason) to do it.")
            return 0
        if not a.reason.strip():
            return refuse("\n--reason is required to apply: a change with no stated "
                          "reason is a tamper.")
        return None

    # ---- the cap -------------------------------------------------------------
    if a.cap is not None:
        if a.cap < len(active):
            return refuse("refused: %d facts are active; a cap of %d would be below them"
                          % (len(active), a.cap))
        print("facts_max %d -> %d  (%s)" % (cap, a.cap, config_path(a.db)))
        g = gate()
        if g is not None:
            return g
        path = config_path(a.db)
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
        config["facts_max"] = a.cap
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        os.replace(tmp, path)
        log_line(a.log, {"action": "set_facts_max", "before": cap, "after": a.cap,
                         "reason": a.reason, "operator": a.operator})
        print("applied: facts_max is now %d. recorded in %s" % (read_cap(a.db), a.log))
        return 0

    # ---- revoke / restore ----------------------------------------------------
    if a.revoke or a.restore:
        revoking = bool(a.revoke)
        ids = {int(x) for x in (a.revoke or a.restore).split(",") if x.strip()}
        by_id = {r["id"]: r for r in rows}
        missing = sorted(ids - set(by_id))
        if missing:
            return refuse("no such fact: %s" % missing)
        if not revoking:
            if len(active) + sum(1 for i in ids if by_id[i]["revoked_at"]) > cap:
                return refuse("refused: restoring would pass the cap of %d" % cap)
        print("facts to %s:" % ("revoke" if revoking else "restore"))
        show([by_id[i] for i in sorted(ids)])
        g = gate()
        if g is not None:
            return g
        now = datetime.now(timezone.utc).isoformat()
        con = sqlite3.connect(a.db)
        try:
            for i in sorted(ids):
                con.execute("UPDATE facts SET revoked_at = ? WHERE id = ?",
                            (now if revoking else None, i))
                log_line(a.log, {"action": "revoke_fact" if revoking else "restore_fact",
                                 "fact": i, "text": by_id[i]["text"][:200],
                                 "source": by_id[i]["source"], "reason": a.reason,
                                 "operator": a.operator})
            con.commit()
        finally:
            con.close()
        after = {r["id"]: r["revoked_at"] for r in all_facts(a.db)}
        print("\napplied:")
        for i in sorted(ids):
            ok = bool(after[i]) == revoking
            print("  #%d %s  %s" % (i, "revoked" if revoking else "active",
                                    "ok" if ok else "FAILED"))
        print("recorded in %s" % a.log)
        return 0

    # ---- add -----------------------------------------------------------------
    if a.add is not None:
        text, source, err = validate_fact(a.add, a.source)
        if err:
            return refuse("refused: %s" % err)
        new = [(text, source)]
    else:
        try:
            new = load_file(a.add_file)
        except (OSError, ValueError) as e:
            return refuse("refused, nothing added: %s" % e)

    present = {(r["text"], r["source"]) for r in active}
    fresh, seen = [], set()
    for f in new:
        if f in present or f in seen:
            continue
        seen.add(f)
        fresh.append(f)
    skipped = len(new) - len(fresh)
    if len(active) + len(fresh) > cap:
        return refuse("refused, nothing added: %d active + %d new would pass this unit's "
                      "cap of %d (raise it with --cap, which is recorded)"
                      % (len(active), len(fresh), cap))
    print("%d to add, %d already there word for word; %d active now, cap %d"
          % (len(fresh), skipped, len(active), cap))
    for text, source in fresh[:3]:
        print("  + %s%s" % (text[:100], " (%s)" % source if source else ""))
    if len(fresh) > 3:
        print("  + ... %d more" % (len(fresh) - 3))
    g = gate()
    if g is not None:
        return g

    now = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(a.db)
    added = []
    try:
        for text, source in fresh:
            cur = con.execute("INSERT INTO facts (created_at, text, source, entered_by) "
                              "VALUES (?, ?, ?, 'owner')", (now, text, source))
            added.append((cur.lastrowid, text, source))
            log_line(a.log, {"action": "add_fact", "fact": cur.lastrowid, "text": text[:200],
                             "source": source, "entered_by": "owner",
                             "reason": a.reason, "operator": a.operator})
        con.commit()
    finally:
        con.close()
    count = sum(1 for r in all_facts(a.db) if not r["revoked_at"])
    print("\napplied: %d added (ids %s-%s); %d active now. recorded in %s"
          % (len(added), added[0][0] if added else "-", added[-1][0] if added else "-",
             count, a.log))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
