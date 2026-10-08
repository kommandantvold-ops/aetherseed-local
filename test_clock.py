"""The date, said by the unit from its own clock (build log 67).

    python3 -m unittest test_clock -v
"""
import unittest
from datetime import datetime

from logic.clock import is_date_question, date_text


class TheDate(unittest.TestCase):
    def test_what_is_asked(self):
        for q in ("What's the date?", "What is the date today?", "what date is it", "What day is it today?",
                  "Today's date?", "What time is it?", "What's the time?", "What year is it?",
                  "Do you know the date?", "Can you tell me the time?",
                  "Hvilken dato er det i dag?", "Hva er datoen?", "Hva er klokka?", "Hvor mye er klokken?",
                  "Hvilken dag er det?"):
            with self.subTest(q=q):
                self.assertTrue(is_date_question(q))

    def test_what_is_not(self):
        for q in ("What's the date of the Battle of Hastings?", "What is the date on the receipt?",
                  "Is there an update?", "I have a date with Ada on Friday.",
                  "What's the time in Tokyo?", "Update the date in notes.md",
                  "When was AetherSeed founded?", "What is a date palm?",
                  "Read the file dates.txt and tell me what is the date for each event in it, "
                  "one per line, and then compare them with what you remember of each one."):
            with self.subTest(q=q):
                self.assertFalse(is_date_question(q))

    def test_it_says_where_the_date_comes_from_and_how_far_to_believe_it(self):
        when = datetime(2026, 10, 8, 14, 5)
        en = date_text(when, "en")
        self.assertTrue(en.startswith("By my own clock it is Thursday 8 October 2026, 14:05."))
        self.assertIn("no clock battery", en)
        self.assertIn("behind", en)
        nb = date_text(when, "nb")
        self.assertTrue(nb.startswith("Etter min egen klokke er det torsdag 8. oktober 2026, kl. 14.05."))
        self.assertIn("klokkebatteri", nb)
        self.assertEqual(date_text(when, "xx"), en)


if __name__ == "__main__":
    unittest.main()
