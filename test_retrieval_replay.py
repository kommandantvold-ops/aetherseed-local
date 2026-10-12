"""The replay's word sweep (build log 72): which turns would word-based
retrieval show, at which threshold. Run on a copy of Lyra on 12 Oct; this
checks it counts what it says it counts.

    python3 -m unittest test_retrieval_replay -v
"""
import contextlib
import io
import re
import unittest

import aetherroot as A
from training import retrieval_replay as RR


class TheWordSweep(unittest.TestCase):

    def test_a_question_finds_its_own_turns_and_not_the_others(self):
        asked = {"rice": "How many kilograms of rice are there?",
                 "builder": "At how many points does builder open?"}
        wording = {A._question_key(q): tid for tid, q in asked.items()}
        eps = [{"user_msg": asked["rice"], "ai_msg": "There are 3 kg of rice."},
               {"user_msg": asked["builder"], "ai_msg": "Builder opens at 500 points."},
               {"user_msg": "Genesis 1:1: In the beginning God created the heavens.",
                "ai_msg": "Noted."}]
        mems = [{"res": 0.5, "rec": 1.0, "task": "rice", "trainer": True,
                 "key": A._question_key(asked["rice"])},
                {"res": 0.5, "rec": 1.0, "task": "builder", "trainer": True,
                 "key": A._question_key(asked["builder"])},
                {"res": 0.9, "rec": 1.0, "task": None, "trainer": False,
                 "key": A._question_key(eps[2]["user_msg"])}]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            RR.words_report(wording, mems, eps, 5, RR.rules()["now"])
        text = out.getvalue()
        self.assertIn("words of her questions: 3 turns", text)
        row = re.search(r"T 0\.5, by words\s+([\d.]+)\s+(\d+) \(\s*\d+%\)\s+(\d+)\s+(\d+)\s+(\d+)",
                        text)
        self.assertIsNotNone(row, text)
        shown_q, same, other_training, other, none = row.groups()
        self.assertEqual((float(shown_q), int(same), int(other_training), int(other), int(none)),
                         (1.0, 2, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
