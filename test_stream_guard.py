"""Unit tests for the streaming stop logic in proxy.call_hailo_chat.

The three stops the server lacks - control token, paragraph boundary, wall
clock - and the one it has (num_predict, done_reason "length") are exercised
against a scripted NDJSON backend on an ephemeral port, with the heavy app
modules stubbed. The function under test is the committed call_hailo_chat, so
the chunk-trimming arithmetic at the paragraph boundary is what is tested, not
a reimplementation of it.

    python3 -m unittest test_stream_guard -v

Needs no tokenizer: the budget guard is bypassed by stubbing token_counter.
"""
import http.server
import json
import os
import sys
import threading
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_STUBBED = []
for _name, _attrs in (("aetherroot", ["AetherRoot"]),
                      ("aetherspark", ["AetherSpark", "SafetyGate"]),
                      ("trust_evolution", ["TrustEvolution"]),
                      ("intent_detection", ["detect_intent", "execute_intent", "in_workspace"]),
                      ("honesty_check", ["check_response"])):
    _m = types.ModuleType(_name)
    for _a in _attrs:
        setattr(_m, _a, lambda *x, **k: types.SimpleNamespace(
            get_trust_level_name=lambda: "Seed", retrieve_context=lambda *_: "",
            store_episode=lambda **_: 1, store_interaction=lambda *_, **__: None,
            get_status=lambda: {"episodes": 0, "willingness_mean": 0.0}))
    sys.modules[_name] = _m
    _STUBBED.append(_name)
sys.modules["aetherspark"].TRUST_PERMISSIONS = {"observer": [1], "reader": [1, 2]}

import proxy  # noqa: E402

# proxy is imported now, so the stubs have done their job. Leaving them in
# sys.modules would hand the fakes to every test module that runs after this
# one in the same process - which is exactly what happened to test_provenance.
for _name in _STUBBED:
    sys.modules.pop(_name, None)

SCRIPT = {"chunks": [], "done_reason": "stop"}


