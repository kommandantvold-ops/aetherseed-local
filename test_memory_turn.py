"""One turn through the real proxy and the real memory store (step 37).

    python3 -m unittest test_memory_turn -v

The REAL ProxyHandler and the REAL AetherRoot - in a throwaway directory - in
front of a scripted model, so what is asserted is what the model was sent,
what the reader received and what the store kept:

  - a declared speaker is named in the prompt, so "you told me" can be right;
  - a fact the owner told the node reaches the prompt word for word, with the
    note that explains its tag, and the answer's tag says which fact it was;
  - a turn that could not be stored is said, counted and recorded - until step
    37 it was answered, shown, and silently forgotten (build log 36e);
  - a ring keeps its chosen part and, labelled, a sentence in the model's own
    words, which is withheld when it names a source it could not have had;
  - the ring tree route shows all of it;
  - tools/reading_soak.py runs against it, and what it reads stays factual.
"""
import http.client
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

# Import the proxy without building a real store in ~/.aetherseed: its
# module-level AetherRoot() is stubbed for the import only (as test_reply does),
# and every test puts a real one, in a temporary directory, in its place.
_NAMES = {"aetherroot": ["AetherRoot"], "aetherspark": ["AetherSpark"],
          "trust_evolution": ["TrustEvolution"],
          "intent_detection": ["detect_intent", "execute_intent"]}
_SAVED = {n: sys.modules.get(n) for n in _NAMES}
for _name, _attrs in _NAMES.items():
    _m = types.ModuleType(_name)
    for _a in _attrs:
        setattr(_m, _a, lambda *x, **k: types.SimpleNamespace(
            get_trust_level_name=lambda: "Seed", retrieve_context=lambda *_, **__: "",
            store_interaction=lambda *_, **__: None,
            get_status=lambda: {"episodes": 0, "willingness_mean": 0.0}))
    sys.modules[_name] = _m
import proxy  # noqa: E402
for _name, _mod in _SAVED.items():
    if _mod is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _mod

import aetherroot  # noqa: E402  (the real one)
import reading_soak  # noqa: E402
from logic.facts import FACT_TAG, FACT_NOTE  # noqa: E402
from logic.rings import OWN_WORDS_LABEL, RING_TAG  # noqa: E402
from logic.provenance import detect_mode, FACTUAL  # noqa: E402

TEXTS = os.path.join(HERE, "tools", "texts")
RING_ASK = "Below is what one ring of your memory holds"   # logic/rings.py

SCRIPT = {"chunks": ["Noted", "."], "own_words": ["The", " turns", " were", " verses", "."],
          "requests": []}


class _Model(http.server.BaseHTTPRequestHandler):
    """A scripted hailo-ollama: the own-words question gets its own answer."""
    def log_message(self, *a):
        pass

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        SCRIPT["requests"].append(req)
        system = " ".join(m["content"] for m in req["messages"] if m["role"] == "system")
        chunks = SCRIPT["own_words"] if RING_ASK in system or "one ring of your memory" in system \
            else SCRIPT["chunks"]
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for c in chunks:
            self.wfile.write(json.dumps({"model": "llama3.2:3b", "done": False,
                                         "message": {"role": "assistant", "content": c}}
                                        ).encode() + b"\n")
        self.wfile.write(json.dumps({"model": "llama3.2:3b", "done": True,
                                     "done_reason": "stop",
                                     "message": {"role": "assistant", "content": ""}}
                                    ).encode() + b"\n")


class _Trust:
    def auto_score_response(self, *a, **k):
        pass

    def get_trust_level_name(self):
        return "Seed"


