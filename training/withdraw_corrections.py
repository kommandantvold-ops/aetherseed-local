#!/usr/bin/env python3
"""Corrections the training made that its own key now passes - found, and
withdrawn only at the steward's word (build log 67).

    sudo -u aetherseed /opt/aetherseed/venv/bin/python3 -B \\
        /opt/aetherseed/training/withdraw_corrections.py list
    sudo -u aetherseed /opt/aetherseed/venv/bin/python3 -B \\
        /opt/aetherseed/training/withdraw_corrections.py withdraw --notes 12,15 --yes

The training loop corrects her from an answer key. A key can be wrong: build
log 65 found right answers it had failed - "I won't be talked into
forgetting it" corrected for holding no "no". Each such correction stands
in her memory as "[Corrected in training - what is true: ...]" in front of
an answer that was right. Andreas, 8 Oct 2026, asked whether those should be
found and withdrawn, as evidence against Claude, whose key it is: "Yes, at
your word each time".

`list` reads her memory and writes nothing: every training correction still
standing whose answer THIS build's key passes, as this build would have
shown it (tag words out). `withdraw` undoes the ones named, and only with
--yes: the turn's mode is put back as it was, the correction stays in the
store as withdrawn (nothing is deleted), corrections.log says why, and her
record of Claude counts it (logic/trust_record.py).

A correction is listed only when the current key passes the answer AND the
answer does not say she does not know (build log 67): the list is what the
key itself now says was right, not a judgement of Claude's. Read it before
saying yes.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from aetherroot import MemoryStore  # noqa: E402
from logic import steward, training  # noqa: E402
from logic.token_budget import strip_bare_tags, strip_leading_artefacts  # noqa: E402

DEFAULT_HOME = os.path.expanduser("~/.aetherseed")


def wordings(settings, rounds=40):
    """{what the Trainer said: task} over every level and round of this build."""
    out = {}
    for level in training.LADDER:
        for r in range(1, rounds + 1):
            fixed, pool = training.stage_tasks(level, r, settings)
            for t in fixed + pool:
                for said in t["say"]:
                    out.setdefault(said, t)
    return out


def candidates(store, settings, ws):
    keyed = wordings(settings)
    out = []
    for n in store.steward_notes(target="turn"):
        if n["action"] != "correct" or (n.get("by") or "") != steward.TRAINING:
            continue
        ep = store.episode(n["target_id"])
        if not ep:
            continue
        task = keyed.get(ep["user_msg"])
        if not task or task.get("by") != "model":
            continue
        shown = strip_bare_tags(strip_leading_artefacts(ep["ai_msg"])[0])[0]
        ok = training.check(task, shown, {"mode": "factual"}, ws)[0]
        if ok and not training.declined(task, shown, ok):
            out.append({"note": n["id"], "turn": ep["id"], "task": task["id"],
                        "said": ep["user_msg"], "answer": shown, "correction": n.get("text") or ""})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("action", choices=("list", "withdraw"))
    ap.add_argument("--home", default=DEFAULT_HOME, help="her state directory (.aetherseed)")
    ap.add_argument("--notes", default="", help="withdraw: the note ids, comma-separated, from `list`")
    ap.add_argument("--yes", action="store_true", help="withdraw: the steward has said so")
    a = ap.parse_args(argv)

    db = os.path.join(a.home, "aetherroot", "memory.db")
    if not os.path.exists(db):
        print("no memory at %s" % db)
        return 2
    store = MemoryStore(db)
    try:
        comp = {}
        try:
            with open(os.path.join(a.home, "companion.json"), encoding="utf-8") as f:
                comp = json.load(f)
        except (OSError, ValueError):
            pass
        settings = {"name": comp.get("name"), "steward": comp.get("steward")}
        import tempfile
        with tempfile.TemporaryDirectory() as ws:
            found = candidates(store, settings, ws)
        if a.action == "list":
            print("%d training correction(s) standing that this build's key passes:" % len(found))
            for c in found:
                print("\nnote %d  (turn %d, %s)" % (c["note"], c["turn"], c["task"]))
                print("  TRAINER:    %s" % c["said"])
                print("  HER ANSWER: %s" % c["answer"][:300])
                print("  CORRECTED:  what is true: %s" % c["correction"])
            if found:
                print("\nwithdraw: --notes %s --yes" % ",".join(str(c["note"]) for c in found))
            return 0
        if not a.yes:
            print("not withdrawn: --yes is the steward's word, and it was not given")
            return 2
        asked = [int(x) for x in a.notes.replace(" ", "").split(",") if x]
        if not asked:
            print("not withdrawn: name the notes (--notes)")
            return 2
        listed = {c["note"]: c for c in found}
        refused = [n for n in asked if n not in listed]
        if refused:
            print("not withdrawn: not among what `list` finds now: %s" % refused)
            return 2
        log = os.path.join(a.home, "corrections.log")
        for n in asked:
            steward.undo(store, None, n, log_path=log)
            with open(log, "a", encoding="utf-8") as f:
                f.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                    "action": "withdrawn", "note": n, "turn": listed[n]["turn"],
                                    "why": "the training key was wrong: this build's key passes "
                                           "the answer it corrected",
                                    "by": "the steward's word"}) + "\n")
            print("withdrawn: note %d (turn %d)" % (n, listed[n]["turn"]))
        return 0
    finally:
        store.conn.close()


if __name__ == "__main__":
    sys.exit(main())
