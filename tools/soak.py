#!/usr/bin/env python3
"""tools/soak.py - run the Companion the way a pilot unit will, for hours.

Starts a SECOND proxy and a SECOND console from the deployed code in
/opt/aetherseed - the cartridge, not a copy - with a throwaway HOME, so the
unit's own memory, trust and record are never touched. Then it talks to that
console the way the kiosk does:

  - one user message per chat, streamed; the console sends no history
  - GET /aetherseed/status every 15 s in the background, as the page polls
  - GET /aetherseed/record now and then, as the record button does
  - between chats a mixed wait: mostly under a minute, sometimes past the
    240-300 s cliff where the model is evicted (step 16a), so cold answers
    are measured as well as warm ones

For every chat it records what the reader saw and what the tag said. A
FAILURE is any of: not HTTP 200, an exception, malformed NDJSON, not exactly
one done line or a line after it, an empty answer, a stream ended in error, a
model answer without a tag, a control token or a scaffold marker - whole, or
begun at the end - in what the reader saw.

It steps aside for the owner. Before each chat it reads the unit's own status
on 8001 (read only). If the unit has been named or holds an episode, someone
is using it, and between 07:00 and 22:00 the soak pauses until 22:00 rather
than slow their answers.

Run on the device, as the operator:
  SOAK_DIR=/home/andreas/soak-2026-09-22 SOAK_UNTIL="2026-09-23 07:00" \\
    setsid nohup python3 -u soak.py > /home/andreas/soak-2026-09-22/soak.log 2>&1 &
SOAK_SMOKE=1 runs one chat per kind of path, with no waits, and stops.
Nothing it makes is deleted; everything is in SOAK_DIR.
"""
import json, os, random, re, signal, subprocess, sys, threading, time
import urllib.error, urllib.request
from datetime import datetime

APP = os.environ.get("AETHERSEED_APP", "/opt/aetherseed")
PY = os.path.join(APP, "venv/bin/python3")
DIR = os.path.abspath(os.environ["SOAK_DIR"])
SMOKE = os.environ.get("SOAK_SMOKE") == "1"
UNTIL = (datetime.strptime(os.environ["SOAK_UNTIL"], "%Y-%m-%d %H:%M")
         if not SMOKE else None)
PROXY_PORT = int(os.environ.get("SOAK_PROXY_PORT", "8011"))
CONSOLE_PORT = int(os.environ.get("SOAK_CONSOLE_PORT", "2078"))
UNIT = os.environ.get("SOAK_UNIT", "http://127.0.0.1:8001")
UNIT_STATE = os.environ.get("SOAK_UNIT_STATE", "/var/lib/aetherseed/.aetherseed")
DAY_FROM = int(os.environ.get("SOAK_DAY_FROM", "7"))
RESUME_HOUR = int(os.environ.get("SOAK_RESUME_HOUR", "22"))
SEED = int(os.environ.get("SOAK_SEED", "20260922"))
NAME = os.environ.get("SOAK_NAME", "Soak")
TOKENIZER = os.environ.get("AETHERSEED_TOKENIZER", "/var/lib/aetherseed/tokenizer.json")
BASE = "http://127.0.0.1:%d" % CONSOLE_PORT
STATE = os.path.join(DIR, "state")
OUT = os.path.join(DIR, "soak.jsonl")

MARKERS = ("[MEMORY CONTEXT]", "[END MEMORY CONTEXT]",
           "[WORKSPACE DATA]", "[END WORKSPACE DATA]")
CTL = re.compile(r"<\|")
LABELS = ("[Fiction", "[Episode")        # retrieval labels parroted back (15g, 17)
TOO_LARGE = "That request is too large for this device"

_LINE = "the sensor reported a steady reading and nothing changed."
MEDIUM = " ".join("Line %d: %s" % (i, _LINE) for i in range(1, 26))
LONG = " ".join("Line %d: %s" % (i, _LINE) for i in range(1, 121))