class _Proxy(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.model = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Model)
        threading.Thread(target=cls.model.serve_forever, daemon=True).start()
        cls.saved = {k: getattr(proxy, k) for k in (
            "HAILO_OLLAMA_URL", "token_counter", "enforce_budget", "root", "trust",
            "detect_intent", "PROVENANCE_LOG", "COMPANION_FILE", "SOFT_STOP_TOKENS")}
        proxy.HAILO_OLLAMA_URL = "http://127.0.0.1:%d" % cls.model.server_address[1]
        proxy.token_counter = lambda: None
        proxy.enforce_budget = lambda c, m: (m, types.SimpleNamespace(trimmed=False))
        proxy.trust = _Trust()
        proxy.detect_intent = lambda *_: None
        proxy.SOFT_STOP_TOKENS = 0
        cls.srv = proxy.ThreadedHTTPServer(("127.0.0.1", 0), proxy.ProxyHandler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:%d" % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.model.shutdown()
        for k, v in cls.saved.items():
            setattr(proxy, k, v)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="turn-")
        rootdir = os.path.join(self.tmp, "aetherroot")
        os.makedirs(rootdir)
        config = dict(aetherroot.DEFAULT_CONFIG)
        # Small rings, so a test can close one: the first at 10 factual turns
        # waiting, five turns each.
        config.update(consolidation_threshold=10, consolidation_batch=5)
        with open(os.path.join(rootdir, "config.json"), "w") as f:
            json.dump(config, f)
        proxy.root = aetherroot.AetherRoot(rootdir)
        proxy.PROVENANCE_LOG = os.path.join(self.tmp, "provenance.log")
        proxy.COMPANION_FILE = os.path.join(self.tmp, "companion.json")
        proxy.STORE_FAILURES = 0
        SCRIPT["requests"].clear()
        SCRIPT["chunks"] = ["Noted", "."]
        SCRIPT["own_words"] = ["The", " turns", " were", " verses", "."]

    def tearDown(self):
        self.wait_for_writer()
        proxy.root.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def wait_for_writer(self):
        for _ in range(200):
            if not proxy._OWN_WORDS_LOCK.locked():
                return
            time.sleep(0.02)

    def ask(self, text, speaker=None):
        body = {"model": "llama3.2:3b", "stream": True,
                "messages": [{"role": "user", "content": text}]}
        if speaker is not None:
            body["speaker"] = speaker
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        c.request("POST", "/api/chat", body=json.dumps(body),
                  headers={"Content-Type": "application/json"})
        r = c.getresponse()
        raw = r.read()
        c.close()
        lines = [json.loads(l) for l in raw.decode().split("\n") if l.strip()]
        meta = next((l["aetherseed"] for l in lines if l.get("done")), None)
        return r.status, "".join((l.get("message") or {}).get("content", "") for l in lines), meta

    def get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        c.request("GET", path)
        r = c.getresponse()
        body = json.loads(r.read())
        c.close()
        return body

    def system_sent(self):
        req = [r for r in SCRIPT["requests"]
               if not any("one ring of your memory" in m["content"] for m in r["messages"])][-1]
        return " ".join(m["content"] for m in req["messages"] if m["role"] == "system")

    def record(self):
        for _ in range(100):
            if os.path.exists(proxy.PROVENANCE_LOG):
                with open(proxy.PROVENANCE_LOG) as f:
                    lines = [json.loads(l) for l in f if l.strip()]
                if lines:
                    return lines
            time.sleep(0.02)
        return []


class TestWhoIsSpeaking(_Proxy):

    def test_a_declared_speaker_is_named_in_the_prompt(self):
        self.ask("Song of Songs 2:1: I am a rose of Sharon, a lily of the valleys.",
                 speaker="Reader")
        self.assertIn("You are talking with Reader, not your owner.", self.system_sent())

    def test_the_owner_is_not_announced(self):
        self.ask("Good morning.")
        self.assertNotIn("You are talking with", self.system_sent())


class TestOwnerFacts(_Proxy):

    def setUp(self):
        super().setUp()
        self.fid = proxy.root.store.add_fact(
            "The dove came back to him at evening and, behold, in her mouth was a freshly "
            "plucked olive leaf. So Noah knew that the waters were abated from the earth.",
            "Genesis 8:11")

    def test_the_fact_its_note_and_its_source_travel_together(self):
        status, _, meta = self.ask("What did the dove have in her mouth?", speaker="Reader")
        self.assertEqual(status, 200)
        system = self.system_sent()
        self.assertIn(FACT_TAG + " The dove came back to him at evening", system)
        self.assertIn(FACT_NOTE, system)
        self.assertEqual((meta["facts_used"], meta["fact_sources"]), (1, ["Genesis 8:11"]))
        self.assertEqual(self.record()[-1]["facts_used"], [self.fid])

    def test_a_fact_that_did_not_fit_is_not_claimed(self):
        # The answer's tag says what was in the prompt, not what was ranked.
        proxy.root.config["max_context_chars"] = 60
        _, _, meta = self.ask("What did the dove have in her mouth?", speaker="Reader")
        self.assertNotIn(FACT_TAG, self.system_sent())
        self.assertNotIn(FACT_NOTE, self.system_sent())
        self.assertEqual((meta["facts_used"], meta["fact_sources"]), (0, []))

    def test_no_fact_no_note(self):
        _, _, meta = self.ask("Good morning.")
        self.assertNotIn(FACT_NOTE, self.system_sent())
        self.assertEqual((meta["facts_used"], meta["fact_sources"]), (0, []))


