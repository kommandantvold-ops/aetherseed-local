"""The console: what it serves, what it refuses, and what it lets run.

    python3 -m unittest test_console -v

Standard library only. No browser is needed - and that is the point of the
first class below. The console's script was refused by its own CSP from the
day it was written until the day someone finally opened it in a browser;
every endpoint had been checked with curl, which runs no JavaScript. These
tests make that failure visible without a browser in the loop.
"""
import base64
import hashlib
import http.client
import importlib.util
import os
import re
import sys
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "gui", "index.html")

_spec = importlib.util.spec_from_file_location("serve", os.path.join(HERE, "gui", "serve.py"))
serve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(serve)

with open(INDEX, encoding="utf-8") as _f:
    HTML = _f.read()


def _sha(body):
    return "'sha256-%s'" % base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode()


class TestThePageMayRunItsOwnScript(unittest.TestCase):
    """The regression tests for the night the console never ran."""

    def setUp(self):
        self.csp = serve.build_csp(HTML)
        self.directives = dict(
            (d.strip().split(" ", 1) + [""])[:2] for d in self.csp.split(";") if d.strip())

    def test_every_inline_script_is_pinned(self):
        # THE test. Fails against the original header, which had no
        # script-src at all and so let default-src 'self' refuse the page.
        scripts = re.findall(r"<script>(.*?)</script>", HTML, re.S)
        self.assertTrue(scripts, "the page has no inline script - this test is testing nothing")
        self.assertIn("script-src", self.directives,
                      "no script-src: default-src 'self' will refuse every inline script")
        for body in scripts:
            self.assertIn(_sha(body), self.directives["script-src"])

    def test_every_inline_style_is_pinned(self):
        for body in re.findall(r"<style>(.*?)</style>", HTML, re.S):
            self.assertIn(_sha(body), self.directives.get("style-src", ""))

    def test_nothing_is_allowed_wholesale(self):
        # A hash says "this script may run". unsafe-inline says "any may".
        self.assertNotIn("unsafe-inline", self.csp)
        self.assertNotIn("unsafe-eval", self.csp)
        self.assertNotIn("*", self.csp)

    def test_a_changed_script_is_not_pinned(self):
        # The pin is to the bytes. One character different is a different script.
        body = re.findall(r"<script>(.*?)</script>", HTML, re.S)[0]
        self.assertNotIn(_sha(body + " "), self.directives["script-src"])

    def test_nothing_leaves(self):
        self.assertEqual(self.directives.get("default-src"), "'self'")
        self.assertEqual(self.directives.get("connect-src"), "'self'")
        self.assertEqual(self.directives.get("frame-ancestors"), "'none'")


class TestThePageReachesForNothing(unittest.TestCase):

    def test_no_external_references(self):
        self.assertIsNone(re.search(r"""(?:src|href)\s*=|@import|url\(\s*['"]?(?:https?:)?//""", HTML),
                          "the console must load nothing from anywhere")
        self.assertNotRegex(HTML, r"https?://")


