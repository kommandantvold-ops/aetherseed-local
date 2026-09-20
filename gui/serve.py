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

Static files only, read-only, no directory listing, no uploads, no writes.
"""
import http.server
import json
import os
import socketserver
import sys
import urllib.error
import urllib.request

BIND = os.environ.get("AETHERSEED_GUI_BIND", "127.0.0.1")
PORT = int(os.environ.get("AETHERSEED_GUI_PORT", "2077"))
BACKEND = os.environ.get("AETHERSEED_BACKEND", "http://127.0.0.1:8001")
ROOT = os.path.dirname(os.path.abspath(__file__))

# Only these reach the backend. An allow-list rather than a prefix match, so a
# future route on the proxy is not exposed to the browser by accident.
PROXIED_POST = ("/api/chat",)
PROXIED_GET = ("/aetherseed/status", "/aetherseed/record", "/api/tags")


class Console(http.server.SimpleHTTPRequestHandler):

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass

    def end_headers(self):
        # The page loads nothing from anywhere. Saying so in a header means a
        # typo in the HTML fails loudly instead of silently reaching out.
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data:; connect-src 'self'; "
                         "frame-ancestors 'none'")
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
            self._relay("GET")
            return
        if self.path == "/":
            self.path = "/index.html"
        if self.path not in ("/index.html",):
            self.send_error(404)
            return
        super().do_GET()

    def do_POST(self):
        if self.path not in PROXIED_POST:
            self.send_error(404)
            return
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
    Threaded((BIND, PORT), Console).serve_forever()
