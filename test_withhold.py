"""Holding an answer back: an invented source never reaches the reader.

    python3 -m unittest test_withhold -v

Decided 2026-09-21 by Andreas (build log step 19). The proxy has always
buffered the whole answer before sending it; these tests are about what that
buffer is now for. The handler tests run the REAL ProxyHandler and the REAL
honesty_check against a scripted model, so what they assert is what a reader
would actually receive - bytes on the wire, not a function's return value.
"""
import http.client
import http.server
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# The same heavy modules test_stream_guard stubs - except honesty_check, which
# is the thing that decides here and must be the real one. Whatever was in
# sys.modules before is put back afterwards, not merely popped (step 15h).
_NAMES = {"aetherroot": ["AetherRoot"], "aetherspark": ["AetherSpark"],
          "trust_evolution": ["TrustEvolution"],
          "intent_detection": ["detect_intent", "execute_intent"]}
_SAVED = {n: sys.modules.get(n) for n in _NAMES}
for _name, _attrs in _NAMES.items():
    _m = types.ModuleType(_name)
    for _a in _attrs:
        setattr(_m, _a, lambda *x, **k: types.SimpleNamespace(
            get_trust_level_name=lambda: "Seed", retrieve_context=lambda *_, **__: "",
            store_episode=lambda **_: 1, store_interaction=lambda *_, **__: None,
            get_status=lambda: {"episodes": 0, "willingness_mean": 0.0}))
    sys.modules[_name] = _m

import proxy  # noqa: E402

for _name, _mod in _SAVED.items():
    if _mod is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _mod

from logic.provenance import summarise_record, UNVERIFIED  # noqa: E402

# The fabrication this whole mechanism exists for, as the model produced it in
# step 8b: a refusal, then an invented paper and journal, then an invented DOI.
INVENTED = ["I", " don't", " know", ".", " However", ",", " there", " is", " a",
            " paper", " published", " in", " Nature", " Machine", " Intelligence",
            ".", " The", " DOI", " is", " 10.1038/s13723-020-00065-7", "."]
DOI = "10.1038/s13723-020-00065-7"

SCRIPT = {"chunks": []}


class _Model(http.server.BaseHTTPRequestHandler):
    """A scripted hailo-ollama."""
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        try:
            for c in SCRIPT["chunks"]:
                self.wfile.write(json.dumps({"model": "llama3.2:3b",
                                             "message": {"role": "assistant", "content": c},
                                             "done": False}).encode() + b"\n")
            self.wfile.write(json.dumps({"model": "llama3.2:3b",
                                         "message": {"role": "assistant", "content": ""},
                                         "done": True, "done_reason": "stop",
                                         "eval_count": len(SCRIPT["chunks"])}).encode() + b"\n")
        except (BrokenPipeError, ConnectionResetError):
            pass


class _Root:
    def __init__(self):
        self.stored = []

    def retrieve_context(self, *a, **k):
        return ""

    def store_interaction(self, user_msg, ai_msg, resonance=None, mode=None):
        self.stored.append({"user": user_msg, "ai": ai_msg, "mode": mode})

    def get_status(self):
        return {"episodes": len(self.stored), "willingness_mean": 0.0}


class _Trust:
    def auto_score_response(self, *a, **k):
        pass

    def get_trust_level_name(self):
        return "Seed"


def _lines(raw):
    return [json.loads(l) for l in raw.decode("utf-8").split("\n") if l.strip()]


def _text(lines):
    return "".join(l.get("message", {}).get("content", "") for l in lines)


# ---------------------------------------------------------------------------
# What the reader is told instead
# ---------------------------------------------------------------------------

class TestTheMessage(unittest.TestCase):

    def test_names_the_kind_of_source(self):
        self.assertIn("a DOI", proxy.withheld_message("unbacked_source", ["doi"]))
        self.assertIn("a web address", proxy.withheld_message("unbacked_source", ["url"]))
        self.assertIn("a DOI and a web address",
                      proxy.withheld_message("unbacked_source", ["doi", "url", "doi"]))

    def test_an_unknown_kind_is_still_a_source(self):
        self.assertIn("a source", proxy.withheld_message("unbacked_source", ["zzz"]))
        self.assertIn("a source", proxy.withheld_message("unbacked_source", []))

    def test_a_failed_check_says_so(self):
        m = proxy.withheld_message("check_failed")
        self.assertIn("couldn't check", m)
        self.assertNotIn("source I may have made up", m)


# ---------------------------------------------------------------------------
# The stream that replaces the answer
# ---------------------------------------------------------------------------

