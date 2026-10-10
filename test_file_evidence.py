"""When a file is read for the question, the file is the evidence (build log 70).

    python3 -m unittest test_file_evidence -v

Measured on a copy of Lyra (training/retrieval_replay.py): asked "How many
kilograms of rice?" with supplies.txt in front of her, she was shown training
turns about trust points and answered "The reader opens at 50 points".
Andreas, 10 Oct 2026: "Stop the runs and implement now".
"""
import json
import os
import shutil
import tempfile
import unittest

import aetherroot


class TheFileIsTheEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="evidence-")
        d = os.path.join(self.tmp, "aetherroot")
        os.makedirs(d)
        with open(os.path.join(d, "config.json"), "w") as f:
            json.dump(dict(aetherroot.DEFAULT_CONFIG), f)
        self.root = aetherroot.AetherRoot(d)
        for q, a in (("At how many points does builder open?", "Builder opens at 500 points."),
                     ("How many points does the reader level need?", "The reader opens at 50 points."),
                     ("How many kilograms of rice are there?", "There are 3 kg of rice.")):
            self.root.store_interaction(q, a, 0.7, speaker="Trainer")
        self.root.store.add_fact("The rice is kept in the cellar.")

    def tearDown(self):
        self.root.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_with_a_file_read_no_past_turn_is_shown(self):
        report = {}
        ctx = self.root.retrieve_context("Open supplies.txt. How many kilograms of rice?",
                                         report=report, past=False)
        self.assertNotIn("[Episode]", ctx)
        self.assertNotIn("points", ctx)
        self.assertNotIn("3 kg", ctx, "a remembered answer about a file is stale")
        self.assertNotIn("cellar", ctx)
        self.assertTrue(report.get("past_left_out"))
        self.assertEqual(report.get("rings"), [])

    def test_without_one_her_past_comes_back_as_before(self):
        report = {}
        ctx = self.root.retrieve_context("How many kilograms of rice are there?", report=report)
        self.assertIn("[Episode]", ctx)
        self.assertFalse(report.get("past_left_out"))


if __name__ == "__main__":
    unittest.main()
