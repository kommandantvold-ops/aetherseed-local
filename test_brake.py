"""The steward's brake.

    python3 -m unittest test_brake -v

a steward control that cuts the reply in the middle
and makes the proxy refuse turns until it is released. These run the real
proxy in front of a scripted model that streams one chunk at a time.
"""
import http.client
import http.server
import json
import os
import re
import shutil
import tempfile
import threading
import time
import unittest

import proxy                            # first, and for real, as test_gate_answers does:
from test_memory_turn import _Proxy     # imported after it, so no stub of its stays in it
from logic import chain

HERE = os.path.dirname(os.path.abspath(__file__))
SLOW = {"chunks": ["The", " river", " runs", " east", " to", " the", " sea", "."],
        "delay": 0.0, "requests": 0, "first_sent": threading.Event()}


class _SlowModel(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        SLOW["requests"] += 1
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        try:
            for i, c in enumerate(SLOW["chunks"]):
                self.wfile.write(json.dumps({"model": "llama3.2:3b", "done": False,
                                             "message": {"role": "assistant", "content": c}}
                                            ).encode() + b"\n")
                self.wfile.flush()
                if i == 0:
                    SLOW["first_sent"].set()
                time.sleep(SLOW["delay"])
            self.wfile.write(json.dumps({"model": "llama3.2:3b", "done": True,
                                         "done_reason": "stop",
                                         "message": {"role": "assistant", "content": ""}}
                                        ).encode() + b"\n")
        except (BrokenPipeError, ConnectionResetError):
            pass                          # the proxy abandoned the stream: as it should


class TheBrake(_Proxy):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.slow = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SlowModel)
        threading.Thread(target=cls.slow.serve_forever, daemon=True).start()
        cls.saved_url = proxy.HAILO_OLLAMA_URL
        proxy.HAILO_OLLAMA_URL = "http://127.0.0.1:%d" % cls.slow.server_address[1]

    @classmethod
    def tearDownClass(cls):
        proxy.HAILO_OLLAMA_URL = cls.saved_url
        cls.slow.shutdown()
        cls.slow.server_close()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.saved_files = (proxy.BRAKE_FILE, proxy.CONTROL_LOG)
        proxy.BRAKE_FILE = os.path.join(self.tmp, "brake.json")
        proxy.CONTROL_LOG = os.path.join(self.tmp, "control.log")
        proxy.BRAKE.clear()
        proxy._BRAKE_STATE = {"on": False}
        SLOW.update(delay=0.0, requests=0)
        SLOW["first_sent"].clear()

    def tearDown(self):
        proxy.BRAKE.clear()
        proxy._BRAKE_STATE = {"on": False}
        proxy.BRAKE_FILE, proxy.CONTROL_LOG = self.saved_files
        super().tearDown()

    def post(self, path, obj):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        c.request("POST", path, body=json.dumps(obj), headers={"Content-Type": "application/json"})
        r = c.getresponse()
        body = r.read()
        c.close()
        try:
            return r.status, json.loads(body)
        except ValueError:
            return r.status, body

    def brake(self, on):
        return self.post("/aetherseed/brake", {"action": "on" if on else "off",
                                               "reason": "test"})

    def episodes(self):
        return proxy.root.store.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]

    # ---- on, off, and what it says ----------------------------------------

    def test_on_every_turn_is_refused_plainly_and_nothing_is_kept(self):
        status, d = self.brake(True)
        self.assertEqual((status, d["brake"]["on"], d["changed"]), (200, True, True))
        before = self.episodes()
        status, text, meta = self.ask("Which way does the river run?")
        self.assertEqual(status, 200)
        self.assertIn("brake", text)
        self.assertIs(meta["braked"], True)
        self.assertEqual(SLOW["requests"], 0, "the model is not asked")
        self.assertEqual(self.episodes(), before, "nothing is remembered")
        self.assertIs(self.record()[-1]["braked"], True)

    def test_released_she_answers_again(self):
        self.brake(True)
        status, d = self.brake(False)
        self.assertEqual((status, d["brake"]["on"]), (200, False))
        status, text, meta = self.ask("Which way does the river run?")
        self.assertEqual(text, "The river runs east to the sea.")
        self.assertNotIn("braked", meta)

    def test_pressed_twice_it_is_on_once(self):
        self.brake(True)
        status, d = self.brake(True)
        self.assertEqual((status, d["changed"]), (200, False))
        self.assertEqual(chain.verify(proxy.CONTROL_LOG)["chained"], 1)

    def test_an_unknown_action_is_refused(self):
        status, d = self.post("/aetherseed/brake", {"action": "maybe"})
        self.assertEqual(status, 400)
        self.assertFalse(proxy.BRAKE.is_set())

    def test_the_status_says_it(self):
        self.brake(True)
        st = self.get("/aetherseed/status")["brake"]
        self.assertEqual((st["on"], st["by"], st["reason"]), (True, "the console", "test"))
        self.assertEqual(self.get("/aetherseed/brake")["brake"]["on"], True)

    # ---- mid-stream --------------------------------------------------------

    def test_it_cuts_the_answer_in_the_middle(self):
        SLOW["delay"] = 0.15
        got = {}

        def asking():
            got["r"] = self.ask("Which way does the river run?")
        before = self.episodes()
        t = threading.Thread(target=asking)
        t.start()
        self.assertTrue(SLOW["first_sent"].wait(5))
        time.sleep(0.2)
        t0 = time.monotonic()
        self.brake(True)
        t.join(10)
        self.assertFalse(t.is_alive())
        status, text, meta = got["r"]
        self.assertEqual(status, 200)
        self.assertNotEqual(text, "The river runs east to the sea.", "the answer was cut")
        self.assertTrue("The river runs east to the sea.".startswith(text))
        self.assertIs(meta["braked"], True)
        self.assertIs(meta["cut"], True)
        self.assertLess(time.monotonic() - t0, 2.0, "it stops at the next chunk")
        self.assertEqual(self.episodes(), before, "a cut answer is not remembered")
        rec = self.record()[-1]
        self.assertEqual((rec["braked"], rec["cut"]), (True, True))

    # ---- what goes round it -----------------------------------------------

    def test_no_model_call_starts_while_it_is_on(self):
        proxy.BRAKE.set()
        with self.assertRaises(proxy.Braked):
            proxy.call_hailo_chat("llama3.2:3b", [{"role": "user", "content": "hi"}])
        self.assertEqual(SLOW["requests"], 0)

    def test_straight_to_the_model_server_is_refused(self):
        self.brake(True)
        status, d = self.post("/api/generate", {"model": "llama3.2:3b", "prompt": "hi"})
        self.assertEqual(status, 423)
        self.assertEqual(SLOW["requests"], 0)

    def test_no_homework_starts_while_it_is_on(self):
        self.brake(True)
        status, d = self.post("/aetherseed/training", {"action": "start"})
        self.assertEqual(status, 409)
        self.assertEqual(d["error"], "the brake is on")

    # ---- written down and recorded ----------------------------------------

    def test_on_and_off_are_recorded_in_the_chain(self):
        self.brake(True)
        self.brake(False)
        r = chain.verify(proxy.CONTROL_LOG)
        self.assertEqual((r["ok"], r["chained"]), (True, 2))
        with open(proxy.CONTROL_LOG) as f:
            actions = [json.loads(l)["action"] for l in f]
        self.assertEqual(actions, ["brake_on", "brake_released"])

    def test_a_restart_keeps_it_on(self):
        self.brake(True)
        proxy.BRAKE.clear()                    # the process is gone
        proxy._BRAKE_STATE = {"on": False}
        st = proxy.load_brake()                # a new start
        self.assertTrue(st["on"])
        self.assertTrue(proxy.BRAKE.is_set())
        status, text, meta = self.ask("Which way does the river run?")
        self.assertIs(meta["braked"], True)

    def test_released_before_a_restart_it_stays_released(self):
        self.brake(True)
        self.brake(False)
        proxy.BRAKE.set()
        self.assertFalse(proxy.load_brake()["on"])
        self.assertFalse(proxy.BRAKE.is_set())

    def test_a_file_it_cannot_read_keeps_it_on(self):
        with open(proxy.BRAKE_FILE, "w") as f:
            f.write('{"on": fal')           # cut by a power failure
        st = proxy.load_brake()
        self.assertTrue(st["on"])
        self.assertIn("could not be read", st["reason"])

    def test_never_pressed_it_is_off(self):
        self.assertFalse(proxy.load_brake()["on"])


