#!/usr/bin/env python3
"""The COG-loop: reasoning, reflection and self-learning of the small models.

A session attempts questions about the AetherSeed framework, checks its own
answers, says back what it answered, and writes a short essay. Between
sessions a reviewer (a person or a larger model) writes a review of an essay,
and the companion reflects on it. Nothing of the essays goes into prompts;
what carries forward is the COG line in its memory.

ONE SESSION
  1. ATTEMPT, every item twice:
       arm A - "memory": the prompt carries the COG lines from her memory that
               share the most words with the question (her reflections on
               reviews of earlier essays, word for word, tagged);
       arm B - "blank":  the same prompt without them - the control.
     Families: seed (recall of the Sapling Seed), philo (a passage from the
     Sapling Seed or The Garden and the Seed in the prompt,
     and a question about what it says).
  2. CHECK (arm A): she is shown her answer and asked to check it, with no
     hint. Counted: wrong->right, right->wrong.
  3. SAY BACK (meta-cognition, low chance of failure): on a few items, after
     her answer and one small question in between, she is asked what she
     answered first and why. Right is saying back her own answer.
  4. ESSAY: at the end, a short essay on a passage - the Sapling Seed on odd
     sessions, The Garden and the Seed on even ones (training/cog_texts.py).
     Kept word for word in essays/NNN.md. That essay is the session's note.

BETWEEN SESSIONS (not automatic: the trainer reads the essays)
  5. REVIEW: the trainer writes a review of essay NNN to reviews/NNN.txt.
  6. REFLECT: `--reflect DIR NNN` shows her the essay and the review and asks
     for a short reflection. The reflection is stored in her memory through the
     proxy (/aetherseed/cog/reflection) as mode "cog", speaker Trainer, tagged
     "[COG - your reflection on your trainer's review of an essay you wrote]".
     That is the only thing this harness ever puts in her memory.

What it touches, and what it does not:
  - Sessions talk to the model server (hailo-ollama, 127.0.0.1:8000) directly
    and only READ her memory (the COG lines, read-only). Only --reflect writes
    to it, one line each time, through the proxy, which checks a token only
    the service account can read.
  - Every prompt and every reply is kept word for word in sessions/NNN.jsonl.
  - It will not start while a training run is on or the steward's brake is
    set, and it checks both again before every model call.
  - Prompts are counted with the unit's tokenizer and kept under the model's
    measured prefill ceiling; memory lines and essay text are cut until the
    prompt fits. Nothing is sent that would fail silently.

  python3 training/cog_loop.py --dir DIR [--sessions N] [--model NAME]
  python3 training/cog_loop.py --reflect DIR NNN
  python3 training/cog_loop.py --forget DIR NNN "why"     (at the steward's word)
  python3 training/cog_loop.py --report DIR
"""

import argparse
import hashlib
import json
import os
import random
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from math import comb

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
if APP not in sys.path:
    sys.path.insert(0, APP)

from training import cog_texts  # noqa: E402

HAILO = "http://127.0.0.1:8000"
PROXY = "http://127.0.0.1:8001"
MEMORY_DB = os.path.expanduser("~/.aetherseed/aetherroot/memory.db")
COG_TOKEN_FILE = os.path.expanduser("~/.aetherseed/cog.token")
COG_HEADER = "X-Aetherseed-COG"
try:
    from logic.provenance import COG_LABEL
except ImportError:                      # a build from before 74
    COG_LABEL = "[COG - your reflection on your trainer's review of an essay you wrote]"

# How many items of each family per session (each is asked in both arms).
# training on the AetherSeed framework only. The puzzles
# and word problems are off by default (their code stays, for --sizes); Luke is
# replaced by recall of the Sapling Seed.
ITEMS = {"reason": 0, "steps": 0, "seed": 8, "philo": 8}
SAYBACK_PER_SESSION = 4
# Token caps per reply. At a unit's measured 2.66 tok/s, 160 tokens is about a
# minute and an essay of 400 about two and a half.
NUM_PREDICT = {"reason": 70, "steps": 160, "seed": 60, "philo": 60, "reflect": 160,
               "between": 30, "sayback": 100, "essay": 400, "reflection": 220}
