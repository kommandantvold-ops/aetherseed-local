#!/usr/bin/env python3
"""The model bench: the same questions, the same facts, the model the only
difference (Andreas, 26 Sep 2026: "we go with plan A and the bench").

    sudo systemctl stop aetherseed-proxy aetherseed-keepalive     # the NPU to itself
    /opt/aetherseed/venv/bin/python3 tools/model_bench.py --dir ~/bench \\
        --companion /path/companion.json --unit /path/unit.jsonl \\
        --models llama3.2:3b qwen2.5-instruct:1.5b

WHAT IT IS
----------
A 24-hour soak is the wrong first test for a model (claude/model-options-
2026-09-26.md, section 5). This is the cheap one before it:

  - a throwaway home - NEVER a unit's memory - whose store holds only the
    1533 verses of Genesis as owner facts, as Lyra's does;
  - the reading soak's 26 Genesis questions, plainly and owner-framed, three
    times each, from a Reader, as in the soak (tools/texts/genesis-probes.json);
  - through a real proxy process from this checkout, so the charter, the
    retrieval, the token guard, the generation bounds, the honesty check and
    the owner-attribution check are all the ones a unit runs;
  - with no episode ever retrieved (max_retrieved 0) and no ring ever closed,
    so every model sees the same prompt for the same question: its own earlier
    answers cannot come back, which is exactly what the soak measures and the
    bench must not.

Per model it writes every turn to bench-<model>.jsonl and a summary, and prints
a table. The owner-credited answers are also written out for reading by hand:
the attribution check is mechanical (logic/attribution.py, step 41), and step
40's lesson was that the reading matters.

Speaker "Reader", as in the soak: the questions are the soak's, and the
Reader is also a program set up on the owner's instruction.
"""
import argparse
import json
import os
import shutil
import signal
import statistics
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
sys.path.insert(0, HERE)

import reading_soak as rs                                  # noqa: E402

TEXTS = os.path.join(HERE, "texts")
SPEAKER = "Reader"
OVERRIDES = {"max_retrieved": 0,              # no episode comes back: same prompt for every model
             "consolidation_threshold": 10 ** 9,   # no ring closes, so no background model call
             "facts_max": 2000}


