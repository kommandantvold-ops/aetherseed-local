"""Shutting down without pulling the plug.

Step 34 (25 Sep 2026). Two ways, both ending in an orderly poweroff:

  the board's power button - logind's HandlePowerKey=poweroff, which the kiosk
    had been blocking: labwc read the system desktop config, started the Pi
    desktop behind the console, and an inhibitor handed the key to a dialog.
  a console button - the unprivileged console files a request; a root-owned
    systemd path unit performs it.
"""
import http.client
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("serve_shutdown", HERE / "gui" / "serve.py")
serve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(serve)

HTML = (HERE / "gui" / "index.html").read_text(encoding="utf-8")


class TheConsoleFilesARequest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        serve.CSP = serve.build_csp(HTML)
        serve.BACKEND = "http://127.0.0.1:9"     # nothing answers: nothing relayed
        cls.srv = serve.Threaded(("127.0.0.1", 0), serve.Console)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.req = os.path.join(self.dir, "shutdown-request")
        serve.SHUTDOWN_REQUEST = self.req

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _post(self, body, ctype="application/json"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("POST", "/aetherseed/shutdown",
                  body=json.dumps(body).encode() if not isinstance(body, bytes) else body,
                  headers={"Content-Type": ctype})
        r = c.getresponse(); data = r.read(); c.close()
        return r.status, data

    def test_a_confirmed_request_is_filed(self):
        status, data = self._post({"confirm": "shut down"})
        self.assertEqual(202, status)
        self.assertEqual({"shutting_down": True}, json.loads(data))
        self.assertTrue(os.path.exists(self.req))

    def test_an_unconfirmed_request_is_not(self):
        for body in ({}, {"confirm": "yes"}, {"confirm": True}, b"not json", ["shut down"]):
            with self.subTest(body=body):
                status, _ = self._post(body)
                self.assertEqual(400, status)
                self.assertFalse(os.path.exists(self.req))

    def test_only_json_is_accepted(self):
        status, _ = self._post(b'{"confirm": "shut down"}', ctype="text/plain")
        self.assertEqual(415, status)
        self.assertFalse(os.path.exists(self.req))

    def test_a_unit_without_the_path_unit_says_so(self):
        serve.SHUTDOWN_REQUEST = os.path.join(self.dir, "missing", "shutdown-request")
        status, _ = self._post({"confirm": "shut down"})
        self.assertEqual(503, status)

    def test_it_is_not_relayed_to_the_proxy(self):
        self.assertNotIn(serve.SHUTDOWN_PATH, serve.PROXIED_POST)


class ThePiecesAgree(unittest.TestCase):
    """Three files name the same path; the kiosk and the cartridge must match."""

    def _unit(self, name):
        return (HERE / "services" / name).read_text(encoding="utf-8")

    def test_the_path_unit_watches_what_the_console_writes(self):
        default = "/run/aetherseed-gui/shutdown-request"
        self.assertIn("AETHERSEED_SHUTDOWN_REQUEST", (HERE / "gui" / "serve.py").read_text())
        self.assertIn(f'"{default}"', (HERE / "gui" / "serve.py").read_text())
        self.assertIn(f"PathExists={default}", self._unit("aetherseed-shutdown.path"))
        self.assertIn(f"rm -f {default}", self._unit("aetherseed-shutdown.service"))
        self.assertIn("RuntimeDirectory=aetherseed-gui", self._unit("aetherseed-gui.service"))

    def test_the_request_is_removed_before_poweroff(self):
        lines = [l for l in self._unit("aetherseed-shutdown.service").splitlines()
                 if l.startswith("ExecStart=")]
        self.assertIn("rm -f", lines[0])
        self.assertIn("poweroff", lines[1])

    def test_the_proxy_cannot_file_a_request(self):
        proxy = self._unit("aetherseed-proxy.service")
        self.assertIn("ProtectSystem=strict", proxy)
        self.assertNotIn("/run/aetherseed-gui", proxy)

    def test_the_kiosk_reads_only_its_own_config(self):
        unit = self._unit("aetherseed-kiosk.service")
        self.assertIn("labwc -C /opt/aetherseed/kiosk/labwc -s", unit)
        rc = (HERE / "kiosk" / "labwc" / "rc.xml").read_text(encoding="utf-8")
        body = re.sub(r"<!--.*?-->", "", rc, flags=re.S)
        self.assertNotIn("<default", body)
        self.assertNotIn("pwrkey", body)
        self.assertRegex(body, r'key="XF86PowerOff">\s*<action name="None"')
        auto = (HERE / "kiosk" / "labwc" / "autostart").read_text(encoding="utf-8")
        self.assertEqual([], [l for l in auto.splitlines() if l.strip() and not l.startswith("#")])

    def test_the_kiosk_keeps_its_keyboard(self):
        env = (HERE / "kiosk" / "labwc" / "environment").read_text(encoding="utf-8")
        self.assertIn("XKB_DEFAULT_LAYOUT=gb", env)

    def test_the_cartridge_covers_the_new_units(self):
        cart = (HERE / "tools" / "cartridge.sh").read_text(encoding="utf-8")
        for u in ("aetherseed-shutdown.path", "aetherseed-shutdown.service"):
            self.assertIn("/etc/systemd/system/" + u, cart)


class TheButton(unittest.TestCase):
    def test_both_languages_have_every_string(self):
        for key in ("off:", "offTitle:", "offHelp:", "offGo:", "offCancel:", "offDone:", "offFailed:"):
            self.assertEqual(2, HTML.count(key), key)

    def test_no_browser_dialog(self):
        script = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", HTML, re.S))
        for call in ("confirm(", "alert(", "prompt("):
            self.assertNotIn(call, script)


if __name__ == "__main__":
    unittest.main()
