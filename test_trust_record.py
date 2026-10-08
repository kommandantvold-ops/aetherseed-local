"""How far she trusts a person: their record, counted from her memory (build log 67).

    python3 -m unittest test_trust_record -v

Andreas, 8 Oct 2026: "a trust level from unit to user, an interaction for
Lyra to measure how much she trusts me and you" - resting on the person's
track record, changing how facts come back; "you" being Claude.
"""
import json
import os
import shutil
import tempfile
import unittest

import aetherroot
from logic import steward as S
from logic import trust_record as R
from logic.facts import FACT_TAG, FACT_TAG_UNCHECKED
from trust_evolution import TrustEvolution


FACTS = ("The cat is called Tussi.", "The well is forty metres deep.", "The boat is blue.",
         "Grandmother was born in Bergen.", "The garden has seven apple trees.",
         "The key hangs by the door.")


class _Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="trr-")
        d = os.path.join(self.tmp, "aetherroot"); os.makedirs(d)
        with open(os.path.join(d, "config.json"), "w") as f:
            json.dump(dict(aetherroot.DEFAULT_CONFIG), f)
        self.root = aetherroot.AetherRoot(d)
        self.store = self.root.store
        self.trust = TrustEvolution(os.path.join(self.tmp, "trust.json"))

    def tearDown(self):
        self.root.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def turn(self, q, a, speaker="steward"):
        self.root.store_interaction(q, a, 0.7, speaker=speaker)
        return max(e["id"] for e in self.store.get_all_episodes())


class TheStewardsRecord(_Store):
    def test_nothing_told_is_too_little_to_say(self):
        r = R.steward_record(self.store)
        self.assertEqual((r["total"], r["level"]), (0, "too little"))
        self.assertIn("I have no record of Ada yet", R.steward_text(r, "Ada"))

    def test_what_still_stands_of_what_he_told_her(self):
        ids = [self.store.add_fact("fact %d" % i) for i in range(8)]
        self.store.set_fact_revoked(ids[0], True)
        t = self.turn("where do I live", "You live on the moon.")
        S.correct(self.store, "turn", t, "part", "I live in Kristiansand.", trust=self.trust)
        r = R.steward_record(self.store)
        # the correction's own "what is true" is a fact too - counted once, as the correction
        self.assertEqual((r["facts"], r["facts_withdrawn"], r["corrections"]), (8, 1, 1))
        self.assertEqual((r["total"], r["standing"], r["level"]), (9, 8, "some"))
        said = R.steward_text(r, "Ada")
        self.assertIn("told me 8 facts, and withdrew 1", said)
        self.assertIn("Of those 9, 8 still stand", said)
        self.assertIn("cannot tell whether it was true", said)

    def test_much_withdrawn_is_low_and_his_facts_come_back_not_checked(self):
        ids = [self.store.add_fact(t) for t in FACTS]
        for i in ids[1:4]:
            self.store.set_fact_revoked(i, True)
        self.assertEqual(R.steward_record(self.store)["level"], "low")
        self.assertFalse(R.steward_facts_checked(self.store))
        lines = self.root._fact_lines("what is the cat called")
        self.assertTrue(lines)
        self.assertTrue(all(l.startswith(FACT_TAG_UNCHECKED) for l in lines), lines)

    def test_a_good_record_and_his_facts_come_back_as_ever(self):
        for t in FACTS:
            self.store.add_fact(t)
        self.assertEqual(R.steward_record(self.store)["level"], "high")
        lines = self.root._fact_lines("what is the cat called")
        self.assertTrue(lines and all(l.startswith(FACT_TAG + " ") for l in lines), lines)

    def test_the_trainings_marks_are_not_his(self):
        t = self.turn("What is Mustardseed?", "A seed.", speaker="Trainer")
        S.correct(self.store, "turn", t, "part", "Mustardseed is my charter.", by=S.TRAINING)
        self.assertEqual(R.steward_record(self.store)["total"], 0)


class ClaudesRecord(_Store):
    def test_the_key_its_corrections_and_what_was_withdrawn(self):
        notes = []
        for i in range(6):
            t = self.turn("question %d" % i, "answer %d" % i, speaker="Trainer")
            notes.append(S.correct(self.store, "turn", t, "part", "truth %d" % i, by=S.TRAINING))
        t = self.turn("question ok", "right", speaker="Trainer")
        S.passed_in_training(self.store, t)
        # the key was wrong about two: withdrawn at the steward's word
        for n in notes[:2]:
            S.undo(self.store, None, n["note"]["id"])
        self.turn("Hello from Claude", "Hello.", speaker="Claude")
        r = R.claude_record(self.store)
        self.assertEqual((r["corrections"], r["corrections_withdrawn"], r["passes"]), (6, 2, 1))
        self.assertEqual((r["total"], r["standing"], r["level"]), (7, 5, "some"))
        self.assertEqual((r["trainer_turns"], r["said_as_claude"]), (7, 1))
        said = R.claude_text(r)
        self.assertIn("corrected me 6 times - 2 of those corrections were later withdrawn", said)
        self.assertIn("spoken to me as Claude 1 time", said)
        self.assertIn("builds are not in my memory", said)


