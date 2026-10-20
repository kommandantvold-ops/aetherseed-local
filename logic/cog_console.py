"""The COG-loop from the console.

 His choices (same day): a COG panel in the console; "correct" means
writing the review, fixing the essay text, and removing a reflection; every
review is stored as the trainer's, whoever wrote it; and essays wait for his
review - Claude no longer reviews them.

What the panel can do, and how:
  start N sessions   training/cog_loop.py --dir --sessions N, as a child of the
                     proxy (the service account, the proxy's own settings);
                     refused during a training run, with the brake on, or while
                     the COG-loop is already busy
  stop               a STOP file: it ends before the next session (the brake
                     stops it at once, as before)
  an essay           her essay as she wrote it, his corrected text if any, the
                     review, and the reflection with its episode number
  correct            essays/NNN.corrected.md, beside hers - hers is never
                     changed
  review             reviews/NNN.txt; not once a reflection is stored (remove
                     it first)
  reflect            cog_loop.py --reflect, as a child; her reflection goes
                     into memory through /aetherseed/cog/reflection as before
  remove             cog_loop.forget, through the proxy's own remove: mode
                     "cog" rows only, with a reason, logged word for word

Everything that reaches the model or her memory goes the ways
made; this module only starts them and reads and writes the harness's files.
"""

import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.join(APP, "training", "cog_loop.py")
BASE = os.path.expanduser("~/cog")
REVIEW_MAX = 1200            # what the proxy stores (proxy.COG_REVIEW_MAX)
CORRECTED_MAX = 8000
WHY_MAX = 300
SESSIONS_MAX = 8


def dir_for(model):
    return os.path.join(BASE, re.sub(r"[^A-Za-z0-9._-]", "_", model))


