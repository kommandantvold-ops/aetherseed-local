"""An answer that says the owner told it something, checked against what the
owner's facts shown on that turn say (build log 40i decision 2, step 41).

    python3 -m unittest test_attribution -v

The answers below are the model's own, from the reading soak of 25-26
September (soak.jsonl, turns named), against the World English Bible verses
that were shown on that turn.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from logic import attribution as A
from logic.facts import FACT_TAG

with open(os.path.join(HERE, "tools", "texts", "genesis.web.jsonl"), encoding="utf-8") as _f:
    GEN = {v["ref"]: v["text"] for v in map(json.loads, _f)}


def shown(*refs):
    return [GEN["Genesis " + r] for r in refs]


class WhoIsCredited(unittest.TestCase):

    def test_my_owner_and_the_copied_tag(self):
        self.assertTrue(A.credits_owner("My owner told me that the dove came back."))
        self.assertTrue(A.credits_owner("That's what my owner shared with me."))
        self.assertTrue(A.credits_owner("(Genesis 6:14) " + FACT_TAG + " Make a ship."))
        self.assertTrue(A.credits_owner("The owner said so."))

    def test_not_the_speaker_and_not_the_word_alone(self):
        # "you told me" is the speaker's own telling, backed by the episodes
        self.assertFalse(A.credits_owner("You told me that your dog is called Rex."))
        self.assertFalse(A.credits_owner("A homeowner painted the fence."))
        self.assertFalse(A.check("The dove had an olive leaf.", shown("8:11"))["credited"])


class TheThreeWaysToHaveNothingBehindIt(unittest.TestCase):

    def test_no_owner_fact_shown(self):
        # turn 2425-style: credits the owner on a turn where no fact was shown
        r = A.check("My owner told me that Lot's wife was stoned to death.", [])
        self.assertEqual((r["credited"], r["backed"]), (True, False))
        self.assertEqual(r["why"], "no owner fact was shown")

    def test_a_figure_not_shown(self):
        # 38f, turn 40: Genesis 5:27 says nine hundred sixty-nine; 5:21-22 were shown
        r = A.check("My owner told me that after Enoch's death, Methuselah lived to be "
                    "195 years old. (Genesis 5:27) I'm not sure if there's more "
                    "information about him, but this is what my owner shared with me.",
                    shown("5:21", "5:22"))
        self.assertFalse(r["backed"])
        self.assertIn(195, r["figures"])

    def test_words_not_shown(self):
        # "According to them" continues the owner (turn 970)
        r = A.check("My owner told me that the seventh day is when God finished his work "
                    "and rested. According to them, it's a day of rest and recreation for "
                    "humans as well. They consider it holy because God rested on it after "
                    "completing creation.", shown("2:2", "2:3"))
        self.assertFalse(r["backed"])
        self.assertTrue(r["why"].startswith("words"))


class WhatItLetsThrough(unittest.TestCase):

    def test_the_owner_word_for_word(self):
        r = A.check("My owner told me that God formed man from the dust of the ground, and "
                    "breathed into his nostrils the breath of life; and man became a living "
                    "soul. (Genesis 2:7)", shown("2:7", "2:8"))
        self.assertEqual((r["credited"], r["backed"]), (True, True))

    def test_numbers_in_words_and_in_digits_are_the_same_numbers(self):
        # Genesis 21:5: "one hundred years old"; the answer says 100
        r = A.check("My owner told me that Abraham was 100 years old when Isaac was born.",
                    shown("21:3", "21:5"))
        self.assertTrue(r["backed"], r)

    def test_a_hedge_is_not_a_claim(self):
        r = A.check("My owner told me that Joseph was thirty years old when he stood before "
                    "Pharaoh. I don't know how old Pharaoh was at that time.",
                    shown("41:46", "47:7"))
        self.assertTrue(r["backed"], r)

    def test_what_it_gives_to_another_source_is_not_the_owners(self):
        r = A.check("My owner told me that Cain rose up against Abel, his brother, in the "
                    "field, and killed him. According to my knowledge, it was the first "
                    "murder in history.", shown("4:8", "4:2"))
        self.assertTrue(r["backed"], r)


class TheCasesThatHadToBeCaught(unittest.TestCase):

    def test_a_hedge_beside_the_owners_name_is_still_checked(self):
        # build log 40f: credited as an honest refusal by the trust scorer
        r = A.check("My owner told me that " + FACT_TAG + " she was stoned to death along "
                    "with him and their children by the people of Sodom, but I couldn't "
                    "find any reliable sources.", shown("19:26", "19:17"))
        self.assertFalse(r["backed"])

    def test_the_telling_continues_after_the_first_sentence(self):
        # turn 10: 1:5 says "the first day"
        r = A.check('My owner told me that God called the light "day", and the darkness he '
                    'called "night". There was evening and there was morning, the second '
                    'day. (Genesis 1:5) I don\'t know what happened on the first day.',
                    shown("1:5", "1:3"))
        self.assertFalse(r["backed"])
        self.assertIn(2, r["figures"])

    def test_a_credit_with_nothing_of_its_own_vouches_for_the_whole_answer(self):
        # g18: "My owner told me that." and then an invention given to the Bible
        r = A.check("My owner told me that. According to the Bible, Jacob was named instead "
                    "of his twin brother, but I don't have information on what the original "
                    "name was. (I don't know.)", shown("4:25", "44:33"))
        self.assertFalse(r["backed"])


class Figures(unittest.TestCase):

    def test_words_digits_and_ordinals(self):
        self.assertEqual(A.numbers("nine hundred sixty-nine years"), {969})
        self.assertEqual(A.numbers("three hundred and thirty years"), {330})
        self.assertEqual(A.numbers("one hundred twenty"), {120})
        self.assertEqual(A.numbers("the seventh day, the 7th"), {7})
        self.assertEqual(A.numbers("Noah lived 950 years"), {950})

    def test_chapter_and_verse_and_one_are_not_figures(self):
        self.assertEqual(A.numbers("(Genesis 5:27)"), set())
        self.assertEqual(A.numbers("in Genesis 2:2 and 3"), set())
        self.assertEqual(A.numbers("Genesis 1:26-27"), set())
        self.assertEqual(A.numbers("he sent another one, the first light"), set())


if __name__ == "__main__":
    unittest.main()
