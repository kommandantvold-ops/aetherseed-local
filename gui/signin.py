"""Signing in as the steward from a phone.

how the steward should sign in from a phone:
"steward name + passkey" - the passkey "The Wi-Fi passkey" - and a chat from a
phone that has not signed in is remembered as "A guest".

Until now whoever reached the console WAS the steward: the unit's own screen,
or a phone on the unit's own Wi-Fi. A guest given the Wi-Fi to talk with her was stored as
the steward, and could open her memory, correct it, grant trust, approve
tools, pull the brake and put her into quantum rest. Now:

  - the unit's own screen is the steward, as before - nothing to sign in to;
  - a phone is a guest until it signs in with the steward's name and the
    passkey. A guest can talk with her - stored as "Guest" - and nothing
    else: no panel, no change, no brake, no quantum rest;
  - a phone that signed in is the steward for SESSION_S, on that address.

What is kept on the unit: a PBKDF2-SHA256 hash of the passkey with a salt of
its own, in /etc/aetherseed/steward.key (root, readable by the unit's own
services), written by tools/steward_key.py. Never the passkey. WPA2 keeps a
cheaper hash of the same passkey in every handshake it makes (PBKDF2-SHA1,
4096 rounds, the network's name as the salt), so this file makes nothing
easier to guess than the network already does.

WHAT IT DOES NOT DO - said where it is built, because it matters. The
passkey is the Wi-Fi passkey, so whoever was given the Wi-Fi holds it, and
the steward's name is no secret. A guest who knows both can sign in as the
steward. What it does is make that a deliberate act: nobody becomes the
steward by joining the network, and a guest's words are not stored in the
steward's voice. A passkey of the steward's own closes the rest
(tools/steward_key.py own); the console is not served over TLS either, so the
network's own encryption is what carries the cookie.

Standard library only. Imported by gui/serve.py and tools/steward_key.py.
"""
import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
import unicodedata

SCHEME = "pbkdf2-sha256"
ITERATIONS = 200_000          # about 0.1 s on a Raspberry Pi 5: once per sign-in
SALT_BYTES = 16
HASH_BYTES = 32
SOURCES = ("wifi", "own")     # the unit's Wi-Fi passkey, or one of the steward's own

COOKIE = "aetherseed_steward"
SESSION_S = 12 * 3600         # a signed-in phone stays the steward this long
MAX_SESSIONS = 8              # the oldest is ended when a ninth signs in

# Tries that fail. Per address: five in a quarter of an hour. All addresses
# together: twenty in an hour - a phone that changes its address does not get
# five more each time. The unit's own screen never signs in, so is never shut
# out by any of this.
TRIES_PER_ADDRESS = 5
ADDRESS_WINDOW_S = 15 * 60
TRIES_ALL = 20
ALL_WINDOW_S = 60 * 60
# A phone that has signed in as the steward is remembered for this long, and
# is not shut out by the count over ALL addresses: a
# guest who makes twenty wrong tries an hour would otherwise keep the steward's
# phone out for good. Such a phone still has the per-address limit.
KNOWN_TTL_S = 30 * 24 * 3600
MAX_KNOWN = 8

_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


def passkey_shape_ok(key) -> bool:
    """A WPA2 passkey: 8-63 printable ASCII characters (tools/hotspot.sh).
    A passkey of the steward's own is held to the same, so the page's one
    field fits both."""
    return (isinstance(key, str) and 8 <= len(key) <= 63
            and all(32 <= ord(c) < 127 for c in key))


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text, length):
    try:
        raw = base64.b64decode(text.encode("ascii"), validate=True)
    except (AttributeError, ValueError, binascii.Error, UnicodeEncodeError):
        return None
    return raw if len(raw) == length else None


def make_record(passkey: str, source: str, iterations: int = ITERATIONS,
                salt: bytes = None, now: str = None) -> dict:
    """What is written to the key file: the hash, its salt and rounds, where
    the passkey came from and when. Never the passkey."""
    if not passkey_shape_ok(passkey):
        raise ValueError("not a usable passkey (8-63 plain characters)")
    if source not in SOURCES:
        raise ValueError("source must be one of %s" % ", ".join(SOURCES))
    salt = salt if salt is not None else secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", passkey.encode("ascii"), salt, iterations)
    return {"scheme": SCHEME, "iterations": iterations, "salt": _b64(salt),
            "hash": _b64(digest), "source": source,
            "set_at": now or time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def record_ok(rec) -> bool:
    return (isinstance(rec, dict) and rec.get("scheme") == SCHEME
            and isinstance(rec.get("iterations"), int)
            and not isinstance(rec.get("iterations"), bool)
            and 10_000 <= rec["iterations"] <= 10_000_000
            and _unb64(rec.get("salt"), SALT_BYTES) is not None
            and _unb64(rec.get("hash"), HASH_BYTES) is not None
            and rec.get("source") in SOURCES)


def load_record(path: str):
    """The key file's record, or None: missing, unreadable, or not a record."""
    try:
        with open(path, "rb") as f:
            raw = f.read(4097)
    except OSError:
        return None
    if len(raw) > 4096:
        return None
    try:
        rec = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return rec if record_ok(rec) else None


def passkey_matches(rec, passkey) -> bool:
    """Does `passkey` hash to the record's hash? Constant time in the hash."""
    if not record_ok(rec) or not isinstance(passkey, str) or len(passkey) > 256:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", passkey.encode("utf-8", "replace"),
                                 _unb64(rec["salt"], SALT_BYTES), rec["iterations"])
    return hmac.compare_digest(digest, _unb64(rec["hash"], HASH_BYTES))


