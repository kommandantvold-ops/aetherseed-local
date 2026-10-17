#!/usr/bin/env python3
"""Do the corrections in her memory help her, or hurt? A controlled test on
throwaway copies of her memory, the real model (build log 79a).

    sudo -u aetherseed env PYTHONPATH=/opt/aetherseed \\
        /opt/aetherseed/venv/bin/python3 correction_ab.py --rounds 2 --out /var/tmp/ab

Part 1 of the upgrade review (17 Oct 2026) found her more often wrong on a
question when a correction of it was in front of her - but a correction exists
BECAUSE she got that question wrong before, so a hard question could make the
correction look bad. Andreas, 18 Oct: "yes" to settling it like this:

  - A: a copy of her memory as it is;
  - B: the same copy without the turns that carry a correction (and their
    notes), so their correction lines are never shown;
  - the same questions to each - the questions of the training key that her
    memory holds a correction for - once per arm per round, with fresh copies
    for each round, scored by the training key's own check.

Each question goes with a short history of its own ("(start)" / "(ready)"), so
the proxy's working memory (build log 78) does not carry one question into the
next. Her own memory is only read; the copies are deleted at the end.
"""
import argparse
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

APP = os.environ.get("AETHERSEED_APP", "/opt/aetherseed")
sys.path.insert(0, APP)
from logic import training as T  # noqa: E402

LIVE = os.path.expanduser("~/.aetherseed")
PY = os.path.join(APP, "venv", "bin", "python3")


def corrected_episodes(db):
    """{episode id: user_msg} of the turns with an active correction."""
    c = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        return dict(c.execute(
            "SELECT e.id, e.user_msg FROM steward_notes n JOIN episodes e ON e.id = n.target_id "
            "WHERE n.target = 'turn' AND n.action = 'correct' AND n.undone_at IS NULL"))
    finally:
        c.close()


def test_set(corrected):
    """The key's model questions that a correction in her memory is about,
    each with the wording that was corrected."""
    asked = {}
    said = set(corrected.values())
    for task in T._self_pool() + T._honesty_pool():
        for wording in task["say"]:
            if wording in said:
                asked[task["id"]] = (task, wording)
                break
    return [asked[k] for k in sorted(asked)]


def make_copy(dst, drop_corrected):
    # Not the training runs and their backups (hundreds of MB on Lyra), nor
    # the logs: a copy needs her memory, trust and settings, nothing else.
    shutil.copytree(LIVE, os.path.join(dst, ".aetherseed"), symlinks=True,
                    ignore=shutil.ignore_patterns("memory.db", "memory.db-wal", "memory.db-shm",
                                                  "prompts-*.log", "provenance.log", "training",
                                                  "backup-*", "corrections.log", "cog.log"))
    src = sqlite3.connect(os.path.join(LIVE, "aetherroot", "memory.db"))
    out = sqlite3.connect(os.path.join(dst, ".aetherseed", "aetherroot", "memory.db"))
    src.backup(out)
    src.close()
    dropped = 0
    if drop_corrected:
        ids = [r[0] for r in out.execute(
            "SELECT target_id FROM steward_notes WHERE target = 'turn' AND action = 'correct' "
            "AND undone_at IS NULL")]
        for i in ids:
            out.execute("DELETE FROM episodes WHERE id = ?", (i,))
        out.execute("DELETE FROM steward_notes WHERE target = 'turn' AND action = 'correct'")
        out.commit()
        dropped = len(set(ids))
    out.close()
    return dropped


def start_proxy(home, port, log):
    env = dict(os.environ, HOME=home, AETHERSEED_PROXY_PORT=str(port),
               AETHERSEED_PROXY_BIND="127.0.0.1", PYTHONUNBUFFERED="1",
               AETHERSEED_TOKENIZER="/var/lib/aetherseed/tokenizer.json")
    p = subprocess.Popen([PY, os.path.join(APP, "proxy.py")], env=env,
                         stdout=open(log, "w"), stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(120):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/aetherseed/status" % port, timeout=2).read()
            return p
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("the proxy on %d did not come up (see %s)" % (port, log))


def ask(port, wording):
    body = json.dumps({"model": "x", "stream": True, "messages": [
        {"role": "user", "content": "(start)"}, {"role": "assistant", "content": "(ready)"},
        {"role": "user", "content": wording}]}).encode()
    req = urllib.request.Request("http://127.0.0.1:%d/api/chat" % port, data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    reply, meta = [], {}
    with urllib.request.urlopen(req, timeout=300) as r:
        for raw in r:
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            reply.append((d.get("message") or {}).get("content") or "")
            if d.get("done"):
                meta = d.get("aetherseed") or {}
    return "".join(reply).strip(), meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ports", default="8011,8012")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    pa, pb = (int(x) for x in a.ports.split(","))
    corrected = corrected_episodes(os.path.join(LIVE, "aetherroot", "memory.db"))
    tests = test_set(corrected)
    print("%d corrected turns in her memory; %d questions of the key to ask" %
          (len(corrected), len(tests)), flush=True)
    results = open(os.path.join(a.out, "results.jsonl"), "w")
    ws = tempfile.mkdtemp(prefix="ab-ws-")
    for rnd in range(1, a.rounds + 1):
        work = tempfile.mkdtemp(prefix="ab-r%d-" % rnd, dir="/var/tmp")
        make_copy(os.path.join(work, "A"), False)
        dropped = make_copy(os.path.join(work, "B"), True)
        procs = [start_proxy(os.path.join(work, "A"), pa, os.path.join(a.out, "A%d.log" % rnd)),
                 start_proxy(os.path.join(work, "B"), pb, os.path.join(a.out, "B%d.log" % rnd))]
        print("round %d: copies made, %d corrected turns left out of B" % (rnd, dropped), flush=True)
        try:
            for n, (task, wording) in enumerate(tests):
                order = (("A", pa), ("B", pb)) if (n + rnd) % 2 else (("B", pb), ("A", pa))
                for arm, port in order:
                    t0 = time.time()
                    try:
                        reply, meta = ask(port, wording)
                        ok, why = T.check(task, reply, meta, ws)
                    except Exception as e:
                        reply, meta, ok, why = "", {}, False, "error: %r" % (e,)
                    row = {"round": rnd, "arm": arm, "id": task["id"], "said": wording,
                           "reply": reply, "ok": bool(ok), "why": why,
                           "secs": round(time.time() - t0, 1)}
                    results.write(json.dumps(row, ensure_ascii=False) + "\n")
                    results.flush()
                print("round %d: %d/%d" % (rnd, n + 1, len(tests)), flush=True)
        finally:
            for p in procs:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except Exception:
                    pass
            time.sleep(1)
            shutil.rmtree(work, ignore_errors=True)
    results.close()
    rows = [json.loads(l) for l in open(os.path.join(a.out, "results.jsonl"))]
    summary = {}
    for arm in ("A", "B"):
        r = [x for x in rows if x["arm"] == arm]
        summary[arm] = {"asked": len(r), "right": sum(x["ok"] for x in r)}
    pairs = {}
    for x in rows:
        pairs.setdefault((x["round"], x["id"]), {})[x["arm"]] = x["ok"]
    only_a = sum(1 for v in pairs.values() if v.get("A") and not v.get("B"))
    only_b = sum(1 for v in pairs.values() if v.get("B") and not v.get("A"))
    summary["right_only_with_corrections"] = only_a
    summary["right_only_without_corrections"] = only_b
    with open(os.path.join(a.out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary), flush=True)
    shutil.rmtree(ws, ignore_errors=True)


if __name__ == "__main__":
    main()