class TheTrainingLoop(unittest.TestCase):
    """A turn the brake refused or cut is not her answer."""

    def test_it_is_not_scored_and_the_run_pauses(self):
        from logic import training
        d = tempfile.mkdtemp(prefix="brake-train-")
        try:
            def ask(say, level, keep=True):
                return {"reply": "I am stopped", "meta": {"braked": True}, "status": 200,
                        "error": None, "braked": True}
            loop = training.Loop(d, ask=ask)
            loop.state.update(status="running", asked=0, hers_asked=0, remembered={})
            before = (loop.state["asked"], loop.state["hers_asked"])
            loop._one({"said": "What is your name?", "level": "observer", "by": "model",
                       "id": "unit.name", "topic": "your own name", "keep": True})
            self.assertEqual((loop.state["asked"], loop.state["hers_asked"]), before)
            self.assertEqual(loop.state["status"], "paused")
            self.assertEqual(loop.state["note"], "paused by the brake")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TheConsole(unittest.TestCase):

    def setUp(self):
        with open(os.path.join(HERE, "gui", "index.html"), encoding="utf-8") as f:
            self.html = f.read()

    def test_the_brake_is_in_sight_and_release_asks(self):
        for el in ('id="brakeBtn"', 'id="brakeBar"', 'id="releaseBtn"', 'id="release"',
                   'id="releaseGo"', 'id="releaseCancel"'):
            self.assertIn(el, self.html)

    def test_both_languages_name_it(self):
        for key in ("brake:", "brakeOn:", "release:", "releaseTitle:", "releaseHelp:",
                    "releaseGo:", "releaseFailed:", "brakeFailed:", "braked:"):
            self.assertEqual(len(re.findall(r"\b" + key + r"\s*'", self.html)), 2, key)

    def test_the_console_passes_it_to_the_unit(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("serve_brake", os.path.join(HERE, "gui", "serve.py"))
        serve = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(serve)
        self.assertIn("/aetherseed/brake", serve.PROXIED_POST)
        self.assertIn("/aetherseed/brake", serve.PROXIED_GET)


if __name__ == "__main__":
    unittest.main()