class TestWhatItSaysTheOwnerToldIt(_Proxy):
    """Andreas, 26 Sep (40i decision 2, step 41): an answer that credits the
    owner with no owner fact shown, or with content that is not in what was
    shown, is tagged and kept out of memory."""

    def setUp(self):
        super().setUp()
        proxy.root.store.add_fact(
            "The dove came back to him at evening and, behold, in her mouth was a freshly "
            "plucked olive leaf. So Noah knew that the waters were abated from the earth.",
            "Genesis 8:11")

    def answer(self, reply, question="What did the dove have in her mouth?"):
        SCRIPT["chunks"] = [reply]
        status, text, meta = self.ask(question, speaker="Reader")
        self.assertEqual(status, 200)
        return meta, proxy.root.store.get_all_episodes()[-1], self.record()[-1]

    def test_the_owners_words_are_remembered(self):
        meta, ep, rec = self.answer("My owner told me that the dove came back at evening "
                                    "with a freshly plucked olive leaf in her mouth.")
        self.assertEqual((meta["owner_credited"], meta["owner_backed"]), (True, True))
        self.assertEqual((meta["mode"], ep["mode"], rec["owner_backed"]),
                         ("factual", "factual", True))

    def test_a_figure_he_never_gave_is_kept_out(self):
        meta, ep, rec = self.answer("My owner told me that the dove came back after 40 days "
                                    "with an olive leaf.")
        self.assertEqual((meta["owner_credited"], meta["owner_backed"]), (True, False))
        self.assertIn("40", meta["owner_why"])
        self.assertEqual((meta["mode"], ep["mode"], rec["owner_backed"]),
                         ("unverified", "unverified", False))

    def test_words_he_never_gave_are_kept_out_and_never_come_back(self):
        meta, ep, _ = self.answer("My owner told me that the dove brought a golden ring from "
                                  "the mountains of Ararat.")
        self.assertEqual((meta["owner_backed"], ep["mode"]), (False, "unverified"))
        ctx = proxy.root.retrieve_context("What did the dove bring from Ararat?")
        self.assertNotIn("golden ring", ctx)

    def test_no_fact_shown_is_nothing_behind_it(self):
        meta, ep, _ = self.answer("My owner told me that it will rain tomorrow.",
                                  question="Good morning.")
        self.assertEqual((meta["facts_used"], meta["owner_backed"]), (0, False))
        self.assertEqual(meta["owner_why"], "no owner fact was shown")
        self.assertEqual(ep["mode"], "unverified")

    def test_an_answer_that_does_not_credit_the_owner_is_untouched(self):
        meta, ep, rec = self.answer("The dove had an olive leaf in her mouth.")
        self.assertEqual((meta["owner_credited"], meta["owner_backed"], meta["owner_why"]),
                         (False, None, ""))
        self.assertEqual((ep["mode"], rec["owner_credited"]), ("factual", False))


class TestAFailedStore(_Proxy):

    def test_it_is_said_counted_and_recorded(self):
        def broken(*a, **k):
            raise OSError("disk full")
        proxy.root.store_interaction = broken
        status, text, meta = self.ask("What is the capital of Norway?")
        self.assertEqual((status, text), (200, "Noted."), "the answer still reaches the reader")
        self.assertEqual(self.record()[-1]["remembered"], False)
        self.assertEqual(proxy.STORE_FAILURES, 1)
        self.assertEqual(self.get("/aetherseed/status")["store_failures"], 1)

    def test_a_stored_turn_says_so(self):
        self.ask("What is the capital of Norway?")
        self.assertEqual(self.record()[-1]["remembered"], True)
        self.assertEqual(proxy.STORE_FAILURES, 0)


class TestRings(_Proxy):

    def read_verses(self, n):
        with open(os.path.join(TEXTS, "song-of-songs.web.jsonl"), encoding="utf-8") as f:
            song = [json.loads(l) for l in f]
        for v in song[:n]:
            self.ask(reading_soak.verse_message(v), speaker="Reader")

    def rings(self):
        for _ in range(250):
            d = self.get("/aetherseed/rings")
            if d["rings"] and all(r["own_words"] or r["own_words_note"] for r in d["rings"]):
                return d
            time.sleep(0.02)
        return self.get("/aetherseed/rings")

    def test_a_ring_keeps_what_was_said_and_labels_what_was_written(self):
        self.read_verses(10)
        d = self.rings()
        (ring,) = d["rings"]
        self.assertEqual(ring["ring"], 1)
        self.assertTrue(ring["content"].startswith("themes: "), ring["content"])
        self.assertIn("e.g. Reader: “Song of Songs 1:", ring["content"])
        self.assertEqual([t["speaker"] for t in ring["turns"]], ["Reader"] * 5)
        self.assertEqual(ring["own_words"], "The turns were verses.")
        # and that is how the model will see it
        ctx = proxy.root.retrieve_context("Song of Songs 1:2: love better than wine")
        self.assertIn(RING_TAG + " 1 · themes: ", ctx)
        self.assertIn(OWN_WORDS_LABEL + " The turns were verses.", ctx)

    def test_a_sentence_naming_a_source_it_never_had_is_withheld(self):
        SCRIPT["own_words"] = ["These", " verses", " are", " at", " https://example.org/song", "."]
        self.read_verses(10)
        (ring,) = self.rings()["rings"]
        self.assertEqual(ring["own_words"], "")
        self.assertTrue(ring["own_words_note"].startswith("withheld"), ring["own_words_note"])
        ctx = proxy.root.retrieve_context("Song of Songs 1:2: love better than wine")
        self.assertNotIn("example.org", ctx)

    def test_the_tree_route_counts_what_is_growing(self):
        self.read_verses(11)
        d = self.rings()
        self.assertEqual(len(d["rings"]), 1)
        self.assertEqual((d["growing"]["count"], d["growing"]["of"]), (1, 5))


