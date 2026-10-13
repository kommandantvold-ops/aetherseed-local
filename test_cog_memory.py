"""A COG reflection in her memory (build log 74).

    python3 -m unittest test_cog_memory -v

Andreas, 13 Oct 2026: "each essay can be reviewed with trainer and that
feedback reflection can go into the memory, and it should have a COG-tag."
"""
import json
import os
import stat
import urllib.error
import urllib.request

import proxy                            # first, and for real (see test_brake)
from test_memory_turn import _Proxy
from logic.provenance import COG, COG_LABEL, TAG_NOTE, memory_tag, visible_modes
from logic.token_budget import strip_bare_tags, strip_leading_artefacts


class TheTag(_Proxy):
    def test_a_cog_line_is_tagged_and_seen(self):
        self.assertEqual(memory_tag(COG), COG_LABEL)
        self.assertIn(COG, visible_modes("factual"))
        self.assertIn("[COG ...]", TAG_NOTE)

    def test_she_does_not_say_the_tag(self):
        self.assertEqual(strip_leading_artefacts(COG_LABEL + " I think so.")[0], "I think so.")
        self.assertEqual(strip_bare_tags("My [COG] reflection: care.")[0], "My reflection: care.")


class TheEndpoint(_Proxy):
    def post(self, body, token=None):
        req = urllib.request.Request(self.url + "/aetherseed/cog/reflection",
                                     data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        if token is not None:
            req.add_header(proxy.COG_HEADER, token)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    BODY = {"essay": "001", "topic": "the right soil",
            "review": "You kept to the passage. Next time, say where you are unsure.",
            "reflection": "I take from the review that I should name what I do not know. "
                          "In my next essay I will say where I am unsure."}

    def setUp(self):
        super().setUp()
        self._log = proxy.COG_LOG
        proxy.COG_LOG = os.path.join(self.tmp, "cog.log")

    def tearDown(self):
        proxy.COG_LOG = self._log
        super().tearDown()

    def count(self):
        return proxy.root.store.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]

    def test_without_the_token_nothing_is_stored(self):
        self.assertEqual(self.post(self.BODY)[0], 403)
        self.assertEqual(self.post(self.BODY, "wrong")[0], 403)
        self.assertEqual(self.count(), 0)

    def test_stored_as_cog_by_the_trainer_waiting_for_no_ring(self):
        status, out = self.post(self.BODY, proxy._COG_TOKEN)
        self.assertEqual(status, 200)
        ep = proxy.root.store.conn.execute(
            "SELECT user_msg, ai_msg, mode, speaker, consolidated FROM episodes WHERE id = ?",
            (out["stored"],)).fetchone()
        self.assertEqual(ep[2], "cog")
        self.assertEqual(ep[3], "Trainer")
        self.assertEqual(ep[4], 1)
        self.assertTrue(ep[0].startswith("Review of your essay on the right soil: You kept"))
        self.assertEqual(ep[1], self.BODY["reflection"])
        with open(proxy.COG_LOG) as f:
            self.assertEqual(json.loads(f.readline())["episode"], out["stored"])

    def test_it_comes_back_tagged_and_whole(self):
        self.post(self.BODY, proxy._COG_TOKEN)
        ctx = proxy.root.retrieve_context("What do you do when you are unsure in an essay?")
        self.assertIn(COG_LABEL, ctx)
        self.assertIn("In my next essay I will say where I am unsure.", ctx)

    def test_refused_with_the_brake_on(self):
        proxy.BRAKE.set()
        try:
            self.assertEqual(self.post(self.BODY, proxy._COG_TOKEN)[0], 409)
        finally:
            proxy.BRAKE.clear()
        self.assertEqual(self.count(), 0)

    def test_empty_or_too_long_is_refused(self):
        self.assertEqual(self.post(dict(self.BODY, review=""), proxy._COG_TOKEN)[0], 400)
        self.assertEqual(self.post(dict(self.BODY, reflection="x" * 5000), proxy._COG_TOKEN)[0], 400)
        self.assertEqual(self.count(), 0)

    def remove(self, body, token=None):
        req = urllib.request.Request(self.url + "/aetherseed/cog/remove",
                                     data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        if token is not None:
            req.add_header(proxy.COG_HEADER, token)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_removed_at_the_stewards_word_and_logged(self):
        ep = self.post(self.BODY, proxy._COG_TOKEN)[1]["stored"]
        self.assertEqual(self.remove({"episode": ep, "why": "x"})[0], 403)
        self.assertEqual(self.remove({"episode": ep}, proxy._COG_TOKEN)[0], 400)
        status, out = self.remove({"episode": ep, "why": "echoed the essay"}, proxy._COG_TOKEN)
        self.assertEqual((status, out), (200, {"removed": ep}))
        self.assertEqual(self.count(), 0)
        with open(proxy.COG_LOG) as f:
            last = json.loads(f.readlines()[-1])
        self.assertEqual((last["removed"], last["why"]), (ep, "echoed the essay"))
        self.assertEqual(last["reflection"], self.BODY["reflection"])

    def test_only_a_cog_line_can_be_removed(self):
        ep = proxy.root.store_interaction("What is 2+2?", "4")
        status, _ = self.remove({"episode": ep, "why": "x"}, proxy._COG_TOKEN)
        self.assertEqual(status, 404)
        self.assertEqual(self.count(), 1)

    def test_the_token_file_is_the_service_accounts_alone(self):
        saved = proxy.COG_TOKEN_FILE
        proxy.COG_TOKEN_FILE = os.path.join(self.tmp, "cog.token")
        try:
            proxy._write_cog_token()
            mode = stat.S_IMODE(os.stat(proxy.COG_TOKEN_FILE).st_mode)
            self.assertEqual(mode, 0o600)
            with open(proxy.COG_TOKEN_FILE) as f:
                self.assertEqual(f.read(), proxy._COG_TOKEN)
        finally:
            proxy.COG_TOKEN_FILE = saved


if __name__ == "__main__":
    import unittest
    unittest.main()