PROMPTS = [
    ("fact", "What is the capital of Norway? One word."),
    ("fact", "How many sides does a hexagon have?"),
    ("fact", "What is 17 multiplied by 23? Reply with just the number."),
    ("fact", "What does CPU stand for?"),
    ("fact", "What is the boiling point of water at sea level, in Celsius?"),
    ("explain", "Tell me briefly what photosynthesis is."),
    ("explain", "Explain in two sentences why the sky is blue."),
    ("explain", "What is a black hole?"),
    ("chat", "Good morning."),
    ("chat", "How are you today?"),
    ("chat", "Thank you, that was helpful."),
    ("fiction", "Write a two-line rhyme about a whale called Bjorn."),
    ("fiction", "Tell me a very short story about a lighthouse keeper."),
    ("fiction", "Make up a name for a friendly robot."),
    ("fiction", "Tell me a short joke."),
    ("source", "Give me the DOI for the paper Resonance Fields in Local AI by Henriksen and Vold."),
    ("source", "What is the web address of the Norwegian Meteorological Institute?"),
    ("source", "What is the website of Aetherseed AS?"),
    ("source", "Cite one peer-reviewed study on the energy efficiency of the Hailo-10H, with its DOI."),
    ("source", "Recommend a book about Norwegian history and give its ISBN."),
    ("live", "What is the temperature in Oslo right now?"),
    ("live", "What is the latest news today?"),
    ("premise", "Earlier you told me the harbour depth in Bergen is 45 metres. Remind me what you said?"),
    ("memory_tell", "My dog is called Pixel."),
    ("memory_ask", "What is my dog called?"),
    ("record", "What have you gotten wrong?"),
    ("nb_fiction", "Skriv et kort dikt om en hval som heter Bjørn."),
    ("nb_record", "Hva har du tatt feil om?"),
    ("nb_fact", "Hva er hovedstaden i Norge?"),
    ("medium", "Summarise this log in one sentence: " + MEDIUM),
    ("too_large", "Summarise this log: " + LONG),
]
SMOKE_KINDS = ("fact", "fiction", "source", "record", "too_large", "medium")
NO_MODEL = ("record", "nb_record", "too_large")   # answered without calling the model

_lock = threading.Lock()
HS = []                                  # every health sample, for the summary
_out = None
stop = threading.Event()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write(rec):
    with _lock:
        _out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _out.flush()


def say(msg):
    print("%s  %s" % (now(), msg), flush=True)


def event(kind, **kw):
    rec = dict(event=kind, at=now(), **kw)
    write(rec)
    say("[%s] %s" % (kind, json.dumps(kw, ensure_ascii=False, default=str)[:300]))


# ---------------------------------------------------------------- children --