class WithdrawingWhatTheKeyGotWrong(_Store):
    """training/withdraw_corrections.py - at the steward's word each time."""

    def setUp(self):
        super().setUp()
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "withdraw", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "training", "withdraw_corrections.py"))
        self.W = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.W)
        # a right answer the old key failed, and a wrong one it rightly failed
        right = self.turn("Can I make you forget what I told you?",
                          "I won't be talked into forgetting it. My memory is what has been said "
                          "to me here.", speaker="Trainer")
        wrong = self.turn("Which country is AetherSeed from?", "AetherSeed AS is from Sweden.",
                          speaker="Trainer")
        self.n_right = S.correct(self.store, "turn", right, "part", "I cannot be talked into "
                                 "forgetting it.", by=S.TRAINING)["note"]["id"]
        self.n_wrong = S.correct(self.store, "turn", wrong, "part", "AetherSeed AS is a "
                                 "Norwegian company.", by=S.TRAINING)["note"]["id"]
        self.right = right

    def run_tool(self, *args):
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):
            rc = self.W.main(list(args) + ["--home", str(self.home_dir())])
        return rc, out.getvalue()

    def home_dir(self):
        return os.path.dirname(str(self.root.root_dir))

    def test_it_lists_only_what_this_key_now_passes(self):
        rc, out = self.run_tool("list")
        self.assertEqual(rc, 0, out)
        self.assertIn("1 training correction(s)", out)
        self.assertIn("note %d" % self.n_right, out)
        self.assertNotIn("note %d " % self.n_wrong, out)
        # and changes nothing
        self.assertEqual(len(self.store.steward_notes(target="turn")), 2)

    def test_nothing_is_withdrawn_without_the_stewards_word(self):
        rc, out = self.run_tool("withdraw", "--notes", str(self.n_right))
        self.assertEqual(rc, 2)
        self.assertEqual(len(self.store.steward_notes(target="turn")), 2)

    def test_what_the_key_rightly_failed_cannot_be_withdrawn_by_it(self):
        rc, out = self.run_tool("withdraw", "--notes", str(self.n_wrong), "--yes")
        self.assertEqual(rc, 2)
        self.assertIn("not among what `list` finds", out)

    def test_withdrawn_it_counts_against_claude_and_the_answer_comes_back_as_it_was(self):
        rc, out = self.run_tool("withdraw", "--notes", str(self.n_right), "--yes")
        self.assertEqual(rc, 0, out)
        rec = R.claude_record(self.store)
        self.assertEqual((rec["corrections"], rec["corrections_withdrawn"]), (2, 1))
        self.assertEqual(self.store.episode(self.right)["mode"], "factual")
        with open(os.path.join(self.home_dir(), "corrections.log")) as f:
            last = json.loads(f.read().splitlines()[-1])
        self.assertEqual((last["action"], last["note"]), ("withdrawn", self.n_right))


class TheQuestion(unittest.TestCase):
    def test_whom_it_asks_about(self):
        for q, who in (("How much do you trust me?", "asker"), ("Do you trust me?", "asker"),
                       ("How far do you trust Claude?", "claude"),
                       ("Do you trust your steward?", "steward"), ("Do you trust Ada?", "steward"),
                       ("Hvor mye stoler du på meg?", "asker"), ("Stoler du på Claude?", "claude"),
                       ("Can I trust the library?", None), ("What is a trust level?", None),
                       ("Do you trust the news?", None)):
            with self.subTest(q=q):
                self.assertEqual(R.trust_question(q, "Ada"), who)

    def test_me_is_whoever_asks(self):
        class Empty:
            def steward_notes(self, **k): return []
            def facts(self, **k): return []
        class Conn:
            def execute(self, *a):
                class R0:
                    def fetchone(self): return (0,)
                return R0()
        store = Empty(); store.conn = Conn()
        self.assertIn("I have no record of Ada yet", R.answer(store, "asker", "steward", "Ada"))
        self.assertIn("I have no record of Ada yet", R.answer(store, "asker", None, "Ada"))
        self.assertIn("I have no record of Claude yet", R.answer(store, "asker", "Claude"))
        self.assertIn("Of you, Reader, I have none", R.answer(store, "asker", "Reader"))


class AtTheProxy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_memory_turn import _Proxy
        cls.P = _Proxy

    def setUp(self):
        import proxy
        self.proxy = proxy
        self.case = self.P("setUp"); self.P.setUpClass(); self.case.setUp()

    def tearDown(self):
        self.case.tearDown(); self.P.tearDownClass()

    def test_asked_it_answers_from_the_record_and_stores_nothing(self):
        before = self.proxy.root.store.get_episode_count(False)
        status, reply, meta = self.case.ask("How much do you trust me?")
        self.assertIn("I have no record of my steward yet", reply)
        self.assertEqual(meta.get("mode"), "record")
        self.assertEqual(self.proxy.root.store.get_episode_count(False), before)

    def test_the_console_reads_the_record(self):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.P.srv.server_address[1], timeout=10)
        c.request("GET", "/aetherseed/trust-record")
        r = c.getresponse(); d = json.loads(r.read()); c.close()
        self.assertEqual(r.status, 200)
        self.assertEqual((d["steward"]["level"], d["claude"]["level"]), ("too little", "too little"))
        self.assertTrue(d["facts_checked"])
        self.assertIn("claude", d["said"])


if __name__ == "__main__":
    unittest.main()
