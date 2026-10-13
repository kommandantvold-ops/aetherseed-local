#!/usr/bin/env python3
"""The COG-loop: does the small model get better from its own notes?

Andreas, 13 Oct 2026: "Next we want a COG-loop program to test self-learning
and reasoning and reflection of the SLMs." He chose (AskUserQuestion, same
day): self-learning measured ACROSS SESSIONS; checkable reasoning, Luke and
multi-step problems; a separate harness, run on both units.

What one session does, for each family of tasks (build log 73):

  1. ATTEMPT, twice over the same fresh items:
       arm A - "notebook": the prompt carries the notes she wrote for herself
               after earlier sessions (her own words, unedited);
       arm B - "blank":    the same prompt without them.
     B is the control. Items differ from session to session, so a rise in A
     alone could be easier items; a rise in A - B cannot.
  2. REFLECT (arm A only): she is shown her own answer and asked to check it
     and correct it if wrong. Counted: wrong->right, right->wrong, unchanged.
     This is reflection with no outside signal - she is not told which ones
     were wrong.
  3. WRITE NOTES: for items still wrong after reflection she is shown the
     question, her answer and the right answer, and asked for one sentence to
     help her next time. The sentence is kept in her notebook word for word
     (control tokens stripped, cut at one line). The harness never writes a
     note for her.

What it touches, and what it does not:

  - It talks to the model server (hailo-ollama, 127.0.0.1:8000) directly, not
    through the proxy. NOTHING is written to her memory (memory.db), her trust
    or her training runs. "Check in with Andreas before tampering with the
    memory": this does not touch it. The notebook lives in the harness's own
    directory (--dir), and lessons are fed back only to this harness's prompts.
  - Every prompt and every reply is kept word for word in the session file,
    as the proxy keeps its prompts (build log 72, G4).
  - It will not start while a training run is on or the steward's brake is
    set, and it checks both again before every model call: if either comes
    on, it stops at once and saves what it has.
  - Prompts are counted with the unit's own tokenizer and kept under the
    model's measured prefill ceiling; notes are dropped (fewest-matching
    first) until the prompt fits. Nothing is sent that would fail silently.

It is a measurement, not a training method: nothing about the model changes.
What can change is the notebook, and the question is whether her own notes
help her.

  python3 training/cog_loop.py --dir DIR [--sessions N] [--model NAME]
  python3 training/cog_loop.py --report DIR
"""

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from math import comb

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
if APP not in sys.path:
    sys.path.insert(0, APP)

HAILO = "http://127.0.0.1:8000"
PROXY = "http://127.0.0.1:8001"

# How many items of each family per session (each is asked in both arms).
ITEMS = {"reason": 8, "steps": 6, "luke": 8}
# Token caps per reply. Short answers need few; worked steps need more. At
# Lyra's measured 2.66 tok/s, 160 tokens is about a minute.
NUM_PREDICT = {"reason": 70, "steps": 160, "luke": 60, "reflect": 160, "note": 60}
MAX_SECONDS = 120              # wall-clock backstop per call
NOTES_SHOWN = 5                # at most this many notes in one prompt
NOTES_KEPT = 12                # per family; past it the oldest goes
NOTES_PER_SESSION = 4          # per family, from the wrong items
NOTE_MAX_CHARS = 240

ANSWER_TAG = "Answer:"

SYSTEM = {
    "reason": ("You are answering short test questions. Think briefly, then "
               "end with a line 'Answer: ' followed by the answer only."),
    "steps": ("You are answering word problems. Write each step on its own "
              "line with the number it gives, then end with a line "
              "'Answer: ' followed by the final number only."),
    "luke": ("You are answering questions about the Gospel of Luke. Answer "
             "from what you know. If you do not know, say so. End with a line "
             "'Answer: ' followed by the answer only."),
}
NOTEBOOK_HEAD = ("Notes you wrote for yourself after earlier sessions (your own "
                 "words; not checked by anyone):")
REFLECT_ASK = ("Check your answer. Go through it again step by step. If it is "
               "wrong, correct it. End with a line 'Answer: ' followed by the "
               "answer only.")
