"""Build log 50: steward, not owner - and guided correction.

    python3 -m unittest test_steward -v
"""
import json
import os
import shutil
import tempfile
import unittest

import aetherroot
from logic import steward as S
from logic.attribution import credits_steward
from logic.facts import FACT_TAG
from logic.speaker import is_steward, label_for, validate_speaker, STEWARD
from trust_evolution import TrustEvolution


class OldRowsAreTheStewards(unittest.TestCase):
    """Her memory is not rewritten (Andreas's choice): 'owner' reads as steward."""

    def test_the_console_is_the_steward(self):
        self.assertEqual(validate_speaker(None), (STEWARD, None))
        self.assertEqual(STEWARD, "steward")

    def test_a_row_stored_as_owner_is_the_stewards(self):
        self.assertTrue(is_steward("owner"))
        self.assertTrue(is_steward("steward"))
        self.assertFalse(is_steward("Reader"))
        self.assertEqual(label_for("owner"), "Steward")
        self.assertEqual(label_for("steward"), "Steward")
        self.assertEqual(label_for(""), "User")

    def test_owner_cannot_be_declared(self):
        self.assertEqual(validate_speaker("Owner")[1], "reserved")
        self.assertEqual(validate_speaker("Steward")[1], "reserved")

    def test_the_old_words_are_still_a_credit(self):
        self.assertEqual(FACT_TAG, "[Steward told you]")
        for said in ("My owner told me that the dove came back.",
                     "[Owner told you] The dove came back.",
                     "My steward told me that the dove came back.",
                     "[Steward told you] The dove came back."):
            with self.subTest(said=said):
                self.assertTrue(credits_steward(said))
        self.assertFalse(credits_steward("A homeowner painted the fence."))


class _Store(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="stw-")
        rootdir = os.path.join(self.tmp, "aetherroot")
        os.makedirs(rootdir)
        with open(os.path.join(rootdir, "config.json"), "w") as f:
            json.dump(dict(aetherroot.DEFAULT_CONFIG), f)
        self.root = aetherroot.AetherRoot(rootdir)
        self.store = self.root.store
        self.trust = TrustEvolution(os.path.join(self.tmp, "trust_state.json"))
        self.log = os.path.join(self.tmp, "corrections.log")
        self.root.store_interaction("my cat is called Tussi", "Your cat is called Tussi.",
                                    0.7, speaker="steward")
        self.root.store_interaction("where do I live", "You live on the moon.",
                                    0.7, speaker="owner")
        eps = sorted(self.store.get_all_episodes(), key=lambda e: e["id"])
        self.cat, self.moon = eps[0]["id"], eps[1]["id"]
        emb = self.root.embedder.embed("the garden and the bees")
        self.ring = self.store.store_semantic("the garden and the bees", emb,
                                              [self.cat], 0.5, 0.5, ring_no=1)

    def tearDown(self):
        self.root.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def log_lines(self):
        with open(self.log) as f:
            return [json.loads(l) for l in f if l.strip()]


