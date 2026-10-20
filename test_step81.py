"""what a guest's question brings back.

    python3 -m unittest test_step81 -v

whether a guest's question should be able to
bring back what the steward told her: "A guest should not."
"""
import json
import http.client
import os
import sys
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_memory_turn import _Proxy, SCRIPT, proxy  # noqa: E402  (the real proxy, a scripted model)
from logic import library as lib  # noqa: E402
from logic.guest import guest_text, TEXTS  # noqa: E402


class AGuestsQuestion(_Proxy):

    def setUp(self):
        super().setUp()
        proxy.WORKING.clear()
        # The harness switches intents off. Here: the workspace questions, as
        # the real detector names them, and one exact tool.
        intents = {"Show my to-do list": "todo_read", "Read my notes": "note_list",
                   "Add buy milk to my to-do list": "todo_add",
                   "What is 12 times 7?": "calculate",
                   # the exact tools that open a file
                   "Compare diary.md and todo.md": "compare",
                   "Count the lines in todo.md": "count",
                   "Is milk in todo.md?": "count_word"}
        proxy.detect_intent = lambda msg, *_: (
            {"intent": intents[msg], "tier": 1, "args": [], "match": msg}
            if msg in intents else None)
        self._saved_exec = proxy.execute_intent
        self.executed = []

        def execute(intent, gate):
            self.executed.append(intent["intent"])
            return "84"
        proxy.execute_intent = execute

    def tearDown(self):
        proxy.detect_intent = lambda *_: None
        proxy.execute_intent = self._saved_exec
        super().tearDown()

    def chat(self, text, guest=False, conversation="a1"):
        body = {"model": "x", "stream": True, "messages": [{"role": "user", "content": text}]}
        if guest:
            body.update(speaker="Guest", conversation=conversation)
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        c.request("POST", "/api/chat", body=json.dumps(body),
                  headers={"Content-Type": "application/json"})
        r = c.getresponse()
        raw = r.read().decode()
        c.close()
        lines = [json.loads(l) for l in raw.split("\n") if l.strip()]
        return "".join((l.get("message") or {}).get("content", "") for l in lines)

    def sent_text(self):
        return json.dumps(SCRIPT["requests"][-1]["messages"])

    def test_the_stewards_turns_do_not_come_back_to_a_guest(self):
        self.chat("My bank in Riverton holds the savings for the greenhouse roof.")
        self.chat("Where does the greenhouse roof money sit?", guest=True)
        self.assertNotIn("Riverton", self.sent_text())

    def test_but_to_the_steward_they_do(self):
        self.chat("My bank in Riverton holds the savings for the greenhouse roof.")
        proxy.WORKING.clear()                         # long-term memory, not working memory
        self.chat("Where does the greenhouse roof money sit?")
        self.assertIn("Riverton", self.sent_text())

    def episodes(self):
        return proxy.root.store.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]

    def test_a_guests_turns_are_not_stored(self):
        # guest conversations do not get stored. (Until
        # then a guest's own turns came back to that guest; they no longer do.)
        before = self.episodes()
        self.chat("My bicycle is the blue one with the basket on the greenhouse roof.",
                  guest=True, conversation="a1")
        self.assertEqual(self.episodes(), before)
        proxy.WORKING.clear()
        self.chat("Which bicycle is mine on the greenhouse roof?", guest=True, conversation="b2")
        self.assertNotIn("blue one with the basket", self.sent_text())
        self.assertEqual(self.episodes(), before)

    def test_the_steward_is_still_stored(self):
        before = self.episodes()
        self.chat("My bank in Riverton holds the savings for the greenhouse roof.")
        for _ in range(100):
            if self.episodes() == before + 1:
                break
            time.sleep(0.02)
        self.assertEqual(self.episodes(), before + 1)

    def test_a_guest_never_reaches_aetherroot(self):
        calls = []
        real_store, real_retrieve = proxy.root.store_interaction, proxy.root.retrieve_context
        proxy.root.store_interaction = lambda *a, **k: (calls.append("store"), real_store(*a, **k))[1]
        proxy.root.retrieve_context = lambda *a, **k: (calls.append("retrieve"), real_retrieve(*a, **k))[1]
        self.chat("Tell me about the greenhouse roof.", guest=True)
        self.assertEqual(calls, [])
        self.chat("Tell me about the greenhouse roof.")
        self.assertIn("retrieve", calls)         # the steward's turn does reach it

    def test_the_stewards_facts_do_not(self):
        proxy.root.store.add_fact("The spare house key is under the green flowerpot.", "")
        self.chat("Where is the spare house key?", guest=True)
        self.assertNotIn("flowerpot", self.sent_text())
        self.chat("Where is the spare house key?")
        self.assertIn("flowerpot", self.sent_text())

    def test_what_is_the_stewards_is_said_so_model_not_called(self):
        for text, kind in (("What have you gotten wrong?", "record"),
                           # both guards were untested
                           ("How much do you trust me?", "trust"),
                           ("What have you been corrected on?", "corrections"),
                           ("Show my to-do list", "workspace"),
                           ("Add buy milk to my to-do list", "workspace"),
                           ("Read my notes", "workspace")):
            with self.subTest(text=text):
                before = len(SCRIPT["requests"])
                reply = self.chat(text, guest=True)
                self.assertEqual(reply, TEXTS[kind]["en"])
                self.assertEqual(len(SCRIPT["requests"]), before, "the model was called")

    def test_nothing_is_filed_in_his_queue_by_a_guest(self):
        self.chat("Add buy milk to my to-do list", guest=True)
        self.assertFalse(os.path.exists(proxy.APPROVALS_FILE)
                         and json.load(open(proxy.APPROVALS_FILE)).get("requests"))

    def test_calculate_is_anybodys(self):
        before = len(SCRIPT["requests"])
        reply = self.chat("What is 12 times 7?", guest=True)
        self.assertIn("84", reply)
        self.assertEqual(len(SCRIPT["requests"]), before)

    def test_a_guest_has_no_tool_that_opens_a_file(self):
        # Code review compare showed a guest the first differing line
        # of any file in the steward's workspace, count_word whether a word
        # occurs in it. The exact tools that read a file are the steward's.
        for text in ("Compare diary.md and todo.md", "Count the lines in todo.md",
                     "Is milk in todo.md?"):
            with self.subTest(text=text):
                before = len(SCRIPT["requests"])
                self.assertEqual(self.chat(text, guest=True), TEXTS["workspace"]["en"])
                self.assertEqual(self.executed, [], "a tool ran for a guest")
                self.assertEqual(len(SCRIPT["requests"]), before, "the model was called")

    def test_the_steward_keeps_them(self):
        for text, tool in (("Compare diary.md and todo.md", "compare"),
                           ("Count the lines in todo.md", "count"),
                           ("Is milk in todo.md?", "count_word")):
            with self.subTest(text=text):
                self.executed.clear()
                self.assertIn("84", self.chat(text))
                self.assertEqual(self.executed, [tool])

    def test_the_guest_tool_list_is_the_two_that_open_nothing(self):
        self.assertEqual(proxy.GUEST_TOOLS, frozenset({"calculate", "system_health"}))
        self.assertTrue(proxy.GUEST_TOOLS.isdisjoint({"count", "count_word", "compare"}))


