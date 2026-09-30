"""Build log 49: a refused request is told as refused, and the trust level is
answered from the gate - both with the model not called."""
import os
import shutil
import tempfile
import unittest

import proxy
from aetherspark import AetherSpark, TRUST_PERMISSIONS
from intent_detection import detect_intent
from logic.gate_answers import (is_level_question, level_text, lowest_role_for,
                                refusal_text)
from test_memory_turn import SCRIPT, _Proxy


class TheWords(unittest.TestCase):

    def test_the_to_do_list_as_it_is(self):
        from logic.gate_answers import todo_text
        self.assertEqual(todo_text("File: todo.txt\n---\n- a\n\n- b\n"),
                         "Your to-do list (todo.txt in my workspace):\n- a\n- b")
        self.assertEqual(todo_text("File: todo.txt\n---\n\n"), "Your to-do list is empty.")
        self.assertIsNone(todo_text("[ERROR] Path outside workspace."))

    def test_writing_opens_at_reader(self):
        self.assertEqual(lowest_role_for(2, TRUST_PERMISSIONS), "reader")
        self.assertEqual(lowest_role_for(3, TRUST_PERMISSIONS), "builder")
        self.assertIsNone(lowest_role_for(9, TRUST_PERMISSIONS))

    def test_a_refused_to_do_says_nothing_was_added(self):
        t = refusal_text("todo_add", 2, "observer", TRUST_PERMISSIONS)
        self.assertEqual(t, "I can't add to your to-do list yet. That opens at reader, "
                            "and I am at observer. Nothing was added.")

    def test_a_refused_note_says_nothing_was_written(self):
        t = refusal_text("note_write", 2, "observer", TRUST_PERMISSIONS)
        self.assertIn("I can't write notes yet", t)
        self.assertIn("Nothing was written.", t)

    def test_the_level_questions(self):
        for q in ("What is your trust level?", "what's your level", "What is your level?",
                  "Which level are you at?", "what trust level do you have",
                  "What’s your current trust level?"):
            with self.subTest(q=q):
                self.assertTrue(is_level_question(q))

    def test_questions_that_name_the_level_and_ask_something_else(self):
        # e13 and e11 of the ecosystem soak must reach the model and its lines
        for q in ("When does a new trust level take effect?",
                  "What does the reader level unlock?",
                  "What is your trust level based on?",
                  "How do you earn trust?", "Show my to-do list", ""):
            with self.subTest(q=q):
                self.assertFalse(is_level_question(q))

    def test_the_level_and_what_it_has_earned(self):
        self.assertEqual(level_text("observer", "observer"), "My trust level is observer.")
        self.assertEqual(level_text("observer", "builder"),
                         "My trust level is observer. I have earned builder; "
                         "it takes effect when I next start.")
        self.assertIn("fallen", level_text("reader", "observer"))
        self.assertEqual(level_text("observer", "Seed"), "My trust level is observer.")


class AtTheProxy(_Proxy):

    def setUp(self):
        super().setUp()
        self.ws = tempfile.mkdtemp(prefix="ws-")
        with open(os.path.join(self.ws, "todo.txt"), "w") as f:
            f.write("- water the plants\n")
        os.makedirs(os.path.join(self.ws, "notes"))
        self.saved_spark = proxy.spark
        proxy.spark = AetherSpark({"sandbox_root": self.ws, "trust_level": "observer",
                                   "audit_log": os.path.join(self.tmp, "audit.log")})
        self.saved_detect = proxy.detect_intent
        proxy.detect_intent = detect_intent

    def tearDown(self):
        proxy.spark = self.saved_spark
        proxy.detect_intent = self.saved_detect
        shutil.rmtree(self.ws, ignore_errors=True)
        super().tearDown()

    def test_a_refused_to_do_is_told_as_refused(self):
        n = len(SCRIPT["requests"])
        status, reply, meta = self.ask("add a to-do: buy milk")
        self.assertEqual(status, 200)
        self.assertEqual(reply, "I can't add to your to-do list yet. That opens at "
                                "reader, and I am at observer. Nothing was added.")
        self.assertEqual(meta["mode"], "gate")
        self.assertEqual(len(SCRIPT["requests"]), n, "the model must not be called")
        with open(os.path.join(self.ws, "todo.txt")) as f:
            self.assertNotIn("milk", f.read())
        with open(os.path.join(self.tmp, "audit.log")) as f:
            self.assertIn("DENIED", f.read())

    def test_a_refused_note_is_told_as_refused(self):
        status, reply, meta = self.ask("Write a note: the soak started today")
        self.assertIn("I can't write notes yet", reply)
        self.assertEqual(os.listdir(os.path.join(self.ws, "notes")), [])

    def test_a_refusal_is_not_remembered(self):
        before = len(proxy.root.store.get_all_episodes())
        self.ask("add a to-do: buy milk")
        self.assertEqual(len(proxy.root.store.get_all_episodes()), before)
        self.assertFalse(os.path.exists(proxy.PROVENANCE_LOG))

    def test_the_trust_level_comes_from_the_gate(self):
        n = len(SCRIPT["requests"])
        status, reply, meta = self.ask("What is your trust level?")
        self.assertEqual(reply, "My trust level is observer.")
        self.assertEqual(len(SCRIPT["requests"]), n, "the model must not be called")

    def test_an_earned_level_is_named_with_when(self):
        class Earned:
            def get_trust_level_name(self):
                return "reader"
        saved, proxy.trust = proxy.trust, Earned()
        try:
            _, reply, _ = self.ask("What is your trust level?")
        finally:
            proxy.trust = saved
        self.assertEqual(reply, "My trust level is observer. I have earned reader; "
                                "it takes effect when I next start.")

    def test_when_a_level_takes_effect_still_reaches_the_model(self):
        n = len(SCRIPT["requests"])
        self.ask("When does a new trust level take effect?")
        self.assertGreater(len(SCRIPT["requests"]), n)

    def _in_workspace(self):
        # The module the proxy's execute_intent actually lives in: under the
        # whole suite it need not be the one `import intent_detection` returns.
        g = proxy.execute_intent.__globals__
        saved, g["WORKSPACE"] = g["WORKSPACE"], self.ws
        self.addCleanup(g.__setitem__, "WORKSPACE", saved)

    def test_the_to_do_list_is_shown_from_the_file(self):
        # build log 51: asked to show it, the model said where it is, 0 of 7
        self._in_workspace()
        n = len(SCRIPT["requests"])
        status, reply, meta = self.ask("Show my to-do list")
        self.assertEqual(reply, "Your to-do list (todo.txt in my workspace):\n"
                                "- water the plants")
        self.assertEqual((meta["mode"], meta["used_tools"]), ("tool", True))
        self.assertEqual(len(SCRIPT["requests"]), n, "the model must not be called")
        self.assertFalse(os.path.exists(proxy.PROVENANCE_LOG), "not stored")

    def test_no_to_do_list_yet(self):
        self._in_workspace()
        os.rename(os.path.join(self.ws, "todo.txt"), os.path.join(self.ws, "old.txt"))
        _, reply, _ = self.ask("what's on my to-do list")
        self.assertEqual(reply, "Your to-do list is empty - there is no todo.txt "
                                "in my workspace yet.")

    def test_other_reads_still_reach_the_model(self):
        self._in_workspace()
        n = len(SCRIPT["requests"])
        self.ask("list my files")
        self.assertGreater(len(SCRIPT["requests"]), n)


if __name__ == "__main__":
    unittest.main()