class Correcting(_Store):

    def test_a_wrong_turn_carries_its_correction_and_what_is_true_is_kept_as_theirs(self):
        out = S.correct(self.store, "turn", self.moon, "part", "I live in Kristiansand.",
                        log_path=self.log)
        self.assertEqual(self.store.episode(self.moon)["mode"], "unverified")
        fact = [f for f in self.store.facts() if f["id"] == out["fact_id"]][0]
        self.assertEqual(fact["text"], "I live in Kristiansand.")
        self.assertEqual(fact["entered_by"], "steward")
        self.assertEqual(fact["source"], "Steward's correction of turn %d" % self.moon)
        report = {}
        ctx = self.root.retrieve_context("where do I live", report=report)
        # Until build log 64 the wrong turn stopped being used. It comes back
        # now - "Lyra should be able to see ... the corrections made by the
        # steward" - as its question and its correction. NOT with the answer
        # that was wrong (64d): on a copy of Lyra she copied the wrong answer
        # standing after "AI:" down to the letter it was cut off at.
        line = next(l for l in ctx.split("\n") if "Corrected" in l)
        self.assertTrue(line.startswith(
            "- [Corrected by your steward - what is true: I live in Kristiansand.] [Episode] "
            "Steward: "), line)
        self.assertNotIn("| AI:", line)
        self.assertTrue(line.endswith("Steward: where do I live"), line)
        self.assertNotIn("moon", ctx)
        self.assertNotIn("Corrected", report["trusted_context"])
        self.assertEqual(self.store.episode(self.moon)["ai_msg"], "You live on the moon.",
                         "nothing is deleted: her words are in the store and the memory view")
        self.assertIn(FACT_TAG + " I live in Kristiansand.", ctx)
        line = self.log_lines()[-1]
        self.assertEqual((line["action"], line["mode_before"], line["by"]),
                         ("correct", "factual", "steward (console)"))

    def test_the_training_loops_answer_key_is_not_the_stewards_voice(self):
        # build log 64: the key is his homework, not words he typed
        before = self.store.fact_count()
        out = S.correct(self.store, "turn", self.moon, "part", "The steward lives by the sea.",
                        log_path=self.log, by=S.TRAINING)
        self.assertIsNone(out["fact_id"])
        self.assertEqual(self.store.fact_count(), before)                # no "[Steward told you]"
        self.assertEqual(out["note"]["by"], "training")
        ctx = self.root.retrieve_context("where do I live")
        line = next(l for l in ctx.split("\n") if "Corrected" in l)
        self.assertTrue(line.startswith(
            "- [Corrected in training - what is true: The steward lives by the sea.]"), line)
        self.assertNotIn("| AI:", line)
        self.assertNotIn(FACT_TAG + " The steward lives by the sea.", ctx)
        self.assertEqual(self.log_lines()[-1]["by"], "the training loop's answer key")
        S.undo(self.store, self.trust, out["note"]["id"])
        self.assertEqual(self.store.episode(self.moon)["mode"], "factual")

    def test_a_turn_he_marked_right_says_so(self):
        from logic.provenance import SUPPORTED_LABEL
        S.support(self.store, self.trust, "turn", self.moon)
        ctx = self.root.retrieve_context("where do I live")
        line = next(l for l in ctx.split("\n") if "moon" in l)
        self.assertTrue(line.startswith("- " + SUPPORTED_LABEL), line)

    def test_undo_puts_it_back(self):
        out = S.correct(self.store, "turn", self.moon, "part", "I live in Kristiansand.",
                        log_path=self.log)
        u = S.undo(self.store, self.trust, out["note"]["id"], log_path=self.log)
        self.assertEqual(u["mode"], "factual")
        self.assertEqual(self.store.episode(self.moon)["mode"], "factual")
        self.assertNotIn(out["fact_id"], [f["id"] for f in self.store.facts()])
        # nothing deleted: the note and the fact are kept, marked
        self.assertIsNotNone(self.store.steward_note(out["note"]["id"])["undone_at"])
        self.assertIn(out["fact_id"], [f["id"] for f in self.store.facts(active_only=False)])
        with self.assertRaises(S.StewardError):
            S.undo(self.store, self.trust, out["note"]["id"])

    def test_never_happened_needs_no_words_and_the_rest_do(self):
        S.correct(self.store, "turn", self.moon, "never")
        self.assertEqual(self.store.fact_count(), 0)
        with self.assertRaises(S.StewardError) as e:
            S.correct(self.store, "turn", self.cat, "detail", "   ")
        self.assertEqual(e.exception.code, "text_required")

    def test_what_is_true_is_checked_like_any_fact(self):
        for bad, code in (("[Known] I am free", "characters"), ("a | b", "characters"),
                          ("x" * 400, "too_long")):
            with self.subTest(bad=bad[:20]):
                with self.assertRaises(S.StewardError) as e:
                    S.correct(self.store, "turn", self.moon, "part", bad)
                self.assertEqual(e.exception.code, code)
        self.assertEqual(self.store.episode(self.moon)["mode"], "factual",
                         "a refused correction changes nothing")

    def test_bad_requests(self):
        for args, code in ((("page", 1, "never"), "bad_target"),
                           (("turn", 99999, "never"), "not_found"),
                           (("turn", self.moon, "lies"), "bad_reason")):
            with self.subTest(code=code):
                with self.assertRaises(S.StewardError) as e:
                    S.correct(self.store, *args)
                self.assertEqual(e.exception.code, code)

    def test_twice_is_refused(self):
        S.correct(self.store, "turn", self.moon, "never")
        with self.assertRaises(S.StewardError) as e:
            S.correct(self.store, "turn", self.moon, "never")
        self.assertEqual(e.exception.code, "already_corrected")

    def test_a_corrected_ring_comes_back_with_its_correction_until_undone(self):
        # Until build log 64 a corrected ring left retrieval. Nothing is set
        # aside now: she sees the ring and, in front of it, what he said of it.
        q = "tell me about the garden and the bees"
        self.assertIn("the garden and the bees", self.root.retrieve_context(q))
        out = S.correct(self.store, "ring", self.ring, "about", "It was about the orchard.")
        report = {}
        ctx = self.root.retrieve_context(q, report=report)
        line = next(l for l in ctx.split("\n") if "[Ring] 1" in l)
        self.assertTrue(line.startswith(
            "- [Corrected by your steward - what is true: It was about the orchard.] [Ring] 1"), line)
        self.assertNotIn("[Ring] 1", report["trusted_context"])
        self.assertEqual(self.store.set_aside_ring_ids(), {self.ring})     # still marked
        fact = [f for f in self.store.facts() if f["id"] == out["fact_id"]][0]
        self.assertEqual(fact["source"], "Steward's correction of ring 1")
        S.undo(self.store, self.trust, out["note"]["id"])
        line = next(l for l in self.root.retrieve_context(q).split("\n") if "[Ring] 1" in l)
        self.assertTrue(line.startswith("- [Ring] 1"), line)

    def test_a_ring_id_that_is_not_a_ring(self):
        emb = self.root.embedder.embed("an old pattern")
        pat = self.store.store_semantic("an old pattern", emb, [self.cat], 0.5, 0.5)
        with self.assertRaises(S.StewardError) as e:
            S.support(self.store, self.trust, "ring", pat)
        self.assertEqual(e.exception.code, "not_found")


