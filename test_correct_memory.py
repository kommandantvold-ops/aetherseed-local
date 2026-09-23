"""An operator correction must be reversible, recorded, and destroy nothing.

The barrier it lives beside: the owner cannot tamper with memory from the
console. An operator can, on the device, and the price of that is a trail.

    python3 -m unittest test_correct_memory -v
"""
import contextlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import correct_memory as cm


def make_db(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE episodes (id INTEGER PRIMARY KEY, timestamp TEXT, "
                "mode TEXT, user_msg TEXT, ai_msg TEXT)")
    con.executemany("INSERT INTO episodes VALUES (?,?,?,?,?)", [
        (1, "2026-09-23T14:00:00", "factual", "hello", "Hi, I am Lyra."),
        (2, "2026-09-23T14:01:00", "factual", "what is aetherseed",
         "AetherSeed is a fictional AI companion."),
        (3, "2026-09-23T14:02:00", "fiction", "a poem", "A whale called Bjorn."),
    ])
    con.commit()
    con.close()


class OperatorCorrection(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "memory.db")
        self.log = os.path.join(self.dir, "corrections.log")
        make_db(self.db)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _modes(self):
        con = sqlite3.connect(self.db)
        try:
            return dict(con.execute("SELECT id, mode FROM episodes").fetchall())
        finally:
            con.close()

    def _run(self, *args):
        # The tool prints what it is about to do, by design. A test suite that
        # prints it too is a test suite people stop reading.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            return cm.main(["--db", self.db, "--log", self.log] + list(args))

    def _log(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]

    def test_a_dry_run_changes_nothing(self):
        self.assertEqual(0, self._run("--ids", "2"))
        self.assertEqual("factual", self._modes()[2])
        self.assertEqual([], self._log())

    def test_applying_without_a_reason_is_refused(self):
        self.assertEqual(2, self._run("--ids", "2", "--apply"))
        self.assertEqual("factual", self._modes()[2])
        self.assertEqual([], self._log())

    def test_a_correction_sets_the_mode_and_is_recorded(self):
        self.assertEqual(0, self._run("--ids", "2", "--reason", "it is not fictional",
                                      "--operator", "andreas", "--apply"))
        self.assertEqual("unverified", self._modes()[2])
        entries = self._log()
        self.assertEqual(1, len(entries))
        e = entries[0]
        self.assertEqual(2, e["episode"])
        self.assertEqual("factual", e["mode_before"])
        self.assertEqual("unverified", e["mode_after"])
        self.assertEqual("it is not fictional", e["reason"])
        self.assertEqual("andreas", e["operator"])
        self.assertIn("at", e)

    def test_nothing_else_is_touched(self):
        self._run("--ids", "2", "--reason", "r", "--apply")
        self.assertEqual({1: "factual", 2: "unverified", 3: "fiction"}, self._modes())

    def test_the_episode_text_survives_the_correction(self):
        self._run("--ids", "2", "--reason", "r", "--apply")
        con = sqlite3.connect(self.db)
        try:
            row = con.execute("SELECT user_msg, ai_msg FROM episodes WHERE id=2").fetchone()
        finally:
            con.close()
        self.assertEqual("what is aetherseed", row[0])
        self.assertIn("fictional", row[1])

    def test_a_correction_can_be_put_back(self):
        self._run("--ids", "2", "--reason", "r", "--apply")
        self.assertEqual("unverified", self._modes()[2])
        self.assertEqual(0, self._run("--restore", "--ids", "2",
                                      "--reason", "changed my mind", "--apply"))
        self.assertEqual("factual", self._modes()[2])
        self.assertEqual(2, len(self._log()))
        self.assertTrue(self._log()[-1]["restore"])

    def test_restoring_something_never_corrected_is_refused(self):
        self.assertEqual(2, self._run("--restore", "--ids", "3",
                                      "--reason", "r", "--apply"))
        self.assertEqual("fiction", self._modes()[3])

    def test_an_unknown_episode_is_refused(self):
        self.assertEqual(2, self._run("--ids", "99", "--reason", "r", "--apply"))
        self.assertEqual([], self._log())


class WhatTheCorrectionMeansToRetrieval(unittest.TestCase):
    """The point of the mode change: the answer never comes back as context."""

    def test_unverified_is_invisible_to_both_request_modes(self):
        from logic.provenance import visible_modes
        self.assertNotIn("unverified", visible_modes("factual"))
        self.assertNotIn("unverified", visible_modes("fiction"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