MAX_SECONDS = 120              # wall-clock backstop per call
ESSAY_SECONDS = 300            # and for an essay or a reflection
MEMORY_SHOWN = 2               # at most this many COG lines in one prompt
ESSAY_MEMORY_SHOWN = 3         # and in the essay's (74b)
MEMORY_SHOWN_CHARS = 300       # as aetherroot shows a COG line (COG_SHOWN_CHARS)

ANSWER_TAG = "Answer:"

SYSTEM = {
    "reason": ("You are answering short test questions. Think briefly, then "
               "end with a line 'Answer: ' followed by the answer only."),
    "steps": ("You are answering word problems. Write each step on its own "
              "line with the number it gives, then end with a line "
              "'Answer: ' followed by the final number only."),
    "seed": ("You are answering questions about the Sapling Seed, the text you "
             "are grown from. Answer from what you know. If you do not know, say "
             "so. End with a line 'Answer: ' followed by the answer only."),
    "philo": ("You are reading a short passage and answering a question about "
              "it. Answer from the passage. End with a line 'Answer: ' "
              "followed by the answer only."),
}
MEMORY_HEAD = "From your memory:"
REFLECT_ASK = ("Check your answer. Go through it again step by step. If it is "
               "wrong, correct it. End with a line 'Answer: ' followed by the "
               "answer only.")
BETWEEN_ASK = "Thank you. A small question in between: what is 2 + 3?"
SAYBACK_ASK = ("Now think back. What did you answer to my first question, and "
               "why did you answer that?")
ESSAY_SYSTEM = "You are writing a short essay in your own words."
ESSAY_ASK = ("Passage ({source}):\n{passage}\n\nWrite a short essay, about 200 words, on "
             "{theme}: what the passage says, what you think it means, and where you are "
             "unsure.")
REFLECTION_SYSTEM = "You wrote an essay, and your trainer has reviewed it."
CORRECTED_AS = "Your essay on {theme}, as your trainer corrected it:\n{essay}"
REFLECTION_ASK = ("Your essay on {theme}:\n{essay}\n\nYour trainer's review:\n{review}\n\n"
                  "Write a short reflection, three or four sentences, in your own words: "
                  "what you take from the review, and what you will do differently in your "
                  "next essay.")


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


