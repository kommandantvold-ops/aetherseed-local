#!/usr/bin/env python3
"""The Companion's GUI server.

Serves the console on port 2077 and reverse-proxies the node's API to the
proxy on 8001, so the browser only ever speaks to ONE origin. That is not
decoration: a page on :2077 calling :8001 is cross-origin, which would mean
either CORS headers on the guard layer or a browser that has to be told to
relax. Neither belongs on a device whose claim is that nothing leaves it.

It talks to 8001, never to hailo-ollama on 8000. Every guard - the token
budget, the sanitizers, all four generation bounds, provenance - lives at the
proxy's exit point, and a UI that went straight to the model would have none
of them.

Static files only, read-only, no directory listing. One write: the shutdown
request (see SHUTDOWN_REQUEST), an empty file that a root-owned systemd path
unit turns into an orderly poweroff. This server never gains the privilege to
shut anything down itself.

A document for the steward's own shelf (build log 62) passes THROUGH this
server and is never written by it: the upload is relayed to the proxy, which
keeps it under its own state directory (logic/own_shelf.py).

Who is the steward here (build log 80): the unit's own screen, and a phone
that has signed in with the steward's name and the passkey (gui/signin.py).
Any other phone is a guest: it may talk with her, and its turns are stored as
a guest's; everything else this server relays or does is the steward's.
"""
import base64
import hashlib
import hmac
import http.server
import json
import math
import os
import re
import secrets
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import signin  # noqa: E402  (gui/signin.py, beside this file)

BIND = os.environ.get("AETHERSEED_GUI_BIND", "127.0.0.1")
PORT = int(os.environ.get("AETHERSEED_GUI_PORT", "2077"))
BACKEND = os.environ.get("AETHERSEED_BACKEND", "http://127.0.0.1:8001")
ROOT = os.path.dirname(os.path.abspath(__file__))

# Only these reach the backend. An allow-list rather than a prefix match, so a
# future route on the proxy is not exposed to the browser by accident.
# /aetherseed/steward: guided correction (build log 50) - the steward supports
# or corrects a turn or a ring. The console's only way to change what the
# companion remembers; the proxy checks and records every one.
PROXIED_POST = ("/api/chat", "/aetherseed/setup", "/aetherseed/steward",
                "/aetherseed/shelf/remove",
                # build log 64: the training loop's buttons, and who her steward is
                "/aetherseed/training", "/aetherseed/steward-name",
                # build log 72: the steward's brake; trust management
                "/aetherseed/brake", "/aetherseed/trust", "/aetherseed/approvals",
                # build log 74c/74d: the COG panel. Not /aetherseed/cog/reflection
                # or /aetherseed/cog/remove: those are the harness's, by token.
                "/aetherseed/cog/start", "/aetherseed/cog/stop", "/aetherseed/cog/review",
                "/aetherseed/cog/correct", "/aetherseed/cog/reflect", "/aetherseed/cog/forget")

# THE STEWARD'S OWN SHELF (build log 62). Andreas, 5 Oct 2026: "a file upload
# button in the gui, that adds documents to the library/workspace". The body
# of the request is the file itself; its name is in X-Filename. Three checks
# here, before a byte is read: the size, the content type, and that the name
# header is there - a page on another origin cannot send a custom header
# without a preflight, and this server answers none. What the file is, the
# proxy decides (logic/own_shelf.accept).
UPLOAD_PATH = "/aetherseed/upload"
UPLOAD_MAX = int(os.environ.get("AETHERSEED_UPLOAD_MAX", str(60 * 1024 * 1024)))
UPLOAD_TYPE = "application/octet-stream"

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

# FIRST START (build log 66). A unit that is onboarded where it will live is
# named there, and there it is also given the time and a passkey for its own
# Wi-Fi - by whoever sits at ITS OWN SCREEN, once. Both need root, so this
# server does with them what it does with a shutdown: it leaves a request in
# its runtime directory, and services/aetherseed-first-start.path starts a
# root oneshot (tools/first_start.sh) that does the two things and says how
# it went. Three locks, each checked here and again by the root side:
#   - the unit is ARMED: /etc/aetherseed/first-start exists (a card made a
#     source by tools/source_card.sh has it; the first start removes it). A
#     unit set up at a shell never has it, and this path then does nothing;
#   - the request comes from loopback - the unit's own screen. A phone can
#     only be on the unit's Wi-Fi once there is a passkey, so it cannot be
#     what sets one; and the console is not served on a cable network at all;
#   - what is asked is a date and time and a passkey, in their own shapes.
# The passkey is written to the request (tmpfs, mode 600), read by root and
# removed; it is never logged here and never sent back.
FIRST_START_PATH = "/aetherseed/first-start"
FIRST_START_FLAG = os.environ.get("AETHERSEED_FIRST_START_FLAG", "/etc/aetherseed/first-start")
FIRST_START_REQUEST = os.environ.get("AETHERSEED_FIRST_START_REQUEST",
                                     "/run/aetherseed-gui/first-start-request")
