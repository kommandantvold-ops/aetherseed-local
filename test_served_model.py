"""One served model, named once (logic/served.py, build log step 44).

Before step 44 the served model was written out in six places. A build that
changed one and not the others would answer with one model while the
keepalive held another resident - two models taking turns on one NPU - or
describe itself as a model it does not run. These tests read the unit files
and tools as shipped and fail when any of them disagrees with SERVED_MODEL.
"""
import importlib
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

from logic.served import SERVED_MODEL                       # noqa: E402
from logic import token_budget                              # noqa: E402


def _unit_file(name):
    with open(os.path.join(HERE, "services", name), encoding="utf-8") as f:
        return f.read()


class TestOneServedModel(unittest.TestCase):

    def test_the_proxy_serves_it(self):
        import proxy
        self.assertEqual(proxy.MODEL, SERVED_MODEL)

    def test_the_guard_can_count_it_and_knows_its_ceiling(self):
        prof = token_budget.MODELS.get(SERVED_MODEL)
        self.assertIsNotNone(prof, "no token-budget profile for the served model")
        self.assertTrue(prof.get("ceiling"), "the served model's prompt ceiling is not measured")

    def test_the_unit_describes_the_model_it_runs(self):
        from logic.knowledge import load_knowledge
        k = load_knowledge(os.path.join(HERE, "knowledge", "companion.en.jsonl"))
        line = k.by_id("self.model")
        self.assertIn(SERVED_MODEL, line)
        for e in k.entries:
            self.assertNotIn("{served_model}", e["text"], e["id"])
        others = [m for m in token_budget.MODELS if m != SERVED_MODEL]
        for m in others:
            self.assertNotIn(m, line)

    def test_the_warm_up_loads_it(self):
        body = re.search(r"--data '(\{.*?\})'", _unit_file("aetherseed-warmup.service"))
        self.assertIsNotNone(body)
        self.assertEqual(json.loads(body.group(1))["model"], SERVED_MODEL)

    def test_the_keepalive_holds_it(self):
        unit = _unit_file("aetherseed-keepalive.service")
        m = re.search(r"^Environment=KEEPALIVE_MODEL=(\S+)\s*$", unit, re.M)
        if m:
            held = m.group(1)
        else:                                 # the script's own default
            with open(os.path.join(HERE, "tools", "keepalive.py"), encoding="utf-8") as f:
                src = f.read()
            held = re.search(r'os\.environ\.get\("KEEPALIVE_MODEL", "([^"]+)"\)', src).group(1)
        self.assertEqual(held, SERVED_MODEL)

    def test_the_keepalive_sends_the_model_it_is_given(self):
        env = dict(os.environ)
        try:
            os.environ["KEEPALIVE_DIR"] = "/tmp"
            os.environ["KEEPALIVE_MODEL"] = "some:model"
            sys.modules.pop("keepalive", None)
            ka = importlib.import_module("keepalive")
            self.assertEqual(json.loads(ka.BODY)["model"], "some:model")
            self.assertEqual(ka.MODEL, "some:model")
        finally:
            os.environ.clear()
            os.environ.update(env)
            sys.modules.pop("keepalive", None)

    def test_the_console_names_no_model(self):
        with open(os.path.join(HERE, "gui", "index.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertNotRegex(page, r"model\s*:\s*'")
        for m in token_budget.MODELS:
            self.assertNotIn(m, page)

    def test_the_reading_soak_names_no_model_unless_told(self):
        rs = importlib.import_module("reading_soak")
        self.assertNotIn("model", rs.chat_body("hello"))
        self.assertEqual(rs.chat_body("hello", model="x:1")["model"], "x:1")
        self.assertEqual(rs.chat_body("hello")["speaker"], "Reader")


if __name__ == "__main__":
    unittest.main()
