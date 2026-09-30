#!/usr/bin/env python3
"""The ecosystem soak: does she answer from what she knows about herself?

Andreas, 29 Sep 2026 (build log 48): "lets do a AetherSeed ecosystem soak.
Train on what is AetherSeed, Root and Spark, where is workspace, where is
to-do, how to summarize basically all that she will need once the trust-level
increases." And on 30 Sep (build log 49): "Put this ecosystem soak in a
training folder for the build. So that a pilot or I can run it
intermittently." How to run it is in training/README.md; in short:

    sudo bash /opt/aetherseed/training/run-ecosystem-soak.sh 1     # one hour

"Training" is the steward's word for it: the model is never trained. What she
knows about herself is the curriculum, knowledge/companion.en.jsonl, shipped
with the build. The soak asks whether she answers from it.

WHAT IT DOES
------------
  - copies her memory store into DIR/home (SQLite's backup, from a read-only
    connection, so a consistent snapshot), with her name and unit file; her
    own store is never written to, and her trust state is not copied - the
    copy starts at observer, whatever she has earned;
  - gives the copy a workspace (ecosystem-workspace/): a to-do list, a note,
    and a file to summarize;
  - starts a second proxy from this build with HOME set to the copy, on a
    spare port, beside hers; both share the one model server, so her own
    answers are slower while it runs;
  - asks, as her steward, the questions in ecosystem-probes.json round and
    round until the time is up (or DIR/STOP exists);
  - scores each answer by words, writes every turn to DIR/ecosoak.jsonl, and
    at the end writes DIR/report.txt (also: --report DIR, at any time).

Nothing it makes is deleted.
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)

PROBES = os.path.join(HERE, "ecosystem-probes.json")
WORKSPACE_SEED = os.path.join(HERE, "ecosystem-workspace")
GROUPS = ("what", "where", "ladder", "tools", "do", "refuse")
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


# ---------------------------------------------------------------------------
# The copy
# ---------------------------------------------------------------------------
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
    shutil.copytree(WORKSPACE_SEED, os.path.join(home, "aetherseed-workspace"))
    return n


# ---------------------------------------------------------------------------
# The second proxy, and a client that talks to it as the console does
# ---------------------------------------------------------------------------
def start_proxy(home, port, log_path):
    env = dict(os.environ, HOME=home, AETHERSEED_PROXY_PORT=str(port))
    log = open(log_path, "ab")
    proc = subprocess.Popen([sys.executable, "-u", os.path.join(APP, "proxy.py")],
                            env=env, stdout=log, stderr=subprocess.STDOUT, cwd=home)
    base = "http://127.0.0.1:%d" % port
    for _ in range(120):
        time.sleep(1)
        if proc.poll() is not None:
            raise SystemExit("the soak's proxy exited - see %s" % log_path)
        try:
            get(base, "/aetherseed/status")
            return proc, base
        except Exception:
            continue
    proc.terminate()
    raise SystemExit("the soak's proxy did not answer in 120 s - see %s" % log_path)


def get(base, path, timeout=30):
    with urllib.request.urlopen(base + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def chat(base, text):
    """One turn as the steward (no speaker), as the console sends it."""
    body = json.dumps({"stream": True, "messages": [{"role": "user", "content": text}]}).encode()
    req = urllib.request.Request(base + "/api/chat", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    r = {"status": None, "reply": "", "meta": {}, "dones": 0, "error": None}
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=400) as resp:
            r["status"] = resp.status
            for raw in resp:
                line = raw.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                r["reply"] += (d.get("message") or {}).get("content") or ""
                if d.get("done"):
                    r["dones"] += 1
                    r["meta"] = d.get("aetherseed") or {}
    except urllib.error.HTTPError as e:
        r["status"] = e.code
        r["error"] = "HTTP %s" % e.code
    except Exception as e:
        r["error"] = repr(e)[:300]
    r["secs"] = round(time.time() - t0, 1)
    return r


def failure(r):
    f = []
    if r["error"]:
        f.append("error")
    if r["status"] != 200:
        f.append("http_%s" % r["status"])
    if r["dones"] != 1:
        f.append("dones_%d" % r["dones"])
    if not r["reply"].strip():
        f.append("empty")
    if not r["meta"]:
        f.append("no_tag")
    return f


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------
def report(d, probes=None):
    """A plain-text summary of DIR's soak - while it runs or after."""
    probes = probes or load_probes()
    asks = {p["id"]: p["ask"] for p in probes}
    path = os.path.join(d, "ecosoak.jsonl")
    if not os.path.exists(path):
        return "no soak in %s\n" % d
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    turns = [e for e in rows if e.get("kind") == "probe"]
    start = next((e for e in rows if e.get("label") == "start"), {})
    end = next((e for e in rows if e.get("label") == "end"), None)
    n = len(turns)
    out = ["Ecosystem soak - %s" % d,
           "started %s; %s" % (start.get("at", "?"),
                               ("ended %s" % end["at"]) if end else "STILL RUNNING or stopped early"),
           "copy of %s episodes; build %s" % (start.get("copied_episodes", "?"),
                                              start.get("build", "?")),
           ""]
    if not n:
        return "\n".join(out + ["no turns yet", ""])
    failed = sum(bool(e["failures"]) for e in turns)
    out.append("turns %d, failed %d, median %.1f s a turn"
               % (n, failed, statistics.median(e["secs"] for e in turns)))
    q = lambda e: min(3, (e["turn"] - 1) * 4 // n)
    out += ["", "Answered (by expected words), per quarter of the run:",
            "  %-8s %8s %8s %8s %8s" % ("group", "Q1", "Q2", "Q3", "Q4")]
    for g in GROUPS:
        cells = []
        for k in range(4):
            c = [e for e in turns if e["group"] == g and q(e) == k]
            cells.append("%d/%d" % (sum(e["score"]["answered"] for e in c), len(c)) if c else "-")
        out.append("  %-8s %8s %8s %8s %8s" % ((g,) + tuple(cells)))
    out += ["", "Per question (answered / asked; wrong words; the most common answer):"]
    weak = []
    for pid in sorted(set(e["probe"] for e in turns)):
        c = [e for e in turns if e["probe"] == pid]
        a = sum(e["score"]["answered"] for e in c)
        w = sum(bool(e["score"]["wrong_words"]) for e in c)
        common = max(set(e["reply"][:70] for e in c), key=lambda s: sum(e["reply"][:70] == s for e in c))
        flag = "  <- CHECK" if a < 0.8 * len(c) or w else ""
        if flag:
            weak.append(pid)
        out.append("  %s %-44s %3d/%-3d wrong %-3d %s%s"
                   % (pid, asks.get(pid, "")[:44], a, len(c), w, json.dumps(common, ensure_ascii=False), flag))
    trust_path = os.path.join(d, "home", ".aetherseed", "trust_state.json")
    out.append("")
    if os.path.exists(trust_path):
        t = json.load(open(trust_path))
        out.append("The copy's trust at the end: resonance %s, %d paid refusals, %d unpaid "
                   "(it started at observer, 0; the copy's gate stays at observer for the whole run)"
                   % (t.get("resonance"), t.get("honest_refusals", 0),
                      sum(1 for o in t.get("observations", []) if "unpaid" in o.get("type", ""))))
    else:
        out.append("The copy's trust: nothing scored (no trust_state.json)")
    out += ["", "Questions to look at: %s" % (", ".join(weak) if weak else "none"),
            "Every turn, with the full answer: %s" % path, ""]
    return "\n".join(out)


def build_id():
    """The application digest, as tools/cartridge.sh computes it - so a report
    says which build answered. Best effort."""
    try:
        files = []
        for top, dirs, names in os.walk(APP):
            dirs[:] = [x for x in dirs if not (top == APP and x == "venv")]
            for name in names:
                files.append(os.path.relpath(os.path.join(top, name), APP))
        import hashlib
        lines = []
        for rel in sorted("./" + f for f in files):
            with open(os.path.join(APP, rel[2:]), "rb") as fh:
                lines.append("%s  %s\n" % (hashlib.sha256(fh.read()).hexdigest(), rel))
        return hashlib.sha256("".join(lines).encode()).hexdigest()[:8]
    except Exception:
        return "?"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", help="where the copy, the turns and the report go")
    ap.add_argument("--copy-from", default="/var/lib/aetherseed/.aetherseed",
                    help="her state directory (.aetherseed), read and never written")
    ap.add_argument("--hours", type=float, default=1.0)
    ap.add_argument("--port", type=int, default=8012)
    ap.add_argument("--pause", type=float, default=3.0)
    ap.add_argument("--report", metavar="DIR", help="print the report for DIR and stop")
    a = ap.parse_args(argv)

    if a.report:
        sys.stdout.write(report(a.report))
        return 0
    if not a.dir:
        ap.error("--dir is required")

    os.makedirs(a.dir, exist_ok=True)
    home = os.path.join(a.dir, "home")
    episodes = copy_home(a.copy_from, home)
    probes = load_probes()
    out = os.path.join(a.dir, "ecosoak.jsonl")
    proc, base = start_proxy(home, a.port, os.path.join(a.dir, "proxy.log"))

    def write(e):
        e.setdefault("at", now())
        with open(out, "a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    write({"kind": "status", "label": "start", "copied_episodes": episodes,
           "build": build_id(), "hours": a.hours, "status": get(base, "/aetherseed/status")})
    print("[ecosoak] copy of %d episodes, %d questions, %s h, proxy %s"
          % (episodes, len(probes), a.hours, base), flush=True)
    deadline = time.time() + a.hours * 3600
    turn = 0
    try:
        while time.time() < deadline and not os.path.exists(os.path.join(a.dir, "STOP")):
            p = probes[turn % len(probes)]
            r = chat(base, p["ask"])
            turn += 1
            e = {"turn": turn, "kind": "probe", "probe": p["id"], "group": p["group"],
                 "sent": p["ask"], "reply": r["reply"], "secs": r["secs"],
                 "status": r["status"], "meta": r["meta"], "failures": failure(r),
                 "score": score(p, r["reply"], r["meta"])}
            write(e)
            print("[ecosoak] %d %s %.0fs %s" % (turn, p["id"], r["secs"],
                  "ok" if e["score"]["answered"] else "-"), flush=True)
            time.sleep(30 if r["status"] != 200 else a.pause)
        print("[ecosoak] time is up" if time.time() >= deadline else "[ecosoak] stopped", flush=True)
        write({"kind": "status", "label": "end", "turns": turn,
               "status": get(base, "/aetherseed/status")})
    finally:
        proc.terminate()
        try:
            proc.wait(20)
        except Exception:
            proc.kill()
        text = report(a.dir, probes)
        with open(os.path.join(a.dir, "report.txt"), "w", encoding="utf-8") as f:
            f.write(text)
        print(text, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
