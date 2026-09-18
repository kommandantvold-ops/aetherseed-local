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
PROXY_PORT = 8001

# The charter lives in exactly one place now. proxy.py previously kept its
# own copy, which had already drifted from prompt_builder's (223 vs 210
# tokens, different final paragraph).
from logic.prompt_builder import MUSTARDSEED as MUSTARDSEED_SEED
from logic.prompt_builder import DATA_NOTE
from logic.token_budget import (TokenCounter, enforce_budget, sanitize_injected,
                                PromptTooLarge, TokenizerUnavailable)

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

def call_hailo_chat(model: str, messages: list) -> tuple:
    """Send chat request to hailo-ollama. Returns (raw_bytes, ai_content).

    Every request leaves through here, so the token guard lives here rather
    than in a prompt builder. The NPU accepts at most 864 prompt tokens and
    fails SILENTLY past that on a streaming call - HTTP 200 with an empty
    body - so an unguarded over-length prompt looks exactly like a successful
    empty answer. Raises PromptTooLarge instead of sending one.
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
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()

    ai_content = ""
    for line in raw.decode("utf-8", errors="replace").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            token_data = json.loads(line)
            msg = token_data.get("message", {})
            if msg.get("role") == "assistant":
                ai_content += msg.get("content", "")
        except json.JSONDecodeError:
            continue

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
    print(f"  Listening:    port {PROXY_PORT}")
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

    server = ThreadedHTTPServer(("0.0.0.0", PROXY_PORT), ProxyHandler)
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
