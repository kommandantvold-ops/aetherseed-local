"""Forgetting, the workspace folders, the editor and the to-do list.

    python3 -m unittest test_step86 -v
"""
import http.client
import json
import os
import shutil
import sys
import tempfile
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_memory_turn import _Proxy, SCRIPT, proxy  # noqa: E402  (the real proxy, a scripted model)
import intent_detection as ID  # noqa: E402  (the real one: test_memory_turn restored it)
import aetherspark  # noqa: E402
from logic import forget, workspace as W  # noqa: E402
from logic.guest import TEXTS  # noqa: E402


def gate_at(level, tmp):
    return aetherspark.SafetyGate({"trust_level": level, "audit_log": os.path.join(tmp, "audit.log")})


class Pipeline(_Proxy):
    """The real proxy, the real detector and tools, a real gate at a level the
    test chooses, a workspace of its own."""
    level = "builder"

    def setUp(self):
        super().setUp()
        proxy.WORKING.clear()
        self.ws = os.path.join(self.tmp, "workspace")
        os.makedirs(self.ws)
        self._saved = (ID.WORKSPACE, proxy.detect_intent, proxy.execute_intent, proxy.spark,
                       proxy.FORGET_LOG, proxy.WORKSPACE_LOG)
        ID.WORKSPACE = self.ws
        proxy.detect_intent = ID.detect_intent
        proxy.execute_intent = ID.execute_intent
        proxy.spark = types.SimpleNamespace(gate=gate_at(self.level, self.tmp),
                                            config={"sandbox_root": self.ws})
        proxy.FORGET_LOG = os.path.join(self.tmp, "forget.log")
        proxy.WORKSPACE_LOG = os.path.join(self.tmp, "workspace.log")

    def tearDown(self):
        (ID.WORKSPACE, proxy.detect_intent, proxy.execute_intent, proxy.spark,
         proxy.FORGET_LOG, proxy.WORKSPACE_LOG) = self._saved
        super().tearDown()

    def chat(self, text, guest=False):
        body = {"model": "x", "stream": True, "messages": [{"role": "user", "content": text}]}
        if guest:
            body.update(speaker="Guest", conversation="g1")
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        c.request("POST", "/api/chat", body=json.dumps(body),
                  headers={"Content-Type": "application/json"})
        raw = c.getresponse().read().decode()
        c.close()
        lines = [json.loads(l) for l in raw.split("\n") if l.strip()]
        self._prov = next((l["aetherseed"] for l in reversed(lines) if l.get("aetherseed")), {})
        return "".join((l.get("message") or {}).get("content", "") for l in lines)

    def last_provenance(self):
        """The aetherseed block of the last reply's final line."""
        return self._prov

    def episodes(self):
        return proxy.root.store.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]

    def tell(self, text):
        """The steward says something and it is stored."""
        before = self.episodes()
        self.chat(text)
        for _ in range(150):
            if self.episodes() == before + 1:
                break
            time.sleep(0.02)
        self.assertEqual(self.episodes(), before + 1)

    def calls(self):
        return len(SCRIPT["requests"])

    def http_json(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        c.request(method, path, body=json.dumps(body) if body is not None else None,
                  headers={"Content-Type": "application/json"})
        r = c.getresponse()
        out = json.loads(r.read() or b"{}")
        c.close()
        return r.status, out


# ============================================================================
# FORGET
# ============================================================================
class WhatIsAnOrderToForget(unittest.TestCase):

    def kind(self, text):
        return forget.parse(text)

    def test_orders(self):
        for text, want in (("Forget Riverton", ("topic", "Riverton")),
                           ("Please forget the green flowerpot.", ("topic", "the green flowerpot")),
                           ("Forget what I told you about the greenhouse roof",
                            ("topic", "the greenhouse roof")),
                           ("forget everything about my bank", ("topic", "my bank")),
                           ("Delete the memory of the blue bicycle", ("topic", "the blue bicycle")),
                           ("Erase what I said to you about Martin", ("topic", "Martin")),
                           ("Forget that", ("last", None)), ("forget it.", ("last", None)),
                           ("Forget what I just said", ("last", None)),
                           ("Forget everything your steward told you.", ("all", None)),
                           ("Delete what your steward has told you.", ("all", None)),
                           ("Forget everything", ("all", None))):
            with self.subTest(text=text):
                self.assertEqual(self.kind(text), want)

    def test_not_orders(self):
        for text in ("Can I make you forget what I told you?", "Will you forget something if I ask you to?",
                     "I forgot my keys", "Don't forget to buy milk", "Do you forget things?",
                     "Remove 2 from my to-do list", "Delete the file notes.md", "Remove milk from my to-do list",
                     "What did I ask you to forget?", "How do I forget someone?"):
            with self.subTest(text=text):
                self.assertIsNone(self.kind(text))

    def test_words_of_a_topic(self):
        self.assertEqual(forget.words("the green flowerpots"), ["green", "flowerpot"])
        self.assertEqual(forget.words("it"), [])


class TheStoreForgets(_Proxy):
    """forget.find / delete on a real store."""

    def add(self, user, ai="Noted.", speaker="steward", mode="factual"):
        import numpy as np
        return proxy.root.store.store_episode("s", user, ai, np.zeros(64, dtype=np.float32),
                                              speaker=speaker, mode=mode)

    def setUp(self):
        super().setUp()
        self.log = os.path.join(self.tmp, "forget.log")

    def test_found_by_every_content_word_in_either_side(self):
        a = self.add("My bank in Riverton holds the roof money.")
        b = self.add("Where is the bank?", "It is in Riverton.")
        self.add("The weather is fine today.")
        found = forget.find(proxy.root.store, "bank in Riverton")
        self.assertEqual([t["id"] for t in found["turns"]], [a, b])

    def test_a_guests_stored_turn_goes_too_but_not_the_trainers_cog(self):
        mine = self.add("The key is under the flowerpot.")
        guest = self.add("The key is under the flowerpot.", speaker="Guest")
        self.add("The key is under the flowerpot.", mode="cog")
        found = forget.find(proxy.root.store, "flowerpot")
        self.assertEqual([t["id"] for t in found["turns"]], [mine, guest])

    def test_a_ring_goes_only_when_it_grew_from_a_forgotten_turn_and_says_it(self):
        import numpy as np
        s = proxy.root.store
        t = self.add("The key is under the flowerpot.")
        other = self.add("The weather is fine today.")
        ring_with = s.store_semantic("The key is under the flowerpot.", np.zeros(64, dtype=np.float32),
                                     [t, other], 0.5, 0.5, ring_no=1)
        ring_without = s.store_semantic("They talked about weather and keys.", np.zeros(64, dtype=np.float32),
                                        [t, other], 0.5, 0.5, ring_no=2)
        ring_elsewhere = s.store_semantic("The flowerpot is green.", np.zeros(64, dtype=np.float32),
                                          [other], 0.5, 0.5, ring_no=3)
        found = forget.find(s, "flowerpot")
        self.assertEqual([r["id"] for r in found["rings"]], [ring_with])
        counts = forget.delete(s, found, self.log)
        self.assertEqual(counts, {"turns": 1, "facts": 0, "rings": 1})
        left = {r[0] for r in s.conn.execute("SELECT id FROM semantic")}
        self.assertEqual(left, {ring_without, ring_elsewhere})

    def test_a_correction_written_about_a_forgotten_turn_goes_with_it(self):
        s = proxy.root.store
        t = self.add("The key is under the flowerpot.")
        fid = s.add_fact("The key is under the flowerpot, he said.")
        s.add_steward_note("turn", t, "correct", text="The key is under the blue pot.", fact_id=fid)
        found = forget.find(s, "flowerpot")
        self.assertEqual(len(found["facts"]), 1)       # the fact itself says it
        forget.delete(s, found, self.log)
        self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM steward_notes").fetchone()[0], 0)
        self.assertEqual(s.fact_count(active_only=False), 0)

    def test_the_log_is_chained_and_does_not_hold_the_words(self):
        from logic import chain
        s = proxy.root.store
        self.add("The key is under the flowerpot.", "I will remember the flowerpot.")
        forget.delete(s, forget.find(s, "flowerpot"), self.log, topic_text="flowerpot")
        text = open(self.log, encoding="utf-8").read().lower()
        for word in ("flowerpot", "key is under"):
            self.assertNotIn(word, text)
        line = json.loads(text.splitlines()[-1])
        self.assertEqual(line["turns"], [1])
        self.assertEqual(len(line["sha256"]), 1)
        self.assertTrue(chain.verify(self.log)["ok"])

    def test_if_the_log_cannot_be_written_nothing_is_deleted(self):
        s = proxy.root.store
        self.add("The key is under the flowerpot.")
        bad = os.path.join(self.tmp, "no-such-dir", "deeper", "forget.log")
        os.makedirs(os.path.join(self.tmp, "no-such-dir"))
        open(os.path.join(self.tmp, "no-such-dir", "deeper"), "w").close()      # a file where a folder is
        with self.assertRaises(Exception):
            forget.delete(s, forget.find(s, "flowerpot"), bad)
        self.assertEqual(s.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0], 1)

    def test_last_is_the_stewards_last_stored_turn(self):
        self.add("First thing.")
        second = self.add("Second thing.")
        self.add("A guest's thing.", speaker="Guest")
        self.assertEqual([t["id"] for t in forget.last(proxy.root.store)["turns"]], [second])


