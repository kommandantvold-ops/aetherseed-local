"""The COG panel's side (logic/cog_console.py, build log 74c).

Andreas, 13 Oct 2026: "Also I would like to trigger and review/correct the
essays."
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

from logic import cog_console as CC
from logic.cog_console import CogConsole, ConsoleError
from training import cog_loop as C


class _Console(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = CC.BASE
        CC.BASE = self.tmp
        self.why = None
        self.removed = []
        # a stand-in harness: records its arguments and exits
        self.args_file = os.path.join(self.tmp, "args.json")
        self.harness = os.path.join(self.tmp, "fake_harness.py")
        with open(self.harness, "w") as f:
            f.write("import json, sys\njson.dump(sys.argv[1:], open(%r, 'w'))\n" % self.args_file)
        self.c = CogConsole("llama3.2:3b", lambda: self.why, self.remove, "tok",
                            python=sys.executable, harness=self.harness)
        C.write_essay(os.path.join(self.c.dir, "essays"), 5, "llama3.2:3b", "ecc.two",
                      "Ecc 4:9-12", "why two are better than one", "Two are better than one.")

    def tearDown(self):
        CC.BASE = self.saved
        shutil.rmtree(self.tmp)

    def remove(self, payload, token):
        self.removed.append((payload, token))
        return 200, {"removed": payload["episode"]}

    def wait(self):
        for _ in range(200):
            if not self.c._running():
                return
            time.sleep(0.02)

    def args(self):
        self.wait()
        with open(self.args_file) as f:
            return json.load(f)


class Starting(_Console):
    def test_start_runs_the_harness_on_this_models_dir(self):
        self.c.start(2)
        self.assertEqual(self.args(), ["--dir", self.c.dir, "--sessions", "2",
                                       "--model", "llama3.2:3b"])
        self.assertTrue(self.c.dir.endswith("llama3.2_3b"))

    def test_refused_when_busy_or_out_of_range(self):
        self.why = "a training run is on"
        with self.assertRaises(ConsoleError) as e:
            self.c.start(1)
        self.assertEqual(e.exception.code, "unit_busy")
        self.why = None
        for bad in (0, 9, "2", None):
            with self.assertRaises(ConsoleError):
                self.c.start(bad)

    def test_one_thing_at_a_time(self):
        with open(self.harness, "w") as f:
            f.write("import time\ntime.sleep(1)\n")
        self.c.start(1)
        with self.assertRaises(ConsoleError) as e:
            self.c.start(1)
        self.assertEqual(e.exception.code, "busy")
        self.assertEqual(self.c.stop(), {"stopping": "after this session"})
        self.assertTrue(os.path.exists(os.path.join(self.c.dir, "STOP")))
        self.assertTrue(self.c.status()["stopping"])
        self.wait()

    def test_a_new_start_clears_an_old_stop(self):
        with open(os.path.join(self.c.dir, "STOP"), "w") as f:
            f.write("x")
        self.c.start(1)
        self.wait()
        self.assertFalse(os.path.exists(os.path.join(self.c.dir, "STOP")))


class Reviewing(_Console):
    def test_waiting_reviewed_reflected_removed(self):
        self.assertEqual(self.c.status()["essays"][0]["state"], "waiting")
        with self.assertRaises(ConsoleError):
            self.c.reflect(5)                       # no review yet
        self.c.review(5, "  Good.  Say where you are unsure. ")
        e = self.c.essay(5)
        self.assertEqual((e["state"], e["review"]), ("reviewed", "Good. Say where you are unsure."))
        self.c.reflect(5)
        self.assertEqual(self.args(), ["--reflect", self.c.dir, "5", "--model", "llama3.2:3b"])
        # as the harness leaves it once stored
        with open(os.path.join(self.c.dir, "reviews", "005.reflection.json"), "w") as f:
            json.dump({"reflection": "I will say where I am unsure.",
                       "stored": {"status": 200, "body": {"stored": 42}}}, f)
        e = self.c.essay(5)
        self.assertEqual((e["state"], e["reflection"]["episode"]), ("reflected", 42))
        with self.assertRaises(ConsoleError) as x:
            self.c.review(5, "changed")             # not under a stored reflection
        self.assertEqual(x.exception.code, "reflected")
        with self.assertRaises(ConsoleError):
            self.c.forget(5, "")                    # a reason is needed
        self.assertEqual(self.c.forget(5, "off the point"), {"removed": 42})
        self.assertEqual(self.removed, [({"episode": 42, "why": "off the point"}, "tok")])
        e = self.c.essay(5)
        self.assertEqual(e["state"], "reviewed")    # the review stands; she may reflect again
        self.assertEqual(e["removed"]["removed"]["why"], "off the point")

    def test_review_limits(self):
        with self.assertRaises(ConsoleError):
            self.c.review(5, "   ")
        with self.assertRaises(ConsoleError):
            self.c.review(5, "x" * (CC.REVIEW_MAX + 1))
        with self.assertRaises(ConsoleError) as e:
            self.c.review(6, "fine")
        self.assertEqual(e.exception.status, 404)


class Correcting(_Console):
    def test_kept_beside_hers_which_never_changes(self):
        self.c.correct(5, "Two are better than one, the Preacher says.")
        _t, hers = C.read_essay(self.c.dir, 5)
        self.assertEqual(hers, "Two are better than one.")
        self.assertEqual(self.c.essay(5)["corrected"], "Two are better than one, the Preacher says.")
        self.assertTrue(self.c.status()["essays"][0]["corrected"])
        self.c.correct(5, "")
        self.assertIsNone(self.c.essay(5)["corrected"])

    def test_her_essay_unchanged_is_not_a_correction(self):
        with self.assertRaises(ConsoleError):
            self.c.correct(5, "Two are better than one.")

    def test_she_reflects_on_the_corrected_text(self):
        self.c.correct(5, "Two are better than one, the Preacher says.")
        os.makedirs(os.path.join(self.c.dir, "reviews"), exist_ok=True)
        self.c.review(5, "Name the verse.")

        class M:
            name = "m"
            def __init__(self):
                self.calls = []
            def fits(self, msgs):
                return True
            def chat(self, msgs, n, stop_at_answer=True, max_seconds=None):
                self.calls.append(msgs)
                return "I will name the verse.", "done", 0.1
        m = M()
        rec = C.reflect(m, self.c.dir, 5, token="t", post=lambda p, t: (200, {"stored": 1}))
        ask = m.calls[0][1]["content"]
        self.assertIn("as your trainer corrected it:\nTwo are better than one, the Preacher says.", ask)
        self.assertNotIn("Your essay on why two are better than one:\n", ask)
        self.assertTrue(rec["corrected"])


class TheReport(_Console):
    def test_status_carries_the_report_and_the_essays(self):
        st = self.c.status()
        self.assertEqual(st["model"], "llama3.2:3b")
        self.assertFalse(st["running"])
        self.assertIn("Essays:", st["report"])
        self.assertEqual(st["essays"][0]["n"], 5)


if __name__ == "__main__":
    unittest.main()