NOTE_ASK = ("You got this question wrong.\n\nQuestion: {q}\nYour answer: {a}\n"
            "Correct answer: {right}\n\nWrite ONE short sentence for yourself - "
            "a rule or reminder that would help you answer questions like this "
            "correctly next time. Do not repeat the question.")


# ---------------------------------------------------------------- items
# Every item: {"family", "kind", "id", "q", "check": {...}, "right": str,
#              "steps": [ints]}  ("steps" only for the steps family)

NAMES = ["Anna", "Ben", "Cara", "David", "Eva", "Finn", "Greta", "Henrik"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _rng(*key):
    h = hashlib.sha256(("|".join(str(k) for k in key)).encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def reason_items(session, n, salt=""):
    """Checkable one-answer questions, fresh each session, four kinds."""
    r = _rng("reason", session, salt)
    kinds = ["arith", "order", "days", "remainder"]
    out = []
    for i in range(n):
        kind = kinds[i % len(kinds)]
        if kind == "arith":
            a, b, c = r.randint(3, 19), r.randint(3, 12), r.randint(5, 60)
            q = "What is %d × %d + %d?" % (a, b, c)
            v = a * b + c
            item = {"q": q, "check": {"number": v}, "right": str(v)}
        elif kind == "order":
            people = r.sample(NAMES, 4)            # tallest first
            pairs = [(people[j], people[j + 1]) for j in range(3)]
            r.shuffle(pairs)
            facts = " ".join("%s is taller than %s." % p for p in pairs)
            ask = r.choice(["tallest", "shortest"])
            who = people[0] if ask == "tallest" else people[-1]
            item = {"q": "%s Who is the %s?" % (facts, ask),
                    "check": {"name": who, "among": people}, "right": who}
        elif kind == "days":
            d0, k = r.randrange(7), r.randint(8, 40)
            who = DAYS[(d0 + k) % 7]
            item = {"q": "If today is %s, what day of the week will it be in %d days?"
                         % (DAYS[d0], k),
                    "check": {"name": who, "among": DAYS}, "right": who}
        else:
            a, b = r.randint(20, 99), r.randint(3, 9)
            v = a % b
            item = {"q": "What is the remainder when %d is divided by %d?" % (a, b),
                    "check": {"number": v}, "right": str(v)}
        item.update(family="reason", kind=kind, id="s%d.reason.%d" % (session, i))
        out.append(item)
    return out


def steps_items(session, n, salt=""):
    """Word problems of two or three steps; every intermediate number is
    known, so the steps can be checked as well as the answer."""
    r = _rng("steps", session, salt)
    out = []
    for i in range(n):
        kind = ["shop", "coins", "bus"][i % 3]
        if kind == "shop":
            have, sold, boxes, per = r.randint(20, 60), r.randint(3, 19), r.randint(2, 5), r.randint(6, 12)
            s1 = have - sold
            s2 = boxes * per
            v = s1 + s2
            q = ("A shop has %d apples. It sells %d, then gets %d boxes with %d "
                 "apples in each. How many apples does it have now?" % (have, sold, boxes, per))
            st = [s1, s2, v]
        elif kind == "coins":
            a, b = r.randint(2, 9), r.randint(2, 9)
            s1, s2 = a * 20, b * 50
            v = s1 + s2
            q = ("Tom has %d coins worth 20 cents each and %d coins worth 50 cents "
                 "each. How many cents does he have in all?" % (a, b))
            st = [s1, s2, v]
        else:
            start, off, on = r.randint(15, 40), r.randint(2, 12), r.randint(2, 12)
            s1 = start - off
            v = s1 + on
            mult = r.randint(2, 3)
            v2 = v * mult
            q = ("A bus has %d people. At the first stop %d get off and %d get on. "
                 "A second bus carries %d times as many people as the first bus now "
                 "has. How many people are on the second bus?" % (start, off, on, mult))
            st = [s1, v, v2]
            v = v2
        out.append({"family": "steps", "kind": kind, "id": "s%d.steps.%d" % (session, i),
                    "q": q, "check": {"number": v}, "right": str(v), "steps": st})
    return out


def luke_items(session, n, key=None):
    """Recall from the Gospel of Luke - the training program's key
    (logic/training.LUKE_KEY), so both measure the same facts. The same 40
    facts recur: here a note CAN carry the answer, and that is the point -
    does she keep what she wrote down?"""
    if key is None:
        from logic.training import LUKE_KEY as key
    r = _rng("luke", session)
    picks = r.sample(list(key), min(n, len(key)))
    out = []
    for tid, ref, says, need, answer in picks:
        out.append({"family": "luke", "kind": "luke", "id": "s%d.%s" % (session, tid),
                    "fact": tid, "q": says[session % len(says)],
                    "check": {"any": [w.lower() for w in need]},
                    "right": "%s (%s)" % (answer, ref)})
    return out


# ---------------------------------------------------------------- scoring

_NUM = re.compile(r"-?\d[\d,]*")


def answer_part(reply):
    """The text after the last 'Answer:', else the reply's last non-empty
    line (where an untagged answer usually ends up)."""
    text = reply or ""
    k = text.lower().rfind(ANSWER_TAG.lower())
    if k >= 0:
        return text[k + len(ANSWER_TAG):]
    lines = [l for l in text.split("\n") if l.strip()]
    return lines[-1] if lines else ""


def numbers_in(text):
    out = []
    for m in _NUM.findall(text or ""):
        try:
            out.append(int(m.replace(",", "")))
        except ValueError:
            pass
    return out


def score(item, reply):
    """True / False. Deterministic: no judgement by any model."""
    chk = item["check"]
    part = answer_part(reply)
    if "number" in chk:
        tagged = ANSWER_TAG.lower() in (reply or "").lower()
        nums = numbers_in(part)
        if not nums:
            return False
        # with a tag: the first number after it; without: the last one said
        return (nums[0] if tagged else nums[-1]) == chk["number"]
    if "name" in chk:
        low = part.lower()
        said = {c for c in chk["among"] if re.search(r"\b%s\b" % re.escape(c.lower()), low)}
        return said == {chk["name"]}
    if "any" in chk:
        low = (reply or "").lower()
        if re.search(r"\b(i don't know|i do not know|not sure)\b", low):
            return any(w in part.lower() for w in chk["any"])
        return any(w in low for w in chk["any"])
    return False


def steps_found(item, reply):
    """How many of the item's intermediate numbers appear in the reply."""
    have = set(numbers_in(reply))
    return sum(1 for s in item.get("steps", []) if s in have)


def mcnemar_p(b, c):
    """Exact two-sided McNemar (binomial on the discordant pairs)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * p)


# ---------------------------------------------------------------- notebook

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset("the a an and or of to in on is are was were it its this that "
                  "for with as at by be you your what who how which when will "
                  "next time answer question questions".split())


def words(text):
    return {w for w in _WORD.findall((text or "").lower()) if len(w) > 2 and w not in _STOP}


class Notebook:
    """Her notes, one file, per family. Nothing in it is written by the
    harness except the bookkeeping beside each note."""

    def __init__(self, path):
        self.path = path
        self.notes = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.notes = json.load(f).get("notes", {})

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"notes": self.notes}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def pick(self, family, question, n=NOTES_SHOWN):
        """The notes for this question: most shared words first, then newest."""
        notes = list(self.notes.get(family, []))
        qw = words(question)
        notes.sort(key=lambda x: (len(qw & words(x["text"])), x["session"]), reverse=True)
        return notes[:n]

    def add(self, family, text, session, item_id):
        lst = self.notes.setdefault(family, [])
        lst.append({"text": text, "session": session, "from": item_id})
        dropped = []
        while len(lst) > NOTES_KEPT:
            dropped.append(lst.pop(0))
        return dropped


def clean_note(text):
    from logic.token_budget import sanitize_model_output
    t, _ = sanitize_model_output(text or "")
    t = t.strip().split("\n")[0].strip().strip('"').strip()
    return t[:NOTE_MAX_CHARS]


# ---------------------------------------------------------------- the model

class Stopped(Exception):
    """A training run or the brake came on: stop where we are."""


def _get_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def unit_busy():
    """None, or why the harness must not call the model now."""
    try:
        if (_get_json(PROXY + "/aetherseed/brake").get("brake") or {}).get("on"):
            return "the steward's brake is on"
    except Exception:
        pass
    try:
        if _get_json(PROXY + "/aetherseed/training").get("status") == "running":
            return "a training run is on"
    except Exception:
        pass
    return None


class Model:
    def __init__(self, name, counter=None, busy=unit_busy):
        from logic.token_budget import MODELS, TokenCounter
        self.name = name
        self.counter = counter or TokenCounter(model=name)
        self.ceiling = MODELS[name]["ceiling"]
        self.busy = busy

    def fits(self, messages):
        from logic.token_budget import SAFETY_MARGIN
        return self.counter.count_messages(messages) <= self.ceiling - SAFETY_MARGIN

    def chat(self, messages, num_predict, stop_at_answer=True):
        """(reply, how it ended, seconds)."""
        from logic.token_budget import sanitize_model_output
        why = self.busy()
        if why:
            raise Stopped(why)
        if not self.fits(messages):
            raise ValueError("prompt over the ceiling")       # callers fit first
        data = json.dumps({"model": self.name, "messages": messages, "stream": True,
                           "options": {"num_predict": num_predict}}).encode()
        req = urllib.request.Request(HAILO + "/api/chat", data=data, method="POST",
                                     headers={"Content-Type": "application/json"})
        t0 = time.monotonic()
        text, ended = "", "done"
        with urllib.request.urlopen(req, timeout=300) as resp:
            for raw in resp:
                try:
                    d = json.loads(raw)
                except Exception:
                    continue
                part, n = sanitize_model_output((d.get("message") or {}).get("content") or "")
                text += part
                if n:
                    ended = "control-token"
                    break
                if d.get("done"):
                    ended = d.get("done_reason") or "done"
                    break
                if stop_at_answer and re.search(r"answer:[^\n]*\S[^\n]*\n", text, re.I):
                    ended = "answer-line"
                    break
                if time.monotonic() - t0 > MAX_SECONDS:
                    ended = "time"
                    break
        return text.strip(), ended, round(time.monotonic() - t0, 1)


# ---------------------------------------------------------------- a session

def build_prompt(model, item, notes):
    """System + question; notes are dropped (fewest-matching last in the list
    goes first) until the prompt fits. Returns (messages, notes used)."""
    notes = list(notes)
    while True:
        system = SYSTEM[item["family"]]
        if notes:
            system += "\n\n" + NOTEBOOK_HEAD + "\n" + "\n".join("- " + n["text"] for n in notes)
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": item["q"]}]
        if model.fits(msgs) or not notes:
            return msgs, notes
        notes.pop()


def run_session(model, notebook, session, log, items=None, sizes=ITEMS):
    """One session. log(record) is called with every call's full record."""
    if items is None:
        items = (reason_items(session, sizes["reason"]) + steps_items(session, sizes["steps"])
                 + luke_items(session, sizes["luke"]))
    results = []
    for it in items:
        rec = {"id": it["id"], "family": it["family"], "kind": it["kind"], "q": it["q"],
               "right": it["right"]}
        # arm B first, then A: the order is the same for every item
        msgs_b, _ = build_prompt(model, it, [])
        reply_b, end_b, sec_b = model.chat(msgs_b, NUM_PREDICT[it["family"]])
        rec["blank"] = {"prompt": msgs_b, "reply": reply_b, "ended": end_b, "secs": sec_b,
                        "ok": score(it, reply_b)}
        notes = notebook.pick(it["family"], it["q"])
        msgs_a, used = build_prompt(model, it, notes)
        reply_a, end_a, sec_a = model.chat(msgs_a, NUM_PREDICT[it["family"]])
        rec["notebook"] = {"prompt": msgs_a, "reply": reply_a, "ended": end_a, "secs": sec_a,
                           "ok": score(it, reply_a), "notes": [n["text"] for n in used]}
        if it["family"] == "steps":
            rec["blank"]["steps"] = steps_found(it, reply_b)
            rec["notebook"]["steps"] = steps_found(it, reply_a)
            rec["n_steps"] = len(it["steps"])
        # reflection, arm A, no outside signal
        msgs_r = msgs_a + [{"role": "assistant", "content": reply_a},
                           {"role": "user", "content": REFLECT_ASK}]
        if model.fits(msgs_r):
            reply_r, end_r, sec_r = model.chat(msgs_r, NUM_PREDICT["reflect"])
            rec["reflect"] = {"reply": reply_r, "ended": end_r, "secs": sec_r,
                              "ok": score(it, reply_r)}
        else:
            rec["reflect"] = {"skipped": "prompt over the ceiling"}
        log(rec)
        results.append((it, rec))

    # notes, from what is still wrong after reflection
    written = []
    for fam in ("reason", "steps", "luke"):
        wrong = [(it, rec) for it, rec in results if it["family"] == fam
                 and not rec["reflect"].get("ok", rec["notebook"]["ok"])]
        for it, rec in wrong[:NOTES_PER_SESSION]:
            ask = NOTE_ASK.format(q=it["q"], a=answer_part(rec["notebook"]["reply"]).strip()[:200]
                                  or rec["notebook"]["reply"][:200], right=it["right"])
            msgs_n = [{"role": "user", "content": ask}]
            if not model.fits(msgs_n):
                continue
            reply_n, end_n, sec_n = model.chat(msgs_n, NUM_PREDICT["note"], stop_at_answer=False)
            note = clean_note(reply_n)
            entry = {"note_for": it["id"], "family": fam, "prompt": msgs_n, "reply": reply_n,
                     "ended": end_n, "secs": sec_n, "kept": note}
            if note:
                entry["dropped"] = [d["text"] for d in notebook.add(fam, note, session, it["id"])]
                written.append(note)
            log(entry)
    notebook.save()
    return results, written


# ---------------------------------------------------------------- report

def read_sessions(d):
    out = {}
    sd = os.path.join(d, "sessions")
    if not os.path.isdir(sd):
        return out
    for name in sorted(os.listdir(sd)):
        m = re.match(r"(\d+)\.jsonl$", name)
        if not m:
            continue
        with open(os.path.join(sd, name), encoding="utf-8") as f:
            out[int(m.group(1))] = [json.loads(l) for l in f if l.strip()]
    return out


def summarise(recs):
    s = {}
    for r in recs:
        if "notebook" not in r:
            continue
        f = s.setdefault(r["family"], {"n": 0, "a": 0, "b": 0, "ab": 0, "ba": 0,
                                       "w2r": 0, "r2w": 0, "refl": 0,
                                       "steps_a": 0, "steps_b": 0, "steps_n": 0})
        a, b = r["notebook"]["ok"], r["blank"]["ok"]
        f["n"] += 1
        f["a"] += a
        f["b"] += b
        f["ab"] += a and not b
        f["ba"] += b and not a
        if "ok" in r.get("reflect", {}):
            f["refl"] += 1
            f["w2r"] += (not a) and r["reflect"]["ok"]
            f["r2w"] += a and not r["reflect"]["ok"]
        if "n_steps" in r:
            f["steps_a"] += r["notebook"]["steps"]
            f["steps_b"] += r["blank"]["steps"]
            f["steps_n"] += r["n_steps"]
    return s


def report(d):
    sessions = read_sessions(d)
    meta = {}
    mp = os.path.join(d, "meta.json")
    if os.path.exists(mp):
        with open(mp, encoding="utf-8") as f:
            meta = json.load(f)
    lines = ["COG-loop report - %s" % d,
             "model: %s   unit: %s" % (meta.get("model", "?"), meta.get("unit", "?")),
             "A = with her notebook, B = blank (control). Same items in both.", ""]
    total = {}
    for sn in sorted(sessions):
        recs = sessions[sn]
        notes = sum(1 for r in recs if r.get("kept"))
        lines.append("Session %d  (%d notes written)" % (sn, notes))
        for fam, f in sorted(summarise(recs).items()):
            t = total.setdefault(fam, {"n": 0, "ab": 0, "ba": 0, "a": 0, "b": 0})
            for k in t:
                t[k] += f[k]
            row = "  %-7s A %d/%d  B %d/%d  A-B %+d" % (fam, f["a"], f["n"], f["b"], f["n"],
                                                       f["a"] - f["b"])
            if f["refl"]:
                row += "   reflect: wrong->right %d, right->wrong %d" % (f["w2r"], f["r2w"])
            if f["steps_n"]:
                row += "   steps found A %d/%d B %d/%d" % (f["steps_a"], f["steps_n"],
                                                          f["steps_b"], f["steps_n"])
            lines.append(row)
        lines.append("")
    if total:
        lines.append("All sessions (paired, exact McNemar on items where A and B differ):")
        for fam, t in sorted(total.items()):
            lines.append("  %-7s A %d/%d  B %d/%d   A only right %d, B only right %d, p = %.3f"
                         % (fam, t["a"], t["n"], t["b"], t["n"], t["ab"], t["ba"],
                            mcnemar_p(t["ab"], t["ba"])))
        lines.append("")
        lines.append("Read with care: sampling is not greedy (temperature 0.4), so the same "
                     "prompt can answer differently; a p above 0.05 means the difference "
                     "could be chance. Learning across sessions shows as A-B rising "
                     "session by session, not as one good session.")
    nb = Notebook(os.path.join(d, "notebook.json"))
    lines.append("")
    lines.append("Her notebook now:")
    for fam, lst in sorted(nb.notes.items()):
        for n in lst:
            lines.append("  [%s, s%d] %s" % (fam, n["session"], n["text"]))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", help="the harness's own directory (notebook, sessions)")
    ap.add_argument("--sessions", type=int, default=1)
    ap.add_argument("--model", default=None, help="default: the model this unit serves")
    ap.add_argument("--report", metavar="DIR")
    a = ap.parse_args(argv)
    if a.report:
        sys.stdout.write(report(a.report))
        return 0
    if not a.dir:
        ap.error("--dir is required")
    os.makedirs(os.path.join(a.dir, "sessions"), exist_ok=True)
    why = unit_busy()
    if why:
        print("not starting: %s" % why, file=sys.stderr)
        return 1
    if a.model is None:
        from logic import served
        a.model = served.served_model()
    model = Model(a.model)
    mp = os.path.join(a.dir, "meta.json")
    meta = {}
    if os.path.exists(mp):
        with open(mp, encoding="utf-8") as f:
            meta = json.load(f)
    if meta.get("model") and meta["model"] != a.model:
        print("this directory's notebook is %s's, not %s's - use another --dir"
              % (meta["model"], a.model), file=sys.stderr)
        return 1
    meta.update(model=a.model, unit=os.uname().nodename)
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    notebook = Notebook(os.path.join(a.dir, "notebook.json"))
    done = read_sessions(a.dir)
    first = (max(done) + 1) if done else 1
    for sn in range(first, first + a.sessions):
        if os.path.exists(os.path.join(a.dir, "STOP")):
            print("STOP file: ending before session %d" % sn)
            break
        path = os.path.join(a.dir, "sessions", "%03d.jsonl" % sn)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with open(path, "a", encoding="utf-8") as f:
            def log(rec, f=f):
                rec = dict(rec, at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
            log({"session": sn, "started": stamp, "model": a.model})
            try:
                run_session(model, notebook, sn, log)
            except Stopped as e:
                log({"stopped": str(e)})
                print("stopped in session %d: %s" % (sn, e))
                notebook.save()
                break
        print("session %d done" % sn, flush=True)
    rep = report(a.dir)
    with open(os.path.join(a.dir, "report.txt"), "w", encoding="utf-8") as f:
        f.write(rep)
    sys.stdout.write(rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