FIRST_START_RESULT = os.environ.get("AETHERSEED_FIRST_START_RESULT",
                                    "/run/aetherseed-gui/first-start-result")
FIRST_START_WAIT = float(os.environ.get("AETHERSEED_FIRST_START_WAIT", "75"))
_WHEN = re.compile(r"^(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])[T ]([01]\d|2[0-3]):([0-5]\d)$")
_FIRST_START_LOCK = threading.Lock()


def first_start_armed():
    return os.path.exists(FIRST_START_FLAG)


def check_when(when):
    """'YYYY-MM-DD HH:MM' if `when` is a date and time that exists, else None."""
    m = _WHEN.match(when if isinstance(when, str) else "")
    if not m:
        return None
    try:
        time.strptime("%s-%s-%s %s:%s" % m.groups(), "%Y-%m-%d %H:%M")
    except ValueError:
        return None                         # the 31st of February
    return "%s-%s-%s %s:%s" % m.groups()


def check_passkey(key):
    """A WPA2 passkey: 8-63 printable ASCII characters (tools/hotspot.sh)."""
    return signin.passkey_shape_ok(key)


# ---- THE STEWARD, AND A GUEST (build log 80) ------------------------------------
# Andreas, 18 Oct 2026: the steward signs in from a phone with "steward name +
# passkey", the passkey being "The Wi-Fi passkey"; a chat from a phone that
# has not signed in is remembered as "A guest". How, and what it does not
# protect against: gui/signin.py.
#
# What a guest may use: the page, the unit's status (names and counts, no
# words of anyone's), the model list, a chat turn and signing in. Everything
# else this server relays or does is the steward's - her memory and records,
# corrections, trust, approvals, training, the COG panel, documents, the
# brake and quantum rest. Andreas, 11 Oct 2026, on the brake: "an authorized
# person should always be able to pause or shut down a model mid-task".
STEWARD_KEY = os.environ.get("AETHERSEED_STEWARD_KEY", "/etc/aetherseed/steward.key")
SIGNIN_PATH = "/aetherseed/steward-signin"
SIGNOUT_PATH = "/aetherseed/steward-signout"
WHOAMI_PATH = "/aetherseed/whoami"
OWN_SCREEN = frozenset({"127.0.0.1", "::1"})     # the unit's own screen: loopback
OPEN_GET = frozenset({"/aetherseed/status", "/api/tags", FIRST_START_PATH, WHOAMI_PATH})
# A guest's turn is stored under this name (logic/speaker.py GUEST).
GUEST = "Guest"
GUEST_CHAT_MAX = 64 * 1024
SESSIONS = signin.Sessions()
LOCKOUT = signin.Lockout()
# A guest's conversation is told apart from another guest's by the address it
# comes from, hashed with a secret of this process - so the working memory of
# one phone is not shown to another (build log 78 keeps it per speaker, and
# every guest is "Guest"). The id means nothing after a restart.
_GUEST_SALT = secrets.token_bytes(16)


# THE CONSOLE WAS SEEN. The page asks for /aetherseed/status every 15 seconds
# for as long as it is loaded, so "the browser is showing the console" has a
# cheap witness: this file's modification time, touched on every status poll.
# services/aetherseed-kiosk-watch.service reads it and restarts the screen when
# the browser has been up for a while and the page is not asking (build log
# 53): on 3 Oct 2026 a pilot unit showed a blank white page twice - the page
# load was cut off as the network came up under it, and a kiosk browser does
# not try again. tmpfs, in this server's own runtime directory, beside the
# shutdown request; it holds nothing but its timestamp.
CONSOLE_SEEN = os.environ.get("AETHERSEED_CONSOLE_SEEN",
                              "/run/aetherseed-gui/console-seen")


def _console_seen():
    try:
        with open(CONSOLE_SEEN, "a"):
            os.utime(CONSOLE_SEEN, None)
    except OSError:
        pass                        # a witness that cannot be written is not worth a crash