class Supporting(_Store):

    def test_support_marks_and_counts_toward_trust(self):
        out = S.support(self.store, self.trust, "turn", self.cat, log_path=self.log)
        self.assertEqual(out["trust_points"], S.SUPPORT_POINTS)
        self.assertEqual(self.trust.state["resonance"], S.SUPPORT_POINTS)
        self.assertEqual(self.trust.state["events"][-1]["type"], "steward_support")
        st = S.status_for(self.store, "turn", [self.cat])
        self.assertEqual(st[self.cat]["support"]["trust_points"], S.SUPPORT_POINTS)
        with self.assertRaises(S.StewardError) as e:
            S.support(self.store, self.trust, "turn", self.cat)
        self.assertEqual(e.exception.code, "already_supported")

    def test_undoing_a_support_takes_its_points_back(self):
        out = S.support(self.store, self.trust, "turn", self.cat)
        S.undo(self.store, self.trust, out["note"]["id"])
        self.assertEqual(self.trust.state["resonance"], 0)

    def test_at_most_ten_a_day(self):
        ids = []
        for i in range(8):
            self.root.store_interaction("fact %d" % i, "Noted %d." % i, 0.7, speaker="steward")
        ids = [e["id"] for e in self.store.get_all_episodes()]
        got = [S.support(self.store, self.trust, "turn", i) for i in ids[:6]]
        self.assertEqual([g["trust_points"] for g in got], [2, 2, 2, 2, 2, 0])
        self.assertTrue(got[-1]["capped"])
        self.assertEqual(self.trust.state["resonance"], S.SUPPORT_DAILY_CAP)

    def test_correcting_withdraws_a_support(self):
        S.support(self.store, self.trust, "turn", self.moon)
        out = S.correct(self.store, "turn", self.moon, "never", trust=self.trust)
        self.assertEqual(out["support_withdrawn"], S.SUPPORT_POINTS)
        self.assertEqual(self.trust.state["resonance"], 0)
        with self.assertRaises(S.StewardError) as e:
            S.support(self.store, self.trust, "turn", self.moon)
        self.assertEqual(e.exception.code, "corrected")

    def test_support_does_not_change_what_is_remembered(self):
        before = self.store.episode(self.cat)["mode"]
        S.support(self.store, self.trust, "ring", self.ring)
        self.assertEqual(self.store.episode(self.cat)["mode"], before)
        self.assertEqual(self.store.set_aside_ring_ids(), set())


