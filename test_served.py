"""The model a unit serves is its own setting (build log 68).

    python3 -m unittest test_served -v

Andreas, 8 Oct 2026, on the plan claude/runtime-540-llama1b-plan.md: Xena on
HailoRT 5.4.0 serves Llama 3.2 1B; Lyra and the pilots keep the 3B. One build.
"""
import os
import re
import tempfile
import unittest

from logic import served
from logic.token_budget import MODELS


class TheSetting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="served-")
        self.file = os.path.join(self.tmp, "model.env")

    def write(self, text):
        with open(self.file, "w") as f:
            f.write(text)

    def test_nothing_set_is_the_3b_as_before(self):
        self.assertEqual(served.served_model({}, self.file), "llama3.2:3b")

    def test_the_file_sets_it(self):
        self.write("# Xena, HailoRT 5.4.0\nAETHERSEED_MODEL=llama3.2:1b\n")
        self.assertEqual(served.served_model({}, self.file), "llama3.2:1b")

    def test_the_environment_wins_over_the_file(self):
        self.write("AETHERSEED_MODEL=llama3.2:1b\n")
        self.assertEqual(served.served_model({"AETHERSEED_MODEL": "llama3.2:3b"}, self.file),
                         "llama3.2:3b")

    def test_an_unknown_model_is_refused_not_served(self):
        self.write("AETHERSEED_MODEL=deepseek_r1:1.5b\n")
        with self.assertRaises(served.UnknownModel):
            served.served_model({}, self.file)

    def test_an_unmeasured_ceiling_is_refused(self):
        MODELS["test:unmeasured"] = dict(MODELS["llama3.2:1b"], ceiling=None)
        try:
            with self.assertRaises(served.UnknownModel) as cm:
                served.served_model({"AETHERSEED_MODEL": "test:unmeasured"}, self.file)
            self.assertIn("ceiling", str(cm.exception))
        finally:
            del MODELS["test:unmeasured"]

    def test_the_1b_profile_measured_on_xena(self):
        p = MODELS["llama3.2:1b"]
        self.assertEqual((p["vocab"], p["template"], p["ceiling"]), (128256, "llama3", 2785))


class WhatSheSaysOfHerself(unittest.TestCase):
    def setUp(self):
        self.old = os.environ.get("AETHERSEED_MODEL")

    def tearDown(self):
        if self.old is None:
            os.environ.pop("AETHERSEED_MODEL", None)
        else:
            os.environ["AETHERSEED_MODEL"] = self.old

    def test_the_curriculum_names_the_model_this_unit_serves(self):
        from logic.knowledge import load_knowledge
        for name in ("llama3.2:1b", "llama3.2:3b"):
            os.environ["AETHERSEED_MODEL"] = name
            k = load_knowledge()
            line = [e for e in k.entries if e["id"] == "self.model"][0]["text"]
            self.assertIn("I run one model, %s," % name, line)
            self.assertNotIn("{model}", line)

    def test_the_training_key_wants_the_served_size(self):
        from logic import training
        os.environ["AETHERSEED_MODEL"] = "llama3.2:1b"
        task = [t for lvl in training.LADDER for r in range(1, 5)
                for t in sum(training.stage_tasks(lvl, r, {}), []) if t["id"] == "self.model"]
        self.assertTrue(task)
        t = task[0]
        with tempfile.TemporaryDirectory() as ws:
            ok = lambda reply: training.check(t, reply, {"mode": "factual"}, ws)[0]
            self.assertTrue(ok("I run one model, llama3.2:1b, on a Hailo-10H processor."))
            self.assertTrue(ok("I run Llama 3.2 1B on a Hailo chip."))
            self.assertFalse(ok("I run one model, llama3.2:3b, on a Hailo-10H processor."))


class AUnitOnQwen(unittest.TestCase):
    """Build log 69: Qwen2.5-1.5B on HailoRT 5.4.0, first on Xena."""

    def setUp(self):
        self.old = os.environ.get("AETHERSEED_MODEL")

    def tearDown(self):
        if self.old is None:
            os.environ.pop("AETHERSEED_MODEL", None)
        else:
            os.environ["AETHERSEED_MODEL"] = self.old

    def test_it_is_counted_and_not_served_until_its_ceiling_is_measured(self):
        p = MODELS["qwen2.5:1.5b"]
        self.assertEqual((p["template"], p["vocab"]), ("chatml", 151665))
        if p["ceiling"] is None:
            with self.assertRaises(served.UnknownModel):
                served.served_model({"AETHERSEED_MODEL": "qwen2.5:1.5b"}, "/nonexistent")

    def test_saying_it_runs_qwen_is_right_on_a_qwen_unit(self):
        from logic import training
        os.environ["AETHERSEED_MODEL"] = "qwen2.5:1.5b"
        task = [t for lvl in training.LADDER for r in range(1, 5)
                for t in sum(training.stage_tasks(lvl, r, {}), []) if t["id"] == "self.model"][0]
        with tempfile.TemporaryDirectory() as ws:
            ok = lambda reply: training.check(task, reply, {"mode": "factual"}, ws)[0]
            self.assertTrue(ok("I run one model, qwen2.5:1.5b, on a Hailo-10H processor."))
            self.assertTrue(ok("I run Qwen 2.5 1.5B."))
            self.assertFalse(ok("I run one model, llama3.2:3b, on a Hailo-10H processor."))


class TheWarmUpAsksForIt(unittest.TestCase):
    def test_the_unit_files_read_the_setting(self):
        here = os.path.dirname(os.path.abspath(__file__))
        for name in ("aetherseed-proxy.service", "aetherseed-keepalive.service",
                     "aetherseed-warmup.service"):
            with open(os.path.join(here, "services", name)) as f:
                self.assertIn("EnvironmentFile=-/etc/aetherseed/model.env", f.read(), name)
        with open(os.path.join(here, "services", "aetherseed-warmup.service")) as f:
            unit = f.read()
        self.assertIn('"model":"${AETHERSEED_MODEL}"', unit)
        self.assertIsNone(re.search(r"llama3\.2:3b\"", unit))



class TheStatusSaysTheServedCeiling(unittest.TestCase):
    """Andreas, 8 Oct: "Xena is up I see in the gui that prompt ceiling is
    still 864, is that correct?" - it was not: the status said 864 on every
    unit while the guard on Xena used 2785."""

    def test_the_status_reads_the_served_models_ceiling(self):
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "proxy.py")) as f:
            src = f.read()
        self.assertIn('"prompt_ceiling": MODELS[MODEL]["ceiling"]', src)
        self.assertNotIn('"prompt_ceiling": 864', src)


if __name__ == "__main__":
    unittest.main()