class TestWhatTheConsoleRelays(unittest.TestCase):
    """A real server on an ephemeral port, relaying to a backend that is not there.

    A relayed route therefore answers 502, and a refused route 404 - which
    tells the two apart without a proxy, a model or an NPU.
    """

    @classmethod
    def setUpClass(cls):
        serve.CSP = serve.build_csp(HTML)
        serve.BACKEND = "http://127.0.0.1:9"        # discard port: nothing answers
        cls.srv = serve.Threaded(("127.0.0.1", 0), serve.Console)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def _req(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path, body=body, headers={"Content-Type": "application/json"})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, r.getheader("Content-Security-Policy"), data

    def test_the_page_is_served_with_its_pin(self):
        status, csp, data = self._req("GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(csp, serve.build_csp(HTML))
        self.assertEqual(data.decode("utf-8"), HTML)

    def test_nothing_is_kept(self):
        # The page must be re-fetched after a new cartridge, and the record's
        # prompt excerpts must never land in the browser's disk cache.
        for method, path in (("GET", "/"), ("GET", "/aetherseed/status"),
                             ("GET", "/nope"), ("POST", "/api/chat")):
            with self.subTest(path=path):
                c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
                c.request(method, path, body=b"{}" if method == "POST" else None)
                r = c.getresponse(); r.read(); c.close()
                self.assertEqual(r.getheader("Cache-Control"), "no-store")

    def test_nothing_else_on_disk_is_served(self):
        for path in ("/serve.py", "/etc/passwd", "/../proxy.py", "/%2e%2e/proxy.py",
                     "/index.html/", "/gui/index.html", "/favicon.ico"):
            with self.subTest(path=path):
                self.assertEqual(self._req("GET", path)[0], 404)

    def test_only_the_allow_list_is_relayed(self):
        for path in serve.PROXIED_GET:
            with self.subTest(path=path):
                self.assertEqual(self._req("GET", path)[0], 502)
        for path in serve.PROXIED_POST:
            with self.subTest(path=path):
                self.assertEqual(self._req("POST", path, b"{}")[0], 502)
        self.assertEqual(set(serve.PROXIED_POST),
                         {"/api/chat", "/aetherseed/setup", "/aetherseed/steward"},
                         "a new POST route reaches the proxy only by being added here on purpose")
        # guided correction's list takes a query string, matched on its path (50)
        self.assertEqual(self._req("GET", "/aetherseed/memories?limit=5&q=cat")[0], 502)
        self.assertEqual(self._req("GET", "/aetherseed/memories")[0], 502)
        self.assertEqual(self._req("GET", "/aetherseed/memoriesX?q=1")[0], 404)
        self.assertEqual(self._req("GET", "/aetherseed/status?x=1")[0], 404)

    def test_a_status_poll_is_the_witness_that_the_console_is_on_the_screen(self):
        # build log 53: services/aetherseed-kiosk-watch.service reads this file's time
        import tempfile
        d = tempfile.mkdtemp(prefix="seen-")
        saved, serve.CONSOLE_SEEN = serve.CONSOLE_SEEN, os.path.join(d, "console-seen")
        try:
            self._req("GET", "/aetherseed/rings")
            self._req("GET", "/")
            self.assertFalse(os.path.exists(serve.CONSOLE_SEEN))
            self._req("GET", "/aetherseed/status")
            self.assertTrue(os.path.exists(serve.CONSOLE_SEEN))
            self.assertEqual(os.path.getsize(serve.CONSOLE_SEEN), 0)
            os.utime(serve.CONSOLE_SEEN, (1, 1))
            self._req("GET", "/aetherseed/status")
            self.assertGreater(os.path.getmtime(serve.CONSOLE_SEEN), 1)
            serve.CONSOLE_SEEN = os.path.join(d, "no", "such", "dir", "x")
            self.assertEqual(self._req("GET", "/aetherseed/status")[0], 502)   # still relayed
        finally:
            serve.CONSOLE_SEEN = saved
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_the_model_cannot_be_reached_around_the_guards(self):
        # /api/generate goes to the model with none of the proxy's guards.
        for path in ("/api/generate", "/api/pull", "/api/delete", "/api/chat/"):
            with self.subTest(path=path):
                self.assertEqual(self._req("POST", path, b"{}")[0], 404)

    def test_the_heartbeat_counts_without_recording(self):
        before = dict(serve._counts)
        self._req("GET", "/")
        self._req("GET", "/nope")
        self.assertEqual(serve._counts["page"], before["page"] + 1)
        self.assertEqual(serve._counts["refused"], before["refused"] + 1)
        self.assertLessEqual(set(serve._counts),
                             {"page", "status", "record", "rings", "chat", "setup", "refused",
                              "memories", "steward"},
                             "the heartbeat keeps counts by route and nothing else")



class TheRingTree(unittest.TestCase):
    """Step 37: the rings chip opens every ring - what it chose, the model's own
    sentence labelled as such, and the turns it took."""

    HTML = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui", "index.html"),
                encoding="utf-8").read()

    def test_both_languages_have_every_string(self):
        for key in ("told:", "usedFacts:", "usedRing:", "treeTitle:", "treeHelp:", "chosen:",
                    "ownWords:", "ownPending:", "ownWithheld:", "ringHead:", "growing:",
                    "noRings:", "noTree:", "steward:", "unknown:"):
            en = self.HTML[self.HTML.index("  en: {"):self.HTML.index("  nb: {")]
            nb = self.HTML[self.HTML.index("  nb: {"):self.HTML.index("\n};\n")]
            with self.subTest(key=key):
                self.assertEqual(1, en.count(key + " "), key)
                self.assertEqual(1, nb.count(key + " "), key)

    def test_what_people_and_the_model_said_is_never_markup(self):
        script = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", self.HTML, re.S))
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            self.assertNotIn(sink, script)

    def test_the_rings_are_relayed_read_only(self):
        self.assertIn("/aetherseed/rings", serve.PROXIED_GET)
        self.assertNotIn("/aetherseed/rings", serve.PROXIED_POST)

    def test_guided_correction_speaks_both_languages(self):
        for key in ("memTitle:", "tabRings:", "tabTurns:", "ringsHelp:", "turnsHelp:",
                    "right:", "wrong:", "undo:", "supported:", "corrected:", "supportAsk:",
                    "capped:", "q1:", "reasons:", "q2:", "q2opt:", "q3:", "willTurn:",
                    "willRing:", "willFact:", "willSupportGone:", "willUndo:", "confirm:",
                    "stewardErrors:"):
            en = self.HTML[self.HTML.index("  en: {"):self.HTML.index("  nb: {")]
            nb = self.HTML[self.HTML.index("  nb: {"):self.HTML.index("\n};\n")]
            with self.subTest(key=key):
                for block in (en, nb):
                    self.assertRegex(block, r"[\s{,]" + re.escape(key) + r" ", key)

    def test_a_correction_says_what_will_change_before_it_is_made(self):
        # step 3 of the guide lists the change and the undo; only its button
        # sends the correction.
        script = self.HTML[self.HTML.index("const step3"):]
        self.assertLess(script.index("s.willUndo"), script.index("action: 'correct'"))
        self.assertEqual(1, self.HTML.count("action: 'correct'"))

    def test_the_steward_route_is_the_only_way_to_change_memory(self):
        self.assertIn("/aetherseed/steward", serve.PROXIED_POST)
        self.assertIn("/aetherseed/memories", serve.PROXIED_GET_QUERY)
        self.assertNotIn("/aetherseed/memories", serve.PROXIED_POST)

    def test_her_own_words_are_always_labelled(self):
        # The label is in the same string as the words - there is no way to
        # render the sentence without it.
        self.assertIn("${s.ownWords(name)} “${ring.own_words}”", self.HTML)

class TheStewardCreditTag(unittest.TestCase):
    """Step 41: an answer that credits the steward with something it was not
    shown is tagged where the person reads it - in both languages, and only
    when the check said so (steward_backed false, not merely absent)."""

    HTML = TheRingTree.HTML

    def test_both_languages_have_it(self):
        self.assertEqual(2, self.HTML.count("stewardUnbacked: "))

    def test_it_follows_the_check_and_nothing_else(self):
        self.assertIn("p.steward_credited && p.steward_backed === false", self.HTML)
        self.assertIn("tag(s.stewardUnbacked, 'flagged')", self.HTML)


if __name__ == "__main__":
    unittest.main(verbosity=2)
