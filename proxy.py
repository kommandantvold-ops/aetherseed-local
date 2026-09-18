"""
Aetherseed Proxy v3 — The Living Agent
========================================
GUI (127.0.0.1:2077) → Aetherseed Proxy (127.0.0.1:8001) → hailo-ollama (127.0.0.1:8000)

Every hop is loopback. Decided 2026-09-18 (build log, step 13): the GUI runs on
the device itself, so nothing on the LAN needs to reach the proxy and the
bind stays 127.0.0.1. Port 2077 was free and is unregistered in /etc/services.

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
                                sanitize_model_output, first_paragraph,
                                ends_sentence, cut_at_scaffold_marker,
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

# Four bounds on generation, in the order they normally fire. They exist
# because the model does not reliably stop on its own (build log, steps 10 and
# 12). The values were set 2026-09-18 (step 13) on the step-12 measurements;
# Andreas delegated the choice. They are recorded there with the reasoning, so
# change them there too.
#
# 1. STOP_AT_PARAGRAPH - the answer is the first paragraph. Measured 2026-09-18
#    over 40 live responses to eight short spoken-style questions: the honest
#    answer was the first paragraph every time, and everything after the blank
#    line was filler ("(I'll keep my answer short and accurate.)", offers of
#    more, stage directions) - or, twice, a fabricated paper and DOI in the
#    second paragraph behind a correct "I don't have information" in the first.
#    "Oslo." became 36-150 tokens. Cutting at the blank line keeps the answer
#    and drops the tail, and it is the tail that fabricates.
#
# 2. SOFT_STOP_TOKENS - once the answer is this long, end it at the next
#    sentence boundary. Answers in the study were 1-15 tokens (one line),
#    30-40 (two sentences) or 54-61 (five sentences, the last one filler);
#    what ran past that was self-narration. 48 tokens is about thirty-six
#    spoken words, and the stop lands on a full stop, which the hard cap below
#    cannot promise. The boundary is "previous token closed a sentence, this
#    token starts with whitespace", so "3." followed by "14" is not one.
#
# 3. GENERATION_OPTIONS["num_predict"] - the server-side hard cap. THIS BUILD
#    HONOURS IT: measured 2026-09-18, num_predict=20 returned exactly 20 tokens
#    with done_reason "length". Step 10 concluded the server offered no bound at
#    all; that was wrong. It tested max_tokens at the top level of the request
#    - the OpenAI-style key - which /api/chat does ignore (max_tokens=20 gave
#    408 tokens). Ollama's key is options.num_predict, and it works.
#    80 tokens is ~30s at the measured 2.66 tok/s. It fires only when no
#    sentence ends between token 48 and token 80, and it cuts mid-sentence.
#
# 4. MAX_GENERATION_SECONDS - wall-clock backstop. With the cap above it should
#    never fire on a healthy server; it exists for a server that stalls or
#    whose decode rate collapses, which no token count can catch. Expressed in
#    seconds because seconds are what the person waiting experiences.
#
# Sampling is left at the manifest's defaults (temperature 0.4, top_p 0.9,
# top_k 50). Greedy decoding was tried and made the rambling worse: at
# temperature 0 the one-word "Oslo." ran to the 150-token cap on both trials,
# and four of eight prompts hit the cap on both trials (8 of 16 runs) versus
# four of twenty-four runs at the default. Determinism is available
# (temperature 0 is exactly reproducible, 3/3) but it is not a fix for this.
STOP_AT_PARAGRAPH = True
SOFT_STOP_TOKENS = 48
GENERATION_OPTIONS = {"num_predict": 80}
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

    3. Where the answer ends. The model does not stop when it is done: it
       answers, then fills - commentary, offers, stage directions, and in the
       worst measured cases a fabrication behind a correct refusal, or "OK"
       followed by ~110s about being "the goddess of time". Four bounds, see
       the constants above: the first paragraph, a sentence boundary once the
       answer is long enough, the server's num_predict (which this build
       honours - step 10's claim that nothing server-side works was tested
       with the wrong key), and a wall-clock backstop.

    Abandoning a stream mid-generation is safe: measured over three trials,
    closing the socket after 20 chunks left the next request answering in
    2.5-4.8s with no reset and no wedge.
    """
    messages, budget = enforce_budget(token_counter(), messages)
    if budget.trimmed:
        print(f"[token-budget] {budget.summary()}", flush=True)

    data = json.dumps({"model": model, "messages": messages, "stream": True,
                       "options": GENERATION_OPTIONS}).encode()
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
                if (not stopped_because and SOFT_STOP_TOKENS
                        and chunks >= SOFT_STOP_TOKENS
                        and clean[:1] in (" ", "\n") and ends_sentence(ai_content)):
                    # Long enough, the previous token closed a sentence, and
                    # this one opens the next. End here, on a boundary a voice
                    # can end on; this token is not forwarded or stored.
                    stopped_because = "sentence"
                    clean = ""
                ai_content += clean
                if msg.get("content"):
                    chunks += 1          # the server's done message is empty

                # Both remaining stops work on the ACCUMULATED text, not this
                # chunk: "[END MEMORY CONTEXT]" is several tokens and a blank
                # line often arrives split across two, so neither is visible to
                # a per-chunk test.
                if not stopped_because:
                    kept, cut = cut_at_scaffold_marker(ai_content)
                    if cut:
                        excess = len(ai_content) - len(kept)
                        clean = clean[:max(0, len(clean) - excess)]
                        msg["content"] = clean
                        d["message"] = msg
                        ai_content = kept
                        stopped_because = "scaffold-marker"
                if STOP_AT_PARAGRAPH and not stopped_because:
                    kept, cut = first_paragraph(ai_content)
                    if cut:
                        # Forward only what precedes the boundary. Everything
                        # already sent is part of the kept text (plus trailing
                        # whitespace); trim this chunk so nothing after the
                        # blank line reaches the caller or the memory store.
                        excess = len(ai_content) - len(kept)
                        clean = clean[:max(0, len(clean) - excess)]
                        ai_content = kept
                        stopped_because = "paragraph"
                msg["content"] = clean
                d["message"] = msg

            out_lines.append(json.dumps(d))

            if d.get("done"):
                if d.get("done_reason") == "length":
                    print(f"[generation] server cap reached: num_predict="
                          f"{GENERATION_OPTIONS.get('num_predict')} after {chunks} chunks",
                          flush=True)
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
    print(f"  Generation:   options={GENERATION_OPTIONS} "
          f"paragraph_stop={STOP_AT_PARAGRAPH} soft_stop={SOFT_STOP_TOKENS} "
          f"backstop={MAX_GENERATION_SECONDS}s")
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
