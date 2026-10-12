"""AetherSpark at its edges (build log 71).

    python3 -m unittest test_spark_edges -v

From the AetherSpark review of 10 Oct 2026. Measured there, before the fix:
  - any "calculate/compute/work out/evaluate" message with a comma in it got
    the comma refusal and the model was never asked: "Evaluate my essay,
    thanks", "calculate 2+2, please".
  - a file name was lowered on the way to the tool: "Read the file README.md"
    was answered "There is no file readme.md in my workspace".
  - "notes/../../<workspace>-private/secret.txt" was read: the workspace check
    compared string prefixes.
  - two notes written in the same second by two threads: one was lost.
  - "calculate 10**30/3" showed digits a float made up.
"""
import os
import shutil
import tempfile
import threading
import unittest
from datetime import datetime

import intent_detection as I
from intent_detection import detect_intent, in_workspace
from logic.exact_tools import calculate, count, compare


class _Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="spark71-")
        self.ws = os.path.join(self.tmp, "aetherseed-workspace")
        os.makedirs(os.path.join(self.ws, "notes"))
        for name, text in (("README.md", "Read me first.\n"),
                           ("Draft.TXT", "one two three\n"),
                           ("todo.txt", "- dry the matches\n")):
            with open(os.path.join(self.ws, name), "w") as f:
                f.write(text)
        self.ctx = in_workspace(self.ws)
        self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)
        shutil.rmtree(self.tmp, ignore_errors=True)


class ACommaInASentenceIsNotASum(unittest.TestCase):
    def test_an_ordinary_request_with_a_comma_goes_to_the_model(self):
        for said in ("Evaluate my essay, thanks", "Can you work out what she meant, please?",
                     "Calculate the cost of a trip to Oslo, roughly"):
            got = detect_intent(said)
            self.assertFalse(got and got["intent"] == "calculate", said)

    def test_manners_are_not_part_of_the_sum(self):
        got = detect_intent("calculate 2+2, please")
        self.assertEqual(got["intent"], "calculate")
        self.assertEqual(calculate(got["captures"][0]), "2+2 = 4")

    def test_a_comma_inside_a_number_is_still_not_guessed(self):
        got = detect_intent("calculate 1,500 * 2")
        self.assertEqual(got["intent"], "calculate")
        self.assertIn("comma", calculate(got["captures"][0]))

    def test_the_rounded_decimal_carries_no_made_up_digits(self):
        out = calculate("10**30/3")
        self.assertNotIn("316505293553664", out)
        self.assertIn("3.333333 × 10^29", out)
        self.assertIn("3.333333 × 10^-7", calculate("1/3000000"))
        self.assertEqual(calculate("1/3"), "1/3 = 1/3 (about 0.333333)")


class AFileKeepsItsCapitals(_Workspace):
    def test_a_name_reaches_the_tool_as_typed(self):
        got = detect_intent("Read the file README.md")
        self.assertEqual(got["captures"][0], "README.md")
        self.assertTrue(I._read_file(got["captures"][0]).startswith("File: README.md\n"))

    def test_count_and_compare_find_it_and_name_it_as_written(self):
        got = detect_intent("Count the words in Draft.TXT")
        self.assertEqual(got["intent"], "count")
        self.assertTrue(count(self.ws, got["captures"][0]).startswith("Draft.TXT has"))
        self.assertTrue(count(self.ws, "draft.txt").startswith("Draft.TXT has"))
        self.assertIn("README.md and README.md are the same",
                      compare(self.ws, "readme.md", "README.md"))

    def test_a_name_in_other_capitals_is_the_one_file_it_can_be(self):
        self.assertTrue(I._read_file("readme.md").startswith("File: README.md\n"))

    def test_two_files_it_could_be_and_it_does_not_guess(self):
        for name in ("Plan.txt", "PLAN.txt"):
            with open(os.path.join(self.ws, name), "w") as f:
                f.write(name)
        self.assertEqual(I._read_file("plan.txt"), "[ERROR] File not found: plan.txt")

    def test_search_by_name_whatever_the_capitals(self):
        self.assertIn("README.md", I._search_files("readme"))
        self.assertIn("Draft.TXT", I._search_files("DRAFT"))

    def test_a_todo_keeps_its_capitals_as_before(self):
        got = detect_intent("Add Call Martin to my todo list")
        self.assertEqual(got["intent"], "todo_add")
        self.assertEqual(got["captures"][0], "Call Martin")


class TheListIsMarkdown(_Workspace):
    """Build log 72 (Andreas, 11 Oct 2026: .md, not .txt): the to-do list is
    todo.md. An old todo.txt is carried over once and kept."""

    def test_an_addition_goes_to_todo_md_after_carrying_the_old_list_over(self):
        self.assertEqual(I._append_todo("buy wicks"), "Added to todo: buy wicks")
        with open(os.path.join(self.ws, "todo.md")) as f:
            self.assertEqual(f.read(), "- dry the matches\n- buy wicks\n")
        with open(os.path.join(self.ws, "todo.txt")) as f:
            self.assertEqual(f.read(), "- dry the matches\n", "the old list is kept as it was")

    def test_with_both_todo_md_is_the_list(self):
        with open(os.path.join(self.ws, "todo.md"), "w") as f:
            f.write("- the new list\n")
        self.assertEqual(I._todo_path().name, "todo.md")
        self.assertIn("- the new list", I._read_file(I._todo_path().name))

    def test_with_neither_nothing_is_made_until_something_is_added(self):
        os.remove(os.path.join(self.ws, "todo.txt"))
        self.assertEqual(I._todo_path().name, "todo.md")
        self.assertFalse(os.path.exists(os.path.join(self.ws, "todo.md")))
        I._append_todo("first")
        with open(os.path.join(self.ws, "todo.md")) as f:
            self.assertEqual(f.read(), "- first\n")


class NothingOutsideTheWorkspace(_Workspace):
    def test_a_sibling_folder_with_a_longer_name_is_outside(self):
        private = self.ws + "-private"
        os.makedirs(private)
        with open(os.path.join(private, "secret.txt"), "w") as f:
            f.write("SECRET")
        path = "notes/../../aetherseed-workspace-private/secret.txt"
        self.assertEqual(I._read_file(path), "[ERROR] Path outside workspace.")
        self.assertNotIn("SECRET", count(self.ws, path))


class NoNoteIsWrittenOverAnother(_Workspace):
    def test_notes_in_the_same_second_on_many_threads_all_survive(self):
        fixed = datetime(2026, 10, 10, 19, 43, 44)

        class _Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed
        saved, I.datetime = I.datetime, _Clock
        try:
            barrier = threading.Barrier(8)
            said = []

            def write(n):
                with in_workspace(self.ws):        # a thread starts without the turn's
                    barrier.wait()
                    said.append(I._write_note("note number %d" % n))
            threads = [threading.Thread(target=write, args=(n,)) for n in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            I.datetime = saved
        names = sorted(os.listdir(os.path.join(self.ws, "notes")))
        self.assertEqual(len(names), 8, said)
        texts = set()
        for n in names:
            with open(os.path.join(self.ws, "notes", n)) as f:
                texts.add(f.read().strip().splitlines()[-1])
        self.assertEqual(texts, {"note number %d" % n for n in range(8)})


class TextOnly(unittest.TestCase):
    def test_what_is_not_text_asks_for_no_tool(self):
        for not_text in (None, ["Read the file README.md"], {"a": 1}, 7):
            self.assertIsNone(detect_intent(not_text))


if __name__ == "__main__":
    unittest.main()
