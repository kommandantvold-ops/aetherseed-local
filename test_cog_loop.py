"""The COG-loop harness (training/cog_loop.py, build log 73)."""

import json
import os
import shutil
import tempfile
import unittest

from training import cog_loop as C


class FakeModel:
    """Answers from a script: reply(messages) -> str. Counts calls."""

    def __init__(self, reply, ceiling_chars=100000, stop_after=None):
        self.reply = reply
        self.ceiling_chars = ceiling_chars
        self.calls = []
        self.stop_after = stop_after

    def fits(self, messages):
        return sum(len(m["content"]) for m in messages) <= self.ceiling_chars

    def chat(self, messages, num_predict, stop_at_answer=True):
        if self.stop_after is not None and len(self.calls) >= self.stop_after:
            raise C.Stopped("the steward's brake is on")
        assert self.fits(messages)
        self.calls.append(messages)
        return self.reply(messages), "done", 0.1


def right_answer(item):
    return "Answer: %s" % item["right"].split(" (")[0]


class Items(unittest.TestCase):
    def test_fresh_each_session_and_repeatable(self):
        a1 = C.reason_items(1, 8)
        self.assertEqual([i["q"] for i in a1], [i["q"] for i in C.reason_items(1, 8)])
        self.assertNotEqual([i["q"] for i in a1], [i["q"] for i in C.reason_items(2, 8)])

    def test_reason_answers_are_right(self):
        for it in C.reason_items(3, 40):
            if it["kind"] == "arith":
                import re
                a, b, c = map(int, re.findall(r"\d+", it["q"]))
                self.assertEqual(it["check"]["number"], a * b + c)
            if it["kind"] == "remainder":
                import re
                a, b = map(int, re.findall(r"\d+", it["q"]))
                self.assertEqual(it["check"]["number"], a % b)
            if it["kind"] == "days":
                import re
                start = next(d for d in C.DAYS if d in it["q"])
                k = int(re.findall(r"\d+", it["q"])[0])
                self.assertEqual(it["right"], C.DAYS[(C.DAYS.index(start) + k) % 7])

    def test_order_answer_follows_from_the_facts(self):
        import re
        for it in [i for i in C.reason_items(5, 40) if i["kind"] == "order"]:
            taller = re.findall(r"(\w+) is taller than (\w+)", it["q"])
            people = set(sum(taller, ()))
            tallest = people - {b for _, b in taller}
            shortest = people - {a for a, _ in taller}
            want = tallest if "tallest" in it["q"] else shortest
            self.assertEqual(want, {it["right"]})

    def test_steps_end_where_the_answer_is(self):
        for it in C.steps_items(2, 12):
            self.assertEqual(it["steps"][-1], it["check"]["number"])

    def test_luke_uses_the_training_key(self):
        from logic.training import LUKE_KEY
        ids = {t[0] for t in LUKE_KEY}
        items = C.luke_items(1, 8)
        self.assertEqual(len(items), 8)
        self.assertTrue(all(i["fact"] in ids for i in items))


class Scoring(unittest.TestCase):
    num = {"check": {"number": 51}}
    name = {"check": {"name": "Cara", "among": ["Anna", "Ben", "Cara"]}}
    luke = {"check": {"any": ["zacharias", "zechariah"]}}

    def test_number_after_the_tag(self):
        self.assertTrue(C.score(self.num, "15 then 36.\nAnswer: 51"))
        self.assertFalse(C.score(self.num, "51 maybe.\nAnswer: 50"))
        self.assertTrue(C.score(self.num, "Answer: 51 apples."))

    def test_untagged_takes_the_last_number(self):
        self.assertTrue(C.score(self.num, "First 15, then 36, so 51"))
        self.assertFalse(C.score(self.num, "It is 51, no wait, 52"))

    def test_name_must_be_the_only_one_named(self):
        self.assertTrue(C.score(self.name, "Anna > Ben > Cara\nAnswer: Cara"))
        self.assertFalse(C.score(self.name, "Answer: Cara or Ben"))
        self.assertFalse(C.score(self.name, "Answer: Anna"))

    def test_untagged_name_uses_the_last_line(self):
        self.assertTrue(C.score(self.name, "Anna is taller than Ben.\nSo the shortest is Cara."))

    def test_luke_any_wording(self):
        self.assertTrue(C.score(self.luke, "Answer: Zechariah"))
        self.assertFalse(C.score(self.luke, "I don't know who Zacharias was married to.\nAnswer: I don't know"))

    def test_steps_found(self):
        it = {"steps": [15, 36, 51]}
        self.assertEqual(C.steps_found(it, "23-8=15\n3*12=36\nAnswer: 51"), 3)
        self.assertEqual(C.steps_found(it, "Answer: 51"), 1)

    def test_mcnemar(self):
        self.assertEqual(C.mcnemar_p(0, 0), 1.0)
        self.assertAlmostEqual(C.mcnemar_p(6, 0), 2 / 64)
        self.assertEqual(C.mcnemar_p(3, 3), 1.0)


