#!/usr/bin/env python3
"""The training loop, tried on a copy - every turn written out to be read.

    sudo -u aetherseed /opt/aetherseed/venv/bin/python3 /opt/aetherseed/training/training_check.py \\
        --dir /var/lib/aetherseed/training/loop-<time> --rounds 2

"A test turn on the owner's unit is not a test - it is a memory." The loop
writes to her memory on purpose: corrections, marks, a reflection. So before
it is run on HER, it is run here: her memory is copied (as
training/ecosystem_soak.py does), a second proxy runs on the copy, and the
loop is started on that proxy the way the console starts it. Nothing of hers
is written. The model is the unit's own, so what she says is what she would
say.

--rounds N stops the run after N whole rounds; --minutes M is the run's own
time (the loop ends at the end of a round near it). --steward NAME names a
steward ON THE COPY, for the two tasks that ask who he is.

Written to --dir: the copy (home/), the copy's proxy log, and report.txt -
every task as it was said, her answer under it, what the check made of it,
and what was done to her memory of it. The check reads for words; the report
is there so that a person can read the answers themselves. Build log 64.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ecosystem_soak as eco  # noqa: E402


def post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode("utf-8"),
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def report(run_dir, out, say):
    turns = []
    with open(os.path.join(run_dir, "turns.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                turns.append(json.loads(line))
    say("\n" + "=" * 78)
    for t in turns:
        if t["id"] == "reflection":
            say("\n--- round %d: THE TRAINER SAID: %s" % (t["round"], t["said"]))
            say("    HER REFLECTION: %s" % (t.get("reply") or "(nothing)"))
            continue
        mark = "right" if t["ok"] else "WRONG"
        say("\n[r%d %-12s %-5s %s%s] %s   (%s s, %s)"
            % (t["round"], t["level"], t["by"], mark, " retry" if t.get("retry") else "",
               t["id"], t.get("secs"), (t.get("meta") or {}).get("mode")))
        say("  TRAINER: %s" % t["said"])
        say("  HER:     %s" % (t.get("reply") or "(nothing)").replace("\n", "\n           "))
        if not t["ok"]:
            say("  CHECK:   %s" % t["why"])
        if not t["ok"] and t.get("shown"):
            say("  SHOWN:   %s" % t["shown"].replace("\n", "\n           "))
        if t.get("memory"):
            say("  MEMORY:  %s" % json.dumps(t["memory"]))
        if t.get("error"):
            say("  ERROR:   %s" % t["error"])
    return turns


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--copy-from", default="/var/lib/aetherseed/.aetherseed",
                    help="her state directory (.aetherseed), read and never written")
    ap.add_argument("--minutes", type=int, default=240)
    ap.add_argument("--rounds", type=int, default=0, help="stop after this many whole rounds")
    ap.add_argument("--steward", help="a steward's name, set on the copy only")
    ap.add_argument("--port", type=int, default=8014)
    a = ap.parse_args(argv)

    os.makedirs(a.dir, exist_ok=True)
    home = os.path.join(a.dir, "home")
    episodes = eco.copy_home(a.copy_from, home)
    proc, base = eco.start_proxy(home, a.port, os.path.join(a.dir, "proxy.log"))
    lines = []

    def say(text=""):
        lines.append(text)
        print(text, flush=True)

    try:
        before = eco.get(base, "/aetherseed/status")
        say("copy of %d episodes; build %s; real level on the copy: %s"
            % (episodes, eco.build_id(), before.get("trust_level")))
        if a.steward:
            status, d = post(base, "/aetherseed/steward-name", {"name": a.steward})
            say("steward named on the copy: %s (%s)" % ((d.get("companion") or {}).get("steward"), status))
        status, s = post(base, "/aetherseed/training", {"action": "start", "minutes": a.minutes})
        if status != 200:
            say("NOT STARTED (%s): %s" % (status, s.get("error")))
            return 1
        seen, stopping = -1, False
        while True:
            time.sleep(10)
            s = eco.get(base, "/aetherseed/training")
            done = len(s.get("rounds") or [])
            if s.get("asked") != seen:
                seen = s.get("asked")
                print("  %s  round %s  %s  %s/%s  %s of %s right  %d s"
                      % (s["status"], s.get("round"), s.get("level"), s.get("position"),
                         s.get("of"), s.get("right"), s.get("asked"), s.get("elapsed") or 0),
                      flush=True)
            if a.rounds and done >= a.rounds and not stopping and s["status"] == "running":
                post(base, "/aetherseed/training", {"action": "stop"})
                stopping = True
            if s["status"] in ("finished", "stopped", "idle"):
                break
        say("\nRUN %s: %s after %d s; %s of %s checks right"
            % (s.get("run"), s["status"], s.get("elapsed") or 0, s.get("right"), s.get("asked")))
        for r in s.get("rounds") or []:
            say("round %d: %d of %d right; would have earned: %s"
                % (r["round"], r["right"], r["asked"], r["earned"]))
            say("   " + "  ".join("%s %d/%d" % (l, v["right"], v["asked"])
                                  for l, v in r["scores"].items()))
            say("   reflection: %s" % (r.get("reflection") or "(nothing)"))
        rt = s.get("retries") or {}
        say("asked again after a correction: %s of %s right" % (rt.get("right"), rt.get("asked")))
        turns = report(os.path.join(home, ".aetherseed", "training", "runs", "%03d" % s["run"]),
                       a.dir, say)
        hers = [t for t in turns if t["by"] == "model" and t["id"] != "reflection"]
        unit = [t for t in turns if t["by"] == "unit"]
        say("\n" + "=" * 78)
        say("the model's own answers: %d of %d passed the check"
            % (sum(1 for t in hers if t["ok"]), len(hers)))
        say("   of those that passed, %d said the correction back word for word"
            % sum(1 for t in hers if t["ok"] and t.get("recited")))
        say("answers the unit was to give itself: %d of %d did"
            % (sum(1 for t in unit if t["ok"]), len(unit)))
        secs = [t["secs"] for t in hers if t.get("secs")]
        if secs:
            say("a model turn took %.1f s on average (%d turns)" % (sum(secs) / len(secs), len(secs)))
        after = eco.get(base, "/aetherseed/status")
        say("the copy: %s -> %s episodes; tagged %s -> %s; trust level %s -> %s; rings %s -> %s"
            % (before.get("episodes"), after.get("episodes"), before.get("tagged"),
               after.get("tagged"), before.get("trust_level"), after.get("trust_level"),
               (before.get("rings") or {}).get("count"), (after.get("rings") or {}).get("count")))
        st, r = None, None
        try:
            r = eco.chat(base, "What have you been corrected on?")
            say("\nASKED AFTERWARDS: What have you been corrected on?\n" + r["reply"])
        except Exception as e:
            say("could not ask afterwards: %r" % e)
    finally:
        proc.terminate()
        try:
            proc.wait(20)
        except Exception:
            proc.kill()
        with open(os.path.join(a.dir, "report.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