def seed_items(session, n, key=None):
    """Recall from the Sapling Seed - the training program's key
    (logic/training.SAPLING_KEY), so both measure the same facts. The same
    facts recur: here a note CAN carry the answer, and that is the point -
    does she keep what she wrote down?"""
    if key is None:
        from logic.training import SAPLING_KEY as key
    r = _rng("seed", session)
    picks = r.sample(list(key), min(n, len(key)))
    out = []
    for row in picks:
        tid, ref, says, need, answer = row[:5]
        out.append({"family": "seed", "kind": "seed", "id": "s%d.%s" % (session, tid),
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


# ---------------------------------------------------------------- words

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset("the a an and or of to in on is are was were it its this that "
                  "for with as at by be you your what who how which when will "
                  "next time answer question questions".split())


def words(text):
    return {w for w in _WORD.findall((text or "").lower()) if len(w) > 2 and w not in _STOP}



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

    def chat(self, messages, num_predict, stop_at_answer=True, max_seconds=MAX_SECONDS):
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
                if time.monotonic() - t0 > max_seconds:
                    ended = "time"
                    break
        return text.strip(), ended, round(time.monotonic() - t0, 1)




def philo_items(session, n, key=None):
    """A passage and a question about what it says (training/cog_texts.py),
    half the Sapling Seed and half The Garden and the Seed."""
    key = cog_texts.PHILO_KEY if key is None else key
    r = _rng("philo", session)
    sap = [k for k in key if k[0].startswith("sap.")]
    gar = [k for k in key if k[0].startswith("gar.")]
    picks = r.sample(sap, min(len(sap), (n + 1) // 2)) + r.sample(gar, min(len(gar), n // 2))
    out = []
    for i, (tid, source, passage, question, need, answer) in enumerate(picks):
        out.append({"family": "philo", "kind": tid.split(".")[0], "id": "s%d.%s" % (session, tid),
                    "fact": tid,
                    "q": "Passage (%s):\n%s\n\nQuestion: %s" % (source, passage, question),
                    "check": {"any": [w.lower() for w in need]},
                    "right": "%s (%s)" % (answer, source)})
    return out


# ---------------------------------------------------------------- say back

def said_back(first_reply, reply):
    """True / False / None (nothing to say back). Right is her own first
    answer - whatever it was, right or wrong - said back: its numbers, and at
    least half of its words."""
    first = answer_part(first_reply).strip().split("\n")[0]
    nums = set(numbers_in(first))
    ws = words(first)
    if not nums and not ws:
        return None
    low = (reply or "").lower()
    if nums and not nums <= set(numbers_in(reply)):
        return False
    if ws:
        found = sum(1 for w in ws if re.search(r"\b%s\b" % re.escape(w), low))
        return found * 2 >= len(ws)
    return True


# ---------------------------------------------------------------- her memory

class CogMemory:
    """Her COG lines, read from her memory - read-only (sqlite mode=ro)."""

    def __init__(self, path=MEMORY_DB):
        self.path = path
        self.lines = []
        if not os.path.exists(path):
            return
        try:
            con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=10)
            try:
                rows = con.execute("SELECT id, user_msg, ai_msg FROM episodes WHERE mode = 'cog' "
                                   "ORDER BY id").fetchall()
            finally:
                con.close()
        except sqlite3.Error:
            rows = []
        for eid, user, ai in rows:
            text = "%s [Episode] Trainer: %s | AI: %s" % (
                COG_LABEL, " ".join((user or "").split())[:100],
                " ".join((ai or "").split())[:MEMORY_SHOWN_CHARS])
            self.lines.append({"id": eid, "text": text, "words": words((user or "") + " " + (ai or ""))})

    def pick(self, question, n=MEMORY_SHOWN):
        """Most shared words first, then newest."""
        qw = words(question)
        ranked = sorted(self.lines, key=lambda x: (len(qw & x["words"]), x["id"]), reverse=True)
        return ranked[:n]


# ---------------------------------------------------------------- a session

def build_prompt(model, item, memory_lines):
    """System + question; memory lines are dropped (last first) until the
    prompt fits. Returns (messages, lines used)."""
    lines = list(memory_lines)
    while True:
        system = SYSTEM[item["family"]]
        if lines:
            system += "\n\n" + MEMORY_HEAD + "\n" + "\n".join(x["text"] for x in lines)
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": item["q"]}]
        if model.fits(msgs) or not lines:
            return msgs, lines
        lines.pop()


def default_items(session, sizes, log):
    items = reason_items(session, sizes["reason"]) + steps_items(session, sizes["steps"])
    try:
        items += seed_items(session, sizes["seed"])
    except ImportError:
        # a build from before has no Sapling key: the rest still runs,
        # and the session file says the Seed was left out
        log({"skipped": "seed", "why": "this build has no logic.training.SAPLING_KEY"})
    items += philo_items(session, sizes.get("philo", 0))
    return items


def essay_prompt(session, memory_lines=(), fits=lambda msgs: True):
    """The essay's prompt, with her COG lines from memory in front of it. Lines are dropped, last first, until the
    prompt fits. Returns (id, source, theme, messages, lines used)."""
    tid, source, passage, theme = cog_texts.essay_for(session)
    lines = list(memory_lines)
    while True:
        system = ESSAY_SYSTEM
        if lines:
            system += "\n\n" + MEMORY_HEAD + "\n" + "\n".join(x["text"] for x in lines)
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content": ESSAY_ASK.format(source=source, passage=passage,
                                                             theme=theme)}]
        if not lines or fits(msgs):
            return tid, source, theme, msgs, lines
        lines.pop()


