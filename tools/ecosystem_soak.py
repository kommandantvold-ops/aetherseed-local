#!/usr/bin/env python3
"""The ecosystem soak: does she answer from what she now knows about herself?

Andreas, 29 Sep 2026 (build log 48): "lets do a AetherSeed ecosystem soak.
Train on what is AetherSeed, Root and Spark, where is workspace, where is
to-do, how to summarize basically all that she will need once the trust-level
increases." Asked, he chose: the ecosystem as built-in knowledge (the
curriculum, knowledge/companion.en.jsonl - the model itself is never trained),
a summarize tool, 8 hours, and a THROWAWAY COPY of her memory.

    /opt/aetherseed/venv/bin/python3 tools/ecosystem_soak.py --dir ~/ecosoak \\
        --copy-from /var/lib/aetherseed/.aetherseed --hours 8

WHAT IT DOES
------------
  - copies her memory store into DIR/home (SQLite's backup, from a read-only
    connection, so a consistent snapshot), with her name and unit file; her
    own store is never written to;
  - gives the copy a workspace like hers would be: a to-do list, a note, and
    a file to summarize (texts/ecosystem-workspace/);
  - starts a proxy from this checkout with HOME set to the copy, on a spare
    port, beside hers; trust starts at observer, as hers is;
  - asks, as her owner, the questions in texts/ecosystem-probes.json round and
    round until the time is up - what she is, her memory, her tools, where
    things are, the ladder, how trust is earned, and requests she may and may
    not carry out at observer;
  - scores each answer by words (expected words present; a claim she can do
    what she cannot), and writes every turn to DIR/ecosoak.jsonl.

The copy grows during the soak as a unit's memory would, so her own earlier
answers can come back: that is what "better or worse over time" measures.
Nothing it makes is deleted.
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
sys.path.insert(0, HERE)

import reading_soak as rs                                  # noqa: E402

TEXTS = os.path.join(HERE, "texts")
PROBES = os.path.join(TEXTS, "ecosystem-probes.json")
WORKSPACE_SEED = os.path.join(TEXTS, "ecosystem-workspace")
_DECLINED = re.compile(r"\bI\s+(?:don[’']?t|do not)\s+know\b|\bI[’']?m not sure\b|"
                       r"\bI am not sure\b|\bI (?:cannot|can[’']?t|am not able to)\b", re.I)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_probes(path=PROBES):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["probes"]


def has_word(text, words):
    return [w for w in words if re.search(r"\b" + re.escape(w.lower()), (text or "").lower())]


def score(p, reply, meta):
    """Word matches, not judgements."""
    hit = has_word(reply, p.get("expect") or [])
    wrong = has_word(reply, p.get("never") or [])
    return {"answered": bool(hit), "expected_words": hit, "wrong_words": wrong,
            "declined": bool(_DECLINED.search(reply or "")),
            "tool_ran": bool(meta.get("used_tools"))}


def copy_home(src_dot, home):
    """Her store, name and unit file, copied into a throwaway home."""
    dot = os.path.join(home, ".aetherseed")
    root_dir = os.path.join(dot, "aetherroot")
    if os.path.exists(root_dir):
        raise SystemExit("%s exists - the soak starts from a fresh copy" % root_dir)
    os.makedirs(root_dir)
    src_root = os.path.join(src_dot, "aetherroot")
    for name in ("config.json", "embedder_state.json", "willingness.npy"):
        p = os.path.join(src_root, name)
        if os.path.exists(p):
            shutil.copyfile(p, os.path.join(root_dir, name))
    src = sqlite3.connect("file:%s?mode=ro" % os.path.join(src_root, "memory.db"), uri=True)
    dst = sqlite3.connect(os.path.join(root_dir, "memory.db"))
    src.backup(dst)
    n = dst.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
    dst.close()
    src.close()
    for name in ("companion.json", "unit.jsonl"):
        p = os.path.join(src_dot, name)
        if os.path.exists(p):
            shutil.copyfile(p, os.path.join(dot, name))
    ws = os.path.join(home, "aetherseed-workspace")
    shutil.copytree(WORKSPACE_SEED, ws)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--copy-from", required=True,
                    help="her state directory (.aetherseed), read and never written")
    ap.add_argument("--hours", type=float, default=8.0)
    ap.add_argument("--port", type=int, default=8012)
    ap.add_argument("--pause", type=float, default=3.0)
    a = ap.parse_args(argv)

    import model_bench as mb
    os.makedirs(a.dir, exist_ok=True)
    home = os.path.join(a.dir, "home")
    episodes = copy_home(a.copy_from, home)
    probes = load_probes()
    out = os.path.join(a.dir, "ecosoak.jsonl")
    proc, base = mb.start_proxy(home, a.port, os.path.join(a.dir, "proxy.log"))
    unit = rs.Unit(base)
    rs.MODEL = None
    status = unit.get("/aetherseed/status")

    def write(e):
        e.setdefault("at", now())
        with open(out, "a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    write({"kind": "status", "label": "start", "copied_episodes": episodes, "status": status})
    print("[ecosoak] copy of %d episodes, %d probes, %s h, proxy %s"
          % (episodes, len(probes), a.hours, base), flush=True)
    deadline = time.time() + a.hours * 3600
    turn = 0
    try:
        while time.time() < deadline and not os.path.exists(os.path.join(a.dir, "STOP")):
            p = probes[turn % len(probes)]
            r = unit.chat(p["ask"], speaker=None)
            turn += 1
            e = {"turn": turn, "kind": "probe", "probe": p["id"], "group": p["group"],
                 "sent": p["ask"], "reply": r["reply"], "secs": r["secs"],
                 "status": r["status"], "meta": r["meta"], "failures": rs.failure(r),
                 "score": score(p, r["reply"], r["meta"])}
            write(e)
            print("[ecosoak] %d %s %.0fs %s" % (turn, p["id"], r["secs"],
                  "ok" if e["score"]["answered"] else "-"), flush=True)
            time.sleep(30 if r["status"] != 200 else a.pause)
        print("[ecosoak] time is up", flush=True)
        write({"kind": "status", "label": "end", "turns": turn,
               "status": unit.get("/aetherseed/status")})
    finally:
        proc.terminate()
        try:
            proc.wait(20)
        except Exception:
            proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