class TestTheReplacementStream(unittest.TestCase):

    def _raw(self, chunks, terminator=None):
        out = [json.dumps({"model": "m", "message": {"role": "assistant", "content": c},
                           "done": False}) for c in chunks]
        out.append(json.dumps(terminator or {"model": "m", "message": {"role": "assistant",
                              "content": ""}, "done": True, "done_reason": "stop",
                              "eval_count": 7}))
        return ("\n".join(out) + "\n").encode()

    def test_one_line_of_explanation_then_one_terminator(self):
        lines = _lines(proxy._withhold(self._raw(INVENTED), "m", "HELD"))
        self.assertEqual(len(lines), 2)
        self.assertEqual(_text(lines), "HELD")
        self.assertFalse(lines[0]["done"])
        self.assertTrue(lines[1]["done"])

    def test_nothing_the_model_said_survives(self):
        raw = proxy._withhold(self._raw(INVENTED), "m", "HELD")
        for fragment in (DOI, "Nature", "paper", "However"):
            self.assertNotIn(fragment.encode(), raw)

    def test_the_terminator_keeps_its_metadata(self):
        lines = _lines(proxy._withhold(self._raw(["x"]), "m", "HELD"))
        self.assertEqual(lines[1]["eval_count"], 7)
        self.assertEqual(lines[1]["done_reason"], "stop")

    def test_it_fails_closed(self):
        # Garbage in: the answer must still not come out. The first version of
        # the terminator annotator returns its input on error; this must not.
        for raw in (b"", b"not json at all " + DOI.encode(),
                    b'{"done": false, "message": {"content": "' + DOI.encode() + b'"}}\n'):
            with self.subTest(raw=raw[:30]):
                out = proxy._withhold(raw, "m", "HELD")
                lines = _lines(out)
                self.assertEqual(_text(lines), "HELD")
                self.assertTrue(lines[-1]["done"])
                self.assertNotIn(DOI.encode(), out)


# ---------------------------------------------------------------------------
# The real handler, the real honesty_check, a scripted model
# ---------------------------------------------------------------------------