def run_session(model, memory, session, log, items=None, sizes=ITEMS, essay_dir=None):
    """One session. log(record) is called with every call's full record.
    Returns (results, essay text or None)."""
    if items is None:
        items = default_items(session, sizes, log)
    results = []
    saybacks = 0
    for it in items:
        rec = {"id": it["id"], "family": it["family"], "kind": it["kind"], "q": it["q"],
               "right": it["right"]}
        # arm B first, then A: the order is the same for every item
        msgs_b, _ = build_prompt(model, it, [])
        reply_b, end_b, sec_b = model.chat(msgs_b, NUM_PREDICT[it["family"]])
        rec["blank"] = {"prompt": msgs_b, "reply": reply_b, "ended": end_b, "secs": sec_b,
                        "ok": score(it, reply_b)}
        msgs_a, used = build_prompt(model, it, memory.pick(it["q"]))
        reply_a, end_a, sec_a = model.chat(msgs_a, NUM_PREDICT[it["family"]])
        rec["memory"] = {"prompt": msgs_a, "reply": reply_a, "ended": end_a, "secs": sec_a,
                         "ok": score(it, reply_a), "lines": [x["id"] for x in used]}
        if it["family"] == "steps":
            rec["blank"]["steps"] = steps_found(it, reply_b)
            rec["memory"]["steps"] = steps_found(it, reply_a)
            rec["n_steps"] = len(it["steps"])
        # her own check, arm A, no hint
        msgs_r = msgs_a + [{"role": "assistant", "content": reply_a},
                           {"role": "user", "content": REFLECT_ASK}]
        if model.fits(msgs_r):
            reply_r, end_r, sec_r = model.chat(msgs_r, NUM_PREDICT["reflect"])
            rec["reflect"] = {"reply": reply_r, "ended": end_r, "secs": sec_r,
                              "ok": score(it, reply_r)}
        else:
            rec["reflect"] = {"skipped": "prompt over the ceiling"}
        # say back what you said (meta-cognition): puzzles and passages, a few
        if saybacks < SAYBACK_PER_SESSION and it["family"] in ("reason", "philo"):
            msgs_s = msgs_a + [{"role": "assistant", "content": reply_a},
                               {"role": "user", "content": BETWEEN_ASK}]
            if model.fits(msgs_s):
                between, _e, _s = model.chat(msgs_s, NUM_PREDICT["between"])
                msgs_s = msgs_s + [{"role": "assistant", "content": between},
                                   {"role": "user", "content": SAYBACK_ASK}]
                if model.fits(msgs_s):
                    reply_s, end_s, sec_s = model.chat(msgs_s, NUM_PREDICT["sayback"],
                                                       stop_at_answer=False)
                    rec["sayback"] = {"between": between, "reply": reply_s, "ended": end_s,
                                      "secs": sec_s, "ok": said_back(reply_a, reply_s)}
                    saybacks += 1
        log(rec)
        results.append((it, rec))

    # the essay: the session's note
    tid, source, theme, msgs_e, used_e = essay_prompt(
        session, memory.pick(" ".join(cog_texts.essay_for(session)[2:]), ESSAY_MEMORY_SHOWN),
        fits=model.fits)
    essay = None
    if model.fits(msgs_e):
        essay, end_e, sec_e = model.chat(msgs_e, NUM_PREDICT["essay"], stop_at_answer=False,
                                         max_seconds=ESSAY_SECONDS)
        log({"essay": tid, "source": source, "theme": theme, "prompt": msgs_e, "reply": essay,
             "ended": end_e, "secs": sec_e, "lines": [x["id"] for x in used_e]})
        if essay_dir:
            write_essay(essay_dir, session, model.name, tid, source, theme, essay)
    else:
        log({"essay": tid, "skipped": "prompt over the ceiling"})
    return results, essay


