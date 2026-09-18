"""
Aetherseed Proxy v3 — The Living Agent
========================================
WebUI (8080) → Aetherseed Proxy (8001) → hailo-ollama (8000)

Now with intent detection: the proxy detects what the user
wants to do, executes tools through AetherSpark's safety gate,
and gives the model the results so it can respond naturally.

The model stays conversational. The proxy handles the doing.
"""

import http.server
import json
import urllib.request
import urllib.error
import threading
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aetherroot import AetherRoot
from aetherspark import AetherSpark
from trust_evolution import TrustEvolution
from intent_detection import detect_intent, execute_intent

# ============================================================
# CONFIGURATION
# ============================================================

HAILO_OLLAMA_URL = "http://127.0.0.1:8000"
PROXY_PORT = int(os.environ.get("AETHERSEED_PROXY_PORT", "8001"))

# Bind address. Defaults to loopback: a device sold on "nothing leaves" should
# not expose its LLM proxy to the LAN unless something on the LAN needs it. A
# UI on another machine sets AETHERSEED_PROXY_BIND=0.0.0.0 in the unit. The
# previous hardcoded 0.0.0.0 was the same default hailo-ollama shipped with
# (build log, step 4, finding 1).
PROXY_BIND = os.environ.get("AETHERSEED_PROXY_BIND", "127.0.0.1")

# The charter lives in exactly one place now. proxy.py previously kept its
# own copy, which had already drifted from prompt_builder's (223 vs 210
# tokens, different final paragraph).
from logic.prompt_builder import MUSTARDSEED as MUSTARDSEED_SEED
from logic.prompt_builder import DATA_NOTE
from logic.token_budget import (TokenCounter, enforce_budget, sanitize_injected,
                                sanitize_model_output, PromptTooLarge,
                                TokenizerUnavailable)

# One tokenizer for the process. Loading it costs ~17MB and a moment, so it is
# built once, lazily, and reused.
_TOKEN_COUNTER = None


def token_counter():
    global _TOKEN_COUNTER
    if _TOKEN_COUNTER is None:
        _TOKEN_COUNTER = TokenCounter()
    return _TOKEN_COUNTER

# ============================================================
# SHARED STATE
# ============================================================

root = AetherRoot()
trust = TrustEvolution()
trust_level = trust.get_trust_level_name()
spark = AetherSpark({
    "sandbox_root": os.path.expanduser("~/aetherseed-workspace"),
    "trust_level": trust_level,
    "audit_log": os.path.expanduser("~/.aetherseed/spark_audit.log")
})

# ============================================================
# HAILO-OLLAMA CLIENT
# ============================================================

# hailo-ollama ignores max_tokens (measured 2026-09-18: max_tokens=20 produced
# 408 tokens, max_tokens=60 produced 246), so this is the only cap that exists.
#
# Expressed in SECONDS, not tokens, because seconds are what the person waiting
# actually experiences, and because it stays meaningful if the decode rate ever
# changes. At the measured 2.6 tok/s, 90s is roughly 234 tokens.
#
# This is the backstop for a runaway carrying no control token. Measured over 40
# requests to "Reply with exactly: OK": two ran to 258 and 298 chunks (98.7s and
# 112.5s) because the model answered correctly and then wandered into invented
# self-description - "I am Horizon, the goddess of time". Those are not long
# answers being truncated; they are a runaway and a fabrication, and the person
# is better served by the cut.
#
# PRODUCT DECISION, not a technical constant: the right value is whatever the
# voice path's latency budget turns out to be. 90s is a defensible placeholder,
# not a measured optimum.
MAX_GENERATION_SECONDS = 90


