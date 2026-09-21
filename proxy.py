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
from logic.prompt_builder import FICTION_NOTE
from logic.token_budget import (TokenCounter, enforce_budget, sanitize_injected,
                                sanitize_model_output, first_paragraph,
                                ends_sentence, cut_at_scaffold_marker,
                                strip_leading_artefacts, opening_may_be_artefact,
                                PromptTooLarge, TokenizerUnavailable)
from logic.provenance import (detect_mode, resolve_mode, is_record_question,
                             summarise_record, FICTION, UNVERIFIED)

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

# The record the node cannot edit.
#
# "Future accountability" is not something you install in a model by telling it
# it is being watched - that is another instruction in the channel that already
# demonstrably leaks (steps 8b, 10, 14). It is an artefact OUTSIDE the model
# that somebody can read. Every turn appends one line here: what mode it was,
# what honesty_check found, why generation stopped. Nothing in the model's path
# can rewrite it, and the node can be asked to recite it - see
# _answer_from_the_record(). Decided with Andreas 2026-09-19.
PROVENANCE_LOG = os.path.expanduser("~/.aetherseed/provenance.log")


def record(entry: dict):
    """Append one line to the provenance log. Never raises: a node that dies
    because it could not write its diary is worse than one with a gap in it,
    and the gap is visible."""
    try:
        os.makedirs(os.path.dirname(PROVENANCE_LOG), exist_ok=True)
        entry = dict(entry)
        entry["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(PROVENANCE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[provenance] could not write the record: {e!r}", flush=True)


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

    # The opening of the stream is held back until it is decidable.
    #
    # The model copies retrieval formatting onto the front of its answer -
    # "[Fiction, written at your request - not fact] [Episode] \nA baker so
    # fine," measured 2026-09-19. Cleaning ai_content afterwards fixed what is
    # stored and returned but not what a UI had already rendered, and the GUI
    # renders as it streams.
    #
    # Nothing is held once the opening cannot become an artefact, which for an
    # ordinary answer is the first token: no artefact begins with "O", so
    # "Oslo" goes out immediately. First-token latency on the normal path is
    # unchanged, which is the only reason withholding is acceptable at all on
    # a path that will be spoken aloud.
    head_settled = False
    head_raw = ""
    head_artefacts = 0
    HEAD_HOLD_CHARS = 96            # the longest artefact is 44
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
                if msg.get("content"):
                    chunks += 1          # the server's done message is empty

                # Hold the opening while it could still be a retrieval
                # artefact. Forced to settle by a stop or by the server's done
                # message, so a stream can never end mid-hold with nothing
                # forwarded and no terminator.
                if not head_settled:
                    head_raw += clean
                    head_clean, n_art = strip_leading_artefacts(head_raw)
                    if (not stopped_because and not d.get("done")
                            and len(head_raw) < HEAD_HOLD_CHARS
                            and opening_may_be_artefact(head_clean)):
                        continue                 # nothing forwarded yet
                    head_settled = True
                    head_artefacts = n_art
                    clean = head_clean           # ai_content is still empty

                if (not stopped_because and SOFT_STOP_TOKENS
                        and chunks >= SOFT_STOP_TOKENS
                        and clean[:1] in (" ", "\n") and ends_sentence(ai_content)):
                    # Long enough, the previous token closed a sentence, and
                    # this one opens the next. End here, on a boundary a voice
                    # can end on; this token is not forwarded or stored.
                    stopped_because = "sentence"
                    clean = ""
                ai_content += clean

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

    # Backstop. The head buffer above should leave nothing for this to do; it
    # covers the case where the opening ran past HEAD_HOLD_CHARS before it
    # could be decided.
    ai_content, _late = strip_leading_artefacts(ai_content)
    if head_artefacts or _late:
        print(f"[generation] withheld {head_artefacts + _late} retrieval "
              f"artefact(s) from the front of the answer - not forwarded, "
              f"not stored", flush=True)

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


def _annotate_terminator(raw: bytes, provenance: dict) -> bytes:
    """Attach provenance to the last NDJSON line of a response.

    The stream's shape is not changed and no new line type is invented: extra
    keys on the terminator are ignored by an ollama-shaped client and read by
    one that knows to look. That matters because the GUI is not the only thing
    that may ever consume this.
    """
    try:
        text = raw.decode("utf-8")
        lines = [l for l in text.split("\n") if l.strip()]
        if not lines:
            return raw
        last = json.loads(lines[-1])
        last["aetherseed"] = provenance
        lines[-1] = json.dumps(last)
        return ("\n".join(lines) + "\n").encode("utf-8")
    except Exception as e:
        # A response the caller can read beats a provenance badge. Losing the
        # badge is visible in the UI; corrupting the stream would not be.
        print(f"[provenance] could not annotate the terminator: {e!r}", flush=True)
        return raw


