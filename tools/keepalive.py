#!/usr/bin/env python3
"""Hold the model resident, and record what that costs.

The model is evicted somewhere between 240 s and 300 s of silence (step 16a),
and the first words after that cost about eighteen seconds more than they need
to. This sends one one-token request every 180 s, **straight to hailo-ollama on
8000 and never through the proxy** - the same reason the warm-up unit does
(step 14a): a request through the proxy would store an episode nobody said and
score the node's trust for it.

The same loop is the degradation instrument. Every request is timed into
keepalive.jsonl, so the unit accumulates one long series of the identical
request, with temperature and free memory beside it. Latency that drifts
upward over weeks is the thing this exists to catch.

Environment: KEEPALIVE_DIR (required), KEEPALIVE_SECONDS (default 180),
KEEPALIVE_URL (default http://127.0.0.1:8000/api/chat).
"""
import json, os, subprocess, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import power as _power          # deployed beside this file
except Exception:                   # a missing power.py costs a column, not the loop
    _power = None

DIR = os.path.abspath(os.environ["KEEPALIVE_DIR"])
EVERY = float(os.environ.get("KEEPALIVE_SECONDS", "180"))
URL = os.environ.get("KEEPALIVE_URL", "http://127.0.0.1:8000/api/chat")
OUT = os.path.join(DIR, "keepalive.jsonl")
BODY = json.dumps({"model": "llama3.2:3b", "stream": False,
                   "messages": [{"role": "user", "content": "hi"}],
                   "options": {"num_predict": 1}}).encode()


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=15).stdout.strip()
    except Exception:
        return "?"


def health():
    return {"temp": sh("vcgencmd measure_temp").replace("temp=", ""),
            "throttled": sh("vcgencmd get_throttled").replace("throttled=", ""),
            "mem_avail_mb": sh("free -m | awk '/Mem:/{print $7}'"),
            "ho_restarts": sh("systemctl show -p NRestarts --value hailo-ollama")}


def power():
    """Board watts and temperature, on EVERY ping rather than every tenth.

    Asked for by Andreas, 23 Sep: energy and temperature alongside latency.
    A vcgencmd call costs about 10 ms against a 180 s period, so there is no
    reason to sample it more sparsely than the thing it explains - 480 points a
    day is what makes drift visible.

    `board_w` is the sum of the twelve PMIC-sensed rails. It does NOT include
    the Hailo NPU, which is not on a sensed rail (tools/power.py has the
    measurement that establishes that). Read it as the board's own draw.
    """
    if _power is None:
        return {}
    try:
        return _power.read()
    except Exception:
        return {}


def ping():
    req = urllib.request.Request(URL, data=BODY, method="POST",
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            r.read()
            return round(time.time() - t0, 2), r.status, None
    except Exception as e:
        return round(time.time() - t0, 2), None, repr(e)[:160]


def main():
    os.makedirs(DIR, exist_ok=True)
    n = fails = 0
    window = []
    print("[keepalive] every %.0fs -> %s ; log %s" % (EVERY, URL, OUT), flush=True)
    while True:
        started = time.time()
        secs, status, err = ping()
        n += 1
        ok = status == 200 and err is None
        if not ok:
            fails += 1
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "n": n,
               "seconds": secs, "status": status, "ok": ok}
        rec.update(power())
        if err:
            rec["error"] = err
        if n % 10 == 1:                      # one health sample every ~30 min
            rec.update(health())
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        window.append(secs)
        if not ok or n % 20 == 0:            # one journal line an hour
            window.sort()
            print("[keepalive] %d pings, %d failed, median %.2fs, worst %.2fs%s"
                  % (n, fails, window[len(window) // 2], window[-1],
                     "" if ok else " LAST FAILED: %s" % (err or status)), flush=True)
            window = []
        time.sleep(max(5.0, EVERY - (time.time() - started)))


if __name__ == "__main__":
    main()