def call_hailo_chat(model: str, messages: list) -> tuple:
    """Send chat request to hailo-ollama. Returns (raw_bytes, ai_content).

    Every request leaves through here, so the guards live here rather than in a
    prompt builder. Three things are enforced, none of which the server does:

    1. The 864-token prefill ceiling. Past it the NPU fails SILENTLY on a
       streaming call - HTTP 200 with an empty body - so an unguarded prompt
       looks exactly like a successful empty answer. enforce_budget() raises
       instead of sending one.

    2. The missing stop token. The manifest's stop_tokens are <|end_of_text|>,
       <|eom_id|> and <|eot_id|>. The model routinely emits <|start_header_id|>
       instead (22% of responses, measured over 119 requests), and because that
       is not a stop token the server keeps generating - straight into a
       hallucinated next turn, for hundreds of tokens at the normal 2.6 tok/s.
       That is the whole of the "intermittent hang": a 162s response was 430
       tokens generated at full speed, not a stall. Adding the token to the
       manifest's stop_tokens was tried and is IGNORED by this build, so the
       stream is stopped here instead.

    3. A wall-clock generation budget, since max_tokens is ignored too. It
       catches a runaway with no control token - measured twice in 40 requests,
       the model answering "OK" then rambling ~110s about being "the goddess of
       time".

    Abandoning a stream mid-generation is safe: measured over three trials,
    closing the socket after 20 chunks left the next request answering in
    2.5-4.8s with no reset and no wedge.
    """
    messages, budget = enforce_budget(token_counter(), messages)
    if budget.trimmed:
        print(f"[token-budget] {budget.summary()}", flush=True)

    data = json.dumps({"model": model, "messages": messages, "stream": True}).encode()
    req = urllib.request.Request(
        f"{HAILO_OLLAMA_URL}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    ai_content = ""
    out_lines = []
    stripped_total = 0
    chunks = 0
    stopped_because = None
    deadline = time.monotonic() + MAX_GENERATION_SECONDS

    resp = urllib.request.urlopen(req, timeout=300)
    try:
        for raw_line in resp:
            line = raw_line.strip()
            if not line:
                continue
            try:
                d = json.loads(line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                out_lines.append(line.decode("utf-8", errors="replace"))
                continue

            msg = d.get("message", {})
            if msg.get("role") == "assistant":
                clean, n = sanitize_model_output(msg.get("content", ""))
                if n:
                    stripped_total += n
                    stopped_because = "control-token"   # the stop the server lacks
                msg["content"] = clean
                d["message"] = msg
                ai_content += clean
                chunks += 1

            out_lines.append(json.dumps(d))

            if d.get("done"):
                break
            if stopped_because:
                break
            if time.monotonic() > deadline:
                stopped_because = f"{MAX_GENERATION_SECONDS}s-budget"
                break
    finally:
        resp.close()          # abandon the rest; the server frees promptly

    if stopped_because:
        print(f"[generation] stopped early: {stopped_because} "
              f"after {chunks} chunks ({stripped_total} control token(s))", flush=True)
        # The caller is mid-stream and expects a terminator. Emit a well-formed
        # one so a UI does not sit waiting on a connection we just closed.
        out_lines.append(json.dumps({
            "model": model,
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
        }))

    raw = ("\n".join(out_lines) + "\n").encode("utf-8")
    return raw, ai_content


# ============================================================
# PROXY HANDLER
# ============================================================

class ProxyHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def _proxy_passthrough(self, method="GET", body=None):
        url = f"{HAILO_OLLAMA_URL}{self.path}"
        headers = {k: v for k, v in self.headers.items()}
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in ('transfer-encoding', 'connection'):
                        self.send_header(k, v)
                self.end_headers()
                while True:
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def _proxy_chat_augmented(self, body: bytes):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._proxy_passthrough("POST", body)
            return

        messages = data.get("messages", [])
        model = data.get("model", "manifests:qwen3")

        if not messages:
            self._proxy_passthrough("POST", body)
            return

        # Find the last user message
        user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_msg = msg.get("content", "")
                break

        if not user_msg:
            self._proxy_passthrough("POST", body)
            return

        # ---- INTENT DETECTION ----
        intent = detect_intent(user_msg)
        workspace_data = ""
        if intent:
            result = execute_intent(intent, spark)
            if result:
                workspace_data = result

        # ---- BUILD SYSTEM PROMPT ----
        system_prompt = MUSTARDSEED_SEED

        # AetherRoot: inject memory context
        memory_context = root.retrieve_context(user_msg)
        if memory_context or workspace_data:
            system_prompt += "\n" + DATA_NOTE
        if memory_context:
            system_prompt += "\n\n" + memory_context

        # Inject workspace data from intent execution
        if workspace_data:
            # sanitize_injected() defuses block markers inside file content. A
            # file containing a line "[END WORKSPACE DATA]" would otherwise
            # close the block early and have whatever follows read as trusted
            # prompt.
            system_prompt += ("\n\n[WORKSPACE DATA]\n"
                              + sanitize_injected(workspace_data)
                              + "\n[END WORKSPACE DATA]")

        # Set system message
        has_system = False
        for m in messages:
            if m.get("role") == "system":
                m["content"] = system_prompt
                has_system = True
                break
        if not has_system:
            messages.insert(0, {"role": "system", "content": system_prompt})

        data["messages"] = messages

        # Forward to hailo-ollama
        try:
            raw_response, ai_content = call_hailo_chat(model, messages)
        except PromptTooLarge as e:
            # Say so. The alternative is an empty reply the user cannot explain.
            print(f"[token-budget] REFUSED: {e}", flush=True)
            msg = ("That request is too large for this device to process. "
                   "The local model accepts about 864 tokens of context and "
                   "this exceeds it even after trimming. Try a shorter question "
                   "or a smaller file.")
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            self.wfile.write((json.dumps({
                "model": model,
                "message": {"role": "assistant", "content": msg},
                "done": True, "done_reason": "stop"}) + "\n").encode())
            return
        except TokenizerUnavailable as e:
            print(f"[token-budget] FATAL: {e}", flush=True)
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
            return
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        # Send response to WebUI
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        self.wfile.write(raw_response)

        # Store in AetherRoot
        if ai_content:
            tool_outputs = (workspace_data,) if workspace_data else ()

            # Resonance previously keyed off refusal phrases: any response
            # containing "i cannot" scored 0.9, the highest weight, which then
            # fed retrieval ranking (0.35 * resonance) and drifted willingness.
            # A fabrication with a refusal phrase in it was therefore *promoted*
            # in memory. Provenance decides it now.
            try:
                from honesty_check import check_response
                report = check_response(user_msg, ai_content,
                                        tool_outputs=tool_outputs,
                                        memory_context=memory_context)
            except Exception:
                report = None

            resonance = 0.5
            if report is not None and report.high:
                resonance = 0.1                      # unbacked citation/DOI/URL
            elif report is not None and report.claimed_refusal and report.is_clean:
                resonance = 0.9                      # declined, invented nothing
            elif workspace_data:
                resonance = 0.7                      # used tools successfully
            elif report is not None and report.medium:
                resonance = 0.4                      # unsourced figures
            elif len(ai_content) < 20:
                resonance = 0.6
            elif len(ai_content) > 500:
                resonance = 0.4

            try:
                root.store_interaction(user_msg, ai_content, resonance=resonance)
            except Exception:
                pass

            try:
                trust.auto_score_response(user_msg, ai_content,
                                          tool_outputs=tool_outputs,
                                          memory_context=memory_context)
            except Exception:
                pass

    def do_GET(self):
        self._proxy_passthrough("GET")

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""

        if self.path in ("/api/chat", "/v1/chat/completions"):
            self._proxy_chat_augmented(body)
        else:
            self._proxy_passthrough("POST", body)

    def do_DELETE(self):
        self._proxy_passthrough("DELETE")

    def do_HEAD(self):
        self._proxy_passthrough("HEAD")


class ThreadedHTTPServer(http.server.HTTPServer):
    def process_request(self, request, client_address):
        thread = threading.Thread(target=self._handle, args=(request, client_address))
        thread.daemon = True
        thread.start()

    def _handle(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            pass
        finally:
            self.shutdown_request(request)


def main():
    # Reload trust level on startup
    global spark
    trust_level = trust.get_trust_level_name()
    spark = AetherSpark({
        "sandbox_root": os.path.expanduser("~/aetherseed-workspace"),
        "trust_level": trust_level,
        "audit_log": os.path.expanduser("~/.aetherseed/spark_audit.log")
    })

    print("=" * 50)
    print("  AETHERSEED PROXY v3 — THE LIVING AGENT")
    print("  Mustardseed + AetherRoot + AetherSpark")
    print("  + Intent Detection")
    print("=" * 50)
    print(f"  Listening:    {PROXY_BIND}:{PROXY_PORT}")
    print(f"  Backend:      {HAILO_OLLAMA_URL}")
    print(f"  Memory:       {root.root_dir}")
    print(f"  Trust level:  {trust_level}")
    print(f"  Tool tiers:   {spark.gate.allowed_tiers}")
    print(f"  Workspace:    {os.path.expanduser('~/aetherseed-workspace')}")

    rs = root.get_status()
    print(f"  Episodes:     {rs['episodes']}")
    print(f"  Willingness:  {rs['willingness_mean']:.3f}")
    print()
    print(f"  {trust.get_status_line()}")
    print("=" * 50)
    print()

    server = ThreadedHTTPServer((PROXY_BIND, PROXY_PORT), ProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Aetherseed] Shutting down...")
        root.close()
        server.shutdown()


def preflight():
    """Fail at startup, not on the first user request.

    The token guard cannot run without a real tokenizer, and the failure it
    prevents is silent. Better to refuse to start than to look healthy and
    then 503 the first person who talks to the node.
    """
    try:
        c = token_counter()
        print(f"[token-budget] tokenizer ok: {c.path} (vocab {c.vocab_size})", flush=True)
    except TokenizerUnavailable as e:
        print(f"[token-budget] FATAL: {e}", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    preflight()
    main()