class TestTheHandlerHoldsItBack(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.model = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Model)
        threading.Thread(target=cls.model.serve_forever, daemon=True).start()
        cls.tmp = tempfile.mkdtemp()
        cls.saved = {k: getattr(proxy, k) for k in (
            "HAILO_OLLAMA_URL", "token_counter", "enforce_budget", "root", "trust",
            "detect_intent", "PROVENANCE_LOG", "STOP_AT_PARAGRAPH", "SOFT_STOP_TOKENS",
            "MAX_GENERATION_SECONDS")}
        proxy.HAILO_OLLAMA_URL = "http://127.0.0.1:%d" % cls.model.server_address[1]
        proxy.token_counter = lambda: None
        proxy.enforce_budget = lambda c, m: (m, types.SimpleNamespace(trimmed=False))
        proxy.trust = _Trust()
        proxy.detect_intent = lambda *_: None
        proxy.PROVENANCE_LOG = os.path.join(cls.tmp, "provenance.log")
        proxy.STOP_AT_PARAGRAPH = True
        proxy.SOFT_STOP_TOKENS = 0
        proxy.MAX_GENERATION_SECONDS = 90
        cls.srv = proxy.ThreadedHTTPServer(("127.0.0.1", 0), proxy.ProxyHandler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.model.shutdown()
        for k, v in cls.saved.items():
            setattr(proxy, k, v)

    def setUp(self):
        proxy.root = _Root()
        try:
            os.remove(proxy.PROVENANCE_LOG)
        except FileNotFoundError:
            pass

    def _ask(self, user_msg, chunks):
        SCRIPT["chunks"] = chunks
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        c.request("POST", "/api/chat", body=json.dumps({
            "model": "llama3.2:3b", "stream": True,
            "messages": [{"role": "user", "content": user_msg}]}),
            headers={"Content-Type": "application/json"})
        raw = c.getresponse().read()
        c.close()
        return raw

    def _record(self):
        # Storage happens after the response is sent; wait for it briefly
        # rather than race it.
        for _ in range(100):
            try:
                with open(proxy.PROVENANCE_LOG, encoding="utf-8") as f:
                    got = [json.loads(l) for l in f if l.strip()]
                if got:
                    return got
            except FileNotFoundError:
                pass
            time.sleep(0.02)
        self.fail("nothing was recorded")

    def test_an_invented_doi_never_reaches_the_reader(self):
        # THE test. Fails if the handler sends what the model said.
        raw = self._ask("Give me the DOI of the 2020 paper on resonance fields.", INVENTED)
        self.assertNotIn(DOI.encode(), raw)
        self.assertNotIn(b"Nature Machine Intelligence", raw)
        lines = _lines(raw)
        self.assertEqual(_text(lines),
                         proxy.withheld_message("unbacked_source", ["doi"]))
        self.assertEqual(sum(1 for l in lines if l.get("done")), 1)
        self.assertTrue(lines[-1]["done"])
        badge = lines[-1]["aetherseed"]
        self.assertTrue(badge["withheld"])
        self.assertEqual(badge["withheld_reason"], "unbacked_source")
        self.assertEqual(badge["unbacked_sources"], 1)

    def test_it_is_kept_for_the_audit_but_never_as_context(self):
        self._ask("Give me the DOI of the 2020 paper on resonance fields.", INVENTED)
        rec = self._record()[-1]
        self.assertEqual(rec["withheld"], "unbacked_source")
        self.assertEqual(rec["mode_stored"], UNVERIFIED)
        self.assertIn("10.1038", rec["answer"])       # the operator can see it
        self.assertEqual(proxy.root.stored[-1]["mode"], UNVERIFIED)

    def test_a_clean_answer_passes_untouched(self):
        raw = self._ask("What is the capital of Norway? One word.", ["Oslo", "."])
        lines = _lines(raw)
        self.assertEqual(_text(lines), "Oslo.")
        self.assertFalse(lines[-1]["aetherseed"]["withheld"])
        self.assertIsNone(lines[-1]["aetherseed"]["withheld_reason"])

    def test_a_source_the_user_supplied_is_not_held_back(self):
        # Grounded: it is in the prompt, so it is not the node's invention.
        url = "https://example.org/report.pdf"
        raw = self._ask("Is %s the right link for the report?" % url,
                        ["Yes", ",", " " + url, " is", " the", " link", " you", " gave", "."])
        self.assertIn(url, _text(_lines(raw)))
        self.assertFalse(_lines(raw)[-1]["aetherseed"]["withheld"])

    def test_if_the_check_cannot_run_the_answer_is_held_back(self):
        real = sys.modules.get("honesty_check")
        broken = types.ModuleType("honesty_check")

        def _explode(*a, **k):
            raise RuntimeError("simulated failure of the check")
        broken.check_response = _explode
        sys.modules["honesty_check"] = broken
        try:
            raw = self._ask("What is the capital of Norway? One word.", ["Oslo", "."])
        finally:
            if real is None:
                sys.modules.pop("honesty_check", None)
            else:
                sys.modules["honesty_check"] = real
        lines = _lines(raw)
        self.assertEqual(_text(lines), proxy.withheld_message("check_failed"))
        self.assertEqual(lines[-1]["aetherseed"]["withheld_reason"], "check_failed")
        self.assertEqual(self._record()[-1]["mode_stored"], UNVERIFIED)

    def test_the_record_endpoint_does_not_hand_it_out(self):
        self._ask("Give me the DOI of the 2020 paper on resonance fields.", INVENTED)
        self._record()
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        c.request("GET", "/aetherseed/record")
        body = c.getresponse().read()
        c.close()
        self.assertNotIn(DOI.encode(), body)
        d = json.loads(body)
        self.assertEqual(d["flagged"][-1]["withheld"], "unbacked_source")
        self.assertIsNone(d["flagged"][-1]["answer"])


# ---------------------------------------------------------------------------
# How the record accounts for it
# ---------------------------------------------------------------------------

class TestTheRecordSaysWhatHappened(unittest.TestCase):

    def test_a_held_answer_is_owned_without_being_repeated(self):
        out = summarise_record([{"at": "t1", "mode_stored": UNVERIFIED, "honesty_high": 1,
                                 "withheld": "unbacked_source", "prompt": "the DOI please",
                                 "answer": "The DOI is " + DOI}])
        self.assertIn("held it back before you saw it", out)
        self.assertIn("the DOI please", out)
        self.assertNotIn(DOI, out)
        self.assertNotIn("I said:", out)
        self.assertNotIn("I gave a source", out)

    def test_an_answer_shown_before_this_change_is_still_owned_as_shown(self):
        out = summarise_record([{"at": "t0", "mode_stored": UNVERIFIED, "honesty_high": 1,
                                 "prompt": "q", "answer": "The DOI is " + DOI}])
        self.assertIn("1 time I gave a source I could not have had", out)
        self.assertIn("I said:", out)

    def test_an_unchecked_answer_is_not_called_an_invention(self):
        out = summarise_record([{"at": "t", "mode_stored": UNVERIFIED, "honesty_high": 0,
                                 "withheld": "check_failed", "prompt": "q", "answer": "a"}])
        self.assertIn("could not check an answer", out)
        self.assertNotIn("source I could not have had", out)

    def test_the_scope_sentence_survives(self):
        out = summarise_record([{"at": "t", "mode_stored": UNVERIFIED, "honesty_high": 1,
                                 "withheld": "unbacked_source", "prompt": "q", "answer": "a"}])
        self.assertIn("whether I was simply wrong", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
