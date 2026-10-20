"""a lesson restated wrongly is not kept as hers.

    python3 -m unittest test_step85 -v

At the end of a training round the companion is told what she had wrong and
what is true of it, and asked to say it again; the key that failed the answer
reads what she says. A restatement the key does not pass is not remembered as
her own unverified words: said right, it is passed; said wrong, it is
corrected from the key, as any wrong answer is.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from logic import training as T  # noqa: E402
from test_training import TheLoop, _Pupil  # noqa: E402



class InTheLoop(unittest.TestCase):
    """The loop's half: which verdict each restatement is marked with."""

    setUp, loop, wait = TheLoop.setUp, TheLoop.loop, TheLoop.wait

    def run_one(self, badly):
        pupil = _Pupil(self.dir, wrong={t["id"] for t in T._self_pool()})
        pupil.reflects_badly = badly
        loop = self.loop(pupil)
        loop.start(seconds=30)
        s = self.wait(loop, "finished")
        told = [say for _, say in pupil.asked
                if say.startswith(("Training round 1 ", "Also in round 1."))]
        marks = {m[0]: m for m in pupil.marks if m[0] in told}
        return s, loop, told, marks

    def test_said_wrong_it_is_corrected_from_the_key(self):
        s, loop, told, marks = self.run_one(badly=True)
        self.assertEqual(len(told), 2)
        for say in told:
            said, ok, truth = marks[say]
            self.assertIs(ok, False, "not kept as her unchecked words")
            truth_told = say.split("What is true: ", 1)[1].rsplit(" Say that again", 1)[0]
            self.assertEqual(truth, truth_told, "the correction is the truth she was told")
        first = s["rounds"][0]
        self.assertEqual(first["restated"], 0)
        self.assertEqual([r["kept"] for r in first["restatements"]],
                         ["corrected from the key"] * 2)
        self.assertEqual(loop.history()[0]["rounds"][0]["restatements"], first["restatements"])

    def test_said_right_it_is_passed(self):
        s, _, told, marks = self.run_one(badly=False)
        self.assertEqual([marks[say][1:] for say in told], [(True, "")] * 2)
        self.assertEqual([r["ok"] for r in s["rounds"][0]["restatements"]], [True, True])

    def test_a_round_with_nothing_wrong_is_still_her_unchecked_words(self):
        pupil = _Pupil(self.dir, wrong=set())
        loop = self.loop(pupil)
        loop.start(seconds=30)
        s = self.wait(loop, "finished")
        said = [say for _, say in pupil.asked if say.startswith("Training round 1 ")]
        self.assertIn("what are you surest of about yourself?", said[0])
        self.assertIn((said[0], None, ""), pupil.marks, "no key reads it: unverified, as before")
        self.assertEqual(s["rounds"][0]["restatements"], [])


# The proxy's half - what comes back to her, on a throwaway memory - is
# test_training.AtTheProxy.test_a_wrong_restatement_comes_back_as_the_truth
# (it needs that class's setup).


class InTheConsole(unittest.TestCase):

    def test_the_page_says_what_was_kept_in_both_languages(self):
        html = open(os.path.join(HERE, "gui", "index.html"), encoding="utf-8").read()
        self.assertEqual(html.count("trNotKept: (n) =>"), 2)
        self.assertIn("corrected from the key; her words are not kept as a lesson", html)
        self.assertIn("rettet fra fasiten; ordene hennes beholdes ikke som lekse", html)
        self.assertIn("s.trNotKept(r.lessons - (r.restated || 0))", html)


# the imported classes' own tests run in their own modules, not again here
del TheLoop

if __name__ == "__main__":
    unittest.main(verbosity=2)
