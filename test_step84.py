"""the manual, on her shelf and in the console.

    python3 -m unittest test_step84 -v

 The manual says what she does; these tests hold it to the code.
"""
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from logic import manual  # noqa: E402
from logic import library as lib  # noqa: E402
from logic import levels  # noqa: E402
from logic import user_training as UT  # noqa: E402

EN = open(manual.source_path("en"), encoding="utf-8").read()
NB = open(manual.source_path("nb"), encoding="utf-8").read()


class TheText(unittest.TestCase):

    def test_both_languages_have_every_section(self):
        en, nb = manual.sections("en"), manual.sections("nb")
        self.assertEqual(len(en), len(nb))
        self.assertGreaterEqual(len(en), 10)
        self.assertTrue(en[0].get("top"))

    def test_the_commands_it_names_are_the_ones_she_knows(self):
        from intent_detection import detect_intent
        for said, intent in (("Show my to-do list", "todo_read"),
                             ("Add a to-do: water the seedlings", "todo_add"),
                             ("Add 'buy milk' to my to-do list", "todo_add"),
                             ("Write a note: the first root goes down.", "note_write"),
                             ("Show me my notes.", "note_list"),
                             ("List the files in your workspace", "file_list"),
                             ("Read the file seed.md", "file_read"),
                             ("Search for rice in my files", "file_search"),
                             ("Summarize the file seed.md", "summarize"),
                             ("Calculate 12 * (7 + 5)", "calculate"),
                             ("Count the words in seed.md", "count"),
                             ("How many times does the word first appear in seed.md?", "count_word"),
                             ("Compare seed.md and copy-of-seed.md", "compare"),
                             ("system health check", "system_health")):
            with self.subTest(said=said):
                self.assertIn(said.rstrip("."), EN.replace('."', '"'))
                got = detect_intent(said)
                self.assertEqual(got and got["intent"], intent)

    def test_the_unit_answers_it_names(self):
        from logic.provenance import is_record_question
        from logic.clock import is_date_question
        from logic.gate_answers import is_level_question, is_ladder_question
        from logic.steward import is_corrections_question
        self.assertTrue(is_record_question("What have you gotten wrong?"))
        self.assertTrue(is_date_question("What's the date today?"))
        self.assertTrue(is_level_question("What is your trust level?"))
        self.assertTrue(is_ladder_question("What are your trust levels, lowest first?"))
        self.assertTrue(is_corrections_question("Show me your corrections."))
        for said in ("look up water purification", "look up momentum in my book"):
            self.assertIsNotNone(lib.lookup_query(said))
        self.assertTrue(lib.lookup_in_own("look up momentum in my book"))
        self.assertTrue(lib.asks_contents("What is in the library?"))
        self.assertTrue(lib.says_look_it_up("look it up"))
        self.assertTrue(lib.says_look_it_up("slå det opp"))

    def test_the_numbers_it_gives_are_the_builds(self):
        for level in levels.LADDER:
            self.assertIn("%s (" % level, EN)
            self.assertIn("%s (" % level, NB)
        for level, pts in levels.POINTS.items():
            if pts:
                self.assertIn("%s (%d)" % (level, pts), EN)
        self.assertIn("up to ten a round", EN)
        self.assertEqual(UT.TURNS, 10)
        self.assertIn("256 KB and 300 questions a file, 20 files, 500 questions in all", EN)
        self.assertEqual((UT.MAX_BYTES, UT.MAX_PER_FILE, UT.MAX_FILES, UT.MAX_TOTAL),
                         (256 * 1024, 300, 20, 500))

    def test_its_example_file_is_taken(self):
        for text in (EN, NB):
            block = "\n".join(l[4:] for l in text.splitlines()
                              if l.startswith("    ") and not l.startswith("     ")
                              and re.match(r"    (title|document|Q|A|KEY|NOT):|    $", l + " "))
            meta, items, errors = UT.parse(block)
            self.assertEqual(errors, [], block)
            self.assertEqual(len(items), 2)


class OnTheShelf(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="library-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_built_once_and_found_by_look_up(self):
        self.assertTrue(manual.ensure(self.dir))
        self.assertFalse(manual.ensure(self.dir), "the same text is not built again")
        library = lib.Library(self.dir, own="")
        c = library.collections[0]
        self.assertFalse(c.own, "nobody's private document: a guest may read it")
        hit = library.look_up("training files")
        self.assertIsNotNone(hit)
        self.assertIn("training file", (hit["heading"] + hit["text"]).lower())
        self.assertIn("treningsfil", (library.look_up("treningsfiler")["text"]).lower())

    def test_built_by_the_install_as_a_command(self):
        import subprocess
        r = subprocess.run([sys.executable, "-m", "logic.manual", self.dir], cwd=HERE,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("built", r.stdout)
        self.assertTrue(manual.current(self.dir))
        r = subprocess.run([sys.executable, "-m", "logic.manual", self.dir], cwd=HERE,
                           capture_output=True, text=True, timeout=120)
        self.assertIn("up to date", r.stdout)

    def test_a_changed_text_is_built_again(self):
        manual.ensure(self.dir)
        saved = manual.SOURCES
        try:
            manual.SOURCES = (("en", "AetherSeed manual"),)
            self.assertTrue(manual.ensure(self.dir))
        finally:
            manual.SOURCES = saved


class InTheConsole(unittest.TestCase):

    def test_the_page_offers_it_in_both_languages(self):
        html = open(os.path.join(HERE, "gui", "index.html"), encoding="utf-8").read()
        self.assertIn('id="helpBtn"', html)
        self.assertIn("help: 'Help'", html)
        self.assertIn("help: 'Hjelp'", html)
        self.assertIn("'/aetherseed/manual?lang='", html)

    def test_the_console_serves_it_to_anybody(self):
        import http.client
        import threading
        sys.path.insert(0, os.path.join(HERE, "gui"))
        import serve
        saved = (serve.OWN_SCREEN, serve.CSP)
        serve.OWN_SCREEN = frozenset()               # a guest's phone
        serve.CSP = "default-src 'self'"
        srv = serve.Threaded(("127.0.0.1", 0), serve.Console)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            for lang, first in (("en", "AetherSeed manual"), ("nb", "AetherSeed-manual")):
                c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
                c.request("GET", "/aetherseed/manual?lang=" + lang)
                r = c.getresponse()
                import json
                d = json.loads(r.read())
                c.close()
                self.assertEqual(r.status, 200)
                self.assertEqual(d["sections"][0]["title"], first)
        finally:
            srv.shutdown(); srv.server_close()
            serve.OWN_SCREEN, serve.CSP = saved


if __name__ == "__main__":
    unittest.main(verbosity=2)
