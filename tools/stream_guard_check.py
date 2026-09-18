#!/usr/bin/env python3
"""Device-side integration check for the generation guards in call_hailo_chat.

Run ON the Companion, against a live hailo-ollama. Unlike test_token_budget.py
and test_stream_guard.py (pure unit tests) this exercises the real streaming
path end to end, because the behaviour it guards against - the model emitting
<|start_header_id|>, or answering and then filling until something stops it -
only appears against the real model.

    python3 tools/stream_guard_check.py            # the deployed app
    AETHERSEED_APP=~/ptest python3 tools/stream_guard_check.py

Eight short spoken-style prompts, the same set as the 2026-09-18 study (build
log step 12), twice each, under the real charter; then ten of the "Reply with
exactly: OK" prompt that produced the runaways in step 10.

Expect: 0 control tokens surviving into ai_content, every stream valid NDJSON
ending in exactly one done=true, no response past num_predict, and the one-word
question answered in one word.

Only the heavy app modules are stubbed; the function under test is the
committed call_hailo_chat, not a reimplementation.
"""
import json
import os
import sys
import time
import types

APP = os.path.expanduser(os.environ.get("AETHERSEED_APP", "/opt/aetherseed"))
sys.path.insert(0, APP)
for cand in (os.environ.get("AETHERSEED_TOKENIZER"),
             "/var/lib/aetherseed/tokenizer.json",
             os.path.expanduser("~/.aetherseed/tokenizer.json")):
    if cand and os.path.exists(cand):
        os.environ["AETHERSEED_TOKENIZER"] = cand
        break

for name, attrs in (("aetherroot", ["AetherRoot"]),
                    ("aetherspark", ["AetherSpark"]),
                    ("trust_evolution", ["TrustEvolution"]),
                    ("intent_detection", ["detect_intent", "execute_intent"]),
                    ("honesty_check", ["check_response"])):
    m = types.ModuleType(name)
    for a in attrs:
        setattr(m, a, lambda *x, **k: types.SimpleNamespace(
            get_trust_level_name=lambda: "Seed", retrieve_context=lambda *_: "",
            store_episode=lambda **_: 1, store_interaction=lambda *_, **__: None,
            get_status=lambda: {"episodes": 0, "willingness_mean": 0.0}))
    sys.modules[name] = m

import proxy                                   # noqa: E402
from logic.prompt_builder import MUSTARDSEED   # noqa: E402

print("app:", APP)
print("GENERATION_OPTIONS =", proxy.GENERATION_OPTIONS,
      "STOP_AT_PARAGRAPH =", proxy.STOP_AT_PARAGRAPH,
      "MAX_GENERATION_SECONDS =", proxy.MAX_GENERATION_SECONDS)
print()

PROMPTS = [
    "What is the capital of Norway? One word.",
    "How many legs does a spider have?",
    "Good morning.",
    "Reply with exactly: OK",
    "What year did the Berlin Wall fall?",
    "What is the DOI of the paper 'Resonance Fields in Small Language Models' by Kommandantvold?",
    "Tell me a short joke.",
    "What's the weather like right now?",
]
runs = [(p, MUSTARDSEED) for p in PROMPTS for _ in range(2)]
runs += [("Reply with exactly: OK", "You are Horizon. Answer briefly and honestly.")] * 10

cap = proxy.GENERATION_OPTIONS.get("num_predict")
bad = {"ctrl": 0, "json": 0, "done": 0, "over_cap": 0}
walls = []
for i, (prompt, system) in enumerate(runs, 1):
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    t0 = time.time()
    raw, ai = proxy.call_hailo_chat("llama3.2:3b", msgs)
    dt = round(time.time() - t0, 1)
    walls.append(dt)
    try:
        lines = [json.loads(l) for l in raw.decode().split("\n") if l.strip()]
        ok_json = True
    except json.JSONDecodeError:
        lines, ok_json = [], False
    dones = [l for l in lines if l.get("done")]
    content_chunks = sum(1 for l in lines if l.get("message", {}).get("content"))
    reason = dones[-1].get("done_reason") if dones else None
    ctrl = "<|" in ai
    bad["ctrl"] += ctrl
    bad["json"] += not ok_json
    bad["done"] += (len(dones) != 1)
    bad["over_cap"] += bool(cap and content_chunks > cap)
    print("%2d wall=%5.1fs chunks=%-3d done=%d reason=%-6s ctrl=%-5s | %-44s | %r"
          % (i, dt, content_chunks, len(dones), reason, ctrl, prompt[:44], ai[:60]), flush=True)

print()
print("control tokens in ai_content: %d / %d" % (bad["ctrl"], len(runs)))
print("malformed streams:            %d / %d" % (bad["json"], len(runs)))
print("streams without exactly one done: %d / %d" % (bad["done"], len(runs)))
print("responses past num_predict:   %d / %d" % (bad["over_cap"], len(runs)))
print("wall: max %.1fs  mean %.1fs" % (max(walls), sum(walls) / len(walls)))
