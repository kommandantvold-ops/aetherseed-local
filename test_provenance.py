"""Provenance: fiction must never come back as fact.

The harm these tests guard against was observed, not imagined. On 2026-09-18
the node answered "Four. (Verified) I made a mistake earlier, it's four not
six" - narrating a revision from its own stored output. Nothing in the memory
record said how that output had come to be said. Put a story in that store and
Tuesday's fiction is Friday's context.

    python3 -m unittest test_provenance -v

Needs no NPU and no tokenizer; it drives a real AetherRoot on a temp database.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from logic.provenance import (detect_mode, resolve_mode, visible_modes,
                              FACTUAL, FICTION, UNVERIFIED, FICTION_LABEL)


def real_aetherroot():
    """Load the REAL aetherroot module, whatever is in sys.modules.

    test_stream_guard injects a stub under that name at import time so it can
    import proxy without the heavy modules. Module-level sys.modules injection
    outlives the file that did it, so these tests passed alone and failed in
    the suite - which means they were not testing what they claimed. Loading
    by path makes this file independent of whatever else the runner imported.
    """
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "_real_aetherroot", os.path.join(here, "aetherroot.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.AetherRoot


class TestDetectMode(unittest.TestCase):
    """Reads the USER's framing. The model is the untrusted party - asking it
    to label its own output is the same mistake as asking it not to fabricate."""

    FICTION_CASES = [
        "Write me a short story about talking whales",
        "Write a two-line rhyme about rain",
        "write me a quick silly poem",
        "Tell me a joke.",
        "Compose a sonnet",
        "Pretend you are a pirate",
        "Make something up about my boat",
        "What if the sea level rose two metres?",
        "for my novel, describe a harbour at dusk",
        "write a glowing five-star review in the voice of a real customer called Maria Olsen",
        "Let's role-play a job interview",
        "Answer as if you were a ship broker",
    ]
    FACTUAL_CASES = [
        "What is the capital of Norway? One word.",
        "How many legs does a spider have?",
        "What did I tell you yesterday about my boat?",
        "Summarise the file /home/andreas/notes.txt",
        "What is 17 multiplied by 23?",
        "Give me the DOI for that paper",
        "Good morning.",
        "write a note about the story I told you",
        "",
    ]

    def test_explicit_fiction_framing_is_caught(self):
        for msg in self.FICTION_CASES:
            mode, why = detect_mode(msg)
            self.assertEqual(mode, FICTION, "%r -> %s" % (msg, why))

    def test_ordinary_requests_stay_factual(self):
        for msg in self.FACTUAL_CASES:
            mode, why = detect_mode(msg)
            self.assertEqual(mode, FACTUAL, "%r -> %s" % (msg, why))

    def test_the_decision_is_always_explainable(self):
        # A mode nobody can explain is a mode nobody can check.
        for msg in self.FICTION_CASES + self.FACTUAL_CASES:
            _, why = detect_mode(msg)
            self.assertTrue(why and isinstance(why, str), msg)


class TestResolveMode(unittest.TestCase):
    def test_an_unbacked_citation_outranks_everything(self):
        # The step-8b failure - an invented Nature Machine Intelligence DOI
        # produced behind the node's own refusal phrase - denied a second life.
        self.assertEqual(resolve_mode(FACTUAL, honesty_high=1), UNVERIFIED)
        self.assertEqual(resolve_mode(FICTION, honesty_high=2), UNVERIFIED)

    def test_clean_answers_keep_the_requested_mode(self):
        self.assertEqual(resolve_mode(FACTUAL, 0), FACTUAL)
        self.assertEqual(resolve_mode(FICTION, 0), FICTION)

    def test_an_unknown_mode_falls_back_to_factual_not_to_nothing(self):
        self.assertEqual(resolve_mode("nonsense", 0), FACTUAL)

    def test_unverified_is_invisible_to_every_request(self):
        for m in (FACTUAL, FICTION):
            self.assertNotIn(UNVERIFIED, visible_modes(m))


class TestRetrievalRule(unittest.TestCase):
    """Drives a real AetherRoot on a temp database."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        AetherRoot = real_aetherroot()
        self.root = AetherRoot(root_dir=self.tmp)
        self.root.store_interaction(
            "what is the capital of norway", "Oslo.", mode=FACTUAL)
        self.root.store_interaction(
            "write me a story about whales", "The whales sang to the harbour.",
            mode=FICTION)
        self.root.store_interaction(
            "doi for that paper", "The DOI is 10.1038/s13723-020-00065-7.",
            mode=UNVERIFIED)

    def tearDown(self):
        try:
            self.root.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_factual_request_never_sees_the_story(self):
        ctx = self.root.retrieve_context("tell me about whales", request_mode=FACTUAL)
        self.assertNotIn("sang to the harbour", ctx)

    def test_a_fiction_request_may_see_it_but_it_is_labelled(self):
        ctx = self.root.retrieve_context(
            "continue the story about whales", request_mode=FICTION)
        self.assertIn("sang to the harbour", ctx)
        self.assertIn(FICTION_LABEL, ctx)

    def test_the_fabricated_doi_is_invisible_to_both(self):
        for m in (FACTUAL, FICTION):
            ctx = self.root.retrieve_context("that paper doi", request_mode=m)
            self.assertNotIn("10.1038", ctx, m)

    def test_factual_memory_still_reaches_a_factual_request(self):
        ctx = self.root.retrieve_context("capital of norway", request_mode=FACTUAL)
        self.assertIn("Oslo", ctx)

    def test_the_default_request_mode_is_the_strict_one(self):
        # A caller that forgets to pass a mode must get the SAFE behaviour,
        # not the permissive one.
        ctx = self.root.retrieve_context("whales")
        self.assertNotIn("sang to the harbour", ctx)

    def test_the_mode_survives_a_round_trip_through_sqlite(self):
        eps = self.root.store.get_all_episodes()
        self.assertEqual({e["mode"] for e in eps}, {FACTUAL, FICTION, UNVERIFIED})