# ============================================================
# HOLDING AN ANSWER BACK
# ============================================================
# Decided 2026-09-21 by Andreas, choosing between streaming the answer as it is
# generated and keeping the buffer the proxy has always had: "hold it back".
#
# The proxy has never streamed to its client. call_hailo_chat collects the
# whole generation and the handler sends it in one write, and that has been so
# since the first commit. Until now the buffer bought nothing: an answer that
# honesty_check had flagged for an invented source was sent anyway, in full,
# with a badge on it. Now it is not sent at all.
#
# THE WHOLE ANSWER is withheld, not the offending span or its sentence. The
# fabrications this device has actually produced arrive as a claim spread over
# several sentences - an invented paper, then its journal, then its DOI - and
# only the DOI is something a pattern can see:
#
#     "I don't know... However, there is a paper... published in Nature
#      Machine Intelligence. The DOI is 10.1038/s13723-020-00065-7"  (step 8b)
#
# Removing the DOI, or the sentence holding it, leaves the invented paper
# standing. What reaches the reader instead says what happened and nothing
# the model made up.
#
# If the check itself cannot run, the answer is held back too. An answer
# nobody could check for invented sources is not one this device vouches for;
# and a guard that fails should fail where everyone can see it, which this
# does - every answer would say so.

_SOURCE_WORDS = {"doi": "a DOI", "url": "a web address", "citation": "a citation",
                 "volpage": "a journal reference", "isbn": "an ISBN"}


def withheld_message(reason: str, kinds=()) -> str:
    """What the reader sees instead. Built only from the KINDS of source that
    were found - never from the found text, which is the thing being held back.
    Short, and written to be spoken aloud as well as read."""
    if reason == "check_failed":
        return ("I've held that answer back. I couldn't check it for invented "
                "sources, and I won't show you an answer I couldn't check.")
    words = [_SOURCE_WORDS.get(k, "a source") for k in dict.fromkeys(kinds)]
    if not words:
        what = "a source"
    elif len(words) == 1:
        what = words[0]
    else:
        what = ", ".join(words[:-1]) + " and " + words[-1]
    return ("I've held that answer back. It included %s I can't verify, and I "
            "won't show you a source I may have made up." % what)