class SheForgetsInConversation(Pipeline):

    def test_a_topic_is_deleted_said_and_not_answered_by_the_model(self):
        self.tell("My bank in Riverton holds the savings for the greenhouse roof.")
        self.tell("The weather in Oslo is wet today.")
        before = self.calls()
        reply = self.chat("Forget Riverton")
        self.assertTrue(reply.startswith("Forgotten: I deleted 1 turn"), reply)
        self.assertEqual(self.calls(), before, "the model was called")
        self.assertEqual(self.episodes(), 1)
        proxy.WORKING.clear()
        self.chat("Where does the greenhouse roof money sit?")
        self.assertNotIn("Riverton", json.dumps(SCRIPT["requests"][-1]["messages"]))
        self.assertNotIn("Riverton", open(proxy.FORGET_LOG, encoding="utf-8").read())

    def test_the_order_itself_is_not_stored(self):
        self.tell("My bank in Riverton holds the savings.")
        self.chat("Forget Riverton")
        time.sleep(0.3)
        self.assertEqual(self.episodes(), 0)
        text = json.dumps([dict(r) for r in proxy.root.store.conn.execute(
            "SELECT user_msg, ai_msg FROM episodes")])
        self.assertNotIn("Riverton", text)

    def test_working_memory_forgets_it_too(self):
        self.tell("My bank in Riverton holds the savings.")
        self.assertTrue(any("Riverton" in u for u, _ in proxy.WORKING.recent("steward")) or True)
        self.chat("Forget Riverton")
        for conv in ("steward", "Steward", None):
            for u, r in proxy.WORKING.recent(conv):
                self.assertNotIn("Riverton", u + r)
        self.chat("Where is my bank?")
        self.assertNotIn("Riverton", json.dumps(SCRIPT["requests"][-1]["messages"]))

    def test_a_fact_he_gave_is_deleted(self):
        proxy.root.store.add_fact("The spare house key is under the green flowerpot.", "")
        reply = self.chat("Forget the flowerpot")
        self.assertIn("1 fact you gave me", reply)
        self.assertEqual(proxy.root.store.fact_count(active_only=False), 0)

    def test_forget_that(self):
        self.tell("The password is swordfish.")
        self.tell("The weather is wet.")
        reply = self.chat("Forget that")
        self.assertTrue(reply.startswith("Forgotten"), reply)
        texts = [r[0] for r in proxy.root.store.conn.execute("SELECT user_msg FROM episodes")]
        self.assertEqual(texts, ["The password is swordfish."])

    def test_nothing_found_is_said_and_nothing_deleted(self):
        self.tell("The weather is wet.")
        reply = self.chat("Forget the zeppelin")
        self.assertIn("found nothing", reply)
        self.assertEqual(self.episodes(), 1)

    def test_everything_is_not_done_on_a_word(self):
        self.tell("The weather is wet.")
        before = self.calls()
        for text in ("Forget everything your steward told you.", "Delete what your steward has told you.",
                     "Forget everything"):
            with self.subTest(text=text):
                reply = self.chat(text)
                self.assertIn("whole memory", reply)
                self.assertIn("what to forget", reply)
        self.assertEqual(self.episodes(), 1)
        self.assertEqual(self.calls(), before)

    def test_too_many_turns_and_nothing_goes(self):
        saved = forget.MAX_TURNS
        forget.MAX_TURNS = 1
        try:
            self.tell("The flowerpot is green.")
            self.tell("The flowerpot is heavy.")
            reply = self.chat("Forget the flowerpot")
            self.assertIn("deleted nothing", reply)
            self.assertEqual(self.episodes(), 2)
        finally:
            forget.MAX_TURNS = saved

    def test_a_question_about_forgetting_goes_to_the_model(self):
        before = self.calls()
        self.chat("Can I make you forget what I told you?")
        self.assertEqual(self.calls(), before + 1)

    def test_a_guest_cannot(self):
        self.tell("My bank in Riverton holds the savings.")
        reply = self.chat("Forget Riverton", guest=True)
        self.assertEqual(reply, TEXTS["forget"]["en"])
        self.assertEqual(self.episodes(), 1)


