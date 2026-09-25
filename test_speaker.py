"""Who said it - stored with the turn, shown to the model, set by an operator.

Step 36 (25 Sep 2026). Every stored turn used to read "User:" in the memory
block, whoever typed it. After 66 turns from Claude the node said "I exist
solely for Claude's use", and an error of Claude's was stored in the owner's
voice (build log 35). The proxy-level tests are in test_reply.TestWhoIsSpeaking;
these cover the rules, the store, the migration and the operator tool.

Every test runs in a throwaway directory. Nothing here touches a unit.
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
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from aetherroot import AetherRoot
from logic.speaker import OWNER, UNKNOWN, label_for, validate_speaker

sys.path.insert(0, str(HERE / "tools"))
import correct_memory  # noqa: E402


class TheRules(unittest.TestCase):

    def test_declaring_nothing_is_the_owner(self):
        self.assertEqual((OWNER, None), validate_speaker(None))

    def test_a_clean_name_is_kept_as_given(self):
        self.assertEqual(("Claude", None), validate_speaker("Claude"))
        self.assertEqual(("Ada Lovelace", None), validate_speaker("  Ada   Lovelace "))
        self.assertEqual(("Øystein", None), validate_speaker("Øystein"))

    def test_reserved_labels_can_never_be_declared(self):
        for name in ("Owner", "owner", "OWNER", "User", "AI", "assistant", "system",
                     "Known", "Episode", "Pattern", "Fiction", "you", "Unknown"):
            with self.subTest(name=name):
                self.assertEqual((None, "reserved"), validate_speaker(name))

    def test_the_companion_cannot_be_declared(self):
        self.assertEqual((None, "reserved"), validate_speaker("Lyra", companion_name="Lyra"))
        self.assertEqual((None, "reserved"), validate_speaker("lyra", companion_name="Lyra"))
        self.assertEqual(("Lyra", None), validate_speaker("Lyra", companion_name=None))

    def test_anything_that_could_forge_a_line_is_refused(self):
        for bad in ("Claude: hi", "[Known] x", "a|b", "<|eot_id|>", '"x"', "x" * 25, "", "123"):
            with self.subTest(bad=bad):
                name, err = validate_speaker(bad)
                self.assertIsNone(name)
                self.assertIsNotNone(err)

    def test_labels(self):
        self.assertEqual("User", label_for(UNKNOWN))
        self.assertEqual("User", label_for(None))
        self.assertEqual("Owner", label_for(OWNER))
        self.assertEqual("Claude", label_for("Claude"))


class _Root(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.root = AetherRoot(self.dir)

    def tearDown(self):
        self.root.store.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def context(self, q):
        return self.root.retrieve_context(q, request_mode="factual")


class TheModelSeesWhoSaidIt(_Root):

    def test_each_speaker_is_named_in_the_memory_block(self):
        self.root.store_interaction("My cat is called Tussi.", "Noted.", speaker=OWNER)
        self.root.store_interaction("Claude here. Vega is in Lyra.", "Thank you.",
                                    speaker="Claude")
        ctx = self.context("Tussi cat Vega Lyra")
        self.assertIn("[Episode] Owner: My cat is called Tussi.", ctx)
        self.assertIn("[Episode] Claude: Claude here. Vega is in Lyra.", ctx)
        self.assertNotIn("User:", ctx)

    def test_a_turn_stored_without_a_speaker_reads_exactly_as_before(self):
        self.root.store_interaction("My cat is called Tussi.", "Noted.")
        self.assertIn("[Episode] User: My cat is called Tussi.", self.context("Tussi cat"))

    def test_the_speaker_is_returned_with_the_episode(self):
        self.root.store_interaction("hello", "hi", speaker="Claude")
        (ep,) = self.root.store.get_all_episodes()
        self.assertEqual("Claude", ep["speaker"])


class TheMigration(unittest.TestCase):
    """A unit upgraded in place: its table predates the column."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        db = os.path.join(self.dir, "memory.db")
        con = sqlite3.connect(db)
        con.executescript("""
            CREATE TABLE episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
                session_id TEXT NOT NULL, user_msg TEXT NOT NULL, ai_msg TEXT NOT NULL,
                embedding BLOB NOT NULL, resonance REAL NOT NULL DEFAULT 0.5,
                topic_tags TEXT DEFAULT '', consolidated INTEGER DEFAULT 0,
                mode TEXT NOT NULL DEFAULT 'factual');
        """)
        import numpy as np
        con.execute("INSERT INTO episodes (timestamp, session_id, user_msg, ai_msg, embedding) "
                    "VALUES ('2026-09-23T14:04:00+00:00', 's', 'My cat is called Tussi.', "
                    "'Noted.', ?)", (np.zeros(64, dtype=np.float32).tobytes(),))
        con.commit()
        con.close()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_the_column_is_added_and_old_rows_claim_nothing(self):
        root = AetherRoot(self.dir)
        try:
            cols = {r[1] for r in root.store.conn.execute("PRAGMA table_info(episodes)")}
            self.assertIn("speaker", cols)
            (ep,) = root.store.get_all_episodes()
            self.assertEqual(UNKNOWN, ep["speaker"])
            self.assertIn("[Episode] User: My cat", root.retrieve_context("Tussi cat"))
        finally:
            root.store.close()