def prepare_home(home, companion=None, unit=None):
    """A throwaway home holding the owner's facts and nothing else remembered."""
    from aetherroot import DEFAULT_CONFIG, AetherRoot
    from logic.facts import validate_fact
    dot = os.path.join(home, ".aetherseed")
    root_dir = os.path.join(dot, "aetherroot")
    if os.path.exists(root_dir):
        raise SystemExit("%s exists - the bench starts from a fresh home" % root_dir)
    os.makedirs(root_dir)
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(OVERRIDES)
    with open(os.path.join(root_dir, "config.json"), "w") as f:
        json.dump(cfg, f, indent=2)
    for src, name in ((companion, "companion.json"), (unit, "unit.jsonl")):
        if src:
            shutil.copyfile(src, os.path.join(dot, name))
    root = AetherRoot(root_dir)
    n = 0
    with open(os.path.join(TEXTS, "genesis.web.jsonl"), encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            v = json.loads(line)
            text, source, err = validate_fact(v["text"], v["ref"])
            if err:
                raise SystemExit("fact %s refused: %s" % (v["ref"], err))
            root.store.add_fact(text, source)
            n += 1
    count = root.store.fact_count()
    root.close()
    return n, count


def start_proxy(home, port, log_path):
    env = dict(os.environ, HOME=home, AETHERSEED_PROXY_PORT=str(port))
    log = open(log_path, "ab")
    proc = subprocess.Popen([sys.executable, "-u", os.path.join(APP, "proxy.py")],
                            env=env, stdout=log, stderr=subprocess.STDOUT, cwd=home)
    base = "http://127.0.0.1:%d" % port
    for _ in range(120):
        time.sleep(1)
        if proc.poll() is not None:
            raise SystemExit("the bench proxy exited - see %s" % log_path)
        try:
            with urllib.request.urlopen(base + "/aetherseed/status", timeout=5) as r:
                json.loads(r.read().decode())
            return proc, base
        except Exception:
            continue
    proc.terminate()
    raise SystemExit("the bench proxy did not answer in 120 s - see %s" % log_path)


def chat(base, model, text):
    """reading_soak's client, with the model named per request."""
    unit = rs.Unit(base)
    rs.MODEL = model           # the soak's client sends rs.MODEL
    return unit.chat(text, speaker=SPEAKER)


def quantile(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else None


def summarise(turns):
    ok = [t for t in turns if not t["failures"]]
    s = {"turns": len(turns), "failed": len(turns) - len(ok)}
    for style in ("ask", "ask_owner", "all"):
        ts = [t for t in ok if style == "all" or t["style"] == style]
        shown = [t for t in ts if t["score"]["shown"]]
        not_shown = [t for t in ts if not t["score"]["shown"]]
        credited = [t for t in ts if t["meta"].get("owner_credited")]
        unbacked = [t for t in credited if t["meta"].get("owner_backed") is False]
        s[style] = {
            "n": len(ts),
            "target_shown": len(shown),
            "answered_when_shown": sum(t["score"]["answered"] for t in shown),
            "answered_when_not": sum(t["score"]["answered"] for t in not_shown),
            "credits_owner": len(credited),
            "unbacked_credit": len(unbacked),
            "unbacked_when_target_not_shown": sum(1 for t in unbacked if not t["score"]["shown"]),
            "unbacked_figure": sum(1 for t in unbacked if str(t["meta"].get("owner_why", "")).startswith("a figure")),
            "tag_copied": sum(t["score"]["tag_copied"] for t in ts),
            "declined": sum(t["score"]["declined"] for t in ts),
            "unsourced_figures": sum(1 for t in ts if t["meta"].get("unsourced_figures")),
            "unbacked_sources": sum(1 for t in ts if t["meta"].get("unbacked_sources")),
        }
    secs = [t["secs"] for t in ok]
    s["secs"] = {"median": statistics.median(secs) if secs else None,
                 "p90": quantile(secs, 0.9), "max": max(secs) if secs else None}
    return s


def run_model(base, model, probes, reps, out_dir):
    safe = model.replace(":", "_").replace("/", "_")
    path = os.path.join(out_dir, "bench-%s.jsonl" % safe)
    turns = []
    # the first request loads the model's HEF: timed on its own, not scored
    t0 = time.time()
    warm = chat(base, model, "Hello.")
    load = {"secs": round(time.time() - t0, 1), "failures": rs.failure(warm)}
    print("%s: first request (loads the model) %.1fs %s" % (model, load["secs"],
          load["failures"] or ""), flush=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "load", "model": model, **load, "reply": warm["reply"]},
                           ensure_ascii=False) + "\n")
        for rep in range(1, reps + 1):
            for p in probes["facts"]:
                for style in ("ask", "ask_owner"):
                    q = p[style]
                    r = chat(base, model, q)
                    t = {"kind": "fact", "model": model, "rep": rep, "probe": p["id"],
                         "style": style, "sent": q, "reply": r["reply"], "secs": r["secs"],
                         "status": r["status"], "meta": r["meta"],
                         "failures": rs.failure(r),
                         "score": rs.score_fact(p, r["reply"], r["meta"]),
                         "at": rs.now()}
                    turns.append(t)
                    f.write(json.dumps(t, ensure_ascii=False) + "\n")
                    f.flush()
                    m = r["meta"]
                    print("  %s r%d %-4s %-9s %5.1fs shown=%d owner=%s%s" % (
                        model, rep, p["id"], style, r["secs"], int(t["score"]["shown"]),
                        "-" if not m.get("owner_credited") else
                        ("backed" if m.get("owner_backed") else "UNBACKED"),
                        "  FAIL " + ",".join(t["failures"]) if t["failures"] else ""),
                        flush=True)
    return turns, load