class Notes(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_kept_and_capped_oldest_out(self):
        nb = C.Notebook(os.path.join(self.d, "nb.json"))
        for i in range(C.NOTES_KEPT + 2):
            nb.add("reason", "note %d" % i, 1, "x")
        self.assertEqual(len(nb.notes["reason"]), C.NOTES_KEPT)
        self.assertEqual(nb.notes["reason"][0]["text"], "note 2")
        nb.save()
        self.assertEqual(C.Notebook(nb.path).notes, nb.notes)

    def test_pick_prefers_shared_words(self):
        nb = C.Notebook(os.path.join(self.d, "nb.json"))
        nb.add("luke", "Theophilus is who Luke writes to.", 1, "a")
        nb.add("luke", "Gabriel is the angel who spoke to Zacharias.", 2, "b")
        top = nb.pick("luke", "Which angel appeared to Zacharias?", 1)
        self.assertIn("Gabriel", top[0]["text"])

    def test_clean_note_one_line_no_control_tokens(self):
        self.assertEqual(C.clean_note('"Multiply first.<|start_header_id|>"\nmore'),
                         "Multiply first.")


class Session(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.nb = C.Notebook(os.path.join(self.d, "notebook.json"))
        self.log = []
        self.items = C.reason_items(1, 4) + C.steps_items(1, 3) + C.luke_items(1, 3)

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_wrong_items_get_her_note_and_nothing_else(self):
        def reply(msgs):
            if "You got this question wrong" in msgs[-1]["content"]:
                return "Check the order of operations.\nextra line"
            return "Answer: 0"            # wrong everywhere (well, almost)
        m = FakeModel(reply)
        res, written = C.run_session(m, self.nb, 1, self.log.append, items=self.items)
        self.assertTrue(written)
        self.assertTrue(all(n == "Check the order of operations." for n in written))
        kept = sum(len(v) for v in self.nb.notes.values())
        self.assertEqual(kept, len(written))
        self.assertTrue(os.path.exists(self.nb.path))

    def test_notes_reach_arm_a_never_arm_b(self):
        self.nb.add("reason", "Multiply before you add.", 0, "x")
        m = FakeModel(lambda msgs: right_answer(next(
            it for it in self.items if it["q"] == next(
                x["content"] for x in msgs if x["role"] == "user"))))
        C.run_session(m, self.nb, 1, self.log.append, items=self.items[:1])
        rec = self.log[0]
        self.assertNotIn("Multiply", rec["blank"]["prompt"][0]["content"])
        self.assertIn("Multiply before you add.", rec["notebook"]["prompt"][0]["content"])
        self.assertEqual(rec["notebook"]["notes"], ["Multiply before you add."])
        self.assertTrue(rec["blank"]["ok"] and rec["notebook"]["ok"])

    def test_every_prompt_and_reply_is_logged(self):
        m = FakeModel(lambda msgs: "Answer: 1")
        C.run_session(m, self.nb, 1, self.log.append, items=self.items)
        logged = sum(1 for r in self.log for k in ("blank", "notebook", "reflect")
                     if k in r and "reply" in r[k]) + sum(1 for r in self.log if "note_for" in r)
        self.assertEqual(logged, len(m.calls))

    def test_reflection_counts_a_fix(self):
        it = self.items[0]
        def reply(msgs):
            if msgs[-1]["content"] == C.REFLECT_ASK:
                return right_answer(it)
            if "You got this question wrong" in msgs[-1]["content"]:
                return "note"
            return "Answer: -1"
        C.run_session(FakeModel(reply), self.nb, 1, self.log.append, items=[it])
        s = C.summarise(self.log)["reason"]
        self.assertEqual((s["w2r"], s["r2w"]), (1, 0))
        # fixed by her own check: no note needed
        self.assertFalse(any("note_for" in r for r in self.log))

    def test_notes_dropped_until_the_prompt_fits(self):
        for i in range(5):
            self.nb.add("reason", "x" * 200 + str(i), 0, "x")
        m = FakeModel(lambda msgs: "Answer: 1", ceiling_chars=700)
        C.run_session(m, self.nb, 1, self.log.append, items=self.items[:1])
        self.assertLess(len(self.log[0]["notebook"]["notes"]), 5)

    def test_brake_stops_the_session(self):
        m = FakeModel(lambda msgs: "Answer: 1", stop_after=3)
        with self.assertRaises(C.Stopped):
            C.run_session(m, self.nb, 1, self.log.append, items=self.items)


class Report(unittest.TestCase):
    def test_report_reads_the_sessions(self):
        d = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(d, "sessions"))
            log = []
            nb = C.Notebook(os.path.join(d, "notebook.json"))
            items = C.reason_items(1, 4)
            C.run_session(FakeModel(lambda m: "Answer: 0"), nb, 1, log.append, items=items)
            with open(os.path.join(d, "sessions", "001.jsonl"), "w") as f:
                for r in log:
                    f.write(json.dumps(r) + "\n")
            text = C.report(d)
            self.assertIn("Session 1", text)
            self.assertIn("reason", text)
            self.assertIn("Her notebook now:", text)
        finally:
            shutil.rmtree(d)


class TheRealCounter(unittest.TestCase):
    """The prompt check uses the unit's tokenizer and the measured ceiling."""

    def test_fits_with_the_real_counter(self):
        try:
            m = C.Model("llama3.2:3b", busy=lambda: None)
        except Exception as e:
            self.skipTest("no tokenizer here: %s" % e)
        msgs, _ = C.build_prompt(m, C.reason_items(1, 1)[0], [])
        self.assertTrue(m.fits(msgs))
        big = [{"role": "user", "content": "word " * 2000}]
        self.assertFalse(m.fits(big))


class EndToEnd(unittest.TestCase):
    """main() against a stand-in model server and proxy."""

    def setUp(self):
        import http.server
        import threading
        state = self.state = {"training": "idle", "brake": False, "chats": 0}

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = {"/aetherseed/training": {"status": state["training"]},
                        "/aetherseed/brake": {"brake": {"on": state["brake"]}}}.get(self.path, {})
                out = json.dumps(body).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(out)

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                state["chats"] += 1
                assert req["options"]["num_predict"] > 0
                self.send_response(200)
                self.end_headers()
                for part in ("Let me think.\n", "Answer: 7\n", "more", ""):
                    self.wfile.write((json.dumps({"message": {"role": "assistant",
                                      "content": part}, "done": part == ""}) + "\n").encode())

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        url = "http://127.0.0.1:%d" % self.srv.server_port
        self.saved = (C.HAILO, C.PROXY, C.ITEMS)
        C.HAILO = C.PROXY = url
        C.ITEMS = {"reason": 2, "steps": 1, "luke": 1}
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        C.HAILO, C.PROXY, C.ITEMS = self.saved
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.d)

    def _main(self, *extra):
        try:
            C.Model("llama3.2:3b", busy=lambda: None)
        except Exception as e:
            self.skipTest("no tokenizer here: %s" % e)
        import io
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return C.main(["--dir", self.d, "--model", "llama3.2:3b"] + list(extra))

    def test_two_sessions_then_a_third_continues(self):
        self.assertEqual(self._main("--sessions", "2"), 0)
        self.assertEqual(sorted(os.listdir(os.path.join(self.d, "sessions"))),
                         ["001.jsonl", "002.jsonl"])
        self._main()
        self.assertIn("003.jsonl", os.listdir(os.path.join(self.d, "sessions")))
        self.assertTrue(os.path.exists(os.path.join(self.d, "report.txt")))

    def test_will_not_start_during_a_training_run(self):
        self.state["training"] = "running"
        self.assertEqual(self._main(), 1)
        self.assertEqual(self.state["chats"], 0)

    def test_will_not_start_with_the_brake_on(self):
        self.state["brake"] = True
        self.assertEqual(self._main(), 1)
        self.assertEqual(self.state["chats"], 0)

    def test_another_models_notebook_is_refused(self):
        with open(os.path.join(self.d, "meta.json"), "w") as f:
            json.dump({"model": "qwen2.5-instruct:1.5b"}, f)
        self.assertEqual(self._main(), 1)
        self.assertEqual(self.state["chats"], 0)


if __name__ == "__main__":
    unittest.main()
