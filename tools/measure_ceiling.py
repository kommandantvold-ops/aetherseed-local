#!/usr/bin/env python3
"""Measure a model's prompt ceiling on this unit: N tokens work, N+1 fail.

    sudo systemctl stop aetherseed-proxy aetherseed-keepalive      # the NPU to itself
    /opt/aetherseed/venv/bin/python3 tools/measure_ceiling.py --model qwen2.5-instruct:1.5b

WHY (build log, steps 5 and 42)
-------------------------------
The prompt ceiling of a compiled HEF is a property of the artifact and is not
declared anywhere. Hailo's table says "context 2048" for llama3.2:3b; the
prompt ceiling measured on this board was 864 (9 x 96 prefill chunks), and a
streaming request past it returns HTTP 200 with zero tokens - silent. The
guard in logic/token_budget.py refuses to serve a model until its ceiling has
been measured, so this is the first thing done with a new model.

HOW
---
A prompt of exactly N tokens - counted with the model's own tokenizer, in the
chat template the server applies (logic/token_budget.py) - is sent straight to
hailo-ollama, streaming, with num_predict 4. It WORKS if any content comes
back. The search is a bisection between a size that works and one that does
not. After every failure the server is restarted before the next attempt:
step 5 found that an over-limit request can wedge hailo-ollama in the kernel,
and a fresh server per failure is how the 864 was measured.

Writes nothing but its own log (--out). Talks to nobody's memory.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from logic.token_budget import TokenCounter, MODELS   # noqa: E402

URL = "http://127.0.0.1:8000"
FILLERS = (" river", " stone", " apple", " the", " a", " and", " of")


def prompt_of(counter, n):
    """Messages whose rendered chat template is exactly n tokens, or None."""
    for filler in FILLERS:
        lo, hi = 0, n
        while lo <= hi:
            mid = (lo + hi) // 2
            # the instruction last, so a long prompt still asks for an answer
            msgs = [{"role": "user", "content": (filler * mid).strip() + "\n\nNow say OK."}]
            got = counter.count_messages(msgs)
            if got == n:
                return msgs
            if got < n:
                lo = mid + 1
            else:
                hi = mid - 1
    return None


def ask(model, msgs, timeout=180):
    """(works, content, seconds, error, last). Works = any content streamed
    back; last is the final line the server sent, kept as evidence of how a
    failure looked."""
    body = json.dumps({"model": model, "messages": msgs, "stream": True,
                       "options": {"num_predict": 4}}).encode()
    req = urllib.request.Request(URL + "/api/chat", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    t0, content, err, last = time.time(), "", None, None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for raw in r:
                line = raw.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                last = d
                content += (d.get("message") or {}).get("content") or ""
    except Exception as e:                       # HTTP 500, timeout, reset
        err = repr(e)[:200]
    if isinstance(last, dict):
        last = {k: v for k, v in last.items() if k != "message"}
    return bool(content.strip()), content, round(time.time() - t0, 1), err, last


def restart_server(model):
    subprocess.run(["sudo", "systemctl", "restart", "hailo-ollama"], check=True)
    for _ in range(60):
        time.sleep(2)
        try:
            with urllib.request.urlopen(URL + "/hailo/v1/list", timeout=5):
                break
        except Exception:
            continue
    # load the model again with a tiny prompt, so the next timing is not a load
    ask(model, [{"role": "user", "content": "hi"}])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=sorted(MODELS))
    ap.add_argument("--good", type=int, default=256, help="a size known to work")
    ap.add_argument("--bad", type=int, default=4096, help="a size assumed to fail")
    ap.add_argument("--out", default="ceiling-%s.jsonl" % time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--no-restart", action="store_true",
                    help="do not restart hailo-ollama after a failure (not recommended)")
    a = ap.parse_args(argv)

    counter = TokenCounter(model=a.model)
    print("tokenizer %s (vocab %d), template %s" % (counter.path, counter.vocab_size,
                                                   counter.template), flush=True)
    log = open(a.out, "a", encoding="utf-8")

    def attempt(n):
        msgs = prompt_of(counter, n)
        if msgs is None:
            print("  %d: no filler gives exactly %d tokens - skipped" % (n, n), flush=True)
            return None
        works, content, secs, err, last = ask(a.model, msgs)
        entry = {"model": a.model, "tokens": n, "works": works, "content": content[:40],
                 "secs": secs, "error": err, "last": last,
                 "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        log.write(json.dumps(entry) + "\n")
        log.flush()
        print("  %5d tokens: %s  (%.1fs)%s" % (n, "WORKS" if works else "fails", secs,
                                              "  " + err if err else ""), flush=True)
        if not works and not a.no_restart:
            restart_server(a.model)
        return works

    good, bad = a.good, a.bad
    if not attempt(good):
        print("the 'good' size does not work - nothing to measure from", flush=True)
        return 2
    if attempt(bad):
        print("even %d works - raise --bad" % bad, flush=True)
        return 2
    while bad - good > 1:
        mid = (good + bad) // 2
        w = attempt(mid)
        if w is None:
            mid += 1
            w = attempt(mid)
            if w is None:
                print("cannot build prompts near %d" % mid, flush=True)
                return 2
        if w:
            good = mid
        else:
            bad = mid
    # confirm both edges once more, each on a fresh server
    if not attempt(good) or attempt(good + 1):
        print("the edge did not repeat: %d / %d - measure again" % (good, good + 1), flush=True)
        return 1
    print("CEILING %s: %d tokens work, %d fail" % (a.model, good, good + 1), flush=True)
    log.write(json.dumps({"model": a.model, "ceiling": good}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
