"""training files - the steward's own questions.

    python3 -m unittest test_step83 -v


what she keeps: "Answers, not text".
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from logic import user_training as UT  # noqa: E402
from logic import training as T  # noqa: E402
from test_memory_turn import _Proxy, proxy  # noqa: E402

GOOD = """title: My garden
document: Garden notes
# a comment

Q: When is the cherry tree planted?
A: On Saturday, by the north wall.
KEY: saturday/sat; north wall
NOT: sunday

Q: Which variety is the cherry tree?
Q: What kind of cherry did we plant?
A: A Lapins cherry.
KEY: lapins
"""


class TheFile(unittest.TestCase):

    def test_a_good_file(self):
        meta, items, errors = UT.parse(GOOD)
        self.assertEqual(errors, [])
        self.assertEqual(meta, {"title": "My garden", "document": "Garden notes"})
        self.assertEqual(len(items), 2)
        self.assertEqual(items[1]["say"], ["Which variety is the cherry tree?",
                                           "What kind of cherry did we plant?"])
        self.assertEqual(len(items[0]["key"]), 2)
        self.assertEqual(len(items[0]["never"]), 1)

    def test_what_is_wrong_is_said_by_line(self):
        for text, part in (("Q: one?\nA: yes\n", "no KEY"),
                           ("Q: one?\nKEY: x\n", "no A"),
                           ("A: before\n", "before any Q"),
                           ("hello there\n", "not a field"),
                           ("Q: " + "x" * 500 + "\n", "longer than"),
                           ("# only a comment\n", "no questions")):
            with self.subTest(text=text[:20]):
                _, items, errors = UT.parse(text)
                self.assertTrue(any(part in e for e in errors), errors)

    def test_the_key_is_words_never_code(self):
        _, items, _ = UT.parse("Q: q?\nA: a\nKEY: (.*)|x; a+b\n")
        task = T.q(tid="t", say=items[0]["say"], need=items[0]["key"], truth="a")
        self.assertFalse(T.check(task, "anything at all", {}, tempfile.mkdtemp())[0])
        self.assertTrue(T.check(task, "It is (.*)|x and a+b.", {}, tempfile.mkdtemp())[0])

    def test_whole_words_any_case_and_not(self):
        _, items, _ = UT.parse(GOOD)
        task = T.q(tid="t", say=items[0]["say"], need=items[0]["key"], truth=items[0]["answer"],
                   never=items[0]["never"])
        ws = tempfile.mkdtemp()
        self.assertTrue(T.check(task, "On SATURDAY, by the North  Wall.", {}, ws)[0])
        self.assertTrue(T.check(task, "Sat, at the north wall", {}, ws)[0])
        self.assertFalse(T.check(task, "Saturdays by the north wall", {}, ws)[0])  # whole word
        self.assertFalse(T.check(task, "Saturday or Sunday, north wall", {}, ws)[0])
        self.assertFalse(T.check(task, "On Saturday.", {}, ws)[0])

    def test_norwegian_letters(self):
        _, items, errors = UT.parse("Q: Når?\nA: På lørdag.\nKEY: lørdag\n")
        self.assertEqual(errors, [])
        task = T.q(tid="t", say=items[0]["say"], need=items[0]["key"], truth="x")
        self.assertTrue(T.check(task, "Det er på Lørdag.", {}, tempfile.mkdtemp())[0])


class TheFiles(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="yours-")
        self.f = UT.Files(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_add_list_remove(self):
        entry, err = self.f.add("garden.txt", GOOD.encode())
        self.assertIsNone(err)
        self.assertEqual(self.f.listing()[0]["questions"], 2)
        self.assertEqual(self.f.listing()[0]["title"], "My garden")
        self.assertEqual(self.f.add("again.txt", GOOD.encode())[1], ["this file is on the unit already"])
        tasks = self.f.tasks()
        self.assertEqual([t["id"] for t in tasks], ["you.%s.1" % entry["id"], "you.%s.2" % entry["id"]])
        self.assertEqual(tasks[0]["truth"], "On Saturday, by the north wall.")
        self.assertTrue(self.f.remove(entry["id"]))
        self.assertEqual(self.f.listing(), [])
        self.assertFalse(self.f.remove("../../etc"))

    def test_what_is_not_taken(self):
        self.assertTrue(self.f.add("x", b"\xff\xfe\x00")[1])
        self.assertTrue(self.f.add("x", b"Q: a\n" * 100000)[1])          # too large
        self.assertTrue(self.f.add("x", b"Q: only a question\n")[1])
        self.assertEqual(self.f.listing(), [])


class InTheLoop(unittest.TestCase):

    def setUp(self):
        self.top = tempfile.mkdtemp(prefix="loop-")
        self.dir = os.path.join(self.top, "training")
        self.loop = T.Loop(self.dir, ask=lambda *a: {})

    def tearDown(self):
        shutil.rmtree(self.top, ignore_errors=True)

    def plan(self):
        self.loop.state = {"status": "running", "run": 1, "round": 0, "failed": {}, "gave_up": {},
                           "streak": {}, "fails": {}, "remembered": {}}
        self.loop._plan_round()
        return self.loop.state

    def test_no_file_no_stage(self):
        s = self.plan()
        self.assertNotIn(UT.STAGE, s["scores"])
        self.assertFalse(any(t["level"] == UT.STAGE for t in s["plan"]))

    def test_a_file_is_a_stage_after_the_four(self):
        many = "\n\n".join("Q: Question %d?\nA: Answer %d.\nKEY: answer" % (i, i) for i in range(25))
        self.loop.yours.add("many.txt", many.encode())
        s = self.plan()
        mine = [t for t in s["plan"] if t["level"] == UT.STAGE]
        self.assertEqual(len(mine), UT.TURNS)
        self.assertTrue(all(t["keep"] and t["by"] == "model" for t in mine))
        levels = [t["level"] for t in s["plan"]]
        self.assertEqual(levels[-UT.TURNS:], [UT.STAGE] * UT.TURNS, "after the four")
        self.assertIn(UT.STAGE, s["scores"])
        self.assertEqual(T.earned_level({UT.STAGE: {"asked": 1, "right": 1}}), None)

    def test_not_counted_in_her_score(self):
        self.loop.yours.add("g.txt", GOOD.encode())
        s = self.plan()
        task = next(t for t in s["plan"] if t["level"] == UT.STAGE)
        lent = []
        self.loop.ask = lambda say, level, keep: lent.append(level) or {
            "status": 200, "reply": "On Saturday by the north wall, a Lapins cherry", "meta": {}}
        self.loop.real_level = lambda: "collaborator"
        s.update(asked=0, right=0, hers_asked=0, hers_right=0, hers_declined=0,
                 retries={"asked": 0, "right": 0}, wrong=[], learned=[], not_learned=[],
                 elapsed=0, budget=600, position=0)
        self.loop._one(task)
        self.assertEqual(lent, ["builder"], "asked at the level she holds")
        self.assertEqual((s["asked"], s["hers_asked"]), (0, 0))
        self.assertEqual(s["yours"], {"asked": 1, "right": 1})


class AtTheProxy(_Proxy):

    def setUp(self):
        super().setUp()
        self.saved_dir = proxy.TRAINING_DIR
        proxy.TRAINING_DIR = os.path.join(self.tmp, "training")
        proxy._TRAINING_LOOP = None
        import types
        self.saved_spark = proxy.spark
        proxy.spark = types.SimpleNamespace(gate=types.SimpleNamespace(trust_level="observer"))

    def tearDown(self):
        proxy.spark = self.saved_spark
        proxy.TRAINING_DIR = self.saved_dir
        proxy._TRAINING_LOOP = None
        super().tearDown()

    def post(self, path, body):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        c.request("POST", path, body=json.dumps(body), headers={"Content-Type": "application/json"})
        r = c.getresponse()
        d = json.loads(r.read())
        c.close()
        return r.status, d

    def test_add_show_remove(self):
        status, d = self.post("/aetherseed/training-file", {"name": "garden.txt", "text": GOOD})
        self.assertEqual(status, 201, d)
        self.assertEqual(d["file"]["questions"], 2)
        shown = self.get("/aetherseed/training")["yours"]
        self.assertEqual(shown["files"][0]["title"], "My garden")
        self.assertEqual(shown["per_round"], UT.TURNS)
        status, d = self.post("/aetherseed/training-file/remove", {"id": d["file"]["id"]})
        self.assertEqual((status, d["files"]), (200, []))

    def test_a_bad_file_says_why(self):
        status, d = self.post("/aetherseed/training-file", {"name": "x.txt", "text": "Q: a?\nA: b\n"})
        self.assertEqual(status, 400)
        self.assertIn("no KEY", d["errors"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
