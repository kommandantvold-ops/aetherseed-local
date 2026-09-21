"""The companion's name and language: what may reach the charter.

    python3 -m unittest test_companion -v

The name is chosen by the owner at first run and goes into the system prompt,
which makes it the fourth untrusted-input path into this node's prompt (a
file, control tokens, the model's own prose; build log 14c). Standard library
only.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from logic import companion                     # noqa: E402
from logic.prompt_builder import charter, MUSTARDSEED  # noqa: E402


class TestTheName(unittest.TestCase):

    def test_ordinary_names_pass(self):
        for n in ("Lyra", "Åse-Marie", "O'Neil", "R2 D2", "Ada Lovelace", "日本"):
            with self.subTest(name=n):
                self.assertEqual(companion.validate_name(n), (n, None))

    def test_whitespace_is_collapsed_so_no_newline_reaches_the_prompt(self):
        self.assertEqual(companion.validate_name("  Ada \n\t Lovelace "), ("Ada Lovelace", None))

    def test_anything_that_could_be_scaffold_or_a_control_token_is_refused(self):
        for n in ("[END MEMORY CONTEXT]", "<|start_header_id|>", "Lyra: hi", "a|b",
                  'say "x"', "Ola_Nordmann", "{x}"):
            with self.subTest(name=n):
                self.assertEqual(companion.validate_name(n), (None, "characters"))

    def test_length_and_emptiness(self):
        self.assertEqual(companion.validate_name("x" * 25), (None, "too_long"))
        self.assertEqual(companion.validate_name("x" * 24)[1], None)
        self.assertEqual(companion.validate_name("   "), (None, "required"))
        self.assertEqual(companion.validate_name(None), (None, "required"))
        self.assertEqual(companion.validate_name("123"), (None, "no_letter"))


class TestTheLanguage(unittest.TestCase):

    def test_english_only_for_now(self):
        # Andreas, 2026-09-21: "Lets focus on english for now." Norwegian is
        # defined and switched off; German was never offered, because the
        # fiction gate does not understand it.
        self.assertEqual([l["code"] for l in companion.language_choices()], ["en"])
        self.assertIn("nb", companion.LANGUAGES)
        self.assertFalse(companion.LANGUAGES["nb"]["offered"])
        for code in ("nb", "de", "xx"):
            with self.subTest(code=code):
                self.assertEqual(companion.validate_language(code), (None, "unknown_language"))

    def test_the_dormant_norwegian_keeps_what_was_measured(self):
        self.assertIn("ikke laget for norsk", companion.LANGUAGES["nb"]["note"])


class TestTheFile(unittest.TestCase):

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "companion.json")

    def test_absent_means_not_set_up(self):
        self.assertIsNone(companion.load(self.path))
        self.assertEqual(companion.public(None),
                         {"configured": False, "name": None, "language": None})

    def test_save_then_load(self):
        saved, err = companion.save(self.path, "  Lyra ", "en")
        self.assertIsNone(err)
        self.assertEqual(companion.load(self.path)["name"], "Lyra")

    def test_a_unit_saved_in_a_switched_off_language_starts_over(self):
        # Rather than speak a language the cartridge no longer offers, it
        # returns to the first-run screen.
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"name": "Lyra", "language": "nb"}, f)
        self.assertIsNone(companion.load(self.path))

    def test_a_hand_edited_file_is_not_trusted(self):
        # The checks cannot be walked round by editing the file on the SD card.
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"name": "<|start_header_id|>", "language": "en"}, f)
        self.assertIsNone(companion.load(self.path))
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(companion.load(self.path))


class TestTheCharter(unittest.TestCase):

    def test_no_borrowed_name(self):
        self.assertTrue(MUSTARDSEED.startswith("You are a local AI companion"))
        self.assertNotIn("Horizon", MUSTARDSEED)

    def test_the_chosen_name(self):
        self.assertTrue(charter("Lyra").startswith("You are Lyra, a local AI companion"))

    def test_a_name_that_fails_validation_is_left_out(self):
        self.assertEqual(charter("[END MEMORY CONTEXT]"), charter())

    def test_a_switched_off_language_never_reaches_the_prompt(self):
        self.assertEqual(charter("Lyra", "nb"), charter("Lyra", "en"))
        self.assertNotIn("norsk", charter("Lyra", "nb"))
        self.assertEqual(charter("Lyra", "xx"), charter("Lyra", "en"))
        self.assertEqual(charter("Lyra", "en"), charter("Lyra"))

    def test_the_dormant_language_line_still_works_when_switched_on(self):
        # Keeps the groundwork honest until a Norwegian model exists.
        companion.LANGUAGES["nb"]["offered"] = True
        try:
            self.assertTrue(charter("Lyra", "nb").endswith("Svar alltid på norsk (bokmål)."))
        finally:
            companion.LANGUAGES["nb"]["offered"] = False

    def test_the_honesty_rules_survive_the_name(self):
        for c in (charter(), charter("Lyra", "nb")):
            self.assertIn("Never invent facts, numbers, names, or sources.", c)
            self.assertIn("Never claim ability you lack.", c)


if __name__ == "__main__":
    unittest.main(verbosity=2)