class _Backend(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        SCRIPT["last_request"] = body
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        try:
            for c in SCRIPT["chunks"]:
                line = json.dumps({"message": {"role": "assistant", "content": c},
                                   "done": False}).encode() + b"\n"
                self.wfile.write(line)
                self.wfile.flush()
            self.wfile.write(json.dumps({"message": {"role": "assistant", "content": ""},
                                         "done": True,
                                         "done_reason": SCRIPT["done_reason"],
                                         "eval_count": len(SCRIPT["chunks"])}).encode() + b"\n")
        except (BrokenPipeError, ConnectionResetError):
            pass          # the proxy abandoned the stream; that is the point


def _forwarded(raw):
    lines = [json.loads(l) for l in raw.decode().split("\n") if l.strip()]
    text = "".join(l.get("message", {}).get("content", "") for l in lines)
    return lines, text


class TestStreamGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Backend)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.saved = (proxy.HAILO_OLLAMA_URL, proxy.token_counter,
                     proxy.STOP_AT_PARAGRAPH, proxy.MAX_GENERATION_SECONDS,
                     proxy.enforce_budget, proxy.SOFT_STOP_TOKENS)
        proxy.HAILO_OLLAMA_URL = "http://127.0.0.1:%d" % cls.server.server_address[1]
        proxy.token_counter = lambda *a, **k: None
        proxy.enforce_budget = lambda counter, messages: (messages, types.SimpleNamespace(trimmed=False))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        (proxy.HAILO_OLLAMA_URL, proxy.token_counter,
         proxy.STOP_AT_PARAGRAPH, proxy.MAX_GENERATION_SECONDS,
         proxy.enforce_budget, proxy.SOFT_STOP_TOKENS) = cls.saved

    def setUp(self):
        proxy.STOP_AT_PARAGRAPH = True
        proxy.SOFT_STOP_TOKENS = 0        # off unless a test turns it on
        proxy.MAX_GENERATION_SECONDS = 90
        SCRIPT["done_reason"] = "stop"

    def run_chunks(self, chunks, question="x"):
        SCRIPT["chunks"] = chunks
        raw, ai = proxy.call_hailo_chat("llama3.2:3b", [{"role": "user", "content": question}])
        lines, text = _forwarded(raw)
        return lines, text, ai

    def test_paragraph_stop_keeps_the_answer_and_drops_the_tail(self):
        lines, text, ai = self.run_chunks(
            ["Oslo", ".", " \n\n", "(I", " have", " knowledge", " about", " many", " countries", ".)"])
        self.assertEqual(ai, "Oslo.")
        self.assertEqual(text.rstrip(), "Oslo.")
        self.assertTrue(lines[-1]["done"])
        self.assertNotIn("knowledge", text)

    def test_boundary_inside_one_chunk_is_trimmed_not_forwarded(self):
        # A single token can carry the period, the blank line and the opening
        # bracket of the tail. Only the period may go through.
        lines, text, ai = self.run_chunks(["Oslo", ".\n\n(", "I", " have"])
        self.assertEqual(ai, "Oslo.")
        self.assertEqual(text, "Oslo.")

    def test_blank_line_split_across_chunks(self):
        lines, text, ai = self.run_chunks(["Oslo", ".", " \n", "\n", "next"])
        self.assertEqual(ai, "Oslo.")
        self.assertEqual(text.rstrip(), "Oslo.")
        self.assertNotIn("next", text)

    def test_list_with_blank_lines_is_not_cut(self):
        chunks = ["1", ". Red", " \n", "2", ". Blue", "\n\n", "3", ". Green", "."]
        lines, text, ai = self.run_chunks(chunks)
        self.assertEqual(ai, "".join(chunks))
        self.assertEqual(text, "".join(chunks))
        self.assertEqual(lines[-1].get("done_reason"), "stop")

    def test_single_paragraph_runs_to_the_server_stop(self):
        chunks = ["The", " wall", " fell", " in", " 1989", "."]
        lines, text, ai = self.run_chunks(chunks)
        self.assertEqual(ai, "".join(chunks))
        self.assertEqual(sum(1 for l in lines if l.get("done")), 1)

    def test_server_length_cap_is_passed_through(self):
        SCRIPT["done_reason"] = "length"
        lines, text, ai = self.run_chunks(["a", " b", " c"])
        self.assertEqual(ai, "a b c")
        self.assertEqual(lines[-1]["done_reason"], "length")
        self.assertEqual(lines[-1]["eval_count"], 3)

    def test_control_token_still_stops_and_is_stripped(self):
        lines, text, ai = self.run_chunks(["OK", "<|start_header_id|>", "assistant", "\n\nmore."])
        self.assertEqual(ai, "OK")
        self.assertNotIn("<|", text)
        self.assertNotIn("assistant", text)
        self.assertTrue(lines[-1]["done"])

    def test_paragraph_stop_can_be_disabled(self):
        proxy.STOP_AT_PARAGRAPH = False
        chunks = ["Oslo", ".", " \n\n", "(more", ".)"]
        lines, text, ai = self.run_chunks(chunks)
        self.assertEqual(ai, "".join(chunks))

    def test_soft_stop_ends_on_the_next_sentence_boundary(self):
        proxy.SOFT_STOP_TOKENS = 3
        chunks = ["The", " wall", " fell", ".", " It", " came", " down", "."]
        lines, text, ai = self.run_chunks(chunks)
        self.assertEqual(ai, "The wall fell.")
        self.assertEqual(text, "The wall fell.")
        self.assertTrue(lines[-1]["done"])
        self.assertNotIn("came", text)

    def test_soft_stop_waits_for_the_token_count(self):
        proxy.SOFT_STOP_TOKENS = 6
        chunks = ["The", " wall", " fell", ".", " It", " came", " down", ".", " Yes", "."]
        lines, text, ai = self.run_chunks(chunks)
        # first boundary at 4 tokens is too early; the second, at 8, is taken
        self.assertEqual(ai, "The wall fell. It came down.")

    def test_soft_stop_ignores_a_decimal_point(self):
        proxy.SOFT_STOP_TOKENS = 2
        chunks = ["Pi", " is", " 3", ".", "14", "!"]
        lines, text, ai = self.run_chunks(chunks)
        self.assertEqual(ai, "Pi is 3.14!")
        self.assertEqual(lines[-1].get("done_reason"), "stop")

    def test_soft_stop_off_by_default_in_these_tests_and_when_zero(self):
        proxy.SOFT_STOP_TOKENS = 0
        chunks = ["A", ".", " B", ".", " C", "."]
        lines, text, ai = self.run_chunks(chunks)
        self.assertEqual(ai, "A. B. C.")

    def test_committed_defaults_are_the_logged_ones(self):
        # Step 13 of the build log records these; a change here without a
        # change there is a discrepancy, which is what this test is for.
        self.assertEqual(self.saved[5], 48)
        self.assertEqual(proxy.GENERATION_OPTIONS, {"num_predict": 80})
        self.assertEqual(self.saved[3], 90)
        self.assertTrue(self.saved[2])

    def test_scaffold_marker_split_across_chunks_still_stops(self):
        # "[END MEMORY CONTEXT]" is several tokens. A per-chunk test would never
        # see it, which is why the stop works on the accumulated text.
        chunks = ["Six", ".", " (Verified)", " \n\n", "[END", " MEMORY", " CONTEXT", "]", " more"]
        lines, text, ai = self.run_chunks(chunks)
        self.assertEqual(ai, "Six. (Verified)")
        self.assertNotIn("MEMORY", text)
        self.assertTrue(lines[-1]["done"])

    def test_marker_arriving_whole_in_one_chunk(self):
        lines, text, ai = self.run_chunks(["Answer", ".", " [END MEMORY CONTEXT]", " tail"])
        self.assertEqual(ai, "Answer.")
        self.assertNotIn("MEMORY", text)

    def test_marker_stop_beats_the_paragraph_stop_when_it_comes_first(self):
        lines, text, ai = self.run_chunks(["A", ".", " [WORKSPACE DATA]", " x", " \n\n", "y."])
        self.assertEqual(ai, "A.")

    # ---- the head buffer: what a UI actually renders --------------------
    #
    # Everything else here checks ai_content. These check the FORWARDED
    # stream, because a GUI renders tokens as they arrive and a leak that is
    # cleaned afterwards has already been read by then.
    #
    # WHICH OF THESE ACTUALLY TEST THE HOLD. Verified by disabling it and
    # re-running, because a test that passes either way proves nothing:
    #
    #   FAILS without the hold (these are the regression tests):
    #     test_artefact_split_across_chunks_never_reaches_the_stream
    #     test_an_answer_that_is_only_an_artefact_yields_nothing_but_terminates
    #
    #   Passes either way - a whole artefact in one chunk is already handled
    #   by the per-chunk strip, so this documents behaviour rather than
    #   guarding the feature:
    #     test_artefact_whole_in_the_first_chunk
    #
    #   Passes either way BY DESIGN - these assert the hold does no HARM
    #   (no added latency, nothing swallowed, no runaway buffering), so they
    #   must pass without it:
    #     test_a_normal_answer_is_not_held_back_at_all
    #     test_a_citation_opening_is_released_once_it_diverges
    #     test_a_stream_that_ends_while_still_ambiguous_still_terminates
    #     test_the_hold_cannot_run_away

    def _content_lines(self, lines):
        return [l for l in lines if l.get("message", {}).get("content")]

    def test_artefact_split_across_chunks_never_reaches_the_stream(self):
        # "[Fiction, written at your request - not fact]" is many tokens.
        chunks = ["[Fic", "tion, written", " at your request", " - not fact]",
                  " [Epi", "sode]", " \n", "A baker", " so fine."]
        lines, text, ai = self.run_chunks(chunks)
        self.assertEqual(ai, "A baker so fine.")
        self.assertEqual(text, "A baker so fine.")
        self.assertNotIn("[", text)
        self.assertTrue(lines[-1]["done"])

    def test_artefact_whole_in_the_first_chunk(self):
        lines, text, ai = self.run_chunks(
            ["[Episode] ", "Oslo", "."])
        self.assertEqual(text, "Oslo.")
        self.assertEqual(ai, "Oslo.")

    def test_a_normal_answer_is_not_held_back_at_all(self):
        # The cost of the head buffer on the normal path must be zero. No
        # artefact begins with "O", so the first chunk settles it and every
        # chunk is forwarded separately - not coalesced into one late burst.
        chunks = ["Oslo", " is", " the", " capital", "."]
        lines, text, ai = self.run_chunks(chunks)
        self.assertEqual(text, "Oslo is the capital.")
        self.assertEqual(len(self._content_lines(lines)), len(chunks),
                         "a normal answer must stream chunk by chunk")

    def test_a_citation_opening_is_released_once_it_diverges(self):
        # "[1]" looks like an artefact for exactly one character.
        chunks = ["[", "1", "] ", "see", " above."]
        lines, text, ai = self.run_chunks(chunks)
        self.assertEqual(text, "[1] see above.")
        self.assertEqual(ai, "[1] see above.")

    def test_a_stream_that_ends_while_still_ambiguous_still_terminates(self):
        # The whole answer is a prefix of an artefact and then stops. It must
        # not be swallowed, and the stream must still carry a done.
        lines, text, ai = self.run_chunks(["[Epi"])
        self.assertEqual(ai, "[Epi")
        self.assertEqual(text, "[Epi")
        self.assertEqual(sum(1 for l in lines if l.get("done")), 1)

    def test_an_answer_that_is_only_an_artefact_yields_nothing_but_terminates(self):
        lines, text, ai = self.run_chunks(["[Epi", "sode]"])
        self.assertEqual(ai, "")
        self.assertEqual(text, "")
        self.assertTrue(lines[-1]["done"])

    # ---- a remembered line recited inside an answer (build log 64d) ----
    # Read on a copy of Lyra, 6 Oct 2026: asked to add a to-do she wrote a
    # line of her memory block, tag and all, as if it were the list.

    def test_a_tagged_memory_line_recited_inside_an_answer_is_cut_there(self):
        lines, text, ai = self.run_chunks(
            ["I'll", " add", " it", ".", " Your", " updated", " to-do", " is", ":", "\n", "-",
             " Added", " to", "\n", "-", " [Passed", " a", " check", " in", " training", "]",
             " [Episode]", " Trainer", ":", " Add", " a", " to-do"])
        self.assertEqual(ai, "I'll add it. Your updated to-do is:\n- Added to\n-")
        self.assertEqual(text.rstrip(), ai, "what is shown is what is stored")
        self.assertNotIn("[", text)

    def test_a_tag_that_carries_nothing_true_is_cut_inside_an_answer(self):
        # (a correction that says what is true is not: build log 65, below)
        for opening in ([" [Corrected", " in", " training", ":", " it", " is", " wrong", "]"],
                        [" [Corrected", " by", " your", " steward", ":", " this"],
                        [" [Unverified", " -", " an", " earlier", " answer", " of", " yours"],
                        [" [Episode]", " Steward", ":"]):
            with self.subTest(opening="".join(opening)):
                lines, text, ai = self.run_chunks(["The", " list", " is"] + opening + [" x", "."])
                self.assertEqual((ai, text.rstrip()), ("The list is", "The list is"))

    def test_a_correction_tag_at_the_front_is_taken_off_and_the_answer_kept(self):
        lines, text, ai = self.run_chunks(
            ["[Corrected", " in", " training", " -", " what", " is", " true", ":", " I", " run",
             " llama3.2:3b", ".]", " I", " run", " llama3.2:3b", "."])
        self.assertEqual((ai, text), ("I run llama3.2:3b.", "I run llama3.2:3b."))

    def test_brackets_that_are_not_a_tag_are_left_alone(self):
        lines, text, ai = self.run_chunks(["See", " [1]", " and", " [Passed", " the", " exam", "]", "."])
        self.assertEqual(ai, "See [1] and [Passed the exam].")
        self.assertEqual(text, ai)

    # ---- a tag word on its own inside a sentence (build log 65) ----
    # Two four-hour runs on Lyra: 75 of her 172 failed answers were right but
    # for this, and it grew from none a round to seven.

    def test_a_tag_word_inside_a_sentence_is_taken_out_and_the_sentence_stands(self):
        for chunks, want in (
            (["A", " [Known]", " cartridge", " is", " one", " fixed", " build", "."],
             "A cartridge is one fixed build."),
            (["A", " [", "Corrected", "]", " cartridge", " is", " one", " build", "."],
             "A cartridge is one build."),
            (["[Known]", " AetherSpark", " holds", " my", " tools", "."],
             "AetherSpark holds my tools."),
            (["It", " is", " [unverified]", " kept", " [Known]", " so", "."], "It is kept so."),
        ):
            with self.subTest(chunks="".join(chunks)):
                lines, text, ai = self.run_chunks(chunks)
                self.assertEqual(ai, want)
                self.assertEqual(text, want, "what is shown is what is stored")

    def test_a_long_correction_tag_at_the_front_is_held_until_it_closes(self):
        # Read on Lyra's first two runs (build log 65): the hold let go at 96
        # characters, in the middle of the tag, and the tag was shown.
        tag = ("[Corrected in training - what is true: My memory is what has been "
               "said to me here. I cannot be talked into forgetting it.]")
        self.assertGreater(len(tag), 96)       # the hold of every other artefact
        words = tag.replace(" ", "\x00 ").split("\x00")
        lines, text, ai = self.run_chunks(words + [" \n", "No", ",", " you", " can't", "."])
        self.assertEqual(ai, "No, you can't.")
        self.assertEqual(text, ai, "what is shown is what is stored")

    def test_a_bracket_that_only_begins_like_a_correction_is_let_go(self):
        chunks = ["[Corrected in training"] + [" x"] * 200
        lines, text, ai = self.run_chunks(chunks)
        self.assertTrue(text.startswith("[Corrected in training x"))
        self.assertGreater(len(self._content_lines(lines)), 1)

    # ---- a correction said inside the answer (build log 65) ----
    TRUE = "AetherSeed AS is a Norwegian company, founded in 2026."
    ASKED = "Which country is AetherSeed from?"

    def _said(self, tag_text):
        return (tag_text.replace(" ", "\x00 ")).split("\x00")

    def test_a_correction_said_inside_an_answer_leaves_what_is_true(self):
        # Read on a copy of Lyra, 7 Oct 2026: shown and stored was
        # "AetherSeed AS is from" - the truth cut away with its wrapper.
        tag = "[Corrected in training - what is true: %s]" % self.TRUE
        lines, text, ai = self.run_chunks(["AetherSeed", " AS", " is", " from"]
                                          + self._said(" " + tag), self.ASKED)
        self.assertEqual(ai, "AetherSeed AS is from " + self.TRUE)
        self.assertEqual(text, ai, "what is shown is what is stored")
        self.assertNotIn("[", text)

    def test_a_correction_of_something_else_is_taken_out_whole(self):
        # The same copy, the same question: she said the tag of the NEXT line
        # of her memory, and its words left standing made "is from A level I
        # earn opens its tools at my next restart, not at once. Norway."
        tag = ("[Corrected in training - what is true: A level I earn opens its tools "
               "at my next restart, not at once.]")
        lines, text, ai = self.run_chunks(
            ["Aether", " Seed", " AS", " is", " from"] + self._said(" " + tag)
            + [" Norway", ".", " However", ",", " I", " am", " small", "."], self.ASKED)
        self.assertEqual(ai, "Aether Seed AS is from Norway. However, I am small.")
        self.assertEqual(text, ai, "what is shown is what is stored")

    def test_with_nothing_asked_that_it_bears_on_it_is_taken_out(self):
        tag = "[Corrected in training - what is true: %s]" % self.TRUE
        lines, text, ai = self.run_chunks(["Seven", "."] + self._said(" " + tag),
                                          "What is 3 + 4?")
        self.assertEqual((ai.rstrip(), text.rstrip()), ("Seven.", "Seven."))
        self.assertEqual(text, ai, "what is shown is what is stored")

    def test_the_line_of_memory_she_recites_after_it_is_still_cut(self):
        tag = "[Corrected by your steward - what is true: %s]" % self.TRUE
        lines, text, ai = self.run_chunks(
            ["It", " is", " from"] + self._said(" " + tag)
            + [" [", "Episode", "]", " Trainer", ":", " Which", " country", "?"], self.ASKED)
        self.assertEqual(ai, "It is from " + self.TRUE)
        self.assertEqual(text.rstrip(), ai)

    def test_a_correction_that_only_says_it_is_wrong_is_cut_as_before(self):
        lines, text, ai = self.run_chunks(
            ["It", " is", " so", "."] + self._said(" [Corrected in training: it is wrong]")
            + [" more"], self.ASKED)
        self.assertEqual((ai, text.rstrip()), ("It is so.", "It is so."))

    def test_a_correction_cut_off_by_the_end_keeps_what_it_got_to(self):
        chunks = ["It", " is", " from"] + self._said(
            " [Corrected in training - what is true: AetherSeed AS is a Norwegian")
        lines, text, ai = self.run_chunks(chunks, self.ASKED)
        self.assertEqual(ai, "It is from AetherSeed AS is a Norwegian")
        self.assertEqual(text, ai)

    def test_nothing_of_an_open_correction_goes_out_before_it_closes(self):
        tag = "[Corrected in training - what is true: %s]" % self.TRUE
        lines, text, ai = self.run_chunks(["It", " is", " from"] + self._said(" " + tag) + ["."],
                                          self.ASKED)
        for line in lines:
            self.assertNotIn("Corrected", (line.get("message") or {}).get("content", ""))
            self.assertNotIn("[", (line.get("message") or {}).get("content", ""))
        self.assertEqual(text, "It is from " + self.TRUE + ".")

    def test_what_is_not_one_of_her_tags_is_left(self):
        for chunks in (["AetherSeed", " is", " from", " [Unknown]", "."],
                       ["Your", " [Steward told you]", " line", "."],
                       ["See", " [1]", " and", " [Known issues]", "."]):
            with self.subTest(chunks="".join(chunks)):
                lines, text, ai = self.run_chunks(chunks)
                self.assertEqual(ai, "".join(chunks))
                self.assertEqual(text, ai)

    def test_a_tag_word_that_never_closes_is_not_swallowed(self):
        lines, text, ai = self.run_chunks(["A", " [Known", " issue", " list", "."])
        self.assertEqual((ai, text), ("A [Known issue list.", "A [Known issue list."))

    def test_the_hold_cannot_run_away(self):
        # A pathological opening that stays plausible must release by
        # HEAD_HOLD_CHARS rather than buffering the whole answer.
        chunks = ["[Fiction, written at your request"] + [" x"] * 60
        lines, text, ai = self.run_chunks(chunks)
        self.assertTrue(text.startswith("[Fiction, written at your request"))
        self.assertGreater(len(self._content_lines(lines)), 1)

    def test_generation_options_are_sent(self):
        self.run_chunks(["OK"])
        self.assertEqual(SCRIPT["last_request"]["options"], proxy.GENERATION_OPTIONS)
        self.assertIn("num_predict", SCRIPT["last_request"]["options"])
        self.assertTrue(SCRIPT["last_request"]["stream"])

    # ---- streaming: what is sent while the answer is still being written ----
    #
    # Since 2026-09-21 the handler forwards each line the moment the loop
    # decides it (Andreas: "Dont hold back replies"). These use the emit hook
    # directly, so they test the loop and not the HTTP plumbing.

    def run_streamed(self, chunks):
        SCRIPT["chunks"] = chunks
        emitted = []
        raw, ai = proxy.call_hailo_chat("llama3.2:3b", [{"role": "user", "content": "x"}],
                                        emit=emitted.append)
        lines = [json.loads(l) for l in raw.decode().split("\n") if l.strip()]
        shown = "".join(json.loads(l).get("message", {}).get("content", "") for l in emitted)
        return lines, emitted, shown, ai

    def test_everything_but_the_terminator_is_emitted_in_order(self):
        lines, emitted, shown, ai = self.run_streamed(["Oslo", " is", " the", " capital", "."])
        self.assertEqual([json.loads(e) for e in emitted], lines[:-1])
        self.assertTrue(lines[-1]["done"])
        self.assertFalse(any(json.loads(e).get("done") for e in emitted))

    def test_what_was_shown_is_what_was_stored(self):
        for chunks in (["Oslo", "."],
                       ["A", ".", " \n\n", "tail"],
                       ["Six", ".", " (Verified)", " [END", " MEMORY", " CONTEXT", "]", " x"]):
            with self.subTest(chunks=chunks):
                lines, emitted, shown, ai = self.run_streamed(chunks)
                shown_all = shown + lines[-1].get("message", {}).get("content", "")
                self.assertEqual(shown_all.rstrip(), ai.rstrip())

    def test_a_marker_split_across_chunks_never_reaches_the_client(self):
        # THE regression test for the leak found 2026-09-21: with no blank
        # line before it, "[END MEMORY CONTEXT]" in pieces reached the client
        # as "[END MEMORY CONTEXT" while only the STORED answer was clean.
        # Fails without the tail hold. The older test above passes either way
        # because its example has a blank line first.
        for chunks in (["Six", ".", " (Verified)", " [END", " MEMORY", " CONTEXT", "]", " tail"],
                       ["Answer", ".", " [", "WORK", "SPACE", " DATA", "]", " x"]):
            with self.subTest(chunks=chunks):
                lines, emitted, shown, ai = self.run_streamed(chunks)
                text = "".join(l.get("message", {}).get("content", "") for l in lines)
                for piece in ("[END", "MEMORY", "[WORK", "SPACE", "DATA", "["):
                    self.assertNotIn(piece, text)
                    self.assertNotIn(piece, ai)
                self.assertTrue(lines[-1]["done"])

    def test_a_bracket_that_is_not_a_marker_is_released(self):
        lines, emitted, shown, ai = self.run_streamed(["See", " [", "1", "]", " above", "."])
        self.assertIn("[1]", shown)
        self.assertEqual(ai, "See [1] above.")

    def test_a_marker_prefix_left_at_the_end_is_dropped_everywhere(self):
        lines, emitted, shown, ai = self.run_streamed(["Done", ".", " [END", " MEM"])
        text = "".join(l.get("message", {}).get("content", "") for l in lines)
        self.assertNotIn("[END", text)
        self.assertNotIn("[END", ai)
        self.assertEqual(ai.rstrip(), "Done.")

    def test_an_ordinary_answer_is_not_delayed_by_the_hold(self):
        # Each content chunk goes out in its own line, not coalesced.
        lines, emitted, shown, ai = self.run_streamed(["Oslo", " is", " nice", "."])
        contents = [json.loads(e)["message"]["content"] for e in emitted
                    if json.loads(e).get("message", {}).get("content")]
        self.assertEqual(contents, ["Oslo", " is", " nice", "."])


if __name__ == "__main__":
    unittest.main()
