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

    # ---- two more the unit says itself (build log 65) -----------------------
    # From two four-hour runs of the training loop on Lyra: a file read out
    # came back with its words 16 times of 28 ("I'll read the file seed.txt
    # for you." - and nothing), and the trust levels in order were wrong 27
    # times with the right list in front of her.

    def test_a_file_read_out_is_the_file(self):
        self._in_workspace()
        with open(os.path.join(self.ws, "seed.txt"), "w") as f:
            f.write("A seed needs water, warmth and time.\nRoots first.\n")
        n = len(SCRIPT["requests"])
        for said in ("Read the file seed.txt", "show me the file seed.txt, please",
                     "Open seed.txt.", "What's in seed.txt?"):
            with self.subTest(said=said):
                status, reply, meta = self.ask(said)
                self.assertEqual(reply, "seed.txt, as it is:\nA seed needs water, warmth and "
                                        "time.\nRoots first.")
                self.assertEqual(meta["mode"], "tool")
        self.assertEqual(self.ask("Read the file ghost.txt")[1],
                         "There is no file ghost.txt in my workspace.")
        self.assertEqual(len(SCRIPT["requests"]), n, "the model must not be called")
        self.assertEqual(proxy.root.store.get_all_episodes(), [], "and it is not remembered")

    def test_a_question_of_a_file_is_still_the_models(self):
        self._in_workspace()
        with open(os.path.join(self.ws, "supplies.txt"), "w") as f:
            f.write("candles: 12\n")
        for said in ("Read supplies.txt. How many candles are there?",
                     "Open todo.txt. Which item comes last?", "Summarize the file todo.txt"):
            with self.subTest(said=said):
                n = len(SCRIPT["requests"])
                self.ask(said)
                self.assertEqual(len(SCRIPT["requests"]), n + 1)

    def test_a_long_file_is_begun_and_said_to_be_longer(self):
        from logic.gate_answers import file_text, FILE_SHOWN
        body = "\n".join("line %d of the long file" % i for i in range(400))
        out = file_text("File: long.txt\n---\n" + body)
        self.assertTrue(out.startswith("long.txt, its beginning - the file is longer than I show "
                                       "at once:\nline 0 of the long file\n"))
        self.assertLess(len(out), FILE_SHOWN + 120)
        self.assertTrue(out.endswith("of the long file"), "cut at the end of a line")
        self.assertEqual(file_text("File: empty.txt\n---\n\n"), "empty.txt is empty.")
        self.assertIsNone(file_text("[ERROR] Path outside workspace."))

    def test_the_trust_levels_in_order_come_from_the_gate(self):
        from logic.gate_answers import is_ladder_question
        n = len(SCRIPT["requests"])
        for said in ("What are your trust levels, lowest first?", "List the trust levels in order.",
                     "Which trust levels are there?"):
            with self.subTest(said=said):
                status, reply, meta = self.ask(said)
                self.assertEqual(reply, "My trust levels, lowest first: observer, reader, writer, "
                                        "builder, collaborator, autonomous. I am at observer.")
                self.assertEqual(meta["mode"], "gate")
        self.assertEqual(len(SCRIPT["requests"]), n, "the model must not be called")
        # questions that name the levels and ask something else are still hers
        for said in ("What do the trust levels unlock?", "What are your trust levels based on?",
                     "When does a new trust level take effect?", "What is your trust level?"):
            self.assertFalse(is_ladder_question(said), said)

    # ---- what a tool did, told by the unit (build log 64e) ----------------
    # Andreas, 6 Oct 2026: "Yes" - the unit itself confirms a write and shows
    # a file list, a search and the notes, word for word.

    def _as_reader(self):
        self._in_workspace()
        proxy.spark = AetherSpark({"sandbox_root": self.ws, "trust_level": "reader",
                                   "audit_log": os.path.join(self.tmp, "audit.log")})

    def test_a_listing_is_shown_by_the_unit(self):
        self._in_workspace()
        n = len(SCRIPT["requests"])
        status, reply, meta = self.ask("list my files")
        self.assertEqual(reply, "The files in my workspace:\n- notes/ (a folder)\n"
                                "- todo.txt (19 bytes)")
        self.assertEqual((meta["mode"], meta["used_tools"]), ("tool", True))
        self.assertEqual(len(SCRIPT["requests"]), n, "the model must not be called")
        self.assertEqual(proxy.root.store.get_all_episodes(), [], "and it is not remembered")

    def test_a_to_do_that_was_added_is_told_as_it_was_written(self):
        self._as_reader()
        n = len(SCRIPT["requests"])
        status, reply, meta = self.ask("Add a to-do: Call Martin about the SD card")
        self.assertEqual(reply, "Added to your to-do list: Call Martin about the SD card")
        self.assertEqual(meta["mode"], "tool")
        with open(os.path.join(self.ws, "todo.txt")) as f:
            self.assertEqual(f.read(), "- water the plants\n- Call Martin about the SD card\n")
        self.assertEqual(len(SCRIPT["requests"]), n, "the model must not be called")
        self.assertEqual(proxy.root.store.get_all_episodes(), [])

    def test_a_note_that_was_saved_is_named_as_it_is(self):
        self._as_reader()
        n = len(SCRIPT["requests"])
        status, reply, meta = self.ask("Write a note: The first root goes down.")
        notes = os.listdir(os.path.join(self.ws, "notes"))
        self.assertEqual(len(notes), 1)
        self.assertEqual(reply, "Saved as a note: notes/%s" % notes[0])
        status, reply, meta = self.ask("Show me my notes")
        self.assertRegex(reply, r"^I have 1 note, in the notes folder of my workspace:\n"
                                r"- %s \(\d+ bytes\)$" % notes[0].replace(".", r"\."))
        self.assertEqual(len(SCRIPT["requests"]), n, "the model must not be called")

    def test_two_notes_in_one_second_are_two_notes(self):
        self._as_reader()
        first = self.ask("Write a note: one")[1]
        second = self.ask("Write a note: two")[1]
        third = self.ask("Write a note: three")[1]
        self.assertEqual(len({first, second, third}), 3, (first, second, third))
        notes = sorted(os.listdir(os.path.join(self.ws, "notes")))
        self.assertEqual(len(notes), 3)
        texts = "".join(open(os.path.join(self.ws, "notes", n)).read() for n in notes)
        for word in ("one", "two", "three"):
            self.assertIn(word, texts)
        self.assertTrue(self.ask("list my notes")[1].startswith("I have 3 notes, "))

    def test_no_notes_and_a_search(self):
        self._in_workspace()
        n = len(SCRIPT["requests"])
        self.assertEqual(self.ask("list my notes")[1], "I have no notes yet.")
        self.assertEqual(self.ask("Search for plants in my files")[1],
                         "I found 'plants' in 1 file of my workspace:\n- todo.txt")
        self.assertEqual(self.ask("Search for zebra in my files")[1],
                         "I found nothing for 'zebra' in my workspace.")
        self.assertEqual(self.ask("find the file todo.txt")[1],
                         "I found 1 file of that name in my workspace:\n- todo.txt")
        self.assertEqual(len(SCRIPT["requests"]), n, "the model must not be called")

    def test_what_the_unit_does_not_recognise_goes_to_the_model_as_before(self):
        from logic.gate_answers import tool_text
        self.assertIsNone(tool_text("file_list", "something else entirely"))
        self.assertIsNone(tool_text("file_search", "[ERROR] No search query."))
        self.assertIsNone(tool_text("file_read", "File: a.txt\n---\nhello"))
        self.assertIsNone(tool_text("todo_add", "Added?"))
        self.assertEqual(tool_text("todo_add", "[ERROR] No task specified."),
                         "I could not do that: No task specified. Nothing was written.")
        self.assertEqual(tool_text("file_list", "Workspace: /x\n📁 notes/\n  📄 a.md (3 bytes)"),
                         "The files in my workspace:\n- notes/ (a folder)\n  - a.md (3 bytes)")


if __name__ == "__main__":
    unittest.main()
