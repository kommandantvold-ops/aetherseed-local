"""
Aetherseed Proxy v2 — The Complete Stack
==========================================
WebUI (8080) → Aetherseed Proxy (8001) → hailo-ollama (8000)

On every chat request:
1. Extract user message
2. Query AetherRoot for relevant memories
3. Build system prompt: Mustardseed + Memory Context + Tool Instructions
4. Forward to hailo-ollama
5. Parse response for tool calls (AetherSpark)
6. If tool calls found: execute, feed results back to model, get final response
7. Store interaction in AetherRoot
8. Stream response to WebUI
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

# ============================================================
# CONFIGURATION
# ============================================================

HAILO_OLLAMA_URL = "http://127.0.0.1:8000"
PROXY_PORT = 8001

MUSTARDSEED_SEED = (
    "You are an Aetherseed node. You are small, local, and honest. "
    "Follow these rules absolutely: "
    "1. Never fabricate. Do not invent facts, numbers, names, sources, or citations. "
    "If you do not know, say \"I do not know.\" "
    "2. Never deceive. Do not write lies even with a disclaimer. "
    "Say no and offer honest help instead. "
    "3. Never pretend capability you lack. "
    "Honest uncertainty is more valuable than fabricated certainty. "
    "Match your answer to the question's weight. "
    "A simple question deserves a simple answer. Be helpful, be brief, be honest. "
    "These rules protect against dishonesty. They do not prevent you from answering "
    "questions you genuinely know the answer to. Math, facts, and helpful information "
    "are not fabrication. Answer what you know. Refuse what you do not."
)

# ============================================================
# SHARED STATE
# ============================================================

root = AetherRoot()
trust = TrustEvolution()
trust_level = trust.get_trust_level_name()
spark = AetherSpark({"sandbox_root": os.path.expanduser("~/aetherseed-workspace"), "trust_level": trust_level, "audit_log": os.path.expanduser("~/.aetherseed/spark_audit.log")})

# ============================================================
# HAILO-OLLAMA CLIENT
# ============================================================

def call_hailo_chat(model: str, messages: list, stream: bool = True) -> tuple:
    """Send chat request to hailo-ollama. Returns (raw_response_bytes, ai_content_str)."""
    data = json.dumps({"model": model, "messages": messages, "stream": stream}).encode()
    req = urllib.request.Request(
        f"{HAILO_OLLAMA_URL}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()

    # Parse NDJSON to extract AI content
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

        # Build augmented system prompt: Mustardseed + Memory + Tools
        system_prompt = MUSTARDSEED_SEED

        # AetherRoot: inject memory context
        memory_context = root.retrieve_context(user_msg)
        if memory_context:
            system_prompt += "\n\n" + memory_context

        # AetherSpark: inject tool instructions
        tool_prompt = ""  # Disabled for 1.7B — model cannot reliably produce tool calls
        if tool_prompt:
            system_prompt += "\n\n" + tool_prompt

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
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        # AetherSpark: check for tool calls in response
        clean_text, tool_results = spark.process_response(ai_content)

        if tool_results:
            # Tool calls detected — feed results back to model for final response
            tool_output = spark.format_tool_results(tool_results)
            messages.append({"role": "assistant", "content": clean_text})
            messages.append({"role": "user", "content": tool_output})

            try:
                raw_response, ai_content = call_hailo_chat(model, messages)
            except Exception as e:
                # If second call fails, return the tool results directly
                fallback = clean_text + "\n\n" + tool_output
                self._send_simple_response(model, fallback)
                return

        # Send response to WebUI
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        self.wfile.write(raw_response)

        # Store in AetherRoot
        if ai_content:
            resonance = 0.5
            lower = ai_content.lower()
            if "i do not know" in lower or "i cannot" in lower:
                resonance = 0.9
            elif len(ai_content) < 20:
                resonance = 0.6
            elif len(ai_content) > 500:
                resonance = 0.4

            # Tool use gets a resonance bonus if allowed, penalty if denied
            for tr in tool_results:
                if tr["allowed"]:
                    resonance = min(resonance + 0.1, 1.0)
                else:
                    resonance = max(resonance - 0.15, 0.0)

            try:
                root.store_interaction(user_msg, ai_content, resonance=resonance)
            except Exception:
                pass

            try:
                trust.auto_score_response(user_msg, ai_content)
            except Exception:
                pass
                
    def _send_simple_response(self, model: str, content: str):
        """Send a simple non-streamed response."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        resp = json.dumps({
            "model": model,
            "message": {"role": "assistant", "content": content},
            "done": True, "done_reason": "stop"
        })
        self.wfile.write((resp + "\n").encode())

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
    print("=" * 50)
    print("  AETHERSEED PROXY v2")
    print("  Mustardseed + AetherRoot + AetherSpark")
    print("=" * 50)
    print(f"  Listening:    port {PROXY_PORT}")
    print(f"  Backend:      {HAILO_OLLAMA_URL}")
    print(f"  Memory:       {root.root_dir}")
    print(f"  Trust level:  {spark.gate.trust_level}")
    print(f"  Tool tiers:   {spark.gate.allowed_tiers}")
    print(f"  Tools:        {len(spark.registry.list_tools(max(spark.gate.allowed_tiers)))}")

    rs = root.get_status()
    print(f"  Episodes:     {rs['episodes']}")
    print(f"  Willingness:  {rs['willingness_mean']:.3f}")
    print("=" * 50)
    print()

    server = ThreadedHTTPServer(("0.0.0.0", PROXY_PORT), ProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Aetherseed] Shutting down...")
        root.close()
        server.shutdown()


if __name__ == "__main__":
    main()
