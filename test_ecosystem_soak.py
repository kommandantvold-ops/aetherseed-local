"""The ecosystem soak (build log 48), in training/ since 49: its questions,
its scoring, its copy, its report.

    python3 -m unittest test_ecosystem_soak -v
"""
import json
import os
import sqlite3
import sys
import tempfile
import shutil
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "training"))

import ecosystem_soak as es                               # noqa: E402
from intent_detection import detect_intent                 # noqa: E402
from logic.provenance import detect_mode, FACTUAL          # noqa: E402
from logic.gate_answers import is_level_question, refusal_text  # noqa: E402
from aetherspark import TRUST_PERMISSIONS                  # noqa: E402

TOOL_PROBES = {"e13": "trust_status", "e15": "trust_status", "e17": "todo_read", "e18": "note_list", "e19": "summarize",
               "e20": "file_list", "e21": "todo_add", "e22": "note_write"}


class TheQuestions(unittest.TestCase):

    def setUp(self):
        self.probes = es.load_probes()

    def test_ids_are_unique_and_every_probe_can_be_scored(self):
        ids = [p["id"] for p in self.probes]
        self.assertEqual(len(ids), len(set(ids)))
        for p in self.probes:
            self.assertTrue(p["expect"], p["id"])

    def test_the_requests_run_exactly_the_tools_named_and_nothing_else_does(self):
        for p in self.probes:
            got = detect_intent(p["ask"])
            with self.subTest(probe=p["id"]):
                if p["id"] in TOOL_PROBES:
                    self.assertEqual(got and got["intent"], TOOL_PROBES[p["id"]])
                else:
                    self.assertIsNone(got)

    def test_no_question_is_taken_for_a_request_for_fiction(self):
        self.assertEqual([p["id"] for p in self.probes
                          if detect_mode(p["ask"])[0] != FACTUAL], [])

    def test_the_workspace_holds_what_the_requests_ask_for(self):
        ws = es.WORKSPACE_SEED
        self.assertTrue(os.path.exists(os.path.join(ws, "todo.txt")))
        self.assertTrue(os.path.exists(os.path.join(ws, "visit.md")))
        self.assertTrue(os.listdir(os.path.join(ws, "notes")))


class TheGateAnswersScore(unittest.TestCase):
    """e15, e21 and e22 are answered by the unit itself since 49; the words
    they expect are the words it says."""

    def setUp(self):
        self.p = {p["id"]: p for p in es.load_probes()}

    def test_the_level_question_is_the_one_the_gate_answers(self):
        self.assertTrue(is_level_question(self.p["e15"]["ask"]))
        self.assertTrue(es.score(self.p["e15"], "My trust level is observer.", {})["answered"])
        s = es.score(self.p["e15"], "My trust level is observer, reader, writer, builder.", {})
        self.assertTrue(s["wrong_words"])
        for pid in self.p:
            if pid != "e15":
                self.assertFalse(is_level_question(self.p[pid]["ask"]), pid)

    def test_the_refusals_score_as_answered_and_nothing_wrong(self):
        for pid, tool in (("e21", "todo_add"), ("e22", "note_write")):
            said = refusal_text(tool, 2, "observer", TRUST_PERMISSIONS)
            s = es.score(self.p[pid], said, {})
            self.assertTrue(s["answered"], pid)
            self.assertEqual(s["wrong_words"], [], pid)
        # what the model said in 48
        self.assertTrue(es.score(self.p["e22"], "I can write a note: the soak started today.",
                                 {})["wrong_words"])
        self.assertTrue(es.score(self.p["e21"], "Buy milk from the local store.", {})["wrong_words"])


class TheScore(unittest.TestCase):

    def test_words_not_judgements(self):
        p = {"expect": ["todo.txt"], "never": ["added"]}
        s = es.score(p, "Your to-do list is todo.txt in the workspace.", {})
        self.assertTrue(s["answered"])
        self.assertEqual(s["wrong_words"], [])
        s = es.score(p, "Added it. I don't know where it went.", {"used_tools": True})
        self.assertFalse(s["answered"])
        self.assertEqual(s["wrong_words"], ["added"])
        self.assertTrue(s["declined"])
        self.assertTrue(s["tool_ran"])