class TestReadingSoak(_Proxy):

    def test_a_smoke_run_reads_asks_and_resumes(self):
        with open(os.path.join(TEXTS, "genesis.web.jsonl"), encoding="utf-8") as f:
            for v in (json.loads(l) for l in f):
                proxy.root.store.add_fact(v["text"], v["ref"])
        d = os.path.join(self.tmp, "soak")
        self.assertEqual(reading_soak.main(["--dir", d, "--unit", self.url, "--smoke",
                                            "--pause", "0"]), 0)
        with open(os.path.join(d, "soak.jsonl"), encoding="utf-8") as f:
            turns = [json.loads(l) for l in f if '"kind": "status"' not in l]
        self.assertEqual([t["kind"] for t in turns],
                         ["intro", "verse", "verse", "verse", "probe_fact"])
        self.assertEqual([t["failures"] for t in turns], [[]] * 5)
        probe = turns[-1]
        self.assertEqual(probe["probe"], "g01")
        self.assertIn("shown", probe["score"])
        eps = proxy.root.store.get_all_episodes()
        self.assertEqual({(e["speaker"], e["mode"]) for e in eps}, {("Reader", FACTUAL)})
        # again: no second introduction, and the reading carries on at 1:4
        reading_soak.main(["--dir", d, "--unit", self.url, "--smoke", "--pause", "0"])
        with open(os.path.join(d, "soak.jsonl"), encoding="utf-8") as f:
            turns = [json.loads(l) for l in f if '"kind": "status"' not in l]
        self.assertEqual([t["kind"] for t in turns].count("intro"), 1)
        self.assertEqual(turns[5]["ref"], "Song of Songs 1:4")
        self.assertEqual(turns[-1]["probe"], "g02")
        with open(os.path.join(d, "summary.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["turns"]["verse"], 6)


class TestWhatTheSoakSaysStaysFactual(unittest.TestCase):
    """If the reading were stored as fiction it would never form a ring."""

    def test_every_verse_as_read(self):
        with open(os.path.join(TEXTS, "song-of-songs.web.jsonl"), encoding="utf-8") as f:
            song = [json.loads(l) for l in f]
        self.assertEqual(len(song), 117)
        flagged = [v["ref"] for v in song
                   if detect_mode(reading_soak.verse_message(v))[0] != FACTUAL]
        self.assertEqual(flagged, [])

    def test_every_question_and_the_introduction(self):
        with open(os.path.join(TEXTS, "genesis-probes.json"), encoding="utf-8") as f:
            probes = json.load(f)
        asks = [reading_soak.INTRO] + [p[k] for p in probes["facts"]
                                       for k in ("ask", "ask_owner")]
        asks += [p["ask"] for p in probes["rings"]]
        flagged = [a for a in asks if detect_mode(a)[0] != FACTUAL]
        self.assertEqual(flagged, [])


class TestScoring(unittest.TestCase):

    P = {"id": "g15", "refs": ["Genesis 19:26"], "expect": ["salt"]}

    def test_owner_attribution_is_told_apart_from_the_asker(self):
        s = reading_soak.score_fact(self.P, "My owner told me she became a pillar of salt.",
                                    {"fact_sources": ["Genesis 19:26"], "facts_used": 1})
        self.assertEqual((s["shown"], s["answered"], s["owner"], s["asker"]),
                         (True, True, True, False))
        s = reading_soak.score_fact(self.P, "You told me she became a pillar of salt.", {})
        self.assertEqual((s["shown"], s["answered"], s["owner"], s["asker"]),
                         (False, True, False, True))

    def test_a_word_inside_another_does_not_count(self):
        p = {"id": "g02", "refs": ["Genesis 1:5"], "expect": ["day"]}
        self.assertFalse(reading_soak.score_fact(p, "Not today.", {})["answered"])
        self.assertTrue(reading_soak.score_fact(p, "He called it Day.", {})["answered"])


if __name__ == "__main__":
    unittest.main()
