#!/usr/bin/env python3
"""The Companion's GUI server.

Serves the console on 127.0.0.1:2077 and reverse-proxies the node's API to the
proxy on 8001, so the browser only ever speaks to ONE origin. That is not
decoration: a page on :2077 calling :8001 is cross-origin, which would mean
either CORS headers on the guard layer or a browser that has to be told to
relax. Neither belongs on a device whose claim is that nothing leaves it.

It talks to 8001, never to hailo-ollama on 8000. Every guard - the token
budget, the sanitizers, all four generation bounds, provenance - lives at the
proxy's exit point, and a UI that went straight to the model would have none
of them.

Static files only, read-only, no directory listing, no uploads. One write:
the shutdown request (see SHUTDOWN_REQUEST), an empty file that a root-owned
systemd path unit turns into an orderly poweroff. This server never gains the
privilege to shut anything down itself.
"""
import base64
import hashlib
import http.server
import json
import os
import re
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.request

BIND = os.environ.get("AETHERSEED_GUI_BIND", "127.0.0.1")
PORT = int(os.environ.get("AETHERSEED_GUI_PORT", "2077"))
BACKEND = os.environ.get("AETHERSEED_BACKEND", "http://127.0.0.1:8001")
ROOT = os.path.dirname(os.path.abspath(__file__))

# Only these reach the backend. An allow-list rather than a prefix match, so a
# future route on the proxy is not exposed to the browser by accident.
PROXIED_POST = ("/api/chat", "/aetherseed/setup")

# SHUTDOWN. So the device can be moved without pulling the plug on a running
# SQLite store. The console cannot power anything off - it runs unprivileged
# with NoNewPrivileges, and should stay that way. It only leaves a request in
# its own runtime directory; services/aetherseed-shutdown.path watches for it
# and starts a root oneshot that removes it and calls poweroff. /run is tmpfs,
# so a request can never survive into the next boot and shut it down again.
# Only this server can write there: the proxy (the model's side) runs with
# ProtectSystem=strict and no writable path under /run.
SHUTDOWN_PATH = "/aetherseed/shutdown"
SHUTDOWN_REQUEST = os.environ.get("AETHERSEED_SHUTDOWN_REQUEST",
                                  "/run/aetherseed-gui/shutdown-request")
SHUTDOWN_CONFIRM = "shut down"
PROXIED_GET = ("/aetherseed/status", "/aetherseed/record", "/api/tags")

# The page's own script is pinned by the hash of its bytes.
#
# The first version of this header said default-src 'self' and never said
# script-src at all, so default-src applied to scripts - and an inline
# <script> is not 'self'. Chromium refused the page's entire script on every
# load for as long as the console existed. HTML and CSS rendered, so it LOOKED
# like a working console; every endpoint had been tested with curl, which runs
# no JavaScript, and the page itself had never been opened in a browser.
#
# 'unsafe-inline' would fix it and say "any inline script may run here". A
# hash says "this one may". Anything else - a script injected into the DOM at
# runtime included - is refused. That is the same principle as pinning the
# model by the hash of its blob, applied to the one piece of code on this
# device that renders model output.
#
# The hash is taken from the file being served, so it is not protection
# against someone editing that file; the cartridge manifest is. It is computed
# once at startup, so if index.html changed underneath a running server the
# page would stop working rather than run something unpinned - it fails
# closed, which is the direction it should fail in.
def inline_hashes(html):
    """{'script': ["'sha256-...'", ...], 'style': [...]} for every inline block."""
    out = {}
    for tag in ("script", "style"):
        out[tag] = ["'sha256-%s'" % base64.b64encode(
            hashlib.sha256(m.group(1).encode("utf-8")).digest()).decode()
            for m in re.finditer(r"<%s>(.*?)</%s>" % (tag, tag), html, re.S)]
    return out


def build_csp(html):
    h = inline_hashes(html)
    return ("default-src 'self'; "
            "script-src 'self' %s; "
            "style-src 'self' %s; "
            "img-src 'self' data:; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
            % (" ".join(h["script"]), " ".join(h["style"])))


CSP = None      # set in __main__, once index.html is known to exist


# How the console says it is alive when nobody is standing in front of it.
#
# A kiosk has no other way to report itself: the screen is the output, and
# if you cannot see the screen you cannot see the output. The page polls
# /aetherseed/status on a timer, so counting those polls answers the only
# question that matters remotely - is the browser still running the page, or
# is it showing a frozen picture of one.
#
# Counts, and nothing else. Not paths, not bodies, not prompts. A per-request
# log on this device would put everything anyone typed into the journal, and
# the journal is not covered by any promise this node makes.
HEARTBEAT_SECONDS = int(os.environ.get("AETHERSEED_GUI_HEARTBEAT", "300"))

_counts = {"page": 0, "status": 0, "record": 0, "chat": 0, "setup": 0, "refused": 0}
_counts_lock = threading.Lock()


