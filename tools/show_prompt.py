#!/usr/bin/env python3
"""show_prompt.py - what was the model given, word for word? (build log 72, G4)

    sudo -u aetherseed env HOME=/var/lib/aetherseed \\
        /opt/aetherseed/venv/bin/python3 tools/show_prompt.py --sha <prompt_sha256>
    ... --last 3          the last three prompts
    ... --dir PATH        another state directory (a copy, a backup)

A turn's line in provenance.log carries "prompt_sha256"; its prompt, as sent,
and what came back are in prompts-YYYY-MM.log under that hash. This prints
them, and says whether the body is still the bytes its hash names.

Reads, writes nothing. Exit 0 when found and holding, 1 when not found or not
holding, 2 when it could not run.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.dirname(HERE), "/opt/aetherseed"):
    if os.path.isfile(os.path.join(_p, "logic", "prompts.py")) and _p not in sys.path:
        sys.path.insert(0, _p)
from logic import prompts  # noqa: E402


def months(state_dir):
    try:
        return sorted(os.path.join(state_dir, n) for n in os.listdir(state_dir)
                      if n.startswith("prompts-") and n.endswith(".log"))
    except OSError:
        return []


def show(rec, out=None):
    out = out or sys.stdout                # the stdout of the moment, not of the import
    holds = prompts.body_holds(rec)
    print("=" * 72, file=out)
    print("prompt %s  %s  %s" % (rec.get("sha256", "")[:16], rec.get("at", ""),
                                 rec.get("outcome", "")), file=out)
    print("body holds its hash: %s" % ("yes" if holds else "NO"), file=out)
    try:
        body = json.loads(rec["body"])
    except (KeyError, ValueError):
        print(rec.get("body", ""), file=out)
        return holds
    print("model %s, options %s" % (body.get("model"), json.dumps(body.get("options"))), file=out)
    for m in body.get("messages") or []:
        print("--- %s ---" % m.get("role"), file=out)
        print(m.get("content", ""), file=out)
    print("--- reply ---", file=out)
    print(rec.get("reply", ""), file=out)
    return holds


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sha", help="the prompt_sha256 of a turn (or its first characters)")
    ap.add_argument("--last", type=int, default=0, help="the last N prompts")
    ap.add_argument("--dir", default=os.path.expanduser("~/.aetherseed"))
    a = ap.parse_args(argv)
    if not a.sha and not a.last:
        ap.error("--sha or --last")
    files = months(a.dir)
    if not files:
        print("no prompts kept in %s" % a.dir)
        return 1
    found = []
    for path in files:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if a.sha and a.sha not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if a.sha and not str(rec.get("sha256", "")).startswith(a.sha):
                    continue
                found.append(rec)
                if a.last:
                    found = found[-a.last:]
    if not found:
        print("not found: %s" % (a.sha or "no prompts"))
        return 1
    if a.sha and len(found) > 1:
        # The hash names the prompt, not the call: the same words sent again
        # (a question asked twice over the same memory) have the same hash.
        print("this prompt was sent %d times; the last %d are shown, oldest first"
              % (len(found), min(len(found), 5)))
        found = found[-5:]
    ok = True
    for rec in found:
        ok = show(rec) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:                 # pragma: no cover
        print("could not run: %r" % (e,))
        sys.exit(2)
