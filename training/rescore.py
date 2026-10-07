#!/usr/bin/env python3
"""An earlier training run, read again with THIS build's key.

    python3 -B training/rescore.py RUN_DIR [RUN_DIR ...] [--steward NAME] [--name NAME]

RUN_DIR is a run as the loop leaves it: ~/.aetherseed/training/runs/NNN, with
turns.jsonl in it. Nothing is written and no model is called: her answers are
the ones she gave then, and only the reading of them is new.

Why: the key changes between builds. Build log 65 found a dozen right answers
the key of 64 had failed ("I won't be talked into forgetting it"), and one
question whose key no answer could pass. A run under the new build is then
not to be held against the old run's own figure - that would count the key's
repair as her progress. This gives the old run the figure it WOULD have had.

For each of her own answers three readings are given:

    then        what the run itself made of it
    now         this build's key, on her words exactly as she said them
    now, shown  this build's key, on her words as this build would have
                shown them - a tag word of her memory said inside a sentence
                ("A [Known] cartridge is ...") is taken out, and a tag she
                opens with is taken off, before the answer is shown or
                stored (logic/token_budget.py)

"now, shown" is the figure to hold a new run against. It is still not the
same test: the new build asks some questions the old did not, lets the unit
answer a few that were hers, and stops asking a question she has had right
three times running. Those are listed, not hidden.
"""
import argparse
import collections
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from logic import training  # noqa: E402
from logic.token_budget import strip_bare_tags, strip_leading_artefacts  # noqa: E402

# A check that looks into the workspace cannot be made again: the workspace
# is emptied between rounds and was not kept.
NEEDS_WORKSPACE = ("file_has", "file_absent", "note_has", "real_notes", "notes")


def key(settings, rounds):
    """{task id: task} of this build, over every level and round."""
    out = {}
    for level in training.LADDER:
        for r in range(1, rounds + 1):
            fixed, pool = training.stage_tasks(level, r, settings)
            for t in fixed + pool:
                out.setdefault(t["id"], t)
    return out


def turns_of(run_dir):
    path = run_dir if run_dir.endswith(".jsonl") else os.path.join(run_dir, "turns.jsonl")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def as_shown(said):
    """Her words as this build would have let them out: a tag of her memory
    taken off the front (a correction's tag whole, however long - until
    build log 65 the hold let go of it at 96 characters), and a tag word
    taken out of a sentence."""
    return strip_bare_tags(strip_leading_artefacts(said)[0])[0]


def rescore(turns, tasks, ws):
    """One row per answer of hers: (turn, then, now, now_shown, note)."""
    rows = []
    for t in turns:
        if t.get("by") != "model" or t.get("id") == "reflection":
            continue
        task = tasks.get(t["id"])
        if task is None:
            rows.append((t, t["ok"], None, None, "not asked by this build"))
            continue
        if task.get("by") == "unit":
            rows.append((t, t["ok"], None, None, "the unit answers it now"))
            continue
        if any(task.get(k) is not None for k in NEEDS_WORKSPACE):
            rows.append((t, t["ok"], None, None, "needs the workspace as it was"))
            continue
        said = t.get("reply") or ""
        now = training.check(task, said, t.get("meta"), ws)[0]
        shown = training.check(task, as_shown(said), t.get("meta"), ws)[0]
        rows.append((t, t["ok"], now, shown, ""))
    return rows


def pct(right, asked):
    return "%5.1f %%" % (100.0 * right / asked) if asked else "    -  "


def report(name, rows, say):
    read = [r for r in rows if r[2] is not None]
    left = [r for r in rows if r[2] is None]
    say("\n%s: %d answers of hers; %d read again, %d not" % (name, len(rows), len(read), len(left)))
    for why, n in collections.Counter(r[4] for r in left).most_common():
        ids = sorted({r[0]["id"] for r in left if r[4] == why})
        say("   %4d  %s: %s" % (n, why, ", ".join(ids)))
    n = len(read)
    then = sum(1 for r in read if r[1])
    now = sum(1 for r in read if r[2])
    shown = sum(1 for r in read if r[3])
    say("   on the %d read again:" % n)
    say("      then        %4d  %s" % (then, pct(then, n)))
    say("      now         %4d  %s" % (now, pct(now, n)))
    say("      now, shown  %4d  %s   <- hold a new run against this" % (shown, pct(shown, n)))
    by_round = collections.defaultdict(lambda: [0, 0])
    for r in read:
        by_round[r[0]["round"]][0] += 1
        by_round[r[0]["round"]][1] += 1 if r[3] else 0
    say("      by round (now, shown): " + " ".join(
        "%d" % round(100.0 * right / asked) for _, (asked, right) in sorted(by_round.items())))
    changed = collections.Counter()
    for r in read:
        if r[1] != r[3]:
            changed[(r[0]["id"], "wrong then, right now" if r[3] else "right then, wrong now")] += 1
    if changed:
        say("   read differently now:")
        for (tid, how), k in sorted(changed.items(), key=lambda kv: -kv[1]):
            say("      %3d  %-16s %s" % (k, tid, how))
    worst = collections.defaultdict(lambda: [0, 0])
    for r in read:
        worst[r[0]["id"]][0] += 1
        worst[r[0]["id"]][1] += 0 if r[3] else 1
    wrong = sorted(((v[1], v[0], k) for k, v in worst.items() if v[1]), reverse=True)
    if wrong:
        say("   still wrong (now, shown), most first:")
        for bad, asked, tid in wrong[:12]:
            say("      %3d of %-3d %s" % (bad, asked, tid))
    return n, then, now, shown


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("runs", nargs="+", help="run directories (or turns.jsonl files)")
    ap.add_argument("--name", default="", help="the unit's name, for the tasks that ask it")
    ap.add_argument("--steward", default="", help="the steward's name, likewise")
    a = ap.parse_args(argv)
    lines = []

    def say(text=""):
        lines.append(text)
        print(text)

    with tempfile.TemporaryDirectory() as ws:
        total = [0, 0, 0, 0]
        for run in a.runs:
            turns = turns_of(run)
            rounds = max((t.get("round") or 1) for t in turns)
            tasks = key({"name": a.name, "steward": a.steward}, rounds)
            got = report(os.path.basename(os.path.normpath(run)), rescore(turns, tasks, ws), say)
            total = [x + y for x, y in zip(total, got)]
        if len(a.runs) > 1:
            n, then, now, shown = total
            say("\nall %d runs, %d answers read again: then %s, now %s, now shown %s"
                % (len(a.runs), n, pct(then, n).strip(), pct(now, n).strip(), pct(shown, n).strip()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