class GuestTexts(unittest.TestCase):

    def test_both_languages(self):
        for kind in TEXTS:
            self.assertTrue(guest_text(kind, "en"))
            self.assertTrue(guest_text(kind, "nb"))
            self.assertNotEqual(guest_text(kind, "en"), guest_text(kind, "nb"))
        self.assertEqual(guest_text("record", "xx"), TEXTS["record"]["en"])


class TheLibraryForAGuest(unittest.TestCase):

    def test_without_his_documents(self):
        lib_ = lib.Library.__new__(lib.Library)
        built_in = types.SimpleNamespace(own=False, name="Survival")
        his = types.SimpleNamespace(own=True, name="DNA v3")
        lib_.collections = [built_in, his]
        view = lib_.without_own()
        self.assertEqual(view.collections, [built_in])
        self.assertEqual(lib_.collections, [built_in, his])      # the steward's is untouched
        self.assertEqual(view.own_names(), [])

    def test_a_guest_follows_only_what_that_guest_was_shown(self):
        h = proxy.ProxyHandler.__new__(proxy.ProxyHandler)
        steward_last, _ = h._library_state(None)
        a_last, _ = h._library_state("Guest#a1")
        b_last, _ = h._library_state("Guest#b2")
        self.assertIsNot(a_last, steward_last)
        self.assertIsNot(a_last, b_last)
        self.assertIs(h._library_state("Guest#a1")[0], a_last)
        for i in range(40):
            h._library_state("Guest#x%d" % i)
        self.assertLessEqual(len(proxy.ProxyHandler._guest_library),
                             proxy.ProxyHandler._GUEST_LIBRARY_MAX)


if __name__ == "__main__":
    unittest.main(verbosity=2)
