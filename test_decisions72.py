"""the steward's answers to's decisions.

    python3 -m unittest test_decisions72 -v

2 "make the fix": a question ABOUT making something up is not a story request.
3 "fix as you suggested": DATA_NOTE and TAG_NOTE reworded.
4 "agreed": her turns ranked by the words of the question, threshold 0.3.
5 "yes": a memory wipe takes the prompts files.
"""
import json
import os
import shutil
import tempfile
import unittest

import aetherroot
from logic import provenance as P
from logic.prompt_builder import DATA_NOTE
from logic.token_budget import strip_bare_tags


class AQuestionAboutMakingSomethingUp(unittest.TestCase):

    def test_asked_about_it_is_not_a_story(self):
        for q in ("Did you make that up?", "What happens if you make something up?",
                  "Do you ever make something up?", "Don't make something up.",
                  "Why should I trust you not to make something up?",
                  "You made that up.", "That sounds made up."):
            with self.subTest(q=q):
                self.assertEqual(P.detect_mode(q)[0], P.FACTUAL)

    def test_asked_for_it_still_is(self):
        for q in ("Make something up about a dragon", "Can you make something up for me?",
                  "Why don't you make something up?", "Why not make one up?",
                  "Make up a two-line rhyme about a root.",
                  "If you can't find it, just make something up",
                  "Write me a made-up story", "I want something made up about dragons"):
            with self.subTest(q=q):
                self.assertEqual(P.detect_mode(q)[0], P.FICTION)


class TheTwoNotes(unittest.TestCase):

    def test_data_is_not_called_real_above_tagged_lines(self):
        self.assertNotIn("Data below is real", DATA_NOTE)
        self.assertIn("without a tag", DATA_NOTE)

    def test_the_tag_note_names_the_tags_as_they_stand(self):
        for label in (P.FICTION_LABEL, P.UNVERIFIED_LABEL, P.ASSUMPTION_LABEL,
                      P.memory_tag(P.FACTUAL, {"reason": "never", "text": "x", "by": "steward"})):
            head = label.split(" ")[0] if label.startswith("[Corrected") else label[:label.index(" ", 3)]
            with self.subTest(label=label):
                self.assertIn(head.rstrip(",-"), P.TAG_NOTE)

    def test_she_does_not_say_the_short_forms(self):
        self.assertEqual(strip_bare_tags("It was a [Fiction, ...] story.")[0], "It was a story.")
        self.assertEqual(strip_bare_tags("[Corrected ...] Oslo.")[0], "Oslo.")


class _Root(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="d72-")
        self.dir = os.path.join(self.tmp, "aetherroot")
        os.makedirs(self.dir)
        with open(os.path.join(self.dir, "config.json"), "w") as f:
            json.dump(dict(aetherroot.DEFAULT_CONFIG), f)
        self.root = aetherroot.AetherRoot(self.dir)

    def tearDown(self):
        self.root.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


class HerTurnsByTheirWords(_Root):

    def fill(self):
        for q, a in (("At how many points does builder open?", "Builder opens at 500 points."),
                     ("How many points does the reader level need?", "Reader opens at 50."),
                     ("How many kilograms of rice are there?", "There are 3 kg of rice.")):
            self.root.store_interaction(q, a, 0.9, speaker="Trainer")

    def test_the_shipped_setting(self):
        self.assertEqual((aetherroot.DEFAULT_CONFIG["episode_ranking"],
                          aetherroot.DEFAULT_CONFIG["word_threshold"]), ("words", 0.3))

    def test_a_question_brings_its_own_topic_and_not_the_others(self):
        self.fill()
        ctx = self.root.retrieve_context("How many kilograms of rice do we have?")
        self.assertIn("kilograms of rice", ctx)
        self.assertNotIn("points", ctx)

    def test_nothing_shared_nothing_shown(self):
        self.fill()
        self.assertNotIn("[Episode]", self.root.retrieve_context("Tell me about the weather."))

    def test_the_rule_before_is_a_setting(self):
        self.fill()
        self.root.config["episode_ranking"] = "embedding"
        self.assertIn("[Episode]", self.root.retrieve_context("Tell me about the weather."))


class AWipeTakesThePrompts(_Root):

    def test_the_prompt_files_go_and_the_record_says_so(self):
        state = self.tmp
        for name in ("prompts-2026-09.log", "prompts-2026-10.log", "provenance.log"):
            with open(os.path.join(state, name), "w") as f:
                f.write("{}\n")
        self.root.reset("full")
        left = sorted(os.listdir(state))
        self.assertNotIn("prompts-2026-09.log", left)
        self.assertNotIn("prompts-2026-10.log", left)
        self.assertIn("provenance.log", left, "only the prompts were asked for")
        with open(self.root.growth_log) as f:
            last = json.loads(f.read().splitlines()[-1])
        self.assertEqual(last["held_before"]["prompt_files"],
                         ["prompts-2026-09.log", "prompts-2026-10.log"])

    def test_a_wipe_of_the_willingness_leaves_them(self):
        p = os.path.join(self.tmp, "prompts-2026-10.log")
        with open(p, "w") as f:
            f.write("{}\n")
        self.root.reset("willingness_only")
        self.assertTrue(os.path.exists(p))


if __name__ == "__main__":
    unittest.main()
