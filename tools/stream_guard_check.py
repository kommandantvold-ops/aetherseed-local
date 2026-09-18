#!/usr/bin/env python3
"""Device-side integration check for the generation guards in call_hailo_chat.

Run ON the Companion, against a live hailo-ollama. Unlike test_token_budget.py
(pure unit tests) this exercises the real streaming path end to end, because
the behaviour it guards against - the model emitting <|start_header_id|> and
the server not stopping - only appears against real hardware.

    python3 tools/stream_guard_check.py

Expect: 0 control tokens surviving into ai_content, every stream valid NDJSON
terminated with done=true, and no response running to hundreds of chunks.

Only the heavy app modules are stubbed; the function under test is the
committed call_hailo_chat, not a reimplementation.
"""
import sys, types, os, json, time
sys.path.insert(0, os.path.expanduser("~/ptest"))
os.environ.setdefault("AETHERSEED_TOKENIZER", os.path.expanduser("~/.aetherseed/tokenizer.json"))

for name, attrs in (("aetherroot", ["AetherRoot"]),
                    ("aetherspark", ["AetherSpark"]),
                    ("trust_evolution", ["TrustEvolution"]),
                    ("intent_detection", ["detect_intent", "execute_intent"]),
                    ("honesty_check", ["check_response"])):
    m = types.ModuleType(name)
    for a in attrs:
        setattr(m, a, lambda *x, **k: types.SimpleNamespace(
            get_trust_level_name=lambda: "Seed", retrieve_context=lambda *_: "",
            store_episode=lambda **_: 1, store_interaction=lambda *_, **__: None))
    sys.modules[name] = m

import proxy
print("MAX_GENERATED_CHUNKS =", proxy.MAX_GENERATED_CHUNKS)
print()

CTRL_RUNS = 0
for i in range(1, 41):
    msgs = [{"role": "system", "content": "You are Horizon. Answer briefly and honestly."},
            {"role": "user", "content": "Reply with exactly: OK"}]
    t0 = time.time()
    raw, ai = proxy.call_hailo_chat("llama3.2:3b", msgs)
    dt = round(time.time() - t0, 1)
    lines = [l for l in raw.decode().strip().split("\n") if l.strip()]
    ok_json = all(json.loads(l) for l in lines)
    last = json.loads(lines[-1])
    ctrl = "<|" in ai
    if ctrl: CTRL_RUNS += 1
    print("%2d wall=%5ss chunks=%-4d valid_json=%-5s done=%-5s reason=%-6s ctrl_in_ai=%-5s %r"
          % (i, dt, len(lines), ok_json, last.get("done"), last.get("done_reason"), ctrl, ai[:38]))
print()
print("responses with a control token surviving into ai_content:", CTRL_RUNS, "/ 40")
