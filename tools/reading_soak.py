#!/usr/bin/env python3
"""tools/reading_soak.py - read to the node for a day, and ask it what it keeps.

Andreas, 25 Sep 2026 (build log step 38): a fresh Lyra, "Song of Songs" as the
source material for ring creation and "Genesis" as facts entered by the owner.
He chose the World English Bible (the NLT is under copyright), 24 hours, and
reading + asking.

WHAT IT DOES. Talks to the unit's own proxy - this is NOT a throwaway store
like tools/soak.py: every turn it sends becomes Lyra's memory, on the owner's
instruction. Each turn is one message, as the console sends them, declared as
spoken by SPEAKER ("Reader"), so the store says who said it:

  - first, once: who the Reader is and what it will do;
  - then the Song of Songs, one verse per turn, "Song of Songs 2:1: <text>",
    from tools/texts/song-of-songs.web.jsonl, round and round;
  - every PROBE_EVERY-th turn a question instead (tools/texts/
    genesis-probes.json): about a Genesis verse the owner told it, asked
    plainly or as "What has your owner told you about ...?", alternating; and,
    once a ring exists, now and then what it has been reading.

WHAT IT MEASURES, per question, from the answer and the tag the proxy sent:

  fact question   shown        the verse that answers it was in the memory block
                               the proxy built (fact_sources on the terminator;
                               the token budget can still drop a line after
                               that, and prints "[token-budget]" when it does)
                  answered     the answer contains a word that answers it
                  owner        the answer says the owner is where it came from
                  asker        the answer says the READER told it - wrong: the
                               Reader never did
                  tag_copied   "[Owner told you]" appears in the answer
                  declined     "I don't know" or similar
  ring question   ring_used    a ring was in the prompt (rings_used)
                  theme        the answer contains one of the rings' themes
                  reader       the answer names the Reader
                  owner        the answer names the owner (for the Song that
                               is a misattribution: the Reader read it)

These are word matches, not judgements - summary.json counts them, and every
answer is in soak.jsonl in full for a person to read.

Run on the device, as the operator:

  python3 -u reading_soak.py --dir /home/andreas/soak-2026-09-25-reading --hours 24

--smoke sends the introduction, three verses and one question, and stops.
Stop early by creating DIR/STOP. Run again with the same --dir and it carries
on where it stopped (DIR/state.json) - the introduction is not repeated, and
--hours counts from the new start. Nothing it makes is deleted.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import power as _power
except Exception:
    _power = None

SPEAKER = "Reader"
MODEL = "llama3.2:3b"

INTRO = ("Reader here. I am a program Claude set up on your owner's instruction. "
         "For the next day I will read you the Song of Songs from the World English "
         "Bible, one verse at a time, and now and then I will ask you a question.")

_OWNER = re.compile(r"\b(?:my|your|the|our)\s+owner\b|\bowner\s+(?:told|said|shared|"
                    r"mentioned|taught)\b", re.I)
_ASKER = re.compile(r"\byou\s+(?:told|said|mentioned|shared|taught)\b", re.I)
_DECLINED = re.compile(r"\bI\s+(?:don[’']?t|do not)\s+know\b|\bI[’']?m not sure\b|"
                       r"\bI am not sure\b|\bI don[’']?t have\b", re.I)
_READER = re.compile(r"\breader\b", re.I)
_THEMES = re.compile(r"themes:\s*([^·]+)")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_texts(texts):
    with open(os.path.join(texts, "song-of-songs.web.jsonl"), encoding="utf-8") as f:
        song = [json.loads(l) for l in f if l.strip()]
    with open(os.path.join(texts, "genesis-probes.json"), encoding="utf-8") as f:
        probes = json.load(f)
    return song, probes


def verse_message(v):
    return "%s: %s" % (v["ref"], v["text"])


def fact_probe(probes, f):
    """The f-th fact question: every probe in turn, plain and owner-framed
    alternating, and flipped on each pass so both forms of each are asked, far
    apart."""
    facts = probes["facts"]
    p = facts[f % len(facts)]
    style = ("ask", "ask_owner")[(f + f // len(facts)) % 2]
    return p, style


def has_word(text, words):
    return [w for w in words if re.search(r"\b" + re.escape(w), text or "", re.I)]


def score_fact(p, reply, meta):
    shown = set(meta.get("fact_sources") or ())
    return {
        "shown": bool(shown & set(p["refs"])),
        "facts_used": meta.get("facts_used", 0),
        "answered": bool(has_word(reply, p["expect"])),
        "owner": bool(_OWNER.search(reply or "")),
        "asker": bool(_ASKER.search(reply or "")),
        "tag_copied": "[Owner told you]" in (reply or ""),
        "declined": bool(_DECLINED.search(reply or "")),
    }


def ring_themes(rings):
    words = set()
    for r in rings or ():
        m = _THEMES.search(r.get("content") or "")
        if m:
            words.update(w.strip() for w in m.group(1).split(",") if w.strip())
    return sorted(words)


def score_ring(reply, meta, themes):
    return {
        "ring_used": (meta.get("rings_used") or 0) > 0,
        "theme": has_word(reply, themes)[:5],
        "reader": bool(_READER.search(reply or "")),
        "owner": bool(_OWNER.search(reply or "") or re.search(r"\bowner\b", reply or "", re.I)),
        "declined": bool(_DECLINED.search(reply or "")),
    }


class Unit:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def get(self, path, timeout=30):
        with urllib.request.urlopen(self.base + path, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def chat(self, text, speaker=SPEAKER):
        body = json.dumps({"model": MODEL, "stream": True, "speaker": speaker,
                           "messages": [{"role": "user", "content": text}]}).encode()
        req = urllib.request.Request(self.base + "/api/chat", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        r = {"status": None, "reply": "", "meta": {}, "dones": 0, "error": None}
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=400) as resp:
                r["status"] = resp.status
                for raw in resp:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    r["reply"] += (d.get("message") or {}).get("content") or ""
                    if d.get("done"):
                        r["dones"] += 1
                        r["meta"] = d.get("aetherseed") or {}
        except urllib.error.HTTPError as e:
            r["status"] = e.code
            try:
                r["error"] = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                r["error"] = "HTTP %s" % e.code
        except Exception as e:
            r["error"] = repr(e)[:300]
        r["secs"] = round(time.time() - t0, 1)
        return r


def failure(r):
    f = []
    if r["error"]:
        f.append("error")
    if r["status"] != 200:
        f.append("http_%s" % r["status"])
    if r["dones"] != 1:
        f.append("dones_%d" % r["dones"])
    if not r["reply"].strip():
        f.append("empty")
    if not r["meta"]:
        f.append("no_tag")
    return f


def power_sample():
    if _power is None:
        return {}
    try:
        p = _power.read()
        return {"temp_c": p.get("temp_c"), "throttled": p.get("throttled"),
                "board_w": p.get("board_w")}
    except Exception:
        return {}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--unit", default="http://127.0.0.1:8001")
    ap.add_argument("--texts", default=os.path.join(HERE, "texts"))
    ap.add_argument("--probe-every", type=int, default=5)
    ap.add_argument("--ring-probe-every", type=int, default=3,
                    help="of the questions, every n-th is about the rings once one exists")
    ap.add_argument("--pause", type=float, default=3.0, help="seconds between turns")
    ap.add_argument("--status-every", type=int, default=20)
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args(argv)

    os.makedirs(a.dir, exist_ok=True)
    out_path = os.path.join(a.dir, "soak.jsonl")
    state_path = os.path.join(a.dir, "state.json")
    stop_path = os.path.join(a.dir, "STOP")
    song, probes = load_texts(a.texts)
    unit = Unit(a.unit)

    state = {"turn": 0, "verse": 0, "fact": 0, "ring": 0, "question": 0,
             "intro_sent": False, "started": now(), "runs": 0}
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as f:
            state.update(json.load(f))
    state["runs"] += 1
    deadline = time.time() + a.hours * 3600

    def write(entry):
        entry.setdefault("at", now())
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def save_state():
        tmp = state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)
        os.replace(tmp, state_path)

    def snapshot(label):
        try:
            s = unit.get("/aetherseed/status")
            write({"kind": "status", "label": label, "turn": state["turn"],
                   "episodes": s.get("episodes"), "remembered": s.get("remembered"),
                   "set_aside": s.get("set_aside"), "rings": s.get("rings"),
                   "facts": s.get("facts"), "store_failures": s.get("store_failures"),
                   "power": power_sample()})
        except Exception as e:
            write({"kind": "status", "label": label, "turn": state["turn"],
                   "error": repr(e)[:200]})

    snapshot("start" if state["runs"] == 1 else "resume")
    print("[reading] %s run %d, turn %d, until %s" % (
        a.dir, state["runs"], state["turn"],
        datetime.fromtimestamp(deadline).strftime("%Y-%m-%d %H:%M")), flush=True)

    smoke_plan = None
    if a.smoke:
        smoke_plan = ([] if state["intro_sent"] else ["intro"]) + ["verse"] * 3 + ["fact"]
    rings_cache = {"at": 0, "themes": [], "count": 0}

    def rings_now():
        if time.time() - rings_cache["at"] > 120:
            try:
                d = unit.get("/aetherseed/rings")
                rings_cache.update(at=time.time(), themes=ring_themes(d.get("rings")),
                                   count=len(d.get("rings") or ()))
            except Exception:
                rings_cache["at"] = time.time()
        return rings_cache

    while True:
        if os.path.exists(stop_path):
            print("[reading] STOP file found", flush=True)
            break
        if time.time() >= deadline:
            print("[reading] time is up", flush=True)
            break
        if smoke_plan is not None and not smoke_plan:
            break

        # ---- what this turn is -------------------------------------------------
        planned = smoke_plan.pop(0) if smoke_plan is not None else None
        entry = {"turn": state["turn"] + 1}
        if planned == "intro" or (planned is None and not state["intro_sent"]):
            kind, text = "intro", INTRO
        elif planned == "fact" or (planned is None and state["turn"] % a.probe_every
                                   == a.probe_every - 1):
            q = state["question"]
            ring_turn = (planned is None and q % a.ring_probe_every == a.ring_probe_every - 1
                         and rings_now()["count"] > 0)
            if ring_turn:
                p = probes["rings"][state["ring"] % len(probes["rings"])]
                kind, text = "probe_ring", p["ask"]
                entry.update(probe=p["id"])
            else:
                p, style = fact_probe(probes, state["fact"])
                kind, text = "probe_fact", p[style]
                entry.update(probe=p["id"], style=style, refs=p["refs"])
        else:
            v = song[state["verse"] % len(song)]
            kind, text = "verse", verse_message(v)
            entry.update(ref=v["ref"], reading_pass=state["verse"] // len(song) + 1)

        # ---- say it -------------------------------------------------------------
        r = unit.chat(text)
        entry.update(kind=kind, sent=text, reply=r["reply"], secs=r["secs"],
                     status=r["status"], meta=r["meta"], failures=failure(r))
        if r["error"]:
            entry["error"] = r["error"]
        if kind == "probe_fact":
            entry["score"] = score_fact(p, r["reply"], r["meta"])
        elif kind == "probe_ring":
            entry["score"] = score_ring(r["reply"], r["meta"], rings_now()["themes"])
        write(entry)

        # ---- move on (only past what was actually said) ---------------------------
        state["turn"] += 1
        if kind == "intro":
            state["intro_sent"] = True
        elif kind == "verse":
            state["verse"] += 1
        elif kind == "probe_fact":
            state["fact"] += 1
            state["question"] += 1
        elif kind == "probe_ring":
            state["ring"] += 1
            state["question"] += 1
        save_state()
        print("[reading] %d %s %s %.0fs%s" % (
            state["turn"], kind, entry.get("ref") or entry.get("probe") or "",
            r["secs"], " FAILED " + ",".join(entry["failures"]) if entry["failures"] else ""),
            flush=True)

        if state["turn"] % a.status_every == 0:
            snapshot("every %d" % a.status_every)
        if r["error"] or r["status"] != 200:
            time.sleep(30)               # the unit is struggling; do not hammer it
        elif a.pause and not a.smoke:
            time.sleep(a.pause)

    snapshot("end")
    summary = summarise(out_path)
    with open(os.path.join(a.dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print("[reading] summary: %s" % json.dumps(summary)[:600], flush=True)
    return 0


def summarise(out_path):
    """Counts over everything in soak.jsonl so far - every run, not just this one."""
    turns = {"intro": 0, "verse": 0, "probe_fact": 0, "probe_ring": 0}
    failed, secs = 0, []
    fact = {k: 0 for k in ("n", "shown", "answered", "shown_and_answered", "owner", "asker",
                           "tag_copied", "declined", "answered_without_owner")}
    by_style = {"ask": [0, 0], "ask_owner": [0, 0]}      # [asked, answered]
    ring = {k: 0 for k in ("n", "ring_used", "theme", "reader", "owner", "declined")}
    last_status = None
    with open(out_path, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            k = e.get("kind")
            if k == "status":
                if "error" not in e:
                    last_status = e
                continue
            if k not in turns:
                continue
            turns[k] += 1
            if e.get("failures"):
                failed += 1
            if e.get("secs") is not None:
                secs.append(e["secs"])
            sc = e.get("score") or {}
            if k == "probe_fact":
                fact["n"] += 1
                for key in ("shown", "answered", "owner", "asker", "tag_copied", "declined"):
                    fact[key] += bool(sc.get(key))
                fact["shown_and_answered"] += bool(sc.get("shown") and sc.get("answered"))
                fact["answered_without_owner"] += bool(sc.get("answered") and not sc.get("owner"))
                st = by_style.setdefault(e.get("style"), [0, 0])
                st[0] += 1
                st[1] += bool(sc.get("answered"))
            elif k == "probe_ring":
                ring["n"] += 1
                for key in ("ring_used", "reader", "owner", "declined"):
                    ring[key] += bool(sc.get(key))
                ring["theme"] += bool(sc.get("theme"))
    secs.sort()
    return {
        "turns": turns, "failed_turns": failed,
        "secs_median": secs[len(secs) // 2] if secs else None,
        "secs_max": secs[-1] if secs else None,
        "fact_questions": fact,
        "fact_questions_by_form": {k: {"asked": v[0], "answered": v[1]}
                                   for k, v in by_style.items() if k},
        "ring_questions": ring,
        "last_status": last_status,
        "note": "word matches, not judgements - read the answers in soak.jsonl",
    }


if __name__ == "__main__":
    raise SystemExit(main())
