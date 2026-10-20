"""Every prompt, word for word, and what came back.

    python3 -m unittest test_prompts -v

Can a turn be reproduced without asking the model? Before this, no: what a
turn was shown is built from things that change after it. Now every request
to the model is kept in prompts-YYYY-MM.log, chained, under the hash of the
bytes sent, and the turn's provenance line carries that hash.
"""
import contextlib
import hashlib
import http.client
import io
import json
import os
import shutil
import tempfile
import threading
import unittest

import proxy                            # first, and for real (see test_brake)
from test_memory_turn import SCRIPT, _Proxy
from logic import chain, prompts

HERE = os.path.dirname(os.path.abspath(__file__))


def _lines(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


class TheRecord(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prompts-")
        self.path = os.path.join(self.tmp, "prompts-2026-10.log")
        prompts.forget()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, body, outcome="answered", reply="Oslo."):
        with contextlib.redirect_stdout(io.StringIO()):
            c = prompts.Call(self.path, body)
            return c.done(outcome, reply)

    def test_the_bytes_sent_their_hash_and_what_came_back(self):
        body = json.dumps({"model": "m", "messages": [{"role": "user", "content": "Capital?"}]}
                          ).encode()
        sha = self.call(body)
        self.assertEqual(sha, hashlib.sha256(body).hexdigest())
        self.assertEqual(prompts.last_sha256(), sha)
        rec = _lines(self.path)[0]
        self.assertEqual((rec["sha256"], rec["body"], rec["reply"], rec["outcome"]),
                         (sha, body.decode(), "Oslo.", "answered"))
        self.assertTrue(prompts.body_holds(rec))
        self.assertEqual(prompts.find(self.path, sha)["reply"], "Oslo.")
        self.assertTrue(prompts.verify(self.path)["ok"])

    def test_a_turn_begins_with_no_prompt(self):
        self.call(b"{}")
        prompts.forget()
        self.assertIsNone(prompts.last_sha256())

    def test_each_thread_has_its_own(self):
        got = {}

        def one(n):
            with contextlib.redirect_stdout(io.StringIO()):
                prompts.Call(self.path, b'{"n": %d}' % n).done("answered", str(n))
            got[n] = prompts.last_sha256()
        threads = [threading.Thread(target=one, args=(n,)) for n in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(got, {n: hashlib.sha256(b'{"n": %d}' % n).hexdigest() for n in range(6)})
        self.assertTrue(prompts.verify(self.path)["ok"])
        self.assertEqual(len(_lines(self.path)), 6)

    def test_a_body_changed_and_the_chain_redone_still_shows(self):
        self.call(b'{"q": "what was asked"}')
        self.call(b'{"q": "the next"}')
        recs = _lines(self.path)
        recs[0]["body"] = '{"q": "something else"}'
        # rewrite the whole chain over the changed body, as one who could
        # write the file might: the chain holds again, the body does not
        os.remove(self.path)
        for r in recs:
            r = {k: v for k, v in r.items() if k not in ("prev", "hash")}
            with contextlib.redirect_stdout(io.StringIO()):
                chain.append(self.path, r)
        v = prompts.verify(self.path)
        self.assertTrue(chain.verify(self.path)["ok"])
        self.assertFalse(v["ok"])
        self.assertEqual(v["bodies_not_holding"], [1])

    def test_a_record_that_cannot_be_written_never_stops_the_turn(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            sha = prompts.Call(self.tmp, b"{}").done("answered", "x")      # a folder
        self.assertEqual(sha, hashlib.sha256(b"{}").hexdigest())
        self.assertIn("could not be kept", out.getvalue())



class AtTheProxy(_Proxy):

    def setUp(self):
        super().setUp()
        self.saved_training = proxy.TRAINING_DIR
        proxy.TRAINING_DIR = os.path.join(self.tmp, "training")
        os.makedirs(os.path.join(proxy.TRAINING_DIR, "workspace"))

    def tearDown(self):
        proxy.TRAINING_DIR = self.saved_training
        proxy.BRAKE.clear()
        super().tearDown()

    def month(self):
        return proxy._prompts_log()

    def test_a_turn_names_its_prompt_and_the_prompt_is_kept_whole(self):
        SCRIPT["chunks"] = ["The capital", " is Oslo."]
        self.ask("What is the capital of Norway?")
        kept = _lines(self.month())
        self.assertEqual(len(kept), 1)
        rec = kept[0]
        self.assertEqual((rec["outcome"], rec["reply"]), ("answered", "The capital is Oslo."))
        body = json.loads(rec["body"])
        self.assertEqual(body["messages"][-1],
                         {"role": "user", "content": "What is the capital of Norway?"})
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertEqual(body, SCRIPT["requests"][-1], "what was kept is what the model got")
        line = _lines(proxy.PROVENANCE_LOG)[-1]
        self.assertEqual(line["prompt_sha256"], rec["sha256"])
        self.assertTrue(prompts.verify(self.month())["ok"])

    def test_an_answer_the_unit_gives_itself_names_no_prompt(self):
        self.ask("What is your trust level?")
        self.assertFalse(os.path.exists(self.month()))

    def test_homework_is_kept_too(self):
        body = {"model": "llama3.2:3b", "stream": True, "training": {"level": "observer"},
                "messages": [{"role": "user", "content": "What is a ring in your memory?"}]}
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        c.request("POST", "/api/chat", body=json.dumps(body),
                  headers={"Content-Type": "application/json",
                           proxy.TRAINING_HEADER: proxy._TRAINING_TOKEN})
        c.getresponse().read()
        c.close()
        rec = _lines(self.month())[-1]
        line = _lines(proxy.PROVENANCE_LOG)[-1]
        self.assertEqual((line["training"], line["prompt_sha256"]), ("observer", rec["sha256"]))

    def test_a_call_that_fails_is_kept_with_why(self):
        saved, proxy.HAILO_OLLAMA_URL = proxy.HAILO_OLLAMA_URL, "http://127.0.0.1:9"
        try:
            with self.assertRaises(Exception):
                proxy.call_hailo_chat("llama3.2:3b", [{"role": "user", "content": "hello"}])
        finally:
            proxy.HAILO_OLLAMA_URL = saved
        rec = _lines(self.month())[-1]
        self.assertTrue(rec["outcome"].startswith("failed: "), rec["outcome"])
        self.assertEqual(rec["reply"], "")

    def test_a_reply_cut_by_the_brake_is_kept_as_far_as_it_went(self):
        SCRIPT["chunks"] = ["The", " river", " runs", " east", "."]

        def emit(line):
            proxy.BRAKE.set()              # pulled after the first words went out
        with self.assertRaises(proxy.Braked):
            proxy.call_hailo_chat("llama3.2:3b", [{"role": "user", "content": "Tell me"}],
                                  emit=emit)
        rec = _lines(self.month())[-1]
        self.assertEqual(rec["outcome"], "braked")
        self.assertTrue("The river runs east.".startswith(rec["reply"]) and rec["reply"],
                        rec["reply"])

    def test_the_records_view_checks_this_month(self):
        self.ask("What is the capital of Norway?")
        got = {r["record"]: r for r in self.get("/aetherseed/records")["records"]}
        month = os.path.basename(self.month())
        self.assertTrue(got[month]["ok"])
        self.assertEqual(got[month]["chained"], 1)

    def test_the_verify_tool_reads_every_month(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "verify_chain", os.path.join(HERE, "tools", "verify_chain.py"))
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        self.ask("What is the capital of Norway?")
        old = os.path.join(self.tmp, "prompts-2026-09.log")
        with contextlib.redirect_stdout(io.StringIO()):
            prompts.Call(old, b'{"q": 1}').done("answered", "a")
        results = tool.check(self.tmp)
        self.assertIn("prompts-2026-09.log", results)
        self.assertIn(os.path.basename(self.month()), results)
        self.assertTrue(tool.verdict_ok(results))


if __name__ == "__main__":
    unittest.main()