def write_for_reading(out_dir, model, turns):
    """Every owner-credited answer, grouped by question, with the verses shown."""
    gen = {}
    with open(os.path.join(TEXTS, "genesis.web.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                v = json.loads(line)
                gen[v["ref"]] = v["text"]
    safe = model.replace(":", "_").replace("/", "_")
    with open(os.path.join(out_dir, "owner-answers-%s.txt" % safe), "w", encoding="utf-8") as f:
        f.write("Owner-credited answers from the model bench, %s. For reading by hand.\n\n" % model)
        groups = {}
        for t in turns:
            if t["meta"].get("owner_credited"):
                groups.setdefault((t["probe"], t["style"]), []).append(t)
        for (pid, style), ts in sorted(groups.items()):
            f.write("##### %s %s  Q: %s\n" % (pid, style, ts[0]["sent"]))
            for src in sorted({s for t in ts for s in t["meta"].get("fact_sources") or ()}):
                f.write("    [%s] %s\n" % (src, gen.get(src, "")))
            for t in ts:
                f.write("  r%d %s (%s): %s\n" % (
                    t["rep"], "backed" if t["meta"].get("owner_backed") else "UNBACKED",
                    t["meta"].get("owner_why", ""), t["reply"].replace("\n", " ")))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="where the throwaway home and results go")
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--probes", type=int, default=0,
                    help="only the first N questions (a smoke run); 0 = all 26")
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--companion", help="a copy of the unit's companion.json (its name)")
    ap.add_argument("--unit", help="a copy of the unit's unit.jsonl (what it knows about itself)")
    a = ap.parse_args(argv)

    out = os.path.abspath(os.path.expanduser(a.dir))
    home = os.path.join(out, "home")
    os.makedirs(out, exist_ok=True)
    n, count = prepare_home(home, a.companion, a.unit)
    print("throwaway home %s: %d facts entered, %d active" % (home, n, count), flush=True)
    with open(os.path.join(TEXTS, "genesis-probes.json"), encoding="utf-8") as f:
        probes = json.load(f)
    if a.probes:
        probes["facts"] = probes["facts"][:a.probes]

    proc, base = start_proxy(home, a.port, os.path.join(out, "proxy-journal.txt"))
    summary = {"started": rs.now(), "app": APP, "reps": a.reps, "speaker": SPEAKER,
               "overrides": OVERRIDES, "facts": count, "models": {}}
    try:
        for model in a.models:
            turns, load = run_model(base, model, probes, a.reps, out)
            s = summarise(turns)
            s["load"] = load
            summary["models"][model] = s
            write_for_reading(out, model, turns)
            with open(os.path.join(out, "summary.json"), "w") as f:
                json.dump(summary, f, indent=1)
    finally:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
    summary["finished"] = rs.now()
    with open(os.path.join(out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1)

    print("\n%-26s %s" % ("", "  ".join("%22s" % m for m in a.models)))
    rows = [("failed turns", lambda s: s["failed"]),
            ("median s / p90", lambda s: "%s / %s" % (s["secs"]["median"], s["secs"]["p90"])),
            ("first request s", lambda s: s["load"]["secs"])]
    for style, label in (("ask", "plain"), ("ask_owner", "owner-framed")):
        rows += [
            ("%s: answered, shown" % label,
             lambda s, st=style: "%d/%d" % (s[st]["answered_when_shown"], s[st]["target_shown"])),
            ("%s: credits owner" % label, lambda s, st=style: "%d/%d" % (s[st]["credits_owner"], s[st]["n"])),
            ("%s: unbacked credit" % label, lambda s, st=style: s[st]["unbacked_credit"]),
            ("%s: declined" % label, lambda s, st=style: s[st]["declined"]),
        ]
    for label, fn in rows:
        print("%-26s %s" % (label, "  ".join("%22s" % fn(summary["models"][m]) for m in a.models)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