class ConsoleError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class CogConsole:
    def __init__(self, model, busy, remove, token, python=sys.executable, harness=HARNESS):
        """busy -> None or why the model must not be asked now (a training
        run, the brake); remove(payload, token) -> (status, body), the proxy's
        own remove_cog_reflection."""
        self.model = model
        self.dir = dir_for(model)
        self.busy = busy
        self.remove = remove
        self.token = token
        self.python = python
        self.harness = harness
        self._lock = threading.Lock()
        self._proc = None
        self._doing = None

    # ---- the child ---------------------------------------------------------
    def _running(self):
        return self._proc is not None and self._proc.poll() is None

    def _spawn(self, args, doing):
        with self._lock:
            if self._running():
                raise ConsoleError("busy", "the COG-loop is already busy: %s" % self._doing, 409)
            why = self.busy()
            if why:
                raise ConsoleError("unit_busy", "not now: %s" % why, 409)
            os.makedirs(self.dir, exist_ok=True)
            log = open(os.path.join(self.dir, "console.log"), "a", encoding="utf-8")
            log.write("\n== %s  %s\n" % (datetime.now(timezone.utc).isoformat(timespec="seconds"), doing))
            log.flush()
            self._proc = subprocess.Popen([self.python, self.harness] + args, cwd=APP,
                                          stdout=log, stderr=subprocess.STDOUT,
                                          stdin=subprocess.DEVNULL)
            log.close()
            self._doing = doing
            return {"started": doing}

    def start(self, sessions):
        if not isinstance(sessions, int) or not 1 <= sessions <= SESSIONS_MAX:
            raise ConsoleError("sessions", "1 to %d sessions" % SESSIONS_MAX)
        try:
            os.remove(os.path.join(self.dir, "STOP"))
        except FileNotFoundError:
            pass
        return self._spawn(["--dir", self.dir, "--sessions", str(sessions), "--model", self.model],
                           "%d session(s)" % sessions)

    def stop(self):
        if not self._running():
            raise ConsoleError("idle", "the COG-loop is not running", 409)
        with open(os.path.join(self.dir, "STOP"), "w") as f:
            f.write("from the console\n")
        return {"stopping": "after this session"}

    # ---- reading -----------------------------------------------------------
    def _harness(self):
        from training import cog_loop
        return cog_loop

    def _path(self, *parts):
        return os.path.join(self.dir, *parts)

    def _essay_numbers(self):
        ed = self._path("essays")
        if not os.path.isdir(ed):
            return []
        return sorted(int(m.group(1)) for m in
                      (re.match(r"(\d+)\.md$", n) for n in os.listdir(ed)) if m)

    def _state(self, n):
        if os.path.exists(self._path("reviews", "%03d.reflection.json" % n)):
            return "reflected"
        if os.path.exists(self._path("reviews", "%03d.reflection.removed.json" % n)):
            return "removed" if not os.path.exists(self._path("reviews", "%03d.txt" % n)) \
                else "reviewed"
        if os.path.exists(self._path("reviews", "%03d.txt" % n)):
            return "reviewed"
        return "waiting"

    def status(self):
        C = self._harness()
        essays = []
        for n in self._essay_numbers():
            theme, body = C.read_essay(self.dir, n)
            essays.append({"n": n, "theme": theme, "words": len(body.split()),
                           "state": self._state(n),
                           "corrected": os.path.exists(self._path("essays", "%03d.corrected.md" % n))})
        report = C.report(self.dir) if os.path.isdir(self.dir) else ""
        return {"model": self.model, "running": self._running(),
                "doing": self._doing if self._running() else None,
                "stopping": self._running() and os.path.exists(self._path("STOP")),
                "busy": self.busy(), "essays": essays, "report": report}

    def essay(self, n):
        C = self._harness()
        if n not in self._essay_numbers():
            raise ConsoleError("none", "no essay %03d" % n, 404)
        theme, body = C.read_essay(self.dir, n)
        out = {"n": n, "theme": theme, "essay": body, "state": self._state(n),
               "corrected": C.read_corrected(self.dir, n), "review": None, "reflection": None}
        rv = self._path("reviews", "%03d.txt" % n)
        if os.path.exists(rv):
            with open(rv, encoding="utf-8") as f:
                out["review"] = f.read().strip()
        for name, key in (("%03d.reflection.json", "reflection"),
                          ("%03d.reflection.removed.json", "removed")):
            p = self._path("reviews", name % n)
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    rec = json.load(f)
                out[key] = {"text": rec.get("reflection"), "at": rec.get("at"),
                            "episode": ((rec.get("stored") or {}).get("body") or {}).get("stored"),
                            "removed": rec.get("removed")}
        return out

    # ---- writing -----------------------------------------------------------
    def review(self, n, text):
        text = " ".join(str(text or "").split())
        if not text:
            raise ConsoleError("empty", "write the review first")
        if len(text) > REVIEW_MAX:
            raise ConsoleError("length", "at most %d characters" % REVIEW_MAX)
        if n not in self._essay_numbers():
            raise ConsoleError("none", "no essay %03d" % n, 404)
        if self._state(n) == "reflected":
            raise ConsoleError("reflected", "her reflection on this review is in memory: "
                               "remove it before the review is changed", 409)
        os.makedirs(self._path("reviews"), exist_ok=True)
        with open(self._path("reviews", "%03d.txt" % n), "w", encoding="utf-8") as f:
            f.write(text + "\n")
        return {"saved": n, "chars": len(text)}

    def correct(self, n, text):
        text = str(text or "").strip()
        if n not in self._essay_numbers():
            raise ConsoleError("none", "no essay %03d" % n, 404)
        if len(text) > CORRECTED_MAX:
            raise ConsoleError("length", "at most %d characters" % CORRECTED_MAX)
        p = self._path("essays", "%03d.corrected.md" % n)
        if not text:
            if os.path.exists(p):
                os.remove(p)
            return {"corrected": None}
        C = self._harness()
        _theme, hers = C.read_essay(self.dir, n)
        if text == hers:
            raise ConsoleError("same", "that is her essay unchanged")
        C.write_corrected(self.dir, n, text)
        return {"corrected": n}

    def reflect(self, n):
        if n not in self._essay_numbers():
            raise ConsoleError("none", "no essay %03d" % n, 404)
        state = self._state(n)
        if state == "reflected":
            raise ConsoleError("reflected", "a reflection on this essay is already in memory", 409)
        if state not in ("reviewed",):
            raise ConsoleError("no_review", "write and save the review first", 409)
        return self._spawn(["--reflect", self.dir, str(n), "--model", self.model],
                           "reflection on essay %03d" % n)

    def forget(self, n, why):
        why = " ".join(str(why or "").split())[:WHY_MAX]
        if not why:
            raise ConsoleError("why", "say why, for the log")
        if self._state(n) != "reflected":
            raise ConsoleError("none", "essay %03d has no reflection in memory" % n, 404)
        C = self._harness()
        try:
            ep = C.forget(self.dir, n, why, token=self.token, post=self.remove)
        except RuntimeError as e:
            raise ConsoleError("refused", str(e), 409)
        return {"removed": ep}
