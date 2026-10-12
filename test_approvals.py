"""The approvals queue (build log 72, T4).

    python3 -m unittest test_approvals -v

Andreas, 12 Oct 2026: "Go ahead without the friction". An action above her
level that would leave something behind (a to-do, a note) is filed as a
request to her steward instead of only refused; writes within her level do
not wait. He approves once, and the unit does it, as asked; or he declines.
"""
import contextlib
import http.client
import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import proxy                            # first, and for real (see test_brake)
from test_memory_turn import SCRIPT, _Proxy
from aetherspark import AetherSpark, TRUST_PERMISSIONS
from intent_detection import detect_intent
from logic import approvals, chain
from logic.approvals import Approvals, words_of
from logic.gate_answers import blocked_text, refusal_text, request_text
from trust_evolution import TrustEvolution

T0 = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


def _actions(log):
    with open(log, encoding="utf-8") as f:
        return [json.loads(l)["action"] for l in f if l.strip()]


class TheQueue(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="approvals-")
        self.path = os.path.join(self.tmp, "approvals.json")
        self.log = os.path.join(self.tmp, "control.log")
        self.clock = _Clock()
        self.q = Approvals(self.path, self.log, clock=self.clock)
        self.done = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def do(self, r):
        self.done.append(r["args"][0])
        return "Added to todo: " + r["args"][0]

    def file(self, words="buy milk", tool="todo_add"):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.q.file(tool, [words], "Andreas", "add a to-do: " + words,
                               "observer", "reader")

    def test_a_request_is_filed_waiting_for_a_day(self):
        r, how = self.file()
        self.assertEqual(how, "filed")
        self.assertEqual((r["id"], r["status"], r["args"]), (1, "waiting", ["buy milk"]))
        self.assertEqual(r["expires_at"], (T0 + timedelta(hours=24)).isoformat(timespec="seconds"))
        self.assertEqual(_actions(self.log), ["request_filed"])
        self.assertEqual(self.q.pending_count(), 1)

    def test_asked_again_it_is_the_same_request(self):
        self.file()
        r, how = self.file()
        self.assertEqual((r["id"], how), (1, "waiting"))
        self.assertEqual(self.q.pending_count(), 1)
        self.assertEqual(_actions(self.log), ["request_filed"])
        r2, how2 = self.file("buy bread")
        self.assertEqual((r2["id"], how2), (2, "filed"))

    def test_a_full_queue_files_nothing(self):
        for n in range(approvals.MAX_PENDING):
            self.file("item %d" % n)
        r, how = self.file("one more")
        self.assertEqual((r, how), (None, "full"))
        self.assertEqual(self.q.pending_count(), approvals.MAX_PENDING)

    def test_approved_it_is_done_once_as_asked(self):
        self.file("Call Martin")
        r, err = self.q.resolve(1, True, "the steward", "fine", self.do)
        self.assertIsNone(err)
        self.assertEqual((r["status"], r["result"]), ("approved", "Added to todo: Call Martin"))
        self.assertEqual(self.done, ["Call Martin"])
        r, err = self.q.resolve(1, True, "the steward", "again", self.do)
        self.assertEqual(err, "it is approved already")
        self.assertEqual(self.done, ["Call Martin"], "done once")
        self.assertEqual(_actions(self.log), ["request_filed", "request_approved"])

    def test_declined_nothing_is_done(self):
        self.file()
        r, err = self.q.resolve(1, False, "the steward", "not now", self.do)
        self.assertEqual((r["status"], err, self.done), ("declined", None, []))
        self.assertEqual(self.q.view()["recent"][0]["reason"], "not now")

    def test_approved_but_not_done_is_said_as_failed(self):
        self.file()
        r, _ = self.q.resolve(1, True, "the steward", "ok", lambda r: "[ERROR] disk full")
        self.assertEqual((r["status"], r["result"]), ("failed", "[ERROR] disk full"))

        def boom(r):
            raise OSError("no workspace")
        self.file("other")
        r, _ = self.q.resolve(2, True, "the steward", "ok", boom)
        self.assertEqual(r["status"], "failed")
        self.assertIn("no workspace", r["result"])
        with open(self.log) as f:
            done = [json.loads(l).get("done") for l in f if "request_approved" in l]
        self.assertEqual(done, [False, False])

    def test_after_a_day_it_expires_and_is_never_done(self):
        self.file()
        self.clock.now = T0 + timedelta(hours=24, seconds=1)
        v = self.q.view()
        self.assertEqual((v["pending"], v["recent"][0]["status"]), ([], "expired"))
        self.q.view()
        self.assertEqual(_actions(self.log), ["request_filed", "request_expired"], "said once")
        r, err = self.q.resolve(1, True, "the steward", "late", self.do)
        self.assertEqual((err, self.done), ("it is expired already", []))

    def test_no_such_request(self):
        self.assertEqual(self.q.resolve(7, True, "the steward", "x", self.do), (None, "no such request"))

    def test_an_unreadable_queue_is_set_aside_and_nothing_in_it_is_done(self):
        self.file()
        with open(self.path, "w") as f:
            f.write("{ not json")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            v = self.q.view()
        self.assertEqual(v, {"pending": [], "recent": []})
        self.assertIn("set aside", out.getvalue())
        self.assertTrue(any(n.startswith("approvals.json.bad-") for n in os.listdir(self.tmp)))
        self.assertEqual(self.q.resolve(1, True, "the steward", "x", self.do)[1], "no such request")

    def test_the_words_are_kept_whole(self):
        long = "x" * approvals.MAX_WORDS
        r, _ = self.file(long, tool="note_write")
        self.assertEqual(r["args"], [long])
        with self.assertRaises(ValueError):
            self.file(long + "x", tool="note_write")
        with self.assertRaises(ValueError):
            self.q.file("todo_add", [], "Andreas", "add a to-do:", "observer", "reader")

    def test_the_record_holds(self):
        self.file()
        self.file("bread")
        self.q.resolve(1, True, "the steward", "ok", self.do)
        self.q.resolve(2, False, "the steward", "no", self.do)
        v = chain.verify(self.log)
        self.assertTrue(v["ok"], v)
        self.assertEqual(v["chained"], 4)


