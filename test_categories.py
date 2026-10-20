"""The console in three categories, the logo, her records and her workspace.

    python3 -m unittest test_categories -v


"""
import json
import os
import re
import shutil
import tempfile
import unittest

import proxy                            # first, and for real (see test_brake)
from test_memory_turn import _Proxy

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "gui", "index.html"), encoding="utf-8") as _f:
    HTML = _f.read()


def block(html, open_tag_id):
    """The markup of the element with that id, to its matching close."""
    m = re.search(r'<div class="setup" id="%s"' % open_tag_id, html)
    depth, i = 0, m.start()
    for t in re.finditer(r"<(/?)div\b", html[i:]):
        depth += -1 if t.group(1) else 1
        if depth == 0:
            return html[i:i + t.end()]
    raise AssertionError("unclosed")


class TheHeader(unittest.TestCase):

    def header(self):
        return HTML[HTML.index("<header>"):HTML.index("</header>")]

    def test_three_categories_the_brake_and_quantum_rest(self):
        h = self.header()
        ids = re.findall(r'<button[^>]*id="(\w+)"', h)
        #a phone that has not signed in as the steward sees
        # "Sign in" in place of the five, which are the steward's. The
        # steward's header is still the five (sign-out is in AetherSeed).
        self.assertEqual(ids, ["signInBtn", "catSeed", "catRoot", "catSpark", "brakeBtn", "offBtn"])
        self.assertIn('id="health"', h, "on device / unreachable stays in sight")

    def test_what_left_the_header_is_in_its_category(self):
        seed, root, spark = (block(HTML, p) for p in ("seedPanel", "rootPanel", "sparkPanel"))
        for i in ("trust", "modelChip", "recordBtn", "whoForm", "trustRecord", "tmTools", "tmReason"):
            self.assertIn('id="%s"' % i, seed, i)
        for i in ("memoryChip", "rings", "recCheck", "recList"):
            self.assertIn('id="%s"' % i, root, i)
        for i in ("trainBtn", "shelfBtn", "wsTodo", "wsNotes", "wsFiles"):
            self.assertIn('id="%s"' % i, spark, i)

    def test_every_id_once(self):
        ids = re.findall(r'\bid="([^"]+)"', HTML)
        dup = sorted({i for i in ids if ids.count(i) > 1})
        self.assertEqual(dup, [])

    def test_the_logo_is_carried_in_the_page(self):
        imgs = re.findall(r'<img[^>]*src="data:image/webp;base64,([A-Za-z0-9+/=]+)"', HTML)
        self.assertEqual(len(imgs), 2, "the mark in the header, the logo on the first screen")
        import base64
        for b in imgs:
            self.assertEqual(base64.b64decode(b)[8:12], b"WEBP")

    def test_both_languages_carry_the_new_words(self):
        for key in ("seedHelp", "rootHelp", "sparkHelp", "tmTitle", "tmReason", "tmGrant",
                    "tmLower", "tmFreeze", "tmUnfreeze", "tmAllow", "tmBlock", "tmClear",
                    "tmEvent", "recTitle", "recHelp", "recHolds", "recBad", "wsTitle",
                    "wsTodoTitle", "wsNoTodo"):
            self.assertEqual(len(re.findall(r"\b%s:" % key, HTML)), 2, key)

    def test_the_console_relays_the_two_new_reads(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("serve_cat", os.path.join(HERE, "gui", "serve.py"))
        serve = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(serve)
        for p in ("/aetherseed/records", "/aetherseed/workspace", "/aetherseed/trust"):
            self.assertIn(p, serve.PROXIED_GET)
        self.assertNotIn("/aetherseed/workspace", serve.PROXIED_POST, "read-only")


class HerWorkspace(unittest.TestCase):

    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix="ws72-")
        os.makedirs(os.path.join(self.ws, "notes"))

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_files_notes_and_the_list_as_they_are(self):
        with open(os.path.join(self.ws, "todo.txt"), "w") as f:
            f.write("- dry the matches\n")
        with open(os.path.join(self.ws, "notes", "note_20261012_101500.md"), "w") as f:
            f.write("# Note — 2026-10-12 10:15\n\nthe seedlings are up\n")
        with open(os.path.join(self.ws, ".hidden"), "w") as f:
            f.write("x")
        v = proxy.workspace_view(self.ws)
        self.assertEqual([f["name"] for f in v["files"]], ["notes", "todo.txt"])
        self.assertEqual((v["todo"], v["todo_name"]), ("- dry the matches\n", "todo.txt"))
        self.assertEqual(v["notes"], [{"name": "note_20261012_101500.md",
                                       "first": "the seedlings are up"}])

    def test_md_is_read_before_txt(self):
        for n, t in (("todo.txt", "old"), ("todo.md", "new")):
            with open(os.path.join(self.ws, n), "w") as f:
                f.write(t)
        self.assertEqual(proxy.workspace_view(self.ws)["todo_name"], "todo.md")

    def test_no_workspace_is_an_empty_one(self):
        v = proxy.workspace_view(os.path.join(self.ws, "none"))
        self.assertEqual((v["files"], v["notes"], v["todo"]), ([], [], None))


class TheRoutes(_Proxy):

    def test_her_records_checked_now(self):
        proxy.record({"prompt": "a", "answer": "b"})
        d = self.get("/aetherseed/records")
        names = [r["record"] for r in d["records"]]
        # and this month's prompts
        self.assertEqual(names, list(proxy.CHAINED_RECORDS)
                         + [os.path.basename(proxy._prompts_log())])
        prov = d["records"][0]
        self.assertEqual((prov["ok"], prov["chained"], prov["exists"]), (True, 1, True))

    def test_her_workspace_read_only(self):
        d = self.get("/aetherseed/workspace")
        self.assertEqual(set(d), {"files", "notes", "todo", "todo_name"})


if __name__ == "__main__":
    unittest.main()
