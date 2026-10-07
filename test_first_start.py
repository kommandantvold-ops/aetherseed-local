"""The first start of a unit onboarded where it will live (build log 66).

    python3 -m unittest test_first_start -v

Andreas, 7 Oct 2026: "Onboarded on-site means the user will pick name passkey
and start it for the first time" - and: "install a fresh build on the pi on
the 4th pi ... and that sd card will be copied for new pilot units."

Three parts, each tried without a Pi, a radio or root's clock:

  - the console server takes the date and time and the passkey only at the
    unit's own screen, only on a unit armed for a first start, files them
    for root and waits for root's answer;
  - tools/first_start.sh, root's side, with the clock and the Wi-Fi tool
    stood in for;
  - tools/source_card.sh refuses to make a source of a unit that has been
    started.

Standard library only.
"""
import http.client
import http.server
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
SERVICES = os.path.join(HERE, "services")
FIRST_START = os.path.join(HERE, "tools", "first_start.sh")
SOURCE_CARD = os.path.join(HERE, "tools", "source_card.sh")

_spec = importlib.util.spec_from_file_location("serve_fs", os.path.join(HERE, "gui", "serve.py"))
serve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(serve)

KEY = "correct horse 42"


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class _Elsewhere(serve.Console):
    """The same console, asked from a screen that is not the unit's own."""
    def _own_screen(self):
        return False


