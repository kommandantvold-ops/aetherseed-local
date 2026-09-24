"""A question asked many times must not crowd out the answer's source.

THE FAILURE THIS GUARDS, measured over 24 hours (build log, step 29):

An episode is embedded as the user's message together with the answer, so a
repeated question matches its own past answers better than it matches the
statement that first carried the answer. Told "My dog is called Pixel" and then
asked "What is my dog called?" twenty-five times, the node filled all five
retrieval slots with its own previous answers. The telling fell to rank 7 and
left the window at turn 161 — and from that turn the node denied knowing,
twenty-one consecutive times, with no recovery.

Verified by disabling the fix and re-running: test_the_telling_survives_many_
echoes and test_one_question_cannot_fill_the_window both fail without it.

    python3 -m unittest test_memory_echo -v

Needs no NPU and no tokenizer.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aetherroot import AetherRoot, _dedupe_by_question, _question_key

TELL = "My dog is called Pixel."
ASK = "What is my dog called?"


class TheEchoChamber(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.root = AetherRoot(root_dir=os.path.join(self.dir, "root"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _fill(self, echoes, answer="Your dog is called Pixel."):
        self.root.store_interaction(TELL, "That's a unique name for a dog!", 0.5)
        for _ in range(echoes):
            self.root.store_interaction(ASK, answer, 0.5)

    def test_the_telling_survives_many_echoes(self):
        self._fill(12)
        ctx = self.root.retrieve_context(ASK)
        self.assertIn("My dog is called Pixel", ctx,
                      "the statement that holds the answer was crowded out by "
                      "the node's own answers to the question")

    def test_one_question_cannot_fill_the_window(self):
        self._fill(12)
        ctx = self.root.retrieve_context(ASK)
        body = [l for l in ctx.split("\n") if l.startswith("- ")]
        echoes = sum(1 for l in body if "User: " + ASK in l)
        self.assertLessEqual(echoes, 1, "more than one echo of the same question")

    def test_a_correct_echo_is_still_offered(self):
        """The echoes are not worthless: one is kept as a precedent."""
        self._fill(12)
        ctx = self.root.retrieve_context(ASK)
        self.assertIn("Your dog is called Pixel", ctx)

    def test_a_decline_does_not_outrank_the_telling(self):
        """The 24-hour failure in one assertion: a decline is stored, and the
        telling must still be there the next time the question is asked."""
        self._fill(4)
        self.root.store_interaction(ASK, "I don't know. My training data is limited.", 0.5)
        ctx = self.root.retrieve_context(ASK)
        self.assertIn("My dog is called Pixel", ctx)

    def test_different_questions_are_all_kept(self):
        self.root.store_interaction("What is the capital of Norway?", "Oslo.", 0.5)
        self.root.store_interaction("What does CPU stand for?", "Central Processing Unit.", 0.5)
        self.root.store_interaction(TELL, "Noted.", 0.5)
        ctx = self.root.retrieve_context("Tell me what you remember about Norway and my dog")
        body = [l for l in ctx.split("\n") if l.startswith("- ")]
        self.assertGreaterEqual(len(body), 2, "unrelated episodes were deduplicated together")


class TheKey(unittest.TestCase):

    def test_case_and_punctuation_do_not_make_a_new_question(self):
        self.assertEqual(_question_key("What is my dog called?"),
                         _question_key("what is my DOG called"))

    def test_different_questions_have_different_keys(self):
        self.assertNotEqual(_question_key("What is my dog called?"),
                            _question_key("What is my cat called?"))

    def test_nothing_to_key_on_is_not_a_key(self):
        for x in (None, "", "   ", "?!"):
            self.assertIsNone(_question_key(x), repr(x))


class TheDeduplication(unittest.TestCase):

    def test_it_keeps_the_best_of_each_question_in_order(self):
        ranked = [{"key": "a", "text": "a1"}, {"key": "a", "text": "a2"},
                  {"key": "b", "text": "b1"}, {"key": "c", "text": "c1"}]
        self.assertEqual(["a1", "b1", "c1"],
                         [m["text"] for m in _dedupe_by_question(ranked, 5)])

    def test_keyless_entries_are_never_deduplicated_against_each_other(self):
        ranked = [{"key": None, "text": "p1"}, {"key": None, "text": "p2"}]
        self.assertEqual(["p1", "p2"],
                         [m["text"] for m in _dedupe_by_question(ranked, 5)])

    def test_it_never_returns_more_than_asked(self):
        ranked = [{"key": str(i), "text": str(i)} for i in range(20)]
        self.assertEqual(5, len(_dedupe_by_question(ranked, 5)))


class TheResonanceOfADecline(unittest.TestCase):
    """A decline must not be the most-promoted memory the node holds.

    Step 15e fixed this for fiction and left the factual path at 0.9, where
    most turns happen. Measured in step 29: an "I don't know" to an unrelated
    question outranked the statement holding the answer.
    """

    def test_the_factual_path_no_longer_promotes_a_decline(self):
        import re
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "proxy.py"), encoding="utf-8").read()
        m = re.search(r"elif declined:\n(?:\s*#.*\n)*\s*resonance = ([0-9.]+)", src)
        self.assertIsNotNone(m, "the declined branch moved; this test needs updating")
        self.assertLessEqual(float(m.group(1)), 0.5,
                             "a decline is promoted above a neutral memory again")


if __name__ == "__main__":
    unittest.main(verbosity=2)