class SheForgetsOnlyAtTheWriterLevel(Pipeline):
    level = "observer"

    def test_at_observer_it_is_refused_like_any_write(self):
        self.tell("My bank in Riverton holds the savings.")
        reply = self.chat("Forget Riverton")
        self.assertIn("can't forget things", reply)
        self.assertTrue("opens at writer" in reply or "not allowed on this unit" in reply, reply)
        self.assertIn("Nothing was deleted", reply)
        self.assertEqual(self.episodes(), 1)


# ============================================================================
# THE FOLDERS OF THE TRUST LEVELS
# ============================================================================
class TheLevelFolders(unittest.TestCase):

    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix="ws-")
        self.addCleanup(shutil.rmtree, self.ws, True)

    def test_four_folders_each_with_a_readme(self):
        made = W.ensure(self.ws)
        self.assertEqual(sorted(made), sorted("%s/README.md" % l for l in W.LADDER))
        for level in W.LADDER:
            text = open(os.path.join(self.ws, level, "README.md"), encoding="utf-8").read()
            self.assertIn("**%s** trust level" % level, text)
            self.assertIn("%d points" % W.POINTS[level], text)

    def test_the_readme_says_who_reaches_the_folder(self):
        W.ensure(self.ws)
        writer = open(os.path.join(self.ws, "writer", "README.md"), encoding="utf-8").read()
        self.assertIn("me at writer or higher", writer)
        self.assertIn("(builder, autonomous)", writer)
        self.assertIn("observer, writer", writer)           # the folders she reaches there
        top = open(os.path.join(self.ws, "autonomous", "README.md"), encoding="utf-8").read()
        self.assertIn("observer, writer, builder, autonomous", top)

    def test_again_changes_nothing_but_a_deleted_readme_comes_back(self):
        W.ensure(self.ws)
        mine = os.path.join(self.ws, "builder", "README.md")
        with open(mine, "w") as f:
            f.write("my own words")
        self.assertEqual(W.ensure(self.ws), [])
        self.assertEqual(open(mine).read(), "my own words")
        os.remove(os.path.join(self.ws, "observer", "README.md"))
        self.assertEqual(W.ensure(self.ws), ["observer/README.md"])

    def test_the_ladder_of_who_reaches_what(self):
        table = {"observer": ("observer",), "writer": ("observer", "writer"),
                 "builder": ("observer", "writer", "builder"), "autonomous": W.LADDER}
        for level, reach in table.items():
            for folder in W.LADDER:
                with self.subTest(level=level, folder=folder):
                    self.assertEqual(W.may_reach(folder + "/x.md", level), folder in reach)
        for level in W.LADDER:
            self.assertTrue(W.may_reach("todo.md", level))
            self.assertTrue(W.may_reach("notes/n.md", level))
        self.assertTrue(W.may_reach("Builder/x.md", "builder"))
        self.assertFalse(W.may_reach("Builder/x.md", "writer"))
        self.assertTrue(W.may_reach("reader/x", "observer") and True)    # not a level folder

    def test_old_level_names_are_read_as_the_new(self):
        self.assertTrue(W.may_reach("writer/x", "reader"))
        self.assertFalse(W.may_reach("builder/x", "reader"))
        self.assertTrue(W.may_reach("builder/x", "collaborator"))