# /aetherseed/rings: the ring tree (step 37) - read-only, like the record.
# /aetherseed/memories: the turns, for guided correction (50); it takes a query
# string (?before=&q=&limit=), so it is matched on its path alone.
# /aetherseed/shelf: the steward's own documents and how far each is read (62).
PROXIED_GET = ("/aetherseed/status", "/aetherseed/record", "/aetherseed/rings", "/api/tags",
               "/aetherseed/shelf", "/aetherseed/training", "/aetherseed/trust-record",
               "/aetherseed/brake", "/aetherseed/trust",
               # build log 72: her records checked; her workspace, read-only
               "/aetherseed/records", "/aetherseed/workspace", "/aetherseed/approvals",
               # build log 74d: the COG panel - its state, and one essay (?n=)
               "/aetherseed/cog")
PROXIED_GET_QUERY = ("/aetherseed/memories", "/aetherseed/cog/essay")

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

_counts = {"page": 0, "status": 0, "record": 0, "rings": 0, "chat": 0, "setup": 0,
           "refused": 0, "upload": 0, "shelf": 0, "training": 0, "signin": 0}
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
            print("[gui] %ds  page=%d status=%d record=%d rings=%d chat=%d setup=%d "
                  "refused=%d upload=%d shelf=%d training=%d signin=%d"
                  % (HEARTBEAT_SECONDS, seen["page"], seen["status"],
                     seen["record"], seen["rings"], seen["chat"],
                     seen["setup"], seen["refused"], seen.get("upload", 0),
                     seen.get("shelf", 0), seen.get("training", 0),
                     seen.get("signin", 0)), flush=True)
        else:
            print("[gui] %ds  idle" % HEARTBEAT_SECONDS, flush=True)


# ---- ONLY REQUESTS ADDRESSED TO THE UNIT (build log 78) ----------------------
# A phone on the unit's own Wi-Fi often keeps its mobile data, and a web page it
# opens over that data can still send requests to http://10.42.0.1:2077. Two
# ways in, both found in this year's personal agents (OpenClaw CVE-2026-25253,
# Hermes Agent CVE-2026-53869, read 17 Oct 2026):
#   - a CROSS-SITE request: the page posts to the console - a chat turn, an
#     approval, an upload - and the console cannot tell it from its own page.
#     The browser says where it came from in the Origin header;
#   - DNS REBINDING: a name the page controls is made to point at the unit, so
#     the browser counts the console as the page's own site and lets it read
#     the answers too. The Host header then carries that name, not the unit's.
# So: the Host must name the unit - localhost, its loopback address, or the
# address the request came in on - and a request that changes something and
# says where it came from must come from the console's own page. A request
# that says nothing (curl, the unit's own tools) is judged by its Host alone.
_LOCAL_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
EXTRA_HOSTS = frozenset(h.strip().lower() for h in
                        os.environ.get("AETHERSEED_CONSOLE_HOSTS", "").split(",") if h.strip())


def _host_name(value: str) -> str:
    """The name in a Host header, lower-case, without its port."""
    v = (value or "").strip().lower()
    if v.startswith("["):                      # [::1]:2077
        return v[1:v.index("]")] if "]" in v else v
    return v.rsplit(":", 1)[0] if v.count(":") == 1 else v


def addressed_here(host, origin, method, here, own_screen) -> bool:
    """(build log 78) Is this request addressed to the unit itself and, if it
    changes something and a browser says where it comes from, from its page?"""
    if host is None:
        return own_screen                       # no Host at all: the unit's own only
    name = _host_name(host)
    if name not in _LOCAL_NAMES | EXTRA_HOSTS | {(here or "").lower()}:
        return False
    if method in ("GET", "HEAD") or origin is None:
        return True
    if origin.strip().lower() in ("null", ""):
        return False
    return origin.strip().lower() == "http://" + host.strip().lower()