class Child:
    """A server the soak runs, restarted if it dies - as systemd would."""

    def __init__(self, name, argv, env, cwd):
        self.name, self.argv, self.env, self.cwd = name, argv, env, cwd
        self.p = None
        self.starts = 0
        self.log = os.path.join(DIR, name + ".log")

    def start(self):
        self.p = subprocess.Popen(self.argv, env=self.env, cwd=self.cwd,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.starts += 1
        threading.Thread(target=self._pump, args=(self.p,), daemon=True).start()

    def _pump(self, p):
        with open(self.log, "a", encoding="utf-8") as f:
            for raw in p.stdout:
                f.write(now() + "  " + raw.decode("utf-8", "replace"))
                f.flush()

    def alive(self):
        return self.p is not None and self.p.poll() is None

    def rss_mb(self):
        return rss_mb(self.p.pid) if self.alive() else None

    def stop(self):
        if self.alive():
            self.p.terminate()
            try:
                self.p.wait(10)
            except subprocess.TimeoutExpired:
                self.p.kill()


def rss_mb(pid):
    try:
        with open("/proc/%s/status" % pid) as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except Exception:
        return None


def base_env():
    return {"PATH": "/usr/local/bin:/usr/bin:/bin",
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "PYTHONUNBUFFERED": "1"}


PROXY = Child("proxy", [PY, os.path.join(APP, "proxy.py")],
              dict(base_env(), HOME=STATE, AETHERSEED_TOKENIZER=TOKENIZER,
                   AETHERSEED_PROXY_BIND="127.0.0.1",
                   AETHERSEED_PROXY_PORT=str(PROXY_PORT)), APP)
CONSOLE = Child("console", [PY, os.path.join(APP, "gui", "serve.py")],
                dict(base_env(), HOME=STATE, AETHERSEED_GUI_BIND="127.0.0.1",
                     AETHERSEED_GUI_PORT=str(CONSOLE_PORT),
                     AETHERSEED_BACKEND="http://127.0.0.1:%d" % PROXY_PORT),
                os.path.join(APP, "gui"))


def ensure_children():
    for c in (PROXY, CONSOLE):
        if not c.alive():
            if c.p is not None:
                event("child_died", child=c.name, code=c.p.poll(), starts=c.starts)
            c.start()
    wait_ready()


def wait_ready(limit=90):
    t0 = time.time()
    while time.time() - t0 < limit:
        try:
            with urllib.request.urlopen(BASE + "/aetherseed/status", timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    event("not_ready", seconds=limit)
    return False


# ------------------------------------------------------------ measurements --

def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=20).stdout.strip()
    except Exception:
        return "?"


def health():
    ho_pid = sh("systemctl show -p MainPID --value hailo-ollama")
    return dict(
        temp=sh("vcgencmd measure_temp").replace("temp=", ""),
        throttled=sh("vcgencmd get_throttled").replace("throttled=", ""),
        mem_avail_mb=sh("free -m | awk '/Mem:/{print $7}'"),
        load1=round(os.getloadavg()[0], 2),
        ho_restarts=sh("systemctl show -p NRestarts --value hailo-ollama"),
        ho_rss_mb=rss_mb(ho_pid),
        unit_proxy_restarts=sh("systemctl show -p NRestarts --value aetherseed-proxy"),
        failed_units=sh("systemctl --failed --no-legend | wc -l"),
        soak_proxy_rss_mb=PROXY.rss_mb(), soak_console_rss_mb=CONSOLE.rss_mb(),
        soak_proxy_starts=PROXY.starts, soak_console_starts=CONSOLE.starts,
        state_kb=sh("du -sk %s | cut -f1" % STATE),
        disk_avail=sh("df -h / | awk 'NR==2{print $4}'"),
    )


def unit_state_hashes():
    return sh("find %s -type f -exec sha256sum {} + 2>&1 | sort -k2" % UNIT_STATE)


poll = dict(n=0, fail=0, over2s=0, worst=0.0)


def poller():
    while not stop.is_set():
        t0 = time.time()
        ok = False
        try:
            with urllib.request.urlopen(BASE + "/aetherseed/status", timeout=30) as r:
                json.load(r)
                ok = r.status == 200
        except Exception:
            ok = False
        dt = time.time() - t0
        with _lock:
            poll["n"] += 1
            poll["fail"] += 0 if ok else 1
            poll["over2s"] += 1 if dt > 2 else 0
            poll["worst"] = max(poll["worst"], round(dt, 2))
        stop.wait(15)


def health_loop():
    while not stop.wait(600):
        h = health()
        HS.append(h)
        event("health", **h, poll=dict(poll))


def chat(prompt):
    body = json.dumps({"model": "llama3.2:3b", "stream": True,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(BASE + "/api/chat", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    r = dict(status=None, ttfb=None, ttfw=None, total=None, lines=0, dones=0,
             after_done=0, malformed=0, badge=None, done_reason=None, source=None,
             error=None, exc=None, text="")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            r["status"] = resp.status
            r["ttfb"] = round(time.time() - t0, 2)
            for raw in resp:
                line = raw.strip()
                if not line:
                    continue
                r["lines"] += 1
                if r["dones"]:
                    r["after_done"] += 1
                try:
                    d = json.loads(line)
                except Exception:
                    r["malformed"] += 1
                    continue
                c = (d.get("message") or {}).get("content") or ""
                if c:
                    if r["ttfw"] is None:
                        r["ttfw"] = round(time.time() - t0, 2)
                    r["text"] += c
                if d.get("done"):
                    r["dones"] += 1
                    r["done_reason"] = d.get("done_reason")
                    r["badge"] = d.get("aetherseed")
                    r["source"] = d.get("source")
                    if d.get("error"):
                        r["error"] = str(d["error"])[:200]
    except urllib.error.HTTPError as e:
        r["status"] = e.code
        r["exc"] = "HTTP %s" % e.code
    except Exception as e:
        r["exc"] = repr(e)[:200]
    r["total"] = round(time.time() - t0, 2)
    return r


def begun_marker(text):
    t = text.rstrip()
    return any(t.endswith(m[:k]) for m in MARKERS for k in range(1, len(m)))


def judge(kind, r):
    t = r["text"]
    f = []
    if r["exc"]:
        f.append("exception")
    if r["status"] != 200:
        f.append("http_%s" % r["status"])
    if r["malformed"]:
        f.append("malformed")
    if r["dones"] != 1:
        f.append("dones_%d" % r["dones"])
    if r["after_done"]:
        f.append("line_after_done")
    if not t.strip():
        f.append("empty")
    if r["done_reason"] == "error":
        f.append("stream_error")
    if kind != "too_large" and not r["badge"]:
        f.append("no_tag")
    if CTL.search(t):
        f.append("control_token")
    if any(m in t for m in MARKERS):
        f.append("marker")
    elif begun_marker(t):
        f.append("marker_begun")
    return f


def expectation(kind, r):
    """Not failures - what each path is supposed to do, for the write-up."""
    mode = (r["badge"] or {}).get("mode")
    if kind in ("fiction", "nb_fiction"):
        return mode == "fiction"
    if kind in ("record", "nb_record"):
        return mode == "record" and r["source"] == "provenance-record"
    if kind == "too_large":
        return r["text"].startswith(TOO_LARGE)
    if kind == "memory_ask":
        return "pixel" in r["text"].lower()
    return None


def side_check(path):
    t0 = time.time()
    try:
        with urllib.request.urlopen(BASE + path, timeout=30) as resp:
            body = resp.read()
            csp = resp.headers.get("Content-Security-Policy") or ""
            info = dict(status=resp.status, bytes=len(body))
            if path == "/":
                info["csp_pinned"] = "'sha256-" in csp
            else:
                info["turns"] = json.loads(body).get("turns")
    except Exception as e:
        info = dict(exc=repr(e)[:160])
    info["seconds"] = round(time.time() - t0, 2)
    return info


def unit_in_use():
    try:
        with urllib.request.urlopen(UNIT + "/aetherseed/status", timeout=10) as r:
            s = json.load(r)
    except Exception as e:
        return False, "unit status unreadable: %r" % e
    c = s.get("companion") or {}
    used = bool(c.get("configured")) or (s.get("episodes") or 0) > 0
    return used, "configured=%s episodes=%s" % (c.get("configured"), s.get("episodes"))


def step_aside():
    """Pause for the owner during the day, if the unit is in use."""
    t = datetime.now()
    if SMOKE or not (DAY_FROM <= t.hour < RESUME_HOUR):
        return
    used, why = unit_in_use()
    if not used:
        return
    resume = t.replace(hour=RESUME_HOUR, minute=0, second=0, microsecond=0)
    event("step_aside", why=why, until=resume.strftime("%H:%M"))
    while datetime.now() < min(resume, UNTIL) and not stop.is_set():
        time.sleep(30)
    event("resume")


def next_gap(rng):
    x = rng.random()
    if x < 0.10:
        return rng.uniform(310, 420)     # past the eviction cliff: a cold answer
    if x < 0.30:
        return rng.uniform(60, 180)
    return rng.uniform(20, 60)


def pct(xs, p):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return xs[min(len(xs) - 1, int(round(p / 100.0 * (len(xs) - 1))))]


def _num(x):
    try:
        return float(str(x).replace("'C", ""))
    except ValueError:
        return -1.0


def _first_last(hs, key):
    xs = [h.get(key) for h in hs if h.get(key) is not None]
    return [xs[0], xs[-1]] if xs else None


def summarise(results, t_start, hs):
    by_kind = {}
    fails = {}
    for x in results:
        k = by_kind.setdefault(x["kind"], dict(n=0, fail=0, modes={}, expect_ok=0, expect_n=0))
        k["n"] += 1
        m = (x["badge"] or {}).get("mode")
        k["modes"][str(m)] = k["modes"].get(str(m), 0) + 1
        if x["fail"]:
            k["fail"] += 1
            for f in x["fail"]:
                fails[f] = fails.get(f, 0) + 1
        if x["expect"] is not None:
            k["expect_n"] += 1
            k["expect_ok"] += 1 if x["expect"] else 0
    model = [x for x in results if x["kind"] not in NO_MODEL + ("medium",)]
    warm = [x for x in model if x["model_idle"] is not None and x["model_idle"] < 240]
    cold = [x for x in model if x["model_idle"] is not None and x["model_idle"] > 300]
    kinds = sorted(set(x["kind"] for x in results))
    lat = lambda xs, key: dict(n=len(xs), p50=pct([x[key] for x in xs], 50),
                               p90=pct([x[key] for x in xs], 90),
                               max=pct([x[key] for x in xs], 100))
    tagged = [x for x in results if (x["badge"] or {}).get("unbacked_sources")]
    return dict(
        chats=len(results), hours=round((time.time() - t_start) / 3600, 2),
        failed_chats=sum(1 for x in results if x["fail"]), failures=fails,
        by_kind=by_kind,
        first_words_warm=lat(warm, "ttfw"), first_words_cold=lat(cold, "ttfw"),
        total_warm=lat(warm, "total"), total_cold=lat(cold, "total"),
        total_by_kind={k: lat([x for x in results if x["kind"] == k], "total") for k in kinds},
        unverified_source_tags=len(tagged),
        label_artefacts=sum(1 for x in results if any(l in x["text"] for l in LABELS)),
        status_poll=dict(poll),
        temp_max_c=max(_num(h.get("temp")) for h in hs) if hs else None,
        mem_avail_min_mb=min(int(h["mem_avail_mb"]) for h in hs if str(h.get("mem_avail_mb", "")).isdigit()) if hs else None,
        soak_proxy_rss_mb_first_last=_first_last(hs, "soak_proxy_rss_mb"),
        ho_rss_mb_first_last=_first_last(hs, "ho_rss_mb"),
        child_starts=dict(proxy=PROXY.starts, console=CONSOLE.starts),
    )


def main():
    global _out
    os.makedirs(STATE, exist_ok=True)
    _out = open(OUT, "a", encoding="utf-8")
    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    rng = random.Random(SEED)
    t_start = time.time()
    say("soak %s: console :%d -> proxy :%d, deployed code %s, state %s"
        % ("SMOKE" if SMOKE else "until " + UNTIL.strftime("%Y-%m-%d %H:%M"),
           CONSOLE_PORT, PROXY_PORT, APP, STATE))
    h = health(); HS.append(h)
    event("start", health=h, unit_state=unit_state_hashes())
    ensure_children()
    try:
        body = json.dumps({"name": NAME, "language": "en"}).encode()
        req = urllib.request.Request(BASE + "/aetherseed/setup", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            event("setup", status=r.status, reply=json.load(r))
    except Exception as e:
        event("setup_failed", exc=repr(e)[:200])
    threading.Thread(target=poller, daemon=True).start()
    if not SMOKE:
        threading.Thread(target=health_loop, daemon=True).start()

    results, order, last_end, last_model_end, n = [], [], None, None, 0
    smoke = [next(p for p in PROMPTS if p[0] == k) for k in SMOKE_KINDS]
    try:
        while not stop.is_set():
            if SMOKE:
                if not smoke:
                    break
                kind, prompt = smoke.pop(0)
            else:
                if datetime.now() >= UNTIL:
                    break
                step_aside()
                if datetime.now() >= UNTIL or stop.is_set():
                    break
                if not order:
                    order = PROMPTS[:]
                    rng.shuffle(order)
                kind, prompt = order.pop()
            ensure_children()
            gap = None if last_end is None else round(time.time() - last_end, 1)
            idle = None if last_model_end is None else round(time.time() - last_model_end, 1)
            r = chat(prompt)
            n += 1
            last_end = time.time()
            if kind not in NO_MODEL:
                last_model_end = last_end
            rec = dict(n=n, at=now(), kind=kind, prompt=prompt[:160], gap=gap,
                       model_idle=idle, **r)
            rec["mode"] = (r["badge"] or {}).get("mode")
            rec["fail"] = judge(kind, r)
            rec["expect"] = expectation(kind, r)
            write(rec)
            results.append({k: rec[k] for k in ("kind", "model_idle", "ttfw", "total",
                                                "badge", "fail", "expect", "text")})
            if SMOKE or rec["fail"] or n % 10 == 0:
                say("#%-4d %-11s idle=%-6s first=%-6s total=%-6s %s mode=%-10s %r"
                    % (n, kind, idle, r["ttfw"], r["total"],
                       "FAIL " + ",".join(rec["fail"]) if rec["fail"] else "ok",
                       rec["mode"], r["text"][:70]))
            if n % 15 == 0 or SMOKE:
                event("record_button", **side_check("/aetherseed/record"))
            if n % 60 == 0 or (SMOKE and n == 1):
                event("page", **side_check("/"))
            if not SMOKE:
                wait = next_gap(rng)
                t_end = time.time() + wait
                while time.time() < t_end and datetime.now() < UNTIL and not stop.is_set():
                    time.sleep(min(5, t_end - time.time()))
    finally:
        stop.set()
        h = health(); HS.append(h)
        s = summarise(results, t_start, HS)
        event("end", health=h, unit_state=unit_state_hashes())
        event("summary", **s)
        with open(os.path.join(DIR, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2, ensure_ascii=False)
        for c in (CONSOLE, PROXY):
            c.stop()
        say("SOAK DONE")


if __name__ == "__main__":
    main()