class TheOperatorTool(_Root):
    """tools/correct_memory.py --speaker: dry run, a reason, a trail, a way back."""

    def setUp(self):
        super().setUp()
        for i in range(3):
            self.root.store_interaction(f"old turn {i}", "ok")      # unknown speaker
        self.db = str(Path(self.dir) / "memory.db")
        self.log = str(Path(self.dir) / "corrections.log")

    def run_tool(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = correct_memory.main(["--db", self.db, "--log", self.log,
                                        "--operator", "test", *args])
        return code, out.getvalue() + err.getvalue()

    def speakers(self):
        return {e["id"]: e["speaker"] for e in self.root.store.get_all_episodes()}

    def test_a_dry_run_changes_nothing(self):
        code, _ = self.run_tool("--ids", "1,2", "--speaker", "Claude")
        self.assertEqual(0, code)
        self.assertEqual({1: "", 2: "", 3: ""}, self.speakers())
        self.assertFalse(os.path.exists(self.log))

    def test_applying_needs_a_reason(self):
        code, out = self.run_tool("--ids", "1", "--speaker", "Claude", "--apply")
        self.assertEqual(2, code)
        self.assertIn("reason", out)
        self.assertEqual("", self.speakers()[1])

    def test_it_sets_logs_and_puts_back(self):
        code, _ = self.run_tool("--ids", "1,2", "--speaker", "Claude",
                                "--reason", "guided rings", "--apply")
        self.assertEqual(0, code)
        self.assertEqual({1: "Claude", 2: "Claude", 3: ""}, self.speakers())
        with open(self.log, encoding="utf-8") as f:
            lines = [json.loads(l) for l in f]
        self.assertEqual({"set_speaker"}, {l["action"] for l in lines})
        self.assertEqual({("", "Claude")}, {(l["speaker_before"], l["speaker_after"])
                                             for l in lines})
        code, _ = self.run_tool("--ids", "1", "--restore-speaker",
                                "--reason", "undo", "--apply")
        self.assertEqual(0, code)
        self.assertEqual({1: "", 2: "Claude", 3: ""}, self.speakers())

    def test_the_operator_may_attribute_to_the_owner(self):
        code, _ = self.run_tool("--ids", "3", "--speaker", "owner",
                                "--reason", "Andreas confirmed", "--apply")
        self.assertEqual(0, code)
        self.assertEqual(OWNER, self.speakers()[3])
        self.assertIn("[Episode] Owner: old turn 2", self.context("old turn 2"))

    def test_a_bad_name_is_refused_here_too(self):
        for bad in ("AI", "Claude: hi", "Known"):
            with self.subTest(bad=bad):
                code, out = self.run_tool("--ids", "1", "--speaker", bad,
                                          "--reason", "x", "--apply")
                self.assertEqual(2, code)
                self.assertIn("refused", out)
        self.assertEqual("", self.speakers()[1])

    def test_a_mode_change_still_works_and_now_shows_the_speaker(self):
        code, out = self.run_tool("--ids", "1", "--reason", "x", "--apply")
        self.assertEqual(0, code)
        self.assertIn("speaker=(unknown)", out)


if __name__ == "__main__":
    unittest.main()