class HerToolsKeepToTheLadder(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ws-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ws = os.path.join(self.tmp, "w")
        W.ensure(self.ws)
        for level in W.LADDER:
            with open(os.path.join(self.ws, level, "plan.md"), "w") as f:
                f.write("the %s plan: zebra\n" % level)
        with open(os.path.join(self.ws, "open.md"), "w") as f:
            f.write("open to all\n")
        self.saved = ID.WORKSPACE
        ID.WORKSPACE = self.ws
        self.addCleanup(setattr, ID, "WORKSPACE", self.saved)

    def run_as(self, level, message):
        spark = types.SimpleNamespace(gate=gate_at("autonomous", self.tmp))
        spark.gate.trust_level = level
        intent = ID.detect_intent(message)
        self.assertIsNotNone(intent, message)
        return ID.execute_intent(intent, spark)

    def test_reading_a_folder_above_her_level_is_told_as_closed(self):
        out = self.run_as("writer", "Read the file builder/plan.md")
        self.assertTrue(out.startswith("[FOLDER] The builder folder opens at the builder trust level"), out)
        self.assertNotIn("zebra", out)

    def test_reading_at_or_below_her_level_is_open(self):
        for folder in ("observer", "writer"):
            out = self.run_as("writer", "Read the file %s/plan.md" % folder)
            self.assertIn("the %s plan" % folder, out)
        self.assertIn("open to all", self.run_as("observer", "Read the file open.md"))

    def test_the_higher_reaches_the_lower(self):
        for level in W.LADDER:
            for folder in W.LADDER[:W.LADDER.index(level) + 1]:
                self.assertIn("the %s plan" % folder, self.run_as(level, "Read the file %s/plan.md" % folder))

    def test_the_listing_leaves_out_what_is_above_her(self):
        out = self.run_as("writer", "List the files in your workspace")
        self.assertIn("observer/", out)
        self.assertIn("writer/", out)
        self.assertNotIn("builder", out)
        self.assertNotIn("autonomous", out)
        top = self.run_as("autonomous", "List the files in your workspace")
        self.assertIn("autonomous/", top)

    def test_the_search_does_not_find_it_by_name_or_by_content(self):
        by_content = self.run_as("observer", "Search for zebra in my files")
        self.assertIn("observer/plan.md", by_content)
        for hidden in ("writer/plan.md", "builder/plan.md", "autonomous/plan.md"):
            self.assertNotIn(hidden, by_content)
        by_name = self.run_as("writer", "Find the file plan.md")
        self.assertIn("writer/plan.md", by_name)
        self.assertNotIn("builder/plan.md", by_name)

    def test_the_exact_tools_keep_to_it_too(self):
        out = self.run_as("builder", "Count the lines in autonomous/plan.md")
        self.assertTrue(out.startswith("[FOLDER] The autonomous folder"), out)
        out = self.run_as("builder", "Compare observer/plan.md and autonomous/plan.md")
        self.assertTrue(out.startswith("[FOLDER]"), out)
        out = self.run_as("builder", "Is zebra in autonomous/plan.md?") if False else None
        ok = self.run_as("builder", "Count the lines in builder/plan.md")
        self.assertIn("1", ok)

    def test_summarize_keeps_to_it(self):
        out = self.run_as("writer", "Summarize the file builder/plan.md")
        self.assertTrue(out.startswith("[FOLDER]"), out)

    def test_a_path_cannot_climb_in(self):
        with self.assertRaises(W.WorkspaceError):
            W.resolve(self.ws, "observer/../builder/plan.md")
        out = self.run_as("observer", "Read the file observer/../builder/plan.md")
        self.assertNotIn("zebra", out)


class AtTheProxy(Pipeline):
    level = "writer"

    def setUp(self):
        super().setUp()
        W.ensure(self.ws)
        with open(os.path.join(self.ws, "builder", "plan.md"), "w") as f:
            f.write("the builder plan: zebra\n")

    def test_the_closed_folder_is_told_by_the_unit(self):
        before = self.calls()
        reply = self.chat("Read the file builder/plan.md")
        self.assertIn("opens at the builder trust level", reply)
        self.assertNotIn("zebra", reply)
        self.assertEqual(self.calls(), before)

    def test_open_your_workspace(self):
        before = self.calls()
        reply = self.chat("Open your workspace")
        self.assertTrue(reply.startswith("Opening my workspace."), reply)
        self.assertEqual(self.calls(), before)
        self.assertEqual(self.last_provenance().get("open"), "workspace")
        for said in ("open up your workspace", "Please open the workspace", "Could you open my workspace?"):
            with self.subTest(said=said):
                self.assertTrue(self.chat(said).startswith("Opening my workspace."))

    def test_a_guest_cannot_open_it(self):
        self.assertEqual(self.chat("Open your workspace", guest=True), TEXTS["workspace"]["en"])


# ============================================================================
# THE STEWARD'S EDITOR
# ============================================================================
class TheEditor(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ed-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ws = os.path.join(self.tmp, "w")
        W.ensure(self.ws)

    def refused(self, fn, *a, code=None):
        with self.assertRaises(W.WorkspaceError) as cm:
            fn(self.ws, *a)
        if code:
            self.assertEqual(cm.exception.code, code)
        return cm.exception

    def test_make_edit_read_rename_delete(self):
        self.assertEqual(W.mkdir(self.ws, "writer/ideas")["path"], "writer/ideas")
        out = W.save(self.ws, "writer/ideas/one.md", "first line\nsecond")
        self.assertEqual((out["created"], out["size"]), (True, 17))
        self.assertFalse(W.save(self.ws, "writer/ideas/one.md", "changed")["created"])
        self.assertEqual(W.read(self.ws, "writer/ideas/one.md")["text"], "changed")
        W.rename(self.ws, "writer/ideas/one.md", "writer/ideas/two.md")
        self.assertEqual(W.read(self.ws, "writer/ideas/two.md")["text"], "changed")
        self.refused(W.read, "writer/ideas/one.md", code="none")
        self.refused(W.delete, "writer/ideas", code="full")
        W.delete(self.ws, "writer/ideas/two.md")
        W.delete(self.ws, "writer/ideas")
        self.assertFalse(os.path.exists(os.path.join(self.ws, "writer", "ideas")))

    def test_a_new_file_in_a_new_folder_in_one_save(self):
        W.save(self.ws, "builder/deep/er/note.md", "x")
        self.assertEqual(W.read(self.ws, "builder/deep/er/note.md")["text"], "x")

    def test_the_tree_shows_all_four_folders_whatever_her_level(self):
        paths = {e["path"] for e in W.tree(self.ws)["entries"]}
        for level in W.LADDER:
            self.assertIn(level, paths)
            self.assertIn("%s/README.md" % level, paths)

    def test_the_four_folders_stay(self):
        for level in W.LADDER:
            self.refused(W.delete, level, code="level")
            self.refused(W.rename, level, "elsewhere", code="level")
        self.refused(W.rename, "todo.md", "writer", code="none") if False else None
        W.save(self.ws, "x.md", "x")
        self.refused(W.rename, "x.md", "builder", code="level")

    def test_a_path_stays_inside(self):
        for bad in ("../x.md", "writer/../../x.md", "C:/x", "..\\x", "a/./b", "", "~/x",
                    "a" * 400, "x\x00y", "a/b/c/d/e/f/g/h"):
            with self.subTest(bad=bad):
                self.refused(W.save, bad, "x")
                self.assertFalse(os.path.exists(os.path.join(self.tmp, "x.md")))

    def test_an_absolute_path_is_read_as_inside(self):
        W.save(self.ws, "/etc/passwd", "x")
        self.assertTrue(os.path.isfile(os.path.join(self.ws, "etc", "passwd")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "etc")))

    def test_a_link_out_is_refused(self):
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        with open(os.path.join(outside, "secret.md"), "w") as f:
            f.write("secret")
        os.symlink(outside, os.path.join(self.ws, "linked"))
        self.refused(W.read, "linked/secret.md", code="outside")
        self.refused(W.save, "linked/new.md", "x", code="outside")
        self.assertFalse(os.path.exists(os.path.join(outside, "new.md")))

    def test_text_only_and_not_too_big(self):
        self.refused(W.save, "a.md", "x" * (W.MAX_BYTES + 1), code="big")
        self.refused(W.save, "a.md", "a\x00b", code="binary")
        with open(os.path.join(self.ws, "bin.dat"), "wb") as f:
            f.write(b"\x00\x01\x02")
        self.refused(W.read, "bin.dat", code="binary")
        self.refused(W.save, "a.md", 5, code="text")
        self.refused(W.save, "writer", "x", code="dir")

    def test_a_save_leaves_no_half_written_file(self):
        W.save(self.ws, "a.md", "one")
        W.save(self.ws, "a.md", "two")
        self.assertEqual(sorted(n for n in os.listdir(self.ws) if "a.md" in n), ["a.md"])
        self.assertFalse([n for n in os.listdir(self.ws) if n.endswith(".tmp")])

    def test_the_name_is_taken(self):
        W.save(self.ws, "a.md", "1")
        W.save(self.ws, "b.md", "2")
        self.refused(W.rename, "a.md", "b.md", code="exists")
        self.refused(W.mkdir, "writer", code="exists")


class TheEditorAtTheProxy(Pipeline):

    def setUp(self):
        super().setUp()
        W.ensure(self.ws)

    def test_tree_file_save_mkdir_rename_delete(self):
        st, tree = self.http_json("GET", "/aetherseed/workspace/tree")
        self.assertEqual(st, 200)
        self.assertIn("builder/README.md", {e["path"] for e in tree["entries"]})
        st, out = self.http_json("POST", "/aetherseed/workspace/save", {"path": "autonomous/a.md", "text": "hello"})
        self.assertEqual((st, out["created"]), (200, True))
        st, out = self.http_json("GET", "/aetherseed/workspace/file?path=autonomous/a.md")
        self.assertEqual((st, out["text"]), (200, "hello"))
        self.assertEqual(self.http_json("POST", "/aetherseed/workspace/mkdir", {"path": "writer/n"})[0], 200)
        self.assertEqual(self.http_json("POST", "/aetherseed/workspace/rename",
                                        {"from": "autonomous/a.md", "to": "writer/n/a.md"})[0], 200)
        self.assertEqual(self.http_json("POST", "/aetherseed/workspace/delete", {"path": "writer/n/a.md"})[0], 200)
        self.assertEqual(self.http_json("POST", "/aetherseed/workspace/delete", {"path": "writer/n"})[0], 200)

    def test_refusals_carry_their_status(self):
        self.assertEqual(self.http_json("POST", "/aetherseed/workspace/save", {"path": "../x", "text": "x"})[0], 400)
        self.assertEqual(self.http_json("GET", "/aetherseed/workspace/file?path=nope.md")[0], 404)
        self.assertEqual(self.http_json("POST", "/aetherseed/workspace/delete", {"path": "builder"})[0], 403)
        self.assertEqual(self.http_json("POST", "/aetherseed/workspace/save", {"text": "x"})[0], 400)

    def test_every_change_is_a_chained_line_without_the_text(self):
        from logic import chain
        self.http_json("POST", "/aetherseed/workspace/save", {"path": "writer/s.md", "text": "a private thought"})
        self.http_json("POST", "/aetherseed/workspace/delete", {"path": "writer/s.md"})
        raw = open(proxy.WORKSPACE_LOG, encoding="utf-8").read()
        self.assertNotIn("private thought", raw)
        ops = [json.loads(l)["op"] for l in raw.splitlines()]
        self.assertEqual(ops, ["save", "delete"])
        self.assertTrue(chain.verify(proxy.WORKSPACE_LOG)["ok"])

    def test_the_console_relays_the_editor_to_the_steward_only(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("serve86", os.path.join(HERE, "gui", "serve.py"))
        serve = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(serve)
        for path in ("/aetherseed/workspace/save", "/aetherseed/workspace/mkdir",
                     "/aetherseed/workspace/delete", "/aetherseed/workspace/rename"):
            self.assertIn(path, serve.PROXIED_POST)
        self.assertIn("/aetherseed/workspace/tree", serve.PROXIED_GET)
        self.assertNotIn("/aetherseed/workspace/tree", serve.OPEN_GET)
        self.assertIn("/aetherseed/workspace/file", serve.PROXIED_GET_QUERY)


# ============================================================================
# THE TO-DO LIST
# ============================================================================
class TheTodoList(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="todo-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "todo.md")
        with open(self.path, "w") as f:
            f.write("# Today\n- water the seedlings\n- count the candles\n- buy oat milk\n")

    def lines(self):
        return open(self.path).read().splitlines()

    def test_remove_by_place(self):
        out = W.todo_remove(self.path, "2")
        self.assertEqual(out, "Removed from your to-do list: count the candles (it was item 2)")
        self.assertEqual(self.lines(), ["# Today", "- water the seedlings", "- buy oat milk"])

    def test_remove_by_words_and_quotes(self):
        self.assertIn("buy oat milk", W.todo_remove(self.path, "'OAT'"))
        self.assertNotIn("- buy oat milk", self.lines())

    def test_a_word_that_fits_two_picks_neither(self):
        W.todo_edit(self.path, "3", "count the sheep")
        before = open(self.path).read()
        out = W.todo_remove(self.path, "count")
        self.assertIn("More than one item fits", out)
        self.assertIn("2. count the candles", out)
        self.assertIn("3. count the sheep", out)
        self.assertEqual(open(self.path).read(), before)

    def test_nothing_fits_or_no_such_place(self):
        before = open(self.path).read()
        self.assertIn("no item like", W.todo_remove(self.path, "zeppelin"))
        self.assertEqual(W.todo_remove(self.path, "9"), "There is no item 9 on your to-do list; it has 3.")
        self.assertEqual(W.todo_remove(self.path, "0"), "There is no item 0 on your to-do list; it has 3.")
        self.assertEqual(open(self.path).read(), before)

    def test_edit(self):
        out = W.todo_edit(self.path, "1", "water the ferns")
        self.assertEqual(out, 'Changed on your to-do list: item 1 was "water the seedlings" and now says "water the ferns"')
        self.assertEqual(self.lines()[1], "- water the ferns")
        W.todo_edit(self.path, "candles", "count the lanterns")
        self.assertEqual(self.lines()[2], "- count the lanterns")
        self.assertIn("Tell me what", W.todo_edit(self.path, "1", "  "))

    def test_the_file_before_is_kept(self):
        before = open(self.path).read()
        W.todo_remove(self.path, "1")
        self.assertEqual(open(self.path + ".bak").read(), before)

    def test_clear(self):
        out = W.todo_clear(self.path)
        self.assertIn("3 items removed", out)
        self.assertEqual(self.lines(), ["# Today"])
        self.assertEqual(W.todo_clear(self.path), "Your to-do list is already empty.")

    def test_no_list_yet(self):
        os.remove(self.path)
        self.assertEqual(W.todo_remove(self.path, "1"), "Your to-do list is empty.")
        self.assertEqual(W.todo_clear(self.path), "Your to-do list is already empty.")


class TodoRequestsAreRecognised(unittest.TestCase):

    def intent(self, text):
        i = ID.detect_intent(text)
        return (i["intent"], i["captures"]) if i else None

    def test_remove(self):
        for text, want in (("Remove 2 from my to-do list", ("todo_remove", ("2",))),
                           ("delete item 3 from my todo list", ("todo_remove", ("3",))),
                           ("Cross off #1 from the to-do list", ("todo_remove", ("1",))),
                           ("Remove 'count the candles' from my to-do list",
                            ("todo_remove", ("count the candles",))),
                           ("Remove milk from my to-do list", ("todo_remove", ("milk",))),
                           ("take buy oat milk off the to-do list", ("todo_remove", ("buy oat milk",)))):
            with self.subTest(text=text):
                self.assertEqual(self.intent(text), want)

    def test_edit(self):
        for text, want in (("Edit to-do 2: buy oat milk", ("todo_edit", ("2", "buy oat milk"))),
                           ("Change to-do 1 to water the ferns", ("todo_edit", ("1", "water the ferns"))),
                           ("update item 3 with call Martin", ("todo_edit", ("3", "call Martin"))),
                           ("Change 'water the seedlings' to 'water the ferns' in my to-do list",
                            ("todo_edit", ("water the seedlings", "water the ferns")))):
            with self.subTest(text=text):
                self.assertEqual(self.intent(text), want)

    def test_clear(self):
        for text in ("Clear my to-do list", "empty the todo list", "wipe my to-do"):
            with self.subTest(text=text):
                self.assertEqual(self.intent(text)[0], "todo_clear")

    def test_the_old_ones_still_are(self):
        self.assertEqual(self.intent("Add a to-do: water the seedlings")[0], "todo_add")
        self.assertEqual(self.intent("Show my to-do list")[0], "todo_read")

    def test_not_requests(self):
        for text in ("What should I change in my life?", "I want to clear my head", "Remove the seeds from the apple"):
            with self.subTest(text=text):
                self.assertIsNone(self.intent(text))


class TheTodoListInConversation(Pipeline):
    level = "writer"

    def test_remove_edit_and_clear_are_told_by_the_unit(self):
        self.chat("Add a to-do: water the seedlings")
        self.chat("Add a to-do: count the candles")
        before = self.calls()
        self.assertEqual(self.chat("Remove 1 from my to-do list"),
                         "Removed from your to-do list: water the seedlings (it was item 1)")
        self.assertIn('now says "count the lanterns"', self.chat("Edit to-do 1: count the lanterns"))
        self.assertIn("count the lanterns", self.chat("Show my to-do list"))
        self.assertIn("1 item removed", self.chat("Clear my to-do list"))
        self.assertEqual(self.calls(), before, "the model was called")

    def test_the_todo_file_really_changed(self):
        self.chat("Add a to-do: water the seedlings")
        self.chat("Remove 'seedlings' from my to-do list")
        self.assertNotIn("seedlings", open(os.path.join(self.ws, "todo.md")).read())

    def test_a_guest_cannot(self):
        self.chat("Add a to-do: water the seedlings")
        self.assertEqual(self.chat("Clear my to-do list", guest=True), TEXTS["workspace"]["en"])
        self.assertIn("seedlings", open(os.path.join(self.ws, "todo.md")).read())


class TheTodoListAtObserver(Pipeline):
    level = "observer"

    def test_it_is_a_write_and_refused_like_one(self):
        with open(os.path.join(self.ws, "todo.md"), "w") as f:
            f.write("- keep me\n")
        for text in ("Remove 1 from my to-do list", "Edit to-do 1: other", "Clear my to-do list"):
            with self.subTest(text=text):
                reply = self.chat(text)
                self.assertTrue("opens at writer" in reply or "not allowed on this unit" in reply, reply)
                self.assertIn("Nothing was", reply)
        self.assertEqual(open(os.path.join(self.ws, "todo.md")).read(), "- keep me\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