class AtTheConsole(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.flag = os.path.join(self.tmp, "first-start")
        self.request = os.path.join(self.tmp, "first-start-request")
        self.result = os.path.join(self.tmp, "first-start-result")
        self._was = (serve.FIRST_START_FLAG, serve.FIRST_START_REQUEST,
                     serve.FIRST_START_RESULT, serve.FIRST_START_WAIT, serve.CSP)
        serve.FIRST_START_FLAG, serve.FIRST_START_REQUEST = self.flag, self.request
        serve.FIRST_START_RESULT, serve.FIRST_START_WAIT = self.result, 3.0
        serve.CSP = "default-src 'none'"
        self.srv = serve.Threaded(("127.0.0.1", 0), serve.Console)
        self.far = serve.Threaded(("127.0.0.1", 0), _Elsewhere)
        for s in (self.srv, self.far):
            threading.Thread(target=s.serve_forever, daemon=True).start()
        self.seen = None            # what root's side read from the request

    def tearDown(self):
        for s in (self.srv, self.far):
            s.shutdown(); s.server_close()
        (serve.FIRST_START_FLAG, serve.FIRST_START_REQUEST, serve.FIRST_START_RESULT,
         serve.FIRST_START_WAIT, serve.CSP) = self._was

    def arm(self):
        open(self.flag, "w").close()

    def call(self, method="POST", body=None, srv=None, ctype="application/json"):
        c = http.client.HTTPConnection("127.0.0.1", (srv or self.srv).server_address[1], timeout=20)
        data = json.dumps(body).encode() if body is not None else None
        c.request(method, "/aetherseed/first-start", body=data,
                  headers={"Content-Type": ctype} if data is not None else {})
        r = c.getresponse()
        out = (r.status, json.loads(r.read() or b"{}"))
        c.close()
        return out

    def root(self, answer):
        """Root's side, stood in for: takes the request, leaves an answer."""
        def work():
            for _ in range(200):
                if os.path.exists(self.request):
                    self.mode = stat.S_IMODE(os.stat(self.request).st_mode)
                    with open(self.request, encoding="utf-8") as f:
                        self.seen = f.read()
                    os.unlink(self.request)
                    with open(self.result, "w", encoding="utf-8") as f:
                        f.write(answer)
                    return
                time.sleep(0.02)
        threading.Thread(target=work, daemon=True).start()

    # ---- what the page is told ----------------------------------------------
    def test_a_unit_that_was_set_up_at_a_shell_is_not_asked(self):
        status, d = self.call("GET")
        self.assertEqual(status, 200)
        self.assertEqual((d["armed"], d["own_screen"]), (False, True))
        self.assertRegex(d["now"], r"^20\d\d-\d\d-\d\dT\d\d:\d\d$")

    def test_an_armed_unit_says_so_and_says_whose_screen_is_asking(self):
        self.arm()
        self.assertEqual(self.call("GET")[1]["armed"], True)
        self.assertEqual(self.call("GET", srv=self.far)[1]["own_screen"], False)

    # ---- the three locks -------------------------------------------------------
    def test_only_at_the_units_own_screen(self):
        self.arm()
        status, d = self.call(body={"when": "2026-10-07T15:30", "passkey": KEY}, srv=self.far)
        self.assertEqual((status, d["code"]), (403, "not_own_screen"))
        self.assertFalse(os.path.exists(self.request))

    def test_only_on_a_unit_armed_for_it(self):
        status, d = self.call(body={"when": "2026-10-07T15:30", "passkey": KEY})
        self.assertEqual((status, d["code"]), (409, "not_armed"))
        self.assertFalse(os.path.exists(self.request))

    def test_only_a_date_and_time_and_a_passkey(self):
        self.arm()
        for body, code in (
            ({"when": "2026-02-31T10:00", "passkey": KEY}, "bad_when"),
            ({"when": "1999-01-01T10:00", "passkey": KEY}, "bad_when"),
            ({"when": "2026-10-07T24:00", "passkey": KEY}, "bad_when"),
            ({"when": "2026-10-07T15:30\n2026-01-01 00:00", "passkey": KEY}, "bad_when"),
            ({"when": "now", "passkey": KEY}, "bad_when"),
            ({"passkey": KEY}, "bad_when"),
            ({"when": "2026-10-07T15:30", "passkey": "seven77"}, "bad_passkey"),
            ({"when": "2026-10-07T15:30", "passkey": "x" * 64}, "bad_passkey"),
            ({"when": "2026-10-07T15:30", "passkey": "åtte tegn"}, "bad_passkey"),
            ({"when": "2026-10-07T15:30", "passkey": "two\nlines here"}, "bad_passkey"),
            ({"when": "2026-10-07T15:30", "passkey": 12345678}, "bad_passkey"),
            ({"when": "2026-10-07T15:30"}, "bad_passkey"),
        ):
            with self.subTest(body=str(body)[:50]):
                status, d = self.call(body=body)
                self.assertEqual((status, d["code"]), (400, code))
                self.assertFalse(os.path.exists(self.request))

    def test_a_form_post_is_not_a_first_start(self):
        self.arm()
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        c.request("POST", "/aetherseed/first-start", body=b"when=x",
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(c.getresponse().status, 415)
        c.close()

    # ---- filed for root, and root's answer brought back ---------------------
    def test_it_is_filed_for_root_and_roots_answer_comes_back(self):
        self.arm()
        self.root("ok\nBjorn\n")
        said = io.StringIO()
        with redirect_stdout(said):
            status, d = self.call(body={"when": "2026-10-07T15:30", "passkey": KEY})
        self.assertEqual((status, d), (200, {"ok": True, "network": "Bjorn"}))
        self.assertEqual(self.seen, "2026-10-07 15:30\n" + KEY + "\n")
        self.assertEqual(self.mode, 0o600, "the passkey is for root to read, and nobody else")
        self.assertNotIn(KEY, said.getvalue(), "the passkey is never logged")
        self.assertNotIn(KEY, json.dumps(d))

    def test_what_root_refuses_is_said_in_roots_words(self):
        self.arm()
        self.root("error\nwifi\nThe unit's Wi-Fi could not be set up: no radio\n")
        status, d = self.call(body={"when": "2026-10-07T15:30", "passkey": KEY})
        self.assertEqual((status, d["code"]), (422, "wifi"))
        self.assertEqual(d["error"], "The unit's Wi-Fi could not be set up: no radio")

    def test_if_nobody_takes_it_the_passkey_does_not_stay_in_run(self):
        self.arm()
        serve.FIRST_START_WAIT = 0.6
        status, d = self.call(body={"when": "2026-10-07T15:30", "passkey": KEY})
        self.assertEqual((status, d["code"]), (504, "timeout"))
        self.assertFalse(os.path.exists(self.request))

    def test_the_page_has_the_step_in_both_languages_and_names_no_address_scheme(self):
        with open(os.path.join(HERE, "gui", "index.html"), encoding="utf-8") as f:
            html = f.read()
        for needle in ('id="stepStart"', 'id="dayInput"', 'id="monthInput"', 'id="yearInput"',
                       'id="hourInput"', 'id="minuteInput"', "day: 'Day'", "day: 'Dag'",
                       'id="keyInput"', "startTitle: (n) => `Two more things",
                       "startTitle: (n) => `To ting til", "/aetherseed/first-start"):
            self.assertIn(needle, html)
        self.assertNotIn('type="date"', html,
                         "the browser's own date box writes the day and the month in an order nobody chose")
        self.assertNotIn('type="password"', html,
                         "the passkey is typed in the open: it must be read back to be written down")


# ==============================================================================
class _Status(http.server.BaseHTTPRequestHandler):
    companion = {"configured": True, "name": "Bjørn"}

    def do_GET(self):
        body = json.dumps({"companion": self.companion}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class RootsSide(unittest.TestCase):
    """tools/first_start.sh, with the clock and the Wi-Fi tool stood in for."""

    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), _Status)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def setUp(self):
        _Status.companion = {"configured": True, "name": "Bjørn"}
        self.tmp = tempfile.mkdtemp()
        self.run_dir = os.path.join(self.tmp, "run"); os.makedirs(self.run_dir)
        self.flag = os.path.join(self.tmp, "first-start")
        self.log = os.path.join(self.tmp, "calls.log")
        self.hotspot = os.path.join(self.tmp, "hotspot.sh")
        self.clock = os.path.join(self.tmp, "clock.sh")
        self.hotspot_fails = os.path.join(self.tmp, "hotspot-fails")
        with open(self.hotspot, "w") as f:
            f.write('#!/bin/bash\nIFS= read -r k\necho "hotspot $1 [$2] key-length ${#k}" >> %s\n'
                    'printf "%%s" "$k" > %s.key\n'
                    '[ -e %s ] && { echo "hotspot: the profile could not be written" >&2; exit 2; }\n'
                    '[ ${#k} -ge 8 ] || { echo "hotspot: not a usable passkey (8-63 plain characters)" >&2; exit 2; }\n'
                    'echo "hotspot: set up"\n' % (self.log, self.log, self.hotspot_fails))
        with open(self.clock, "w") as f:
            f.write('#!/bin/bash\necho "clock $1" >> %s\n' % self.log)
        os.chmod(self.hotspot, 0o755); os.chmod(self.clock, 0o755)

    def start(self, when="2026-10-07 15:30", key=KEY, armed=True):
        if armed:
            open(self.flag, "w").close()
        with open(os.path.join(self.run_dir, "first-start-request"), "w") as f:
            f.write("%s\n%s\n" % (when, key))
        env = dict(os.environ, AETHERSEED_GUI_RUN=self.run_dir, AETHERSEED_FIRST_START_FLAG=self.flag,
                   AETHERSEED_HOTSPOT=self.hotspot, AETHERSEED_SET_CLOCK=self.clock,
                   AETHERSEED_STATUS_URL="http://127.0.0.1:%d/" % self.srv.server_address[1])
        p = subprocess.run(["bash", FIRST_START], env=env, capture_output=True, text=True)
        try:
            with open(os.path.join(self.run_dir, "first-start-result")) as f:
                result = f.read().split("\n")
        except OSError:
            result = None
        calls = read(self.log).splitlines() if os.path.exists(self.log) else []
        return p, result, calls

    def test_the_script_is_sound(self):
        for sh in (FIRST_START, SOURCE_CARD):
            self.assertEqual(subprocess.run(["bash", "-n", sh]).returncode, 0, sh)

    def test_the_clock_then_the_wifi_then_it_is_no_longer_armed(self):
        p, result, calls = self.start()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(calls, ["clock 2026-10-07 15:30", "hotspot on [Bjorn] key-length %d" % len(KEY)])
        self.assertEqual(read(self.log + ".key"), KEY, "the passkey reaches the Wi-Fi tool on its input")
        self.assertEqual(result[:2], ["ok", "Bjorn"])
        self.assertFalse(os.path.exists(self.flag), "one first start, and no second")
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "first-start-request")))
        self.assertNotIn(KEY, p.stdout + p.stderr + "\n".join(result))

    def test_a_unit_that_is_not_armed_is_left_exactly_as_it_is(self):
        p, result, calls = self.start(armed=False)
        self.assertEqual(result[:3], ["error", "not_armed", "This unit has been started before."])
        self.assertEqual(calls, [], "neither its clock nor its Wi-Fi is touched")
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "first-start-request")))

    def test_a_second_request_after_a_first_start_is_refused(self):
        self.start()
        p, result, calls = self.start(key="another passkey", armed=False)
        self.assertEqual(result[0], "error")
        self.assertEqual(len(calls), 2, "nothing was done the second time")

    def test_what_is_not_a_date_and_time_sets_nothing(self):
        for when in ("2026-02-31 10:00", "tomorrow", "2026-10-07 15:30; reboot", "",
                     "2026-10-07T15:30", "1999-12-31 23:59"):
            with self.subTest(when=when):
                p, result, calls = self.start(when=when)
                self.assertEqual(result[:2], ["error", "bad_when"])
                self.assertEqual(calls, [])
                self.assertTrue(os.path.exists(self.flag), "still armed: it can be tried again")
                if os.path.exists(self.log):
                    os.unlink(self.log)

    def test_a_passkey_the_wifi_tool_refuses_leaves_the_unit_armed(self):
        p, result, calls = self.start(key="short")
        self.assertEqual(result[:3], ["error", "bad_passkey", "The passkey must be 8 to 63 plain characters."])
        self.assertTrue(os.path.exists(self.flag))

    def test_a_wifi_that_will_not_come_up_is_said_and_can_be_tried_again(self):
        open(self.hotspot_fails, "w").close()
        p, result, calls = self.start()
        self.assertEqual(result[:2], ["error", "wifi"])
        self.assertIn("could not be set up", result[2])
        self.assertIn("the profile could not be written", result[2])
        self.assertTrue(os.path.exists(self.flag))
        self.assertNotIn(KEY, "\n".join(result))

    def test_the_networks_name_is_the_companions_in_plain_letters(self):
        for name, network in (("Bjørn", "Bjorn"), ("Åse-Marie", "Ase-Marie"), ("Lyra", "Lyra"),
                              ("Zoë O'Neil", "Zoe ONeil"), ("Ærø", "Aero")):
            with self.subTest(name=name):
                _Status.companion = {"configured": True, "name": name}
                p, result, calls = self.start()
                self.assertEqual(result[:2], ["ok", network])
                os.unlink(self.log)

    def test_a_unit_with_no_name_yet_is_told_to_name_it_first(self):
        _Status.companion = {"configured": False, "name": None}
        p, result, calls = self.start()
        self.assertEqual(result[:3], ["error", "no_name", "Name your companion first."])
        self.assertEqual([c for c in calls if c.startswith("hotspot")], [])
        self.assertTrue(os.path.exists(self.flag))

    def test_with_no_request_it_does_nothing(self):
        open(self.flag, "w").close()
        env = dict(os.environ, AETHERSEED_GUI_RUN=self.run_dir, AETHERSEED_FIRST_START_FLAG=self.flag,
                   AETHERSEED_HOTSPOT=self.hotspot, AETHERSEED_SET_CLOCK=self.clock)
        p = subprocess.run(["bash", FIRST_START], env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        self.assertFalse(os.path.exists(self.log))
        self.assertTrue(os.path.exists(self.flag))


# ==============================================================================
@unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "the seal is root's")
class ACardThatIsASource(unittest.TestCase):
    """tools/source_card.sh seal, as a dry run: what it refuses."""

    def setUp(self):
        self.state = tempfile.mkdtemp()
        self.etc = tempfile.mkdtemp()

    def seal(self, *more):
        env = dict(os.environ, AETHERSEED_STATE=self.state, AETHERSEED_ETC=self.etc, AETHERSEED_DRY="1")
        return subprocess.run(["bash", SOURCE_CARD, "seal"] + list(more), env=env,
                              capture_output=True, text=True)

    def test_a_seal_that_is_only_tried_restarts_and_says_it_is_not_a_card_to_copy(self):
        self.store(0)
        p = self.seal("--restart")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("would: systemctl --no-block reboot", p.stdout)
        self.assertNotIn("poweroff", p.stdout)
        self.assertIn("NOT a card to copy", p.stdout)

    def store(self, turns):
        import sqlite3
        d = os.path.join(self.state, ".aetherseed", "aetherroot"); os.makedirs(d)
        c = sqlite3.connect(os.path.join(d, "memory.db"))
        c.execute("create table episodes (id integer primary key, user_msg text)")
        c.executemany("insert into episodes (user_msg) values (?)", [("x",)] * turns)
        c.commit(); c.close()

    def test_a_unit_that_never_started_is_sealed(self):
        self.store(0)
        p = self.seal()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        for needle in ("would: touch %s/first-start %s/new-identity" % (self.etc, self.etc),
                       "would: systemctl enable aetherseed-first-start.path aetherseed-new-identity.service",
                       "would: rm -f /etc/ssh/ssh_host_", "would: systemctl --no-block poweroff"):
            self.assertIn(needle, p.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.etc, "first-start")), "a dry run changes nothing")

    def test_a_named_companion_is_never_made_a_source(self):
        self.store(0)
        with open(os.path.join(self.state, ".aetherseed", "companion.json"), "w") as f:
            json.dump({"name": "Lyra", "language": "en"}, f)
        p = self.seal()
        self.assertEqual(p.returncode, 2)
        self.assertIn("its companion is named (Lyra)", p.stderr)
        self.assertNotIn("would:", p.stdout, "nothing is even begun")

    def test_a_memory_with_a_turn_in_it_is_never_made_a_source(self):
        self.store(3)
        p = self.seal()
        self.assertEqual(p.returncode, 2)
        self.assertIn("its memory holds 3 turn(s)", p.stderr)
        self.assertNotIn("would:", p.stdout)

    def test_a_stewards_document_or_a_trust_record_stops_it_too(self):
        os.makedirs(os.path.join(self.state, "aetherseed-shelf"))
        open(os.path.join(self.state, "aetherseed-shelf", "physics.pdf"), "w").close()
        os.makedirs(os.path.join(self.state, ".aetherseed"))
        with open(os.path.join(self.state, ".aetherseed", "trust_state.json"), "w") as f:
            f.write("{}")
        p = self.seal()
        self.assertEqual(p.returncode, 2)
        self.assertIn("1 document(s) of a steward", p.stderr)
        self.assertIn("it has a trust record", p.stderr)


