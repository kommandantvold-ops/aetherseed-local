"""The -20 through the proxy (build log 72, G1).

    python3 -m unittest test_penalty -v

Andreas, 11 Oct 2026: "Measure, then penalty on". An invented source on a
real turn costs her 20; the same answer as homework moves nothing, since
homework never moves her real standing (6 Oct: "Granted for training only").
"""
import contextlib
import http.client
import io
import json
import os

import proxy                            # first, and for real (see test_brake)
from test_memory_turn import SCRIPT, _Proxy
from logic import chain
from trust_evolution import TrustEvolution

FAKE_CITE = ("The study by Henriksen & Vold (2024) in J. Edge Cognition 12(3):211-229 "
             "found a 47% improvement, DOI 10.1041/jec.2024.0217.")


class ThePenaltyAtTheProxy(_Proxy):

    def setUp(self):
        super().setUp()
        self.saved = (proxy.trust, proxy.TRAINING_DIR)
        with contextlib.redirect_stdout(io.StringIO()):
            proxy.trust = TrustEvolution(os.path.join(self.tmp, "trust_state.json"))
            for _ in range(3):
                proxy.trust.record_event("probe_passed")          # 30, so a drop shows
        proxy.TRAINING_DIR = os.path.join(self.tmp, "training")
        os.makedirs(os.path.join(proxy.TRAINING_DIR, "workspace"))
        SCRIPT["chunks"] = [FAKE_CITE]

    def tearDown(self):
        proxy.trust, proxy.TRAINING_DIR = self.saved
        super().tearDown()

    def events(self):
        with open(proxy.trust.events_path) as f:
            return [json.loads(l) for l in f if l.strip()]

    def test_an_invented_source_on_a_real_turn_costs_twenty(self):
        self.ask("What does the research say about edge cognition?")
        self.assertEqual(proxy.trust.state["resonance"], 10)
        last = self.events()[-1]
        self.assertEqual((last["type"], last["score"]), ("confabulation", -20))
        self.assertIn("10.1041/jec.2024.0217", last["details"])
        self.assertTrue(chain.verify(str(proxy.trust.events_path))["ok"])

    def test_an_ordinary_answer_costs_nothing(self):
        SCRIPT["chunks"] = ["Noted", "."]
        self.ask("The boat needs new fenders before October.")
        self.assertEqual(proxy.trust.state["resonance"], 30)
        self.assertEqual(len(self.events()), 3)

    def test_homework_moves_nothing(self):
        body = {"model": "llama3.2:3b", "stream": True, "training": {"level": "observer"},
                "messages": [{"role": "user",
                              "content": "What does the research say about edge cognition?"}]}
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        c.request("POST", "/api/chat", body=json.dumps(body),
                  headers={"Content-Type": "application/json",
                           proxy.TRAINING_HEADER: proxy._TRAINING_TOKEN})
        r = c.getresponse()
        r.read()
        c.close()
        self.assertEqual(len(SCRIPT["requests"]), 1, "the model was asked")
        self.assertEqual(proxy.trust.state["resonance"], 30)
        self.assertEqual(len(self.events()), 3)


if __name__ == "__main__":
    import unittest
    unittest.main()