class WhatIsFiled(unittest.TestCase):

    def test_the_words_after_the_colon(self):
        self.assertEqual(words_of(detect_intent("add a to-do: buy milk")), "buy milk")
        self.assertEqual(words_of(detect_intent("Write a note: the soak started today")),
                         "the soak started today")

    def test_nothing_to_act_on_is_not_filed(self):
        self.assertIsNone(words_of(detect_intent("save this as a note")))
        self.assertIsNone(words_of({"captures": ("   ",)}))
        self.assertIsNone(words_of({"captures": ("x" * (approvals.MAX_WORDS + 1),)}))
        self.assertIsNone(words_of(None))

    def test_only_the_writes(self):
        self.assertEqual(approvals.QUEUEABLE, ("todo_add", "note_write"))


class AtTheProxy(_Proxy):

    def setUp(self):
        super().setUp()
        self.ws = tempfile.mkdtemp(prefix="ws-")
        with open(os.path.join(self.ws, "todo.md"), "w") as f:
            f.write("- water the plants\n")
        os.makedirs(os.path.join(self.ws, "notes"))
        self.saved = (proxy.spark, proxy.detect_intent, proxy.trust, proxy.TRUST_CONTROL_FILE)
        proxy.TRUST_CONTROL_FILE = os.path.join(self.tmp, "trust_control.json")
        proxy._TRUST_CONTROLS.clear()
        proxy._APPROVALS.clear()
        self.level("observer")
        proxy.detect_intent = detect_intent
        g = proxy.execute_intent.__globals__
        self.addCleanup(g.__setitem__, "WORKSPACE", g["WORKSPACE"])
        g["WORKSPACE"] = self.ws
        with contextlib.redirect_stdout(io.StringIO()):
            proxy.trust = TrustEvolution(os.path.join(self.tmp, "trust_state.json"))

    def tearDown(self):
        proxy.spark, proxy.detect_intent, proxy.trust, proxy.TRUST_CONTROL_FILE = self.saved
        proxy._TRUST_CONTROLS.clear()
        proxy._APPROVALS.clear()
        proxy.BRAKE.clear()
        shutil.rmtree(self.ws, ignore_errors=True)
        super().tearDown()

    def level(self, role):
        proxy.spark = AetherSpark({"sandbox_root": self.ws, "trust_level": role,
                                   "audit_log": os.path.join(self.tmp, "audit.log")})
        proxy.spark.gate.overrides = lambda: proxy._tool_rules()

    def post(self, path, obj):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        c.request("POST", path, body=json.dumps(obj), headers={"Content-Type": "application/json"})
        r = c.getresponse()
        d = json.loads(r.read())
        c.close()
        return r.status, d

    def todo(self):
        with open(os.path.join(self.ws, "todo.md")) as f:
            return f.read()

    def test_above_her_level_a_write_is_asked_for_and_not_done(self):
        n = len(SCRIPT["requests"])
        status, reply, meta = self.ask("add a to-do: buy milk")
        self.assertEqual(status, 200)
        self.assertEqual(reply, "I can't add to your to-do list yet. That opens at reader, and "
                                "I am at observer. I have asked my steward for an OK (request 1). "
                                "Nothing has been added yet.")
        self.assertEqual(meta["mode"], "gate")
        self.assertEqual(len(SCRIPT["requests"]), n, "the model must not be called")
        self.assertEqual(self.todo(), "- water the plants\n")
        pending = self.get("/aetherseed/approvals")["pending"]
        self.assertEqual([(r["tool"], r["args"], r["level"], r["opens_at"]) for r in pending],
                         [("todo_add", ["buy milk"], "observer", "reader")])
        self.assertEqual(self.get("/aetherseed/status")["approvals_pending"], 1)

    def test_asked_twice_it_waits_once(self):
        self.ask("add a to-do: buy milk")
        _, reply, _ = self.ask("add a to-do: buy milk")
        self.assertIn("already waiting for my steward's OK (request 1)", reply)
        self.assertEqual(len(self.get("/aetherseed/approvals")["pending"]), 1)

    def test_approved_the_unit_adds_it_once_as_asked(self):
        self.ask("add a to-do: Call Martin")
        status, d = self.post("/aetherseed/approvals",
                              {"id": 1, "action": "approve", "reason": "yes, add it"})
        self.assertEqual(status, 200, d)
        self.assertEqual((d["done"]["status"], d["done"]["result"]),
                         ("approved", "Added to todo: Call Martin"))
        self.assertEqual(self.todo(), "- water the plants\n- Call Martin\n")
        status, d = self.post("/aetherseed/approvals",
                              {"id": 1, "action": "approve", "reason": "again"})
        self.assertEqual((status, d["error"]), (409, "it is approved already"))
        self.assertEqual(self.todo().count("Call Martin"), 1)
        self.assertEqual(d["pending"], [])

    def test_a_note_approved_is_written_as_asked(self):
        self.ask("Write a note: the soak started today")
        self.assertEqual(os.listdir(os.path.join(self.ws, "notes")), [])
        status, d = self.post("/aetherseed/approvals",
                              {"id": 1, "action": "approve", "reason": "ok"})
        self.assertEqual(status, 200, d)
        names = os.listdir(os.path.join(self.ws, "notes"))
        self.assertEqual(len(names), 1)
        with open(os.path.join(self.ws, "notes", names[0])) as f:
            self.assertTrue(f.read().endswith("\nthe soak started today\n"))

    def test_declined_nothing_is_written(self):
        self.ask("add a to-do: buy milk")
        status, d = self.post("/aetherseed/approvals",
                              {"id": 1, "action": "decline", "reason": "we have milk"})
        self.assertEqual((status, d["done"]["status"]), (200, "declined"))
        self.assertEqual(self.todo(), "- water the plants\n")

    def test_every_answer_needs_a_reason_and_a_real_id(self):
        self.ask("add a to-do: buy milk")
        for bad in ({"id": 1, "action": "approve"}, {"id": 1, "action": "approve", "reason": "  "}):
            status, d = self.post("/aetherseed/approvals", bad)
            self.assertEqual(status, 400)
            self.assertIn("reason", d["error"])
        for bad in ({"id": "1", "action": "approve", "reason": "x"},
                    {"id": True, "action": "approve", "reason": "x"},
                    {"id": 1, "action": "allow", "reason": "x"}, ["approve"]):
            self.assertEqual(self.post("/aetherseed/approvals", bad)[0], 400, bad)
        self.assertEqual(self.post("/aetherseed/approvals",
                                   {"id": 9, "action": "approve", "reason": "x"})[1]["error"],
                         "no such request")
        self.assertEqual(self.todo(), "- water the plants\n")
        self.assertEqual(len(self.get("/aetherseed/approvals")["pending"]), 1)

    def test_within_her_level_a_write_does_not_wait(self):
        self.level("reader")
        _, reply, _ = self.ask("add a to-do: buy milk")
        self.assertIn("buy milk", self.todo())
        self.assertEqual(self.get("/aetherseed/approvals")["pending"], [])

    def test_a_blocked_tool_is_his_word_and_not_asked_for(self):
        self.post("/aetherseed/trust", {"action": "block", "tool": "todo_add", "reason": "test"})
        _, reply, _ = self.ask("add a to-do: buy milk")
        self.assertEqual(reply, blocked_text("todo_add"))
        self.assertEqual(self.get("/aetherseed/approvals")["pending"], [])

    def test_blocked_after_it_was_asked_it_cannot_be_approved(self):
        self.ask("add a to-do: buy milk")
        self.post("/aetherseed/trust", {"action": "block", "tool": "todo_add", "reason": "test"})
        status, d = self.post("/aetherseed/approvals",
                              {"id": 1, "action": "approve", "reason": "ok"})
        self.assertEqual(status, 409)
        self.assertIn("blocked", d["error"])
        self.assertEqual(self.todo(), "- water the plants\n")
        self.assertEqual(self.post("/aetherseed/approvals",
                                   {"id": 1, "action": "decline", "reason": "blocked"})[0], 200)

    def test_nothing_is_done_while_the_brake_is_on(self):
        self.ask("add a to-do: buy milk")
        proxy.BRAKE.set()
        status, d = self.post("/aetherseed/approvals",
                              {"id": 1, "action": "approve", "reason": "ok"})
        self.assertEqual(status, 409)
        self.assertIn("brake", d["error"])
        self.assertEqual(self.todo(), "- water the plants\n")
        self.assertEqual(self.post("/aetherseed/approvals",
                                   {"id": 1, "action": "decline", "reason": "braked"})[0], 200)

    def test_homework_is_refused_as_before_and_never_filed(self):
        saved = proxy.TRAINING_DIR
        self.addCleanup(setattr, proxy, "TRAINING_DIR", saved)
        proxy.TRAINING_DIR = os.path.join(self.tmp, "training")
        os.makedirs(os.path.join(proxy.TRAINING_DIR, "workspace"))
        body = {"model": "llama3.2:3b", "stream": True, "training": {"level": "observer"},
                "messages": [{"role": "user", "content": "add a to-do: buy milk"}]}
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        c.request("POST", "/api/chat", body=json.dumps(body),
                  headers={"Content-Type": "application/json",
                           proxy.TRAINING_HEADER: proxy._TRAINING_TOKEN})
        r = c.getresponse()
        lines = [json.loads(l) for l in r.read().decode().split("\n") if l.strip()]
        c.close()
        reply = "".join((l.get("message") or {}).get("content", "") for l in lines)
        self.assertEqual(reply, refusal_text("todo_add", 2, "observer", TRUST_PERMISSIONS))
        self.assertEqual(self.get("/aetherseed/approvals")["pending"], [])
        self.assertFalse(os.path.exists(proxy.CONTROL_LOG))

    def test_nothing_to_act_on_is_refused_as_before(self):
        _, reply, _ = self.ask("save this as a note")
        self.assertEqual(reply, refusal_text("note_write", 2, "observer", TRUST_PERMISSIONS))
        self.assertEqual(self.get("/aetherseed/approvals")["pending"], [])

    def test_a_request_is_not_remembered_or_scored(self):
        before = len(proxy.root.store.get_all_episodes())
        self.ask("add a to-do: buy milk")
        self.assertEqual(len(proxy.root.store.get_all_episodes()), before)
        self.assertFalse(os.path.exists(proxy.PROVENANCE_LOG))
        self.assertFalse(os.path.exists(proxy.trust.events_path))

    def test_the_record_holds_every_step(self):
        self.ask("add a to-do: buy milk")
        self.ask("Write a note: dry the matches")
        self.post("/aetherseed/approvals", {"id": 1, "action": "approve", "reason": "ok"})
        self.post("/aetherseed/approvals", {"id": 2, "action": "decline", "reason": "no"})
        v = chain.verify(proxy.CONTROL_LOG)
        self.assertTrue(v["ok"], v)
        self.assertEqual(_actions(proxy.CONTROL_LOG),
                         ["request_filed", "request_filed", "request_approved", "request_declined"])

    def test_the_words_she_says_match_the_queue(self):
        req = {"id": 3}
        self.assertEqual(request_text("note_write", 2, "observer", TRUST_PERMISSIONS, req, "filed"),
                         "I can't write notes yet. That opens at reader, and I am at observer. "
                         "I have asked my steward for an OK (request 3). "
                         "Nothing has been written yet.")
        self.assertEqual(request_text("todo_add", 2, "observer", TRUST_PERMISSIONS, None, "full"),
                         "I can't add to your to-do list yet. That opens at reader, and I am at "
                         "observer. Too many requests are already waiting for my steward, so I "
                         "have not asked. Nothing was added.")


if __name__ == "__main__":
    unittest.main()