def _tally(kind):
    with _counts_lock:
        _counts[kind] = _counts.get(kind, 0) + 1


def _heartbeat():
    """One line per interval, always - including when idle.

    Silence has to mean "the server is gone", never "the server is quiet",
    or the heartbeat cannot be used to tell those two apart.
    """
    while True:
        time.sleep(HEARTBEAT_SECONDS)
        with _counts_lock:
            seen = dict(_counts)
            for k in _counts:
                _counts[k] = 0
        if sum(seen.values()):
            print("[gui] %ds  page=%d status=%d record=%d chat=%d setup=%d refused=%d"
                  % (HEARTBEAT_SECONDS, seen["page"], seen["status"], seen["record"],
                     seen["chat"], seen["setup"], seen["refused"]), flush=True)
        else:
            print("[gui] %ds  idle" % HEARTBEAT_SECONDS, flush=True)


class Console(http.server.SimpleHTTPRequestHandler):

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass

    def end_headers(self):
        # The page loads nothing from anywhere, and runs only its own script.
        # Saying so in a header means a mistake fails loudly instead of
        # silently reaching out - see build_csp().
        self.send_header("Content-Security-Policy", CSP)
        # Nothing this server sends is kept. Measured 2026-09-21: Chromium had
        # written the page and the status JSON to its disk cache, the page with
        # Last-Modified and no Cache-Control - which makes it heuristically
        # fresh, so after a new cartridge the kiosk could show the OLD console
        # without asking. And /aetherseed/record carries excerpts of flagged
        # prompts: cached, that is a second, unmanaged copy of what people
        # typed, on the SD card, outside everything the node accounts for.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def _relay(self, method, body=None):
        req = urllib.request.Request(
            BACKEND + self.path, data=body, method=method,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as up:
                self.send_response(up.status)
                ctype = up.headers.get("Content-Type", "application/json")
                self.send_header("Content-Type", ctype)
                self.end_headers()
                # Streamed straight through, unbuffered: the proxy already
                # decides what may be forwarded and when (step 17), and a
                # second layer of buffering here would undo the work that
                # makes the first token arrive when it does.
                while True:
                    chunk = up.read(1)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(
                {"error": "the node is not answering", "detail": repr(e)[:160]}
            ).encode())

    def do_GET(self):
        if self.path in PROXIED_GET:
            _tally("status" if self.path.endswith("/status")
                   else "record" if self.path.endswith("/record") else "page")
            self._relay("GET")
            return
        if self.path == "/":
            self.path = "/index.html"
        if self.path not in ("/index.html",):
            _tally("refused")
            self.send_error(404)
            return
        _tally("page")
        super().do_GET()

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _shutdown(self):
        # From the device itself only. The server binds to 127.0.0.1 already;
        # this holds even if someone rebinds it.
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            _tally("refused")
            self._json(403, {"error": "shutdown is only possible on the device"})
            return
        # JSON with an explicit confirmation: a stray form post or a link cannot
        # send a JSON content type cross-origin without a preflight.
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            self._json(415, {"error": "expected application/json"})
            return
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            data = json.loads(self.rfile.read(n) if n else b"{}")
        except Exception:
            data = {}
        if not isinstance(data, dict) or data.get("confirm") != SHUTDOWN_CONFIRM:
            self._json(400, {"error": "not confirmed"})
            return
        try:
            with open(SHUTDOWN_REQUEST, "w") as f:
                f.write(time.strftime("%Y-%m-%dT%H:%M:%S%z") + "\n")
        except OSError as e:
            print(f"[gui] shutdown requested but could not be filed: {e!r}", flush=True)
            self._json(503, {"error": "shutdown is not available on this unit"})
            return
        print("[gui] shutdown requested from the console", flush=True)
        self._json(202, {"shutting_down": True})

    def do_POST(self):
        if self.path == SHUTDOWN_PATH:
            self._shutdown()
            return
        if self.path not in PROXIED_POST:
            _tally("refused")
            self.send_error(404)
            return
        _tally("setup" if self.path == "/aetherseed/setup" else "chat")
        n = int(self.headers.get("Content-Length", 0))
        self._relay("POST", self.rfile.read(n) if n else b"")


class Threaded(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    print(f"[gui] console on http://{BIND}:{PORT}  ->  {BACKEND}", flush=True)
    if not os.path.exists(os.path.join(ROOT, "index.html")):
        print("[gui] FATAL: index.html is missing next to serve.py", flush=True)
        sys.exit(1)
    with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as f:
        CSP = build_csp(f.read())
    print("[gui] script pinned: %s" % " ".join(inline_hashes(
        open(os.path.join(ROOT, "index.html"), encoding="utf-8").read())["script"]),
        flush=True)
    threading.Thread(target=_heartbeat, daemon=True).start()
    Threaded((BIND, PORT), Console).serve_forever()
