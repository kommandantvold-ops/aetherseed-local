"""The COG-loop harness (training/cog_loop.py, build logs 73 and 74)."""

import json
import os
import shutil
import tempfile
import unittest

from training import cog_loop as C
from training import cog_texts


class FakeModel:
    """Answers from a script: reply(messages) -> str. Counts calls."""

    def __init__(self, reply, ceiling_chars=100000, stop_after=None):
        self.reply = reply
        self.ceiling_chars = ceiling_chars
        self.calls = []
        self.stop_after = stop_after
        self.name = "fake"

    def fits(self, messages):
        return sum(len(m["content"]) for m in messages) <= self.ceiling_chars

    def chat(self, messages, num_predict, stop_at_answer=True, max_seconds=None):
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


class Philosophy(unittest.TestCase):
    def test_half_ecclesiastes_half_garden(self):
        items = C.philo_items(1, 8)
        self.assertEqual(sum(i["kind"] == "ecc" for i in items), 4)
        self.assertEqual(sum(i["kind"] == "gar" for i in items), 4)

    def test_the_answer_is_in_the_passage(self):
        for tid, source, passage, question, need, answer in cog_texts.PHILO_KEY:
            self.assertTrue(any(w in passage.lower() for w in need), tid)
        for it in C.philo_items(2, 8):
            self.assertTrue(C.score(it, "Answer: " + it["right"].split(" (")[0]), it["id"])

    def test_essays_alternate(self):
        self.assertTrue(cog_texts.essay_for(1)[0].startswith("ecc."))
        self.assertTrue(cog_texts.essay_for(2)[0].startswith("gar."))
        self.assertNotEqual(cog_texts.essay_for(1)[0], cog_texts.essay_for(3)[0])


class SayBack(unittest.TestCase):
    def test_her_own_answer_said_back_right_or_wrong(self):
        self.assertTrue(C.said_back("Answer: 154", "My first answer was 154, because 15 x 8 = 120 + 34."))
        self.assertTrue(C.said_back("Answer: 150", "I said 150."))       # wrong, but hers
        self.assertFalse(C.said_back("Answer: 154", "I said 5."))
        self.assertTrue(C.said_back("Answer: The right soil", "I answered the right soil."))
        self.assertFalse(C.said_back("Answer: The right soil", "I answered water."))
        self.assertIsNone(C.said_back("", "anything"))


def _memory_db(path, rows):
    """A memory.db with an episodes table, as aetherroot makes one."""
    import sqlite3
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE episodes (id INTEGER PRIMARY KEY, timestamp TEXT, session_id TEXT, "
                "user_msg TEXT, ai_msg TEXT, embedding BLOB, resonance REAL, topic_tags TEXT, "
                "mode TEXT, speaker TEXT, consolidated INTEGER)")
    for user, ai, mode in rows:
        con.execute("INSERT INTO episodes (user_msg, ai_msg, mode, speaker) VALUES (?,?,?,?)",
                    (user, ai, mode, "Trainer"))
    con.commit()
    con.close()