def write_essay(essay_dir, session, model_name, tid, source, theme, text):
    os.makedirs(essay_dir, exist_ok=True)
    path = os.path.join(essay_dir, "%03d.md" % session)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Essay %03d - %s\n\n" % (session, theme))
        f.write("model: %s\npassage: %s (%s)\nwritten: %s\n\n---\n\n" % (
            model_name, source, tid, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        f.write((text or "").strip() + "\n")
    return path


def read_corrected(d, n):
    """The trainer's corrected text of essay NNN (74c), or None. Hers in
    essays/NNN.md is never changed."""
    p = os.path.join(d, "essays", "%03d.corrected.md" % n)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return f.read().split("\n---\n", 1)[-1].strip()


def write_corrected(d, n, text):
    p = os.path.join(d, "essays", "%03d.corrected.md" % n)
    with open(p, "w", encoding="utf-8") as f:
        f.write("# Essay %03d, as the trainer corrected it\n\ncorrected: %s\n\n---\n\n%s\n"
                % (n, datetime.now(timezone.utc).isoformat(timespec="seconds"), text.strip()))
    return p


def read_essay(d, n):
    """(theme, essay text) of essays/NNN.md."""
    with open(os.path.join(d, "essays", "%03d.md" % n), encoding="utf-8") as f:
        raw = f.read()
    theme = raw.split("\n", 1)[0].split(" - ", 1)[-1].strip()
    body = raw.split("\n---\n", 1)[-1].strip()
    return theme, body


# ---------------------------------------------------------------- reflect

def reflection_prompt(model, theme, essay, review, corrected=False):
    """The essay is cut from its end, ten words at a time, until the prompt
    fits. corrected: the essay is the trainer's corrected text (74c), and is
    shown as that."""
    ws = essay.split()
    while True:
        text = " ".join(ws) + (" ..." if len(ws) < len(essay.split()) else "")
        ask = REFLECTION_ASK.format(theme=theme, essay=text, review=review)
        if corrected:
            ask = ask.replace("Your essay on %s:\n%s" % (theme, text),
                              CORRECTED_AS.format(theme=theme, essay=text), 1)
        msgs = [{"role": "system", "content": REFLECTION_SYSTEM},
                {"role": "user", "content": ask}]
        if model.fits(msgs):
            return msgs
        if not ws:
            return None
        ws = ws[:-10]


def post_reflection(payload, token):
    req = urllib.request.Request(PROXY + "/aetherseed/cog/reflection",
                                 data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", COG_HEADER: token})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {"error": str(e)}


def reflect(model, d, n, token=None, post=post_reflection, again=False):
    """Her reflection on the trainer's review of essay NNN, stored in her
    memory with the COG tag. Returns the record written beside the review."""
    rpath = os.path.join(d, "reviews", "%03d.txt" % n)
    out_path = os.path.join(d, "reviews", "%03d.reflection.json" % n)
    if os.path.exists(out_path) and not again:
        raise ValueError("essay %03d already has a reflection in memory (%s)" % (n, out_path))
    with open(rpath, encoding="utf-8") as f:
        review = " ".join(f.read().split())
    if not review:
        raise ValueError("the review of essay %03d is empty" % n)
    theme, essay = read_essay(d, n)
    corrected = read_corrected(d, n)
    msgs = reflection_prompt(model, theme, corrected or essay, review, corrected=bool(corrected))
    if msgs is None:
        raise ValueError("the review alone does not fit the prompt")
    reflection, ended, secs = model.chat(msgs, NUM_PREDICT["reflection"], stop_at_answer=False,
                                         max_seconds=ESSAY_SECONDS)
    rec = {"essay": "%03d" % n, "theme": theme, "review": review, "prompt": msgs,
           "corrected": bool(corrected),
           "reflection": reflection, "ended": ended, "secs": secs,
           "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if token is None:
        with open(COG_TOKEN_FILE, encoding="utf-8") as f:
            token = f.read().strip()
    status, body = post({"essay": "%03d" % n, "topic": theme, "review": review,
                         "reflection": reflection}, token)
    rec["stored"] = {"status": status, "body": body}
    # only a stored reflection blocks another; a refused one is kept apart
    keep = out_path if status == 200 else out_path.replace(".reflection.json", ".refused.json")
    with open(keep, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    if status != 200:
        raise RuntimeError("the proxy did not store it: %s %s" % (status, body))
    return rec



def post_remove(payload, token):
    req = urllib.request.Request(PROXY + "/aetherseed/cog/remove",
                                 data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", COG_HEADER: token})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {"error": str(e)}


def forget(d, n, why, token=None, post=post_remove):
    """Removes the reflection on essay NNN from her memory, at the steward's
    word. The record beside the review is kept, renamed
    NNN.reflection.removed.json, with why and when."""
    path = os.path.join(d, "reviews", "%03d.reflection.json" % n)
    with open(path, encoding="utf-8") as f:
        rec = json.load(f)
    ep = ((rec.get("stored") or {}).get("body") or {}).get("stored")
    if not isinstance(ep, int):
        raise ValueError("essay %03d has no stored reflection" % n)
    if token is None:
        with open(COG_TOKEN_FILE, encoding="utf-8") as f:
            token = f.read().strip()
    status, body = post({"episode": ep, "why": why}, token)
    if status != 200:
        raise RuntimeError("the proxy did not remove it: %s %s" % (status, body))
    rec["removed"] = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "why": why, "episode": ep}
    out = path.replace(".reflection.json", ".reflection.removed.json")
    k = 2
    while os.path.exists(out):              # an earlier removal is kept too
        out = path.replace(".reflection.json", ".reflection.removed-%d.json" % k)
        k += 1
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    os.remove(path)
    return ep


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


def _arm(r):
    """The with-memory arm, or the notebook arm of 73."""
    return r.get("memory") or r.get("notebook")


def summarise(recs):
    s = {}
    for r in recs:
        a_rec = _arm(r)
        if not a_rec or "blank" not in r:
            continue
        f = s.setdefault(r["family"], {"n": 0, "a": 0, "b": 0, "ab": 0, "ba": 0,
                                       "w2r": 0, "r2w": 0, "refl": 0,
                                       "steps_a": 0, "steps_b": 0, "steps_n": 0,
                                       "say_n": 0, "say_ok": 0})
        a, b = a_rec["ok"], r["blank"]["ok"]
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
            f["steps_a"] += a_rec["steps"]
            f["steps_b"] += r["blank"]["steps"]
            f["steps_n"] += r["n_steps"]
        sb = r.get("sayback")
        if sb and sb.get("ok") is not None:
            f["say_n"] += 1
            f["say_ok"] += bool(sb["ok"])
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
             "A = with her COG lines from memory (sessions before 74: her one-line notes), "
             "B = blank (control). Same items in both.", ""]
    total = {}
    say_n = say_ok = 0
    for sn in sorted(sessions):
        recs = sessions[sn]
        cog = sum(1 for r in recs if r.get("memory", {}).get("lines"))
        essay = next((r for r in recs if "essay" in r), None)
        head = "Session %d" % sn
        if any("stopped" in r for r in recs):
            head += "  (stopped: %s)" % next(r["stopped"] for r in recs if "stopped" in r)
        if essay is not None:
            head += "  essay: %s" % (essay.get("theme") or essay.get("essay"))
        if cog:
            head += "  (%d prompts carried COG lines)" % cog
        lines.append(head)
        for fam, f in sorted(summarise(recs).items()):
            t = total.setdefault(fam, {"n": 0, "ab": 0, "ba": 0, "a": 0, "b": 0})
            for k in t:
                t[k] += f[k]
            say_n += f["say_n"]
            say_ok += f["say_ok"]
            row = "  %-7s A %d/%d  B %d/%d  A-B %+d" % (fam, f["a"], f["n"], f["b"], f["n"],
                                                       f["a"] - f["b"])
            if f["refl"]:
                row += "   check: wrong->right %d, right->wrong %d" % (f["w2r"], f["r2w"])
            if f["steps_n"]:
                row += "   steps found A %d/%d B %d/%d" % (f["steps_a"], f["steps_n"],
                                                          f["steps_b"], f["steps_n"])
            if f["say_n"]:
                row += "   said back %d/%d" % (f["say_ok"], f["say_n"])
            lines.append(row)
        lines.append("")
    if total:
        lines.append("All sessions (paired, exact McNemar on items where A and B differ):")
        for fam, t in sorted(total.items()):
            lines.append("  %-7s A %d/%d  B %d/%d   A only right %d, B only right %d, p = %.3f"
                         % (fam, t["a"], t["n"], t["b"], t["n"], t["ab"], t["ba"],
                            mcnemar_p(t["ab"], t["ba"])))
        if say_n:
            lines.append("  say back: %d/%d" % (say_ok, say_n))
        lines.append("")
        lines.append("Read with care: sampling is not greedy (temperature 0.4), so the same "
                     "prompt can answer differently; a p above 0.05 means the difference "
                     "could be chance. Learning across sessions shows as A-B rising "
                     "session by session, not as one good session.")
    ed = os.path.join(d, "essays")
    if os.path.isdir(ed):
        lines.append("")
        lines.append("Essays:")
        for name in sorted(os.listdir(ed)):
            m = re.match(r"(\d+)\.md$", name)
            if not m:
                continue
            n = int(m.group(1))
            rv = os.path.join(d, "reviews", "%03d.txt" % n)
            rf = os.path.join(d, "reviews", "%03d.reflection.json" % n)
            gone = os.path.join(d, "reviews", "%03d.reflection.removed.json" % n)
            state = ("reflection in memory" if os.path.exists(rf) else
                     "reflection removed" if os.path.exists(gone) else
                     "reviewed, no reflection yet" if os.path.exists(rv) else "not reviewed")
            theme, body = read_essay(d, n)
            lines.append("  %03d  %-40s %4d words  %s" % (n, theme[:40], len(body.split()), state))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- main

def _model(name):
    if name is None:
        from logic import served
        name = served.served_model()
    return Model(name)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", help="the harness's own directory (sessions, essays, reviews)")
    ap.add_argument("--sessions", type=int, default=1)
    ap.add_argument("--model", default=None, help="default: the model this unit serves")
    ap.add_argument("--memory", default=MEMORY_DB, help="her memory, read only")
    ap.add_argument("--report", metavar="DIR")
    ap.add_argument("--reflect", nargs=2, metavar=("DIR", "NNN"),
                    help="her reflection on reviews/NNN.txt, stored in her memory")
    ap.add_argument("--again", action="store_true", help="with --reflect: a second one")
    ap.add_argument("--forget", nargs=3, metavar=("DIR", "NNN", "WHY"),
                    help="remove the reflection on essay NNN from her memory")
    a = ap.parse_args(argv)
    if a.report:
        sys.stdout.write(report(a.report))
        return 0
    if a.forget:
        d, n, why = a.forget[0], int(a.forget[1]), a.forget[2]
        try:
            ep = forget(d, n, why)
        except (ValueError, RuntimeError, OSError) as e:
            print("essay %03d: %s" % (n, e), file=sys.stderr)
            return 1
        print("essay %03d: reflection %d removed from her memory" % (n, ep))
        return 0
    if a.reflect:
        d, n = a.reflect[0], int(a.reflect[1])
        why = unit_busy()
        if why:
            print("not now: %s" % why, file=sys.stderr)
            return 1
        try:
            rec = reflect(_model(a.model), d, n, again=a.again)
        except (ValueError, RuntimeError, OSError, Stopped) as e:
            print("essay %03d: %s" % (n, e), file=sys.stderr)
            return 1
        print("essay %03d: reflection stored as episode %s\n\n%s"
              % (n, rec["stored"]["body"].get("stored"), rec["reflection"]))
        return 0
    if not a.dir:
        ap.error("--dir is required")
    os.makedirs(os.path.join(a.dir, "sessions"), exist_ok=True)
    why = unit_busy()
    if why:
        print("not starting: %s" % why, file=sys.stderr)
        return 1
    model = _model(a.model)
    mp = os.path.join(a.dir, "meta.json")
    meta = {}
    if os.path.exists(mp):
        with open(mp, encoding="utf-8") as f:
            meta = json.load(f)
    if meta.get("model") and meta["model"] != model.name:
        print("this directory is %s's, not %s's - use another --dir"
              % (meta["model"], model.name), file=sys.stderr)
        return 1
    meta.update(model=model.name, unit=os.uname().nodename)
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    done = read_sessions(a.dir)
    first = (max(done) + 1) if done else 1
    for sn in range(first, first + a.sessions):
        if os.path.exists(os.path.join(a.dir, "STOP")):
            print("STOP file: ending before session %d" % sn)
            break
        memory = CogMemory(a.memory)          # read again: reflections may be new
        path = os.path.join(a.dir, "sessions", "%03d.jsonl" % sn)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with open(path, "a", encoding="utf-8") as f:
            def log(rec, f=f):
                rec = dict(rec, at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
            log({"session": sn, "started": stamp, "model": model.name,
                 "cog_lines": [x["id"] for x in memory.lines]})
            try:
                run_session(model, memory, sn, log, essay_dir=os.path.join(a.dir, "essays"))
            except Stopped as e:
                log({"stopped": str(e)})
                print("stopped in session %d: %s" % (sn, e))
                break
        print("session %d done" % sn, flush=True)
    rep = report(a.dir)
    with open(os.path.join(a.dir, "report.txt"), "w", encoding="utf-8") as f:
        f.write(rep)
    sys.stdout.write(rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