class Console(http.server.SimpleHTTPRequestHandler):

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass

    def _refused_if_not_from_here(self) -> bool:
        """True (and answered 403) when the request is not addressed to the unit."""
        try:
            here = self.connection.getsockname()[0]
        except (OSError, AttributeError, IndexError):
            here = ""
        if addressed_here(self.headers.get("Host"), self.headers.get("Origin"),
                          self.command, here, self._own_screen()):
            return False
        _tally("refused")
        print("[gui] refused a %s %s: Host %r, Origin %r - not addressed to this unit"
              % (self.command, self.path.split("?", 1)[0], self.headers.get("Host"),
                 self.headers.get("Origin")), flush=True)
        self._json(403, {"error": "This console answers only its own page on this unit.",
                         "code": "not_from_here"})
        return True

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

    def _relay(self, method, body=None, headers=None):
        req = urllib.request.Request(
            BACKEND + self.path, data=body, method=method,
            headers=headers or {"Content-Type": "application/json"})
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

    # ---- who is asking (build log 80) ----------------------------------------
    def _is_steward(self) -> bool:
        """The unit's own screen, or a phone signed in from this address."""
        if self._own_screen():
            return True
        return SESSIONS.valid(signin.token_from_cookie(self.headers.get("Cookie")),
                              self.client_address[0])

    def _steward_only(self) -> bool:
        """True (and answered 401) when this is not the steward."""
        if self._is_steward():
            return False
        _tally("refused")
        self._json(401, {"error": "Sign in as the steward to use this.", "code": "sign_in"})
        return True

    def _whoami(self):
        # "key" says which passkey a phone signs in with - the Wi-Fi's, or one
        # of the steward's own (tools/steward_key.py) - so the page can name it
        own = self._own_screen()
        rec = None if own else signin.load_record(STEWARD_KEY)
        self._json(200, {"steward": self._is_steward(), "own_screen": own,
                         "sign_in": rec is not None, "key": rec["source"] if rec else None})

    def _steward_name(self):
        """(the steward's name or None, whether the proxy answered at all)."""
        try:
            with urllib.request.urlopen(BACKEND + "/aetherseed/status", timeout=10) as up:
                d = json.loads(up.read(262144))
        except Exception:
            return None, False
        c = d.get("companion") if isinstance(d, dict) else None
        name = c.get("steward") if isinstance(c, dict) else None
        return (name if isinstance(name, str) and name.strip() else None), True

    def _sign_in(self):
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            self._json(415, {"error": "expected application/json"})
            return
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n < 0 or n > 4096:
            self.close_connection = True
            self._json(400, {"error": "not a sign-in", "code": "bad_request"})
            return
        try:
            data = json.loads(self.rfile.read(n) if n else b"{}")
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if self._own_screen():
            self._json(200, {"steward": True, "own_screen": True})   # nothing to sign in to
            return
        addr = self.client_address[0]
        wait = LOCKOUT.wait(addr)
        if wait > 0:
            self._json(429, {"error": "Too many tries. Wait, then try again.", "code": "locked",
                             "wait_s": int(math.ceil(wait))})
            return
        rec = signin.load_record(STEWARD_KEY)
        if rec is None:
            self._json(503, {"error": "Signing in as the steward is not set up on this unit.",
                             "code": "no_key"})
            return
        steward_name, answered = self._steward_name()
        if not answered:
            self._json(502, {"error": "the node is not answering", "code": "network"})
            return
        if not steward_name:
            self._json(409, {"error": "This unit has no steward's name yet.", "code": "no_steward_name"})
            return
        # Both are checked every time, whichever is wrong, and the answer does
        # not say which. The passkey is not kept, logged or sent back.
        key_ok = signin.passkey_matches(rec, data.get("passkey"))
        name_ok = signin.names_match(data.get("name"), steward_name)
        del data
        if not (key_ok and name_ok):
            LOCKOUT.failed(addr)
            print("[gui] a steward sign-in from %s did not match" % addr, flush=True)
            self._json(401, {"error": "That name and passkey do not match.", "code": "wrong"})
            return
        LOCKOUT.succeeded(addr)
        token = SESSIONS.open(addr)
        print("[gui] the steward signed in from %s" % addr, flush=True)
        self._json(200, {"steward": True, "own_screen": False},
                   headers={"Set-Cookie": signin.set_cookie(token)})

    def _sign_out(self):
        token = signin.token_from_cookie(self.headers.get("Cookie"))
        if token and SESSIONS.valid(token, self.client_address[0]):
            print("[gui] the steward signed out from %s" % self.client_address[0], flush=True)
        if token:
            SESSIONS.close(token)
        own = self._own_screen()
        self._json(200, {"steward": own, "own_screen": own},
                   headers={"Set-Cookie": signin.clear_cookie()})

    def _guest_conversation(self) -> str:
        return hmac.new(_GUEST_SALT, self.client_address[0].encode("utf-8"),
                        hashlib.sha256).hexdigest()[:16]

    def _guest_chat(self):
        """A guest's turn: the console's shape and nothing else - one message,
        stored as a guest's (build log 80). Whatever else a request carries -
        a name of its own choosing, a history, a system message, a flag - is
        not passed on: a guest cannot speak as anyone, or put words in her
        mouth."""
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n <= 0 or n > GUEST_CHAT_MAX:
            self.close_connection = True
            self._json(413 if n > GUEST_CHAT_MAX else 400,
                       {"error": "not a chat turn from the console", "code": "bad_chat"})
            return
        try:
            data = json.loads(self.rfile.read(n))
        except Exception:
            data = None
        msgs = data.get("messages") if isinstance(data, dict) else None
        last = msgs[-1] if isinstance(msgs, list) and msgs else None
        text = last.get("content") if isinstance(last, dict) and last.get("role") == "user" else None
        if not isinstance(text, str) or not text.strip():
            self._json(400, {"error": "a chat turn is one message from you", "code": "bad_chat"})
            return
        body = {"stream": data.get("stream") is not False,
                "messages": [{"role": "user", "content": text}],
                "speaker": GUEST, "conversation": self._guest_conversation()}
        if isinstance(data.get("model"), str) and len(data["model"]) <= 64:
            body["model"] = data["model"]
        self._relay("POST", json.dumps(body).encode("utf-8"))

    def do_GET(self):
        if self._refused_if_not_from_here():
            return
        if self.path == WHOAMI_PATH:
            _tally("status")
            self._whoami()
            return
        if self.path.split("?", 1)[0] in PROXIED_GET_QUERY:
            if self._steward_only():
                return
            _tally("memories" if self.path.startswith("/aetherseed/memories") else "cog")
            self._relay("GET")
            return
        if self.path in PROXIED_GET:
            if self.path not in OPEN_GET and self._steward_only():
                return
            # Only the unit's own screen is the witness: a phone on the
            # unit's Wi-Fi polls too (build log 54), and its polls must not
            # hide a blank page on the screen from the kiosk watch.
            if self.path == "/aetherseed/status" and self._own_screen():
                _console_seen()
            _tally("status" if self.path.endswith("/status")
                   else "record" if self.path.endswith("/record")
                   else "rings" if self.path.endswith("/rings")
                   else "shelf" if self.path.endswith("/shelf")
                   else "training" if self.path.endswith("/training")
                   else "record" if self.path.endswith("/trust-record")
                   else "cog" if self.path == "/aetherseed/cog" else "page")
            self._relay("GET")
            return
        if self.path == FIRST_START_PATH:
            _tally("status")
            self._first_start_state()
            return
        if self.path == "/":
            self.path = "/index.html"
        if self.path not in ("/index.html",):
            _tally("refused")
            self.send_error(404)
            return
        _tally("page")
        super().do_GET()

    def _json(self, code, obj, headers=None):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _shutdown(self):
        # From the steward's screens (build log 63). Andreas, 5 Oct 2026: "I
        # need a way to initiate quantum rest from the phone or laptop". Step
        # 54 had it at the unit only. Until build log 80 any phone on the
        # unit's own Wi-Fi could ask for it; now a phone must be signed in as
        # the steward (do_POST checks before this is reached). Nothing else
        # reaches this server: the firewall admits the console port on
        # loopback and on the unit's own Wi-Fi, not on a cable network
        # (services/nftables.conf).
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
        print("[gui] shutdown requested from %s" % ("the unit's own screen" if self._own_screen()
              else "the steward's phone on the unit's Wi-Fi"), flush=True)
        self._json(202, {"shutting_down": True})

    def _own_screen(self):
        return self.client_address[0] in OWN_SCREEN

    def _first_start_state(self):
        # What the page needs to decide whether to show the first-start step:
        # is this unit armed for it, is this screen the unit's own, and what
        # the unit's clock says now (to start the date and time fields from).
        self._json(200, {"armed": first_start_armed(), "own_screen": self._own_screen(),
                         "now": time.strftime("%Y-%m-%dT%H:%M")})

    def _first_start(self):
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            self._json(415, {"error": "expected application/json"})
            return
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n > 4096:
            self.close_connection = True
            self._json(400, {"error": "not a first start", "code": "bad_request"})
            return
        try:
            data = json.loads(self.rfile.read(n) if n else b"{}")
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if not self._own_screen():
            self._json(403, {"error": "A unit is started for the first time at its own screen.",
                             "code": "not_own_screen"})
            return
        if not first_start_armed():
            self._json(409, {"error": "This unit has been started before.", "code": "not_armed"})
            return
        when = check_when(data.get("when"))
        if not when:
            self._json(400, {"error": "That is not a date and time I can set.", "code": "bad_when"})
            return
        key = data.get("passkey")
        if not check_passkey(key):
            self._json(400, {"error": "The passkey must be 8 to 63 plain characters.",
                             "code": "bad_passkey"})
            return
        if not _FIRST_START_LOCK.acquire(blocking=False):
            self._json(409, {"error": "A first start is already under way.", "code": "busy"})
            return
        try:
            try:
                os.unlink(FIRST_START_RESULT)
            except OSError:
                pass
            try:
                fd = os.open(FIRST_START_REQUEST, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(when + "\n" + key + "\n")
            except OSError as e:
                print(f"[gui] first start asked for but could not be filed: {e!r}", flush=True)
                self._json(503, {"error": "The first start is not available on this unit.",
                                 "code": "unavailable"})
                return
            del key
            print("[gui] first start asked for at the unit's own screen", flush=True)
            deadline = time.monotonic() + FIRST_START_WAIT
            lines = None
            while time.monotonic() < deadline:
                try:
                    with open(FIRST_START_RESULT, encoding="utf-8") as f:
                        lines = f.read().split("\n")
                    break
                except OSError:
                    time.sleep(0.25)
            if lines is None:
                # Nobody took it: do not leave a passkey lying in /run.
                try:
                    os.unlink(FIRST_START_REQUEST)
                except OSError:
                    pass
                self._json(504, {"error": "The unit did not answer. Try again.", "code": "timeout"})
                return
            if lines[0] == "ok":
                print("[gui] first start done", flush=True)
                self._json(200, {"ok": True, "network": lines[1] if len(lines) > 1 else ""})
            else:
                # root's side: "error", a word the page has a sentence for in
                # each language, and root's own sentence
                code = lines[1] if len(lines) > 1 and re.fullmatch(r"[a-z_]{1,24}", lines[1]) else "refused"
                said = lines[2] if len(lines) > 2 and lines[2] else "It could not be done."
                print(f"[gui] first start refused: {said}", flush=True)
                self._json(422, {"error": said, "code": code})
        finally:
            _FIRST_START_LOCK.release()

    def _upload(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        name = self.headers.get("X-Filename") or ""
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if n > UPLOAD_MAX:
            # Refused unread: the rest of the request is not taken in.
            self.close_connection = True
            _tally("refused")
            self._json(413, {"error": "That file is too large: %d MB is the most I take."
                             % (UPLOAD_MAX // (1024 * 1024)), "code": "too_large"})
            return
        if n <= 0 or ctype != UPLOAD_TYPE or not name or len(name) > 800 \
                or not re.fullmatch(r"[A-Za-z0-9._~%!'()*-]+", name):
            self.close_connection = True
            _tally("refused")
            self._json(400, {"error": "not an upload from the console", "code": "bad_upload"})
            return
        _tally("upload")
        self._relay("POST", self.rfile.read(n),
                    headers={"Content-Type": UPLOAD_TYPE, "X-Filename": name})

    def do_POST(self):
        if self._refused_if_not_from_here():
            return
        if self.path == SIGNIN_PATH:
            _tally("signin")
            self._sign_in()
            return
        if self.path == SIGNOUT_PATH:
            _tally("signin")
            self._sign_out()
            return
        if self.path == SHUTDOWN_PATH:
            if self._steward_only():
                return
            self._shutdown()
            return
        if self.path == FIRST_START_PATH:
            # the unit's own screen only - checked in _first_start - and the
            # unit's own screen is the steward
            _tally("setup")
            self._first_start()
            return
        if self.path == UPLOAD_PATH:
            if self._steward_only():
                return
            self._upload()
            return
        if self.path not in PROXIED_POST:
            _tally("refused")
            self.send_error(404)
            return
        if self.path == "/api/chat" and not self._is_steward():
            _tally("chat")
            self._guest_chat()
            return
        if self.path != "/api/chat" and self._steward_only():
            return
        _tally("setup" if self.path == "/aetherseed/setup"
               else "steward" if self.path in ("/aetherseed/steward", "/aetherseed/steward-name")
               else "training" if self.path == "/aetherseed/training"
               else "shelf" if self.path.startswith("/aetherseed/shelf")
               else "cog" if self.path.startswith("/aetherseed/cog/") else "chat")
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