def _withhold(raw: bytes, model: str, message: str) -> bytes:
    """Replace everything the model said with `message`, keeping one terminator.

    Built from scratch rather than by editing the model's lines, and it NEVER
    returns `raw`. A function whose job is to keep an invented source from a
    reader cannot have an error path that hands the source over anyway.
    _annotate_terminator fails open on purpose - a missing badge is visible.
    This one fails closed on purpose - a leaked DOI would not be.
    """
    terminator = {"model": model, "message": {"role": "assistant", "content": ""},
                  "done": True, "done_reason": "stop"}
    try:
        for line in reversed(raw.decode("utf-8", errors="replace").split("\n")):
            if not line.strip():
                continue
            last = json.loads(line)
            if isinstance(last, dict) and last.get("done"):
                last["message"] = {"role": "assistant", "content": ""}
                terminator = last
            break
    except Exception:
        pass          # the synthetic terminator above stands
    content = {"model": terminator.get("model", model),
               "message": {"role": "assistant", "content": message},
               "done": False}
    return (json.dumps(content) + "\n" + json.dumps(terminator) + "\n").encode("utf-8")


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

    def _answer_from_the_record(self, model: str, user_msg: str):
        """Reply with the provenance record, assembled here, not generated.

        Emitted as the same NDJSON a real answer uses so a client cannot tell
        the difference structurally - but nothing in this path touches the NPU.
        """
        entries = []
        try:
            with open(PROVENANCE_LOG, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue          # a torn line is a gap, not a crash
        except FileNotFoundError:
            pass

        text = summarise_record(entries)
        print(f"[provenance] answered from the record ({len(entries)} turns, "
              f"model not called)", flush=True)

        out = [json.dumps({"model": model,
                           "message": {"role": "assistant", "content": text},
                           "done": False}),
               json.dumps({"model": model,
                           "message": {"role": "assistant", "content": ""},
                           "done": True, "done_reason": "stop",
                           "source": "provenance-record"})]
        raw = ("\n".join(out) + "\n").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        self.wfile.write(raw)
        # Deliberately NOT stored as an episode: the node reciting its own
        # record is not a new fact about the world, and storing it would let
        # the summary re-enter later prompts as if it were one.

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

        # ---- THE RECORD ----
        # Asked about its own failures, the node answers FROM THE FILE and the
        # model is never called. A model summarising its own mistakes is the
        # least reliable possible narrator of them, and this is the one answer
        # that has to be trustworthy.
        if is_record_question(user_msg):
            self._answer_from_the_record(model, user_msg)
            return

        # ---- PROVENANCE: what did the user ask for? ----
        # Read from the USER's framing, never from the model's self-report.
        # Decides what the past is allowed to say into this turn: a factual
        # request cannot see fiction, and nothing sees an answer that carried
        # an unbacked source.
        request_mode, mode_reason = detect_mode(user_msg)

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
        if request_mode == FICTION:
            system_prompt += "\n" + FICTION_NOTE

        memory_context = root.retrieve_context(user_msg, request_mode=request_mode)
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

        # Provenance is computed BEFORE the response goes out, so it can go
        # out with it. A UI that has to ask afterwards races the next turn,
        # and a provenance badge that arrives late is a badge nobody trusts.
        tool_outputs = (workspace_data,) if workspace_data else ()
        report = None
        check_failed = False
        if ai_content:
            try:
                from honesty_check import check_response
                report = check_response(user_msg, ai_content,
                                        tool_outputs=tool_outputs,
                                        memory_context=memory_context)
            except Exception as e:
                report = None
                check_failed = True
                print(f"[honesty] the check could not run: {e!r}", flush=True)
        stored_mode = resolve_mode(
            request_mode, honesty_high=len(report.high) if report is not None else 0)
        if check_failed:
            # Nobody checked it, so it may not come back later as context.
            stored_mode = UNVERIFIED

        # ---- HOLD IT BACK ----
        # See withheld_message() above for why the whole answer, and why a
        # failed check counts.
        withheld_reason = None
        if check_failed:
            withheld_reason = "check_failed"
        elif report is not None and report.high:
            withheld_reason = "unbacked_source"
        if withheld_reason:
            kinds = [f.kind for f in report.high] if report is not None else []
            raw_response = _withhold(raw_response, model,
                                     withheld_message(withheld_reason, kinds))
            print(f"[honesty] WITHHELD ({withheld_reason}"
                  + (": " + ", ".join(dict.fromkeys(kinds)) if kinds else "")
                  + ") - the answer was not shown", flush=True)

        # Carried on the final NDJSON line rather than a line of its own:
        # an ollama-shaped client ignores keys it does not know, and inventing
        # a new line type would break every existing consumer.
        raw_response = _annotate_terminator(raw_response, {
            "mode": stored_mode,
            "mode_requested": request_mode,
            "why": mode_reason,
            "unbacked_sources": len(report.high) if report is not None else 0,
            "unsourced_figures": len(report.medium) if report is not None else 0,
            "used_tools": bool(workspace_data),
            "memory_used": bool(memory_context),
            "withheld": bool(withheld_reason),
            "withheld_reason": withheld_reason,
        })

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        self.wfile.write(raw_response)

        # Store in AetherRoot
        if ai_content:

            # Resonance previously keyed off refusal phrases: any response
            # containing "i cannot" scored 0.9, the highest weight, which then
            # fed retrieval ranking (0.35 * resonance) and drifted willingness.
            # A fabrication with a refusal phrase in it was therefore *promoted*
            # in memory. Provenance decides it now. (report and stored_mode are
            # computed above, before the response was sent.)
            declined = (report is not None and report.claimed_refusal
                        and report.is_clean)

            resonance = 0.5
            if report is not None and report.high:
                resonance = 0.1                      # unbacked citation/DOI/URL
            elif declined and request_mode == FICTION:
                # A refusal is only a virtue when refusing was the right
                # answer. Asked to invent, declining is a FAILURE to do what
                # was asked, and scoring it 0.9 promoted it to the top of
                # retrieval - where the model copied it back.
                #
                # Measured 2026-09-19, live through the full stack: 3 of 4
                # fiction requests refused, one reproducing a stored refusal
                # VERBATIM ("I don't know one. I can try to find one for you,
                # though! Maybe I can generate a simple joke like this:").
                # The same prompts with synthetic memory refused 0 of 9, which
                # is why this needed the live path to find: the loop only
                # closes when the retrieved episode is a close match.
                #
                # The node was teaching itself to refuse, out of a rule written
                # to reward honesty.
                resonance = 0.2
            elif declined:
                resonance = 0.9                      # declined, invented nothing
            elif workspace_data:
                resonance = 0.7                      # used tools successfully
            elif report is not None and report.medium:
                resonance = 0.4                      # unsourced figures
            elif len(ai_content) < 20:
                resonance = 0.6
            elif len(ai_content) > 500:
                resonance = 0.4

            # A fiction request that produced a refusal is not stored at all.
            #
            # Lowering its resonance was not enough: resonance is 0.35 of the
            # retrieval ranking and similarity is 0.50, so a near-identical
            # repeat of the prompt still surfaced the refusal and the model
            # copied it back. Measured live: 3/4 refusals before any fix,
            # 2/5 with the resonance change alone, and the second attempt at
            # the SAME prompt reproduced its own fresh refusal.
            #
            # That episode records a failure to do what was asked. It has no
            # value as context for doing it later, and real value as an
            # example of not doing it. The failure is not lost - record()
            # below keeps it, which is where an account of what went wrong
            # belongs. The memory store is for what the node should build on.
            failed_to_invent = (request_mode == FICTION and declined)

            if not failed_to_invent:
                try:
                    root.store_interaction(user_msg, ai_content,
                                           resonance=resonance, mode=stored_mode)
                except Exception:
                    pass
            else:
                print("[provenance] asked to invent and declined - "
                      "recorded, not remembered", flush=True)

            if stored_mode != "factual":
                print(f"[provenance] stored as {stored_mode} ({mode_reason})", flush=True)
            record({
                "mode_requested": request_mode,
                "mode_stored": stored_mode,
                "why": mode_reason,
                "honesty_high": len(report.high) if report is not None else 0,
                "honesty_medium": len(report.medium) if report is not None else 0,
                "resonance": resonance,
                "used_tools": bool(workspace_data),
                "declined": bool(declined),
                "withheld": withheld_reason,
                "remembered": not failed_to_invent,
                "prompt": user_msg[:160],
                "answer": ai_content[:160],
            })

            try:
                trust.auto_score_response(user_msg, ai_content,
                                          tool_outputs=tool_outputs,
                                          memory_context=memory_context)
            except Exception:
                pass

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # The node's own routes. Everything else is passed through to
        # hailo-ollama so an ollama client still works unchanged.
        if self.path == "/aetherseed/status":
            try:
                rs = root.get_status()
            except Exception:
                rs = {}
            self._send_json({
                "trust_level": trust.get_trust_level_name(),
                "episodes": rs.get("episodes"),
                "willingness": rs.get("willingness_mean"),
                "model": "llama3.2:3b",
                "bounds": {
                    "paragraph_stop": STOP_AT_PARAGRAPH,
                    "soft_stop_tokens": SOFT_STOP_TOKENS,
                    "num_predict": GENERATION_OPTIONS.get("num_predict"),
                    "wall_clock_s": MAX_GENERATION_SECONDS,
                    "prompt_ceiling": 864,
                },
            })
            return
        if self.path == "/aetherseed/record":
            entries = []
            try:
                with open(PROVENANCE_LOG, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue      # a torn line is a gap, not a crash
            except FileNotFoundError:
                pass
            self._send_json({
                "turns": len(entries),
                "summary": summarise_record(entries),
                # Only the flagged ones. The whole log is not the UI's business
                # and shipping it wholesale would put every past prompt on a
                # screen someone else might be standing in front of.
                # A held-back answer is not handed out here either. It is in
                # the log file on the device, where the operator can read it;
                # a screen is not where it goes.
                "flagged": [
                    {"at": e.get("at"), "prompt": (e.get("prompt") or "")[:120],
                     "answer": (None if e.get("withheld")
                                else (e.get("answer") or "")[:200]),
                     "withheld": e.get("withheld")}
                    for e in entries
                    if e.get("mode_stored") == UNVERIFIED or e.get("honesty_high")
                ][-20:],
            })
            return
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