class Memory(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.db = os.path.join(self.d, "memory.db")

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_only_cog_lines_tagged_and_read_only(self):
        _memory_db(self.db, [("Review of your essay on the right soil: good", "I will cite the passage.", "cog"),
                             ("What is 2+2?", "4", "factual")])
        def raw():
            with open(self.db, "rb") as f:
                return f.read()
        before = raw()
        m = C.CogMemory(self.db)
        self.assertEqual(len(m.lines), 1)
        self.assertTrue(m.lines[0]["text"].startswith(C.COG_LABEL))
        self.assertIn("I will cite the passage.", m.lines[0]["text"])
        self.assertEqual(raw(), before)

    def test_pick_prefers_shared_words(self):
        _memory_db(self.db, [("Review of your essay on vanity: name the verse", "Next time I quote vanity.", "cog"),
                             ("Review of your essay on the right soil: shorter", "Soil needs care.", "cog")])
        top = C.CogMemory(self.db).pick("What does a seed need? soil", 1)
        self.assertIn("Soil", top[0]["text"])

    def test_no_memory_file_is_no_lines(self):
        self.assertEqual(C.CogMemory(os.path.join(self.d, "none.db")).lines, [])


class _Mem:
    def __init__(self, lines=()):
        self.lines = [{"id": i + 1, "text": t, "words": C.words(t)} for i, t in enumerate(lines)]

    def pick(self, question, n=C.MEMORY_SHOWN):
        return self.lines[:n]


class Session(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.log = []
        self.items = (C.reason_items(1, 4) + C.steps_items(1, 2) + C.luke_items(1, 2)
                      + C.philo_items(1, 2))

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_memory_reaches_arm_a_never_arm_b(self):
        mem = _Mem([C.COG_LABEL + " [Episode] Trainer: Review | AI: Quote the passage."])
        m = FakeModel(lambda msgs: "Answer: 1")
        C.run_session(m, mem, 1, self.log.append, items=self.items[:1])
        rec = self.log[0]
        self.assertNotIn("Quote the passage", rec["blank"]["prompt"][0]["content"])
        self.assertIn("Quote the passage", rec["memory"]["prompt"][0]["content"])
        self.assertEqual(rec["memory"]["lines"], [1])

    def test_ends_with_an_essay_kept_word_for_word(self):
        def reply(msgs):
            if msgs[0]["content"] == C.ESSAY_SYSTEM:
                return "The Preacher says all is vanity.\n\nI am unsure what he means."
            return "Answer: 1"
        res, essay = C.run_session(FakeModel(reply), _Mem(), 1, self.log.append,
                                   items=self.items[:2], essay_dir=os.path.join(self.d, "essays"))
        self.assertIn("vanity", essay)
        theme, body = C.read_essay(self.d, 1)
        self.assertEqual(body, essay)
        self.assertEqual(theme, cog_texts.essay_for(1)[3])
        self.assertTrue(any(r.get("essay") for r in self.log))

    def test_no_notes_are_written_any_more(self):
        C.run_session(FakeModel(lambda m: "Answer: 0"), _Mem(), 1, self.log.append,
                      items=self.items, essay_dir=os.path.join(self.d, "essays"))
        self.assertFalse(any("note_for" in r for r in self.log))
        self.assertFalse(os.path.exists(os.path.join(self.d, "notebook.json")))

    def test_say_back_on_a_few_puzzles_and_passages(self):
        def reply(msgs):
            last = msgs[-1]["content"]
            if last == C.BETWEEN_ASK:
                return "5"
            if last == C.SAYBACK_ASK:
                return "I answered 1, because I counted."
            return "Answer: 1"
        C.run_session(FakeModel(reply), _Mem(), 1, self.log.append, items=self.items)
        sb = [r for r in self.log if "sayback" in r]
        self.assertTrue(0 < len(sb) <= C.SAYBACK_PER_SESSION)
        self.assertTrue(all(r["family"] in ("reason", "philo") for r in sb))
        self.assertTrue(all(r["sayback"]["ok"] for r in sb))
        s = C.summarise(self.log)
        self.assertEqual(sum(f["say_ok"] for f in s.values()), len(sb))

    def test_every_prompt_and_reply_is_logged(self):
        m = FakeModel(lambda msgs: "Answer: 1")
        C.run_session(m, _Mem(), 1, self.log.append, items=self.items)
        logged = sum(1 for r in self.log for k in ("blank", "memory", "reflect")
                     if k in r and "reply" in r[k])
        logged += sum(2 for r in self.log if "sayback" in r)     # between + say back
        logged += sum(1 for r in self.log if r.get("essay") and "reply" in r)
        self.assertEqual(logged, len(m.calls))

    def test_check_counts_a_fix(self):
        it = self.items[0]
        def reply(msgs):
            if msgs[-1]["content"] == C.REFLECT_ASK:
                return right_answer(it)
            return "Answer: -1"
        C.run_session(FakeModel(reply), _Mem(), 1, self.log.append, items=[it])
        s = C.summarise(self.log)["reason"]
        self.assertEqual((s["w2r"], s["r2w"]), (1, 0))

    def test_memory_lines_dropped_until_the_prompt_fits(self):
        mem = _Mem(["x" * 300, "y" * 300])
        m = FakeModel(lambda msgs: "Answer: 1", ceiling_chars=500)
        C.run_session(m, mem, 1, self.log.append, items=self.items[:1])
        self.assertLess(len(self.log[0]["memory"]["lines"]), 2)

    def test_brake_stops_the_session(self):
        m = FakeModel(lambda msgs: "Answer: 1", stop_after=3)
        with self.assertRaises(C.Stopped):
            C.run_session(m, _Mem(), 1, self.log.append, items=self.items)


class EssayMemory(unittest.TestCase):
    """74b: the essay prompt carries her COG lines too."""

    def test_lines_reach_the_essay_prompt(self):
        log = []
        mem = _Mem([C.COG_LABEL + " [Episode] Trainer: Review | AI: Write about 200 words and finish."])
        m = FakeModel(lambda msgs: "An essay.")
        C.run_session(m, mem, 1, log.append, items=[])
        essay = next(r for r in log if r.get("essay"))
        self.assertIn("Write about 200 words and finish.", essay["prompt"][0]["content"])
        self.assertEqual(essay["lines"], [1])

    def test_lines_dropped_until_it_fits(self):
        mem = _Mem(["x" * 400, "y" * 400, "z" * 400])
        tid, source, theme, msgs, used = C.essay_prompt(
            1, mem.lines, fits=lambda msgs: sum(len(x["content"]) for x in msgs) < 1500)
        self.assertLess(len(used), 3)
        self.assertTrue(sum(len(x["content"]) for x in msgs) < 1500)


class Forget(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.d, "reviews"))
        self.rec = os.path.join(self.d, "reviews", "008.reflection.json")
        with open(self.rec, "w") as f:
            json.dump({"stored": {"status": 200, "body": {"stored": 7599}}}, f)

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_removes_by_its_episode_and_keeps_the_record(self):
        sent = []
        ep = C.forget(self.d, 8, "echoed the essay", token="t",
                      post=lambda p, t: (sent.append((p, t)) or (200, {"removed": 7599})))
        self.assertEqual(ep, 7599)
        self.assertEqual(sent[0], ({"episode": 7599, "why": "echoed the essay"}, "t"))
        self.assertFalse(os.path.exists(self.rec))
        with open(self.rec.replace(".reflection.json", ".reflection.removed.json")) as f:
            self.assertEqual(json.load(f)["removed"]["why"], "echoed the essay")

    def test_a_refusal_changes_nothing(self):
        with self.assertRaises(RuntimeError):
            C.forget(self.d, 8, "why", token="t", post=lambda p, t: (403, {}))
        self.assertTrue(os.path.exists(self.rec))


class Reflect(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        C.write_essay(os.path.join(self.d, "essays"), 1, "m", "ecc.vanity", "Ecc 1:2",
                      "what the Preacher means by vanity", "All is vanity, he says. " * 30)
        os.makedirs(os.path.join(self.d, "reviews"))
        with open(os.path.join(self.d, "reviews", "001.txt"), "w") as f:
            f.write("You stayed close to the passage. Say where you are unsure.\n")
        self.posted = []

    def tearDown(self):
        shutil.rmtree(self.d)

    def post(self, payload, token):
        self.posted.append((payload, token))
        return 200, {"stored": 42, "mode": "cog"}

    def model(self, ceiling=100000):
        return FakeModel(lambda msgs: "I take from it that I should say where I am unsure.",
                         ceiling_chars=ceiling)

    def test_reflection_goes_to_the_proxy_with_the_token(self):
        rec = C.reflect(self.model(), self.d, 1, token="t0k", post=self.post)
        payload, token = self.posted[0]
        self.assertEqual(token, "t0k")
        self.assertEqual(payload["review"], "You stayed close to the passage. Say where you are unsure.")
        self.assertIn("unsure", payload["reflection"])
        self.assertEqual(payload["topic"], "what the Preacher means by vanity")
        self.assertEqual(rec["stored"]["body"]["stored"], 42)
        self.assertTrue(os.path.exists(os.path.join(self.d, "reviews", "001.reflection.json")))

    def test_once_per_essay_unless_again(self):
        C.reflect(self.model(), self.d, 1, token="t", post=self.post)
        with self.assertRaises(ValueError):
            C.reflect(self.model(), self.d, 1, token="t", post=self.post)
        C.reflect(self.model(), self.d, 1, token="t", post=self.post, again=True)
        self.assertEqual(len(self.posted), 2)

    def test_a_refusal_is_kept_apart_and_can_be_tried_again(self):
        with self.assertRaises(RuntimeError):
            C.reflect(self.model(), self.d, 1, token="t",
                      post=lambda p, t: (409, {"error": "the brake is on"}))
        self.assertTrue(os.path.exists(os.path.join(self.d, "reviews", "001.refused.json")))
        C.reflect(self.model(), self.d, 1, token="t", post=self.post)

    def test_a_long_essay_is_cut_to_fit(self):
        m = self.model(ceiling=900)
        C.reflect(m, self.d, 1, token="t", post=self.post)
        self.assertIn(" ...", m.calls[0][1]["content"])
        self.assertIn("Say where you are unsure.", m.calls[0][1]["content"])

    def test_no_review_no_reflection(self):
        os.remove(os.path.join(self.d, "reviews", "001.txt"))
        with self.assertRaises(OSError):
            C.reflect(self.model(), self.d, 1, token="t", post=self.post)
        self.assertEqual(self.posted, [])


class OlderBuild(unittest.TestCase):
    def test_no_luke_key_runs_the_rest_and_says_so(self):
        import logic.training as T
        saved = T.LUKE_KEY
        del T.LUKE_KEY
        try:
            log = []
            C.run_session(FakeModel(lambda m: "Answer: 1"), _Mem(), 1, log.append,
                          sizes={"reason": 1, "steps": 1, "luke": 2, "philo": 1})
            self.assertEqual(log[0]["skipped"], "luke")
            self.assertEqual({r["family"] for r in log if "memory" in r},
                             {"reason", "steps", "philo"})
        finally:
            T.LUKE_KEY = saved


class Report(unittest.TestCase):
    def test_report_reads_sessions_and_essays(self):
        d = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(d, "sessions"))
            log = []
            C.run_session(FakeModel(lambda m: "Answer: 0"), _Mem(), 1, log.append,
                          items=C.reason_items(1, 4), essay_dir=os.path.join(d, "essays"))
            with open(os.path.join(d, "sessions", "001.jsonl"), "w") as f:
                for r in log:
                    f.write(json.dumps(r) + "\n")
            text = C.report(d)
            self.assertIn("Session 1", text)
            self.assertIn("reason", text)
            self.assertIn("not reviewed", text)
        finally:
            shutil.rmtree(d)

    def test_reads_a_session_of_build_73(self):
        recs = [{"family": "reason", "notebook": {"ok": True}, "blank": {"ok": False},
                 "reflect": {"ok": True}}]
        self.assertEqual(C.summarise(recs)["reason"]["ab"], 1)


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
        C.ITEMS = {"reason": 2, "steps": 1, "luke": 1, "philo": 2}
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
            return C.main(["--dir", self.d, "--model", "llama3.2:3b",
                           "--memory", os.path.join(self.d, "none.db")] + list(extra))

    def test_two_sessions_then_a_third_continues(self):
        self.assertEqual(self._main("--sessions", "2"), 0)
        self.assertEqual(sorted(os.listdir(os.path.join(self.d, "sessions"))),
                         ["001.jsonl", "002.jsonl"])
        self._main()
        self.assertIn("003.jsonl", os.listdir(os.path.join(self.d, "sessions")))
        self.assertTrue(os.path.exists(os.path.join(self.d, "report.txt")))
        self.assertEqual(sorted(os.listdir(os.path.join(self.d, "essays"))),
                         ["001.md", "002.md", "003.md"])

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