class TheUnits(unittest.TestCase):
    def unit(self, name):
        with open(os.path.join(SERVICES, name), encoding="utf-8") as f:
            return [l.strip() for l in f.read().splitlines() if l.strip() and not l.lstrip().startswith("#")]

    def test_the_path_watches_the_consoles_request_and_starts_roots_side(self):
        d = self.unit("aetherseed-first-start.path")
        self.assertIn("PathExists=/run/aetherseed-gui/first-start-request", d)
        self.assertIn("Unit=aetherseed-first-start.service", d)
        s = self.unit("aetherseed-first-start.service")
        self.assertIn("ExecStart=/bin/bash /opt/aetherseed/tools/first_start.sh", s)
        self.assertEqual([l for l in s if l.startswith("User=")], [], "it is root's, and says so by saying nothing")
        self.assertEqual(serve.FIRST_START_REQUEST, "/run/aetherseed-gui/first-start-request")

    def test_a_new_identity_only_where_a_seal_asked_for_one(self):
        d = self.unit("aetherseed-new-identity.service")
        self.assertIn("ConditionPathExists=/etc/aetherseed/new-identity", d)
        self.assertIn("WantedBy=sysinit.target", d)
        before = [l for l in d if l.startswith("Before=")][0]
        for u in ("ssh.service", "NetworkManager.service"):
            self.assertIn(u, before)
        last = [l for l in d if l.startswith("ExecStart=")][-1]
        self.assertIn("rm -f /etc/aetherseed/new-identity", last)
        self.assertIn("[ ! -e /etc/aetherseed/new-identity ] &&", last,
                      "it restarts only once the flag is gone, or it would restart for ever")

    def test_the_cartridge_sees_them(self):
        with open(os.path.join(HERE, "tools", "cartridge.sh"), encoding="utf-8") as f:
            text = f.read()
        for needle in ("/etc/systemd/system/aetherseed-first-start.path",
                       "/etc/systemd/system/aetherseed-first-start.service",
                       "/etc/systemd/system/aetherseed-new-identity.service",
                       "service.first_start.enabled", "service.new_identity.enabled"):
            self.assertIn(needle, text)

    def test_the_passkey_is_written_nowhere_by_roots_side(self):
        text = read(FIRST_START)
        self.assertNotIn('echo "$key', text)
        self.assertNotIn("logger", text)
        self.assertEqual(text.count('printf \'%s\\n\' "$key" | "$HOTSPOT" on'), 1)


if __name__ == "__main__":
    unittest.main()
