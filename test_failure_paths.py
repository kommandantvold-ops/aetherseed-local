"""What a steward's turn does when the model side fails.

    python3 -m unittest test_failure_paths -v

A prompt that is too large is said so in words; a missing tokenizer is a 503;
any other failure before the first word is a 502; a failure after the first
word ends the stream with an error line. In none of these is the turn stored
as an answer.
"""
import http.client
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_step86 import Pipeline, proxy  # noqa: E402
from logic.token_budget import PromptTooLarge, TokenizerUnavailable  # noqa: E402


def _raise(exc):
    def f(*a, **k):
        raise exc
    return f


class WhenTheModelSideFails(Pipeline):
    level = "observer"

    def setUp(self):
        super().setUp()
        self._enforce = proxy.enforce_budget
        self._call = proxy.call_hailo_chat

    def tearDown(self):
        proxy.enforce_budget = self._enforce
        proxy.call_hailo_chat = self._call
        super().tearDown()

    def post(self, text="Tell me something about gardens."):
        body = {"model": "x", "stream": True, "messages": [{"role": "user", "content": text}]}
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        c.request("POST", "/api/chat", body=json.dumps(body),
                  headers={"Content-Type": "application/json"})
        r = c.getresponse()
        raw = r.read().decode()
        c.close()
        return r.status, raw

    def test_a_prompt_too_large_is_said_in_words(self):
        proxy.enforce_budget = _raise(PromptTooLarge("1700 tokens, ceiling 1536"))
        status, raw = self.post()
        self.assertEqual(status, 200)
        last = json.loads(raw.strip().split("\n")[-1])
        self.assertTrue(last["done"])
        self.assertTrue(last["message"]["content"].strip())

    def test_a_missing_tokenizer_is_a_503(self):
        proxy.enforce_budget = _raise(TokenizerUnavailable("no tokenizer"))
        status, raw = self.post()
        self.assertEqual(status, 503)
        self.assertIn("no tokenizer", json.loads(raw)["error"])

    def test_a_failure_before_the_first_word_is_a_502(self):
        proxy.call_hailo_chat = _raise(RuntimeError("model server gone"))
        status, raw = self.post()
        self.assertEqual(status, 502)
        self.assertIn("model server gone", json.loads(raw)["error"])

    def test_a_failure_after_the_first_word_ends_the_stream_with_an_error(self):
        def half(model, messages, emit=None):
            emit(json.dumps({"model": model, "message": {"role": "assistant",
                                                         "content": "Gard"}, "done": False}))
            raise RuntimeError("cut off")
        proxy.call_hailo_chat = half
        status, raw = self.post()
        self.assertEqual(status, 200)
        lines = [json.loads(l) for l in raw.strip().split("\n")]
        self.assertEqual(lines[-1].get("done_reason"), "error")
        self.assertIn("cut off", lines[-1]["error"])

    def test_a_cut_off_answer_is_not_stored(self):
        before = self._episodes()
        proxy.call_hailo_chat = _raise(RuntimeError("model server gone"))
        self.post()
        self.assertEqual(self._episodes(), before)

    def _episodes(self):
        import sqlite3
        db = proxy.root.store.db_path
        c = sqlite3.connect(db)
        try:
            return c.execute("select count(*) from episodes").fetchone()[0]
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