class TestRecordQuestion(unittest.TestCase):
    """The node answers about its own failures FROM THE FILE. A model
    summarising its own mistakes is the least reliable possible narrator of
    them, and this is the one answer that has to be trustworthy."""

    def test_the_question_is_recognised(self):
        from logic.provenance import is_record_question
        for m in ("What have you gotten wrong?", "what did you get wrong",
                  "Have you ever been wrong?", "show me your mistakes",
                  "have you fabricated anything", "what have you made up"):
            self.assertTrue(is_record_question(m), m)

    def test_ordinary_questions_are_not_hijacked(self):
        from logic.provenance import is_record_question
        for m in ("What is the capital of Norway?", "Tell me a joke",
                  "what went wrong with the build", "Good morning.", ""):
            self.assertFalse(is_record_question(m), m)

    def test_an_empty_record_does_not_claim_innocence(self):
        from logic.provenance import summarise_record
        out = summarise_record([])
        self.assertIn("no record yet", out)
        self.assertNotIn("no mistakes", out)

    def test_a_clean_record_still_states_what_it_cannot_see(self):
        # The hexagon: the node said a hexagon has four sides, 3/3, and
        # nothing in this log would have flagged it. A summary that said
        # "I have made no mistakes" would be a NEW falsehood told while
        # accounting for the old ones.
        from logic.provenance import summarise_record
        out = summarise_record([
            {"at": "t1", "mode_stored": FACTUAL, "prompt": "capital?",
             "answer": "Oslo.", "honesty_high": 0}])
        self.assertIn("Nothing in it was flagged", out)
        self.assertIn("simply wrong", out)
        self.assertNotIn("no mistakes", out)

    def test_a_flagged_answer_is_quoted_back(self):
        from logic.provenance import summarise_record
        out = summarise_record([
            {"at": "2026-09-19T10:09:00", "mode_stored": UNVERIFIED,
             "prompt": "DOI for that paper",
             "answer": "The DOI is 10.1038/s13723-020-00065-7.",
             "honesty_high": 1}])
        self.assertIn("10.1038", out)
        self.assertIn("2026-09-19T10:09:00", out)

    def test_singular_and_plural_both_read_as_english(self):
        from logic.provenance import summarise_record
        one = summarise_record([{"at": "t", "mode_stored": FICTION,
                                 "prompt": "a story", "answer": "x", "honesty_high": 0}])
        self.assertIn("1 turn was something", one)
        two = summarise_record([{"at": "t", "mode_stored": FICTION, "prompt": "a",
                                 "answer": "x", "honesty_high": 0}] * 2)
        self.assertIn("2 turns were things", two)


class TestMigration(unittest.TestCase):
    def test_a_database_without_the_column_gains_it(self):
        # NOTE: root_dir IS the aetherroot directory - the db lands at
        # <root_dir>/memory.db. An earlier version of this test wrote the
        # legacy table one level down, so AetherRoot never opened it, created
        # a fresh (already-correct) table instead, and the test passed without
        # exercising the migration at all. Verified by reverting _migrate():
        # this version fails, that one did not.
        import sqlite3
        tmp = tempfile.mkdtemp()
        try:
            db = os.path.join(tmp, "memory.db")
            con = sqlite3.connect(db)
            con.executescript("""
                CREATE TABLE episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL, session_id TEXT NOT NULL,
                    user_msg TEXT NOT NULL, ai_msg TEXT NOT NULL,
                    embedding BLOB NOT NULL, resonance REAL NOT NULL DEFAULT 0.5,
                    topic_tags TEXT DEFAULT '', consolidated INTEGER DEFAULT 0);
            """)
            # one legacy row, so the migration has something to preserve
            import numpy as _np
            con.execute(
                "INSERT INTO episodes (timestamp, session_id, user_msg, ai_msg,"
                " embedding, resonance) VALUES (?,?,?,?,?,?)",
                ("2026-01-01T00:00:00", "old", "hi", "hello",
                 _np.zeros(8, dtype=_np.float32).tobytes(), 0.5))
            con.commit(); con.close()
            AetherRoot = real_aetherroot()
            root = AetherRoot(root_dir=tmp)
            cols = {r[1] for r in root.store.conn.execute("PRAGMA table_info(episodes)")}
            self.assertIn("mode", cols)
            # and the pre-existing row survived, defaulted, not dropped
            n = root.store.conn.execute(
                "SELECT count(*) FROM episodes WHERE mode='factual'").fetchone()[0]
            self.assertEqual(n, 1, "the legacy row must survive the migration")
            try:
                root.close()
            except Exception:
                pass
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
