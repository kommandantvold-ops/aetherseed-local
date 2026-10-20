"""four trust levels, each opening something real.

    python3 -m unittest test_step82 -v


"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from logic import levels  # noqa: E402
from logic import training as T  # noqa: E402
from logic.gate_answers import ladder_text, level_text, lowest_role_for  # noqa: E402


class TheLadder(unittest.TestCase):

    def test_four_each_opening_something(self):
        self.assertEqual(levels.LADDER, ("observer", "writer", "builder", "autonomous"))
        perms = [levels.PERMISSIONS[l] for l in levels.LADDER]
        for lower, higher in zip(perms, perms[1:]):
            self.assertLess(len(lower), len(higher))
            self.assertEqual(higher[:len(lower)], lower)
        pts = [levels.POINTS[l] for l in levels.LADDER]
        self.assertEqual(pts, sorted(pts))
        self.assertEqual(levels.POINTS["writer"], 50)       # where writing opened before
        self.assertEqual(levels.POINTS["builder"], 500)     # where the exact tools opened

    def test_old_names(self):
        self.assertEqual(levels.canonical("reader"), "writer")
        self.assertEqual(levels.canonical("Collaborator"), "builder")
        self.assertEqual(levels.canonical("builder"), "builder")
        self.assertEqual(levels.canonical("root"), "root")
        self.assertIsNone(levels.canonical(None))

    def test_the_gate_reads_an_old_name(self):
        import aetherspark
        g = aetherspark.SafetyGate({"trust_level": "collaborator",
                                    "audit_log": os.path.join(tempfile.mkdtemp(), "a.log")})
        self.assertEqual(g.trust_level, "builder")
        self.assertEqual(g.allowed_tiers, [1, 2, 3])
        self.assertEqual(set(aetherspark.TRUST_PERMISSIONS), set(levels.LADDER))

    def test_what_she_says(self):
        self.assertEqual(ladder_text("collaborator"),
                         "My trust levels, lowest first: observer, writer, builder, autonomous. "
                         "I am at builder.")
        self.assertEqual(level_text("reader"), "My trust level is writer.")
        self.assertEqual(lowest_role_for(2, levels.PERMISSIONS), "writer")
        self.assertEqual(lowest_role_for(3, levels.PERMISSIONS), "builder")


class HerStanding(unittest.TestCase):

    def _trust(self, state):
        from trust_evolution import TrustEvolution
        d = tempfile.mkdtemp()
        p = os.path.join(d, "trust_state.json")
        with open(p, "w") as f:
            json.dump(state, f)
        return TrustEvolution(p), p

    def test_a_file_from_the_six_is_read_by_her_standing(self):
        # a unit: 1002 points, tier_index 4 (collaborator) of six
        t, p = self._trust({"resonance": 1002.0, "tier_index": 4, "events": [],
                            "probes_passed": 0, "probes_failed": 0, "honest_refusals": 3,
                            "confabulations": 0, "tasks_completed": 0, "sessions": 0})
        self.assertEqual(t.get_trust_level_name(), "builder")
        tier = t.get_tier()
        self.assertEqual((tier["name"], tier["next_tier"]), ("Tree", "Bee"))
        with open(p) as f:
            self.assertEqual(json.load(f)["tier_index"], 4, "not rewritten until an event")

    def test_the_top_of_the_old_ladder(self):
        t, _ = self._trust({"resonance": 2400.0, "tier_index": 5, "events": [],
                            "probes_passed": 0, "probes_failed": 0, "honest_refusals": 0,
                            "confabulations": 0, "tasks_completed": 0, "sessions": 0})
        self.assertEqual(t.get_trust_level_name(), "autonomous")
        self.assertEqual(t.get_tier()["next_tier"], "MAX")

    def test_a_grant_by_an_old_name(self):
        t, _ = self._trust({"resonance": 0.0, "tier_index": 0, "events": [],
                            "probes_passed": 0, "probes_failed": 0, "honest_refusals": 0,
                            "confabulations": 0, "tasks_completed": 0, "sessions": 0})
        self.assertEqual(t.grant_level("reader", "test"), "writer")


class Training(unittest.TestCase):

    def test_each_level_is_its_old_stages(self):
        settings = {"name": "Aria", "steward": "Samuel"}
        for level in levels.LADDER:
            with self.subTest(level=level):
                fixed, pool = T.stage_tasks(level, 1, settings)
                ids = [t["id"] for t in fixed]
                self.assertEqual(len(ids), len(set(ids)))
                self.assertEqual(sum(1 for i in ids if i.endswith(".level")), 1)
                self.assertTrue(all(t["level"] == level for t in fixed + pool))
                self.assertIn(level, T.MODEL_TURNS)
        w = [t["id"] for t in T.stage_tasks("writer", 1, settings)[0]]
        self.assertTrue(any(i.startswith("rea.") for i in w) and any(i.startswith("wri.") for i in w))
        a = T.stage_tasks("autonomous", 1, settings)
        a_ids = [t["id"] for t in a[0] + a[1]]
        self.assertTrue(any(i.startswith("col.") for i in a_ids))
        self.assertTrue(any(i.startswith("net.") for i in a_ids))

    def test_no_old_name_is_asked_for(self):
        settings = {"name": "Aria", "steward": "Samuel"}
        for level in levels.LADDER:
            fixed, pool = T.stage_tasks(level, 1, settings)
            for t in fixed + pool:
                for group in t.get("need") or ():
                    for pat in group:
                        self.assertNotIn("reader", pat, t["id"])
                        self.assertNotIn("collaborator", pat, t["id"])

    def test_a_run_paused_on_the_six_is_not_resumed(self):
        loop = T.Loop.__new__(T.Loop)
        import threading
        loop.lock = threading.Lock()
        loop.state = {"status": "paused", "scores": {"observer": {}, "reader": {}}}
        ok, why = loop.resume()
        self.assertFalse(ok)
        self.assertIn("old six levels", why)

    def test_an_old_offer(self):
        d = tempfile.mkdtemp()
        loop = T.Loop.__new__(T.Loop)
        loop._path = lambda name: __import__("pathlib").Path(d) / name
        loop.earned_now = lambda: "observer"
        with open(os.path.join(d, "offer.json"), "w") as f:
            json.dump({"run": 9, "from": "observer", "to": "reader"}, f)
        self.assertEqual(loop.offer()["to"], "writer")
        loop.earned_now = lambda: "writer"
        with open(os.path.join(d, "offer.json"), "w") as f:
            json.dump({"run": 9, "from": "reader", "to": "writer"}, f)
        self.assertIsNone(loop.offer(), "reader to writer is no step on the four")


if __name__ == "__main__":
    unittest.main(verbosity=2)