def fold_name(name) -> str:
    """A name as it is compared: one form of each letter, any case, spaces
    as one ("alex", " alex " and "ALEX" are one name)."""
    if not isinstance(name, str):
        return ""
    return " ".join(unicodedata.normalize("NFC", name).casefold().split())


def names_match(typed, steward) -> bool:
    a, b = fold_name(typed), fold_name(steward)
    return bool(a) and bool(b) and hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class Sessions:
    """Signed-in phones: a token each, bound to the address it signed in
    from, ended after `ttl_s`. Kept in this process only - a restart of the
    console signs every phone out, and nothing of it is ever written."""

    def __init__(self, ttl_s: float = SESSION_S, max_sessions: int = MAX_SESSIONS,
                 clock=time.monotonic):
        self.ttl_s = ttl_s
        self.max_sessions = max_sessions
        self.clock = clock
        self._lock = threading.Lock()
        self._by_token = {}           # token -> (expires_at, address)

    def _sweep(self, now):
        for tok in [t for t, (exp, _) in self._by_token.items() if exp <= now]:
            del self._by_token[tok]

    def open(self, address: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            now = self.clock()
            self._sweep(now)
            while len(self._by_token) >= self.max_sessions:
                oldest = min(self._by_token, key=lambda t: self._by_token[t][0])
                del self._by_token[oldest]
            self._by_token[token] = (now + self.ttl_s, address)
        return token

    def valid(self, token, address) -> bool:
        if not isinstance(token, str) or not _TOKEN.match(token):
            return False
        with self._lock:
            now = self.clock()
            self._sweep(now)
            found = self._by_token.get(token)
        return bool(found) and found[1] == address

    def close(self, token):
        with self._lock:
            self._by_token.pop(token, None)

    def count(self) -> int:
        with self._lock:
            self._sweep(self.clock())
            return len(self._by_token)


class Lockout:
    """How long until `address` may try again: 0 when it may now."""

    def __init__(self, per_address: int = TRIES_PER_ADDRESS,
                 address_window_s: float = ADDRESS_WINDOW_S,
                 all_tries: int = TRIES_ALL, all_window_s: float = ALL_WINDOW_S,
                 clock=time.monotonic):
        self.per_address = per_address
        self.address_window_s = address_window_s
        self.all_tries = all_tries
        self.all_window_s = all_window_s
        self.clock = clock
        self._lock = threading.Lock()
        self._by_address = {}         # address -> [times of failed tries]
        self._all = []                # times of every failed try
        self._known = {}              # address -> time of its last good sign-in

    def _trim(self, now):
        self._all = [t for t in self._all if now - t < self.all_window_s]
        for a in list(self._by_address):
            kept = [t for t in self._by_address[a] if now - t < self.address_window_s]
            if kept:
                self._by_address[a] = kept
            else:
                del self._by_address[a]

    def wait(self, address: str) -> float:
        with self._lock:
            now = self.clock()
            self._trim(now)
            waits = [0.0]
            mine = self._by_address.get(address, [])
            if len(mine) >= self.per_address:
                waits.append(mine[-self.per_address] + self.address_window_s - now)
            if len(self._all) >= self.all_tries and not self._known_address(address, now):
                waits.append(self._all[-self.all_tries] + self.all_window_s - now)
            return max(waits)

    def _known_address(self, address, now):
        t = self._known.get(address)
        return t is not None and now - t < KNOWN_TTL_S

    def failed(self, address: str):
        with self._lock:
            now = self.clock()
            self._by_address.setdefault(address, []).append(now)
            self._all.append(now)

    def succeeded(self, address: str):
        """The steward's own address starts over, and is remembered: the count
        over all addresses does not stop it (A4). The count itself does not
        start over - a success proves nothing about the other tries."""
        with self._lock:
            self._by_address.pop(address, None)
            self._known[address] = self.clock()
            while len(self._known) > MAX_KNOWN:
                del self._known[min(self._known, key=self._known.get)]


def token_from_cookie(header):
    """The session token in a Cookie header, if there is one of our shape."""
    if not isinstance(header, str):
        return None
    for part in header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE and _TOKEN.match(v.strip()):
            return v.strip()
    return None


def set_cookie(token: str, max_age: int = SESSION_S) -> str:
    # HttpOnly: the page's script never holds it. SameSite=Strict: no other
    # site's page can send it along. No Secure flag: the console is plain
    # HTTP on the unit's own network, and a Secure cookie would never be sent.
    return "%s=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d" % (COOKIE, token, int(max_age))


def clear_cookie() -> str:
    return "%s=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0" % COOKIE