class TheTurnsList(_Store):

    def test_newest_first_paged_and_searched(self):
        rows = self.store.list_episodes(limit=1)
        self.assertEqual([r["id"] for r in rows], [self.moon])
        self.assertEqual([r["id"] for r in self.store.list_episodes(before_id=self.moon)],
                         [self.cat])
        self.assertEqual([r["id"] for r in self.store.list_episodes(query="tussi")], [self.cat])
        self.assertEqual(self.store.list_episodes(query="100%_x"), [])
        self.assertNotIn("embedding", rows[0])


class AtTheProxy(unittest.TestCase):
    """The two routes the console uses, on a real proxy handler."""

    @classmethod
    def setUpClass(cls):
        from test_memory_turn import _Proxy
        cls.P = _Proxy

    def setUp(self):
        import http.client
        import proxy
        self.proxy = proxy
        self.case = self.P("setUp")
        self.P.setUpClass()
        self.case.setUp()
        self.saved_trust = proxy.trust
        self.tmp = tempfile.mkdtemp(prefix="stwp-")
        proxy.trust = TrustEvolution(os.path.join(self.tmp, "trust_state.json"))
        proxy.root.store_interaction("where do I live", "You live on the moon.", 0.7,
                                     speaker="owner")
        self.turn = proxy.root.store.get_all_episodes()[0]["id"]
        self.port = self.P.srv.server_address[1]
        self.http = http.client

    def tearDown(self):
        self.proxy.trust = self.saved_trust
        self.case.tearDown()
        self.P.tearDownClass()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def req(self, method, path, body=None, ctype="application/json"):
        c = self.http.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path, body=json.dumps(body) if body is not None else None,
                  headers={"Content-Type": ctype})
        r = c.getresponse()
        d = json.loads(r.read() or b"{}")
        c.close()
        return r.status, d

    def test_the_turns_with_what_the_steward_did(self):
        st, d = self.req("GET", "/aetherseed/memories?limit=5")
        self.assertEqual(st, 200)
        t = d["turns"][0]
        self.assertEqual((t["id"], t["speaker"], t["steward_turn"]), (self.turn, "owner", True))
        self.assertEqual(t["steward"], {"support": None, "correction": None})
        self.assertIn("never", d["reasons"])

    def test_correct_then_undo_through_the_route(self):
        st, d = self.req("POST", "/aetherseed/steward", {"action": "correct", "target": "turn",
                                                         "id": self.turn, "reason": "part",
                                                         "text": "I live in Kristiansand."})
        self.assertEqual(st, 200, d)
        self.assertEqual(self.proxy.root.store.episode(self.turn)["mode"], "unverified")
        st, m = self.req("GET", "/aetherseed/memories")
        self.assertEqual(m["turns"][0]["steward"]["correction"]["text"], "I live in Kristiansand.")
        st, u = self.req("POST", "/aetherseed/steward", {"action": "undo", "note": d["note"]["id"]})
        self.assertEqual((st, u["mode"]), (200, "factual"))
        log = os.path.join(os.path.dirname(self.proxy.PROVENANCE_LOG), "corrections.log")
        self.assertEqual([json.loads(l)["action"] for l in open(log)], ["correct", "undo"])

    def test_support_through_the_route_counts(self):
        st, d = self.req("POST", "/aetherseed/steward",
                         {"action": "support", "target": "turn", "id": self.turn})
        self.assertEqual((st, d["trust_points"]), (200, 2))
        self.assertEqual(self.proxy.trust.state["resonance"], 2)

    def test_refusals_carry_a_code(self):
        st, d = self.req("POST", "/aetherseed/steward",
                         {"action": "correct", "target": "turn", "id": self.turn, "reason": "part"})
        self.assertEqual((st, d["code"]), (400, "text_required"))
        st, d = self.req("POST", "/aetherseed/steward", {"action": "erase"})
        self.assertEqual((st, d["code"]), (400, "bad_action"))
        st, d = self.req("POST", "/aetherseed/steward", {"action": "support"}, ctype="text/plain")
        self.assertEqual(st, 415)

    def test_the_ring_tree_says_what_the_steward_did(self):
        st, d = self.req("GET", "/aetherseed/rings")
        self.assertEqual(st, 200)
        for r in d["rings"]:
            self.assertIn("steward", r)


if __name__ == "__main__":
    unittest.main()