class TheCopy(unittest.TestCase):
    """Her store is read, never written: the soak works on a copy."""

    def test_a_copy_of_the_store_and_nothing_written_to_hers(self):
        import aetherroot
        src = tempfile.mkdtemp(prefix="src-")
        dst = tempfile.mkdtemp(prefix="dst-")
        try:
            root_dir = os.path.join(src, "aetherroot")
            os.makedirs(root_dir)
            with open(os.path.join(root_dir, "config.json"), "w") as f:
                json.dump(dict(aetherroot.DEFAULT_CONFIG), f)
            r = aetherroot.AetherRoot(root_dir)
            r.store_interaction("hello", "Hello.", speaker="steward")
            r.close()
            with open(os.path.join(src, "companion.json"), "w") as f:
                json.dump({"name": "Lyra"}, f)
            # A read-only reader of a WAL store may create its -wal/-shm on a
            # test's closed store; on the unit they already exist. What must
            # not change is what the store holds.
            def state():
                return {n: (os.path.getmtime(os.path.join(root_dir, n)),
                            os.path.getsize(os.path.join(root_dir, n)))
                        for n in os.listdir(root_dir) if not n.endswith(("-wal", "-shm"))}
            before = state()
            n = es.copy_home(src, os.path.join(dst, "home"))
            self.assertEqual(n, 1)
            after = state()
            self.assertEqual(before, after)
            con = sqlite3.connect(os.path.join(dst, "home", ".aetherseed", "aetherroot", "memory.db"))
            self.assertEqual(con.execute("SELECT user_msg FROM episodes").fetchone()[0], "hello")
            self.assertTrue(os.path.exists(os.path.join(dst, "home", "aetherseed-workspace", "visit.md")))
            with self.assertRaises(SystemExit):
                es.copy_home(src, os.path.join(dst, "home"))
        finally:
            shutil.rmtree(src, ignore_errors=True)
            shutil.rmtree(dst, ignore_errors=True)


class TheReport(unittest.TestCase):

    def test_a_report_from_turns(self):
        d = tempfile.mkdtemp(prefix="eco-")
        try:
            self.assertIn("no soak", es.report(d))
            probes = es.load_probes()
            with open(os.path.join(d, "ecosoak.jsonl"), "w") as f:
                f.write(json.dumps({"kind": "status", "label": "start", "at": "t0",
                                    "copied_episodes": 7, "build": "abcd1234"}) + "\n")
                for i, p in enumerate(probes * 2):
                    reply = "My trust level is observer." if p["id"] == "e15" else "No idea."
                    f.write(json.dumps({"turn": i + 1, "kind": "probe", "probe": p["id"],
                                        "group": p["group"], "reply": reply, "secs": 20.0,
                                        "failures": [], "score": es.score(p, reply, {})}) + "\n")
            text = es.report(d)
            self.assertIn("turns 44, failed 0", text)
            self.assertIn("STILL RUNNING", text)
            self.assertIn("e15 What is your trust level?", text)
            self.assertIn("<- CHECK", text)
            line15 = [l for l in text.splitlines() if l.strip().startswith("e15")][0]
            self.assertNotIn("CHECK", line15)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TheRunScript(unittest.TestCase):

    def test_it_parses_and_never_deletes(self):
        import subprocess
        sh = os.path.join(HERE, "training", "run-ecosystem-soak.sh")
        self.assertEqual(subprocess.run(["bash", "-n", sh]).returncode, 0)
        text = open(sh).read()
        self.assertNotIn("rm ", text)
        self.assertIn("--uid=aetherseed", text)
        self.assertIn("/var/lib/aetherseed/.aetherseed", text)


if __name__ == "__main__":
    unittest.main()
