"""Training files: the steward's own questions, for her training runs.

 Asked how:
who writes the questions - "Create a how-to, then users can either do it
themselves, or use cloudcompute to create it, then upload into the unit";
and what she keeps - "Answers, not text": the document stays on the shelf,
looked up word for word, and her memory keeps her checked answers (passed,
or corrected with what is true). Part 1 of the review (17 Oct) measured why:
whole texts in her memory crowd out what matters.

THE FILE (docs/TRAINING-FILES.md is the how-to). Plain text, UTF-8:

    title: My garden
    document: Garden notes            (optional: the shelf document it is about)

    Q: When is the cherry tree planted?
    A: On Saturday, by the north wall.
    KEY: saturday; north wall
    NOT: sunday

  - Q is the question as she is asked it; several Q lines are several
    wordings of one question (a round takes one).
  - A is the answer as it is true - what she is told when she is wrong, and
    what her memory keeps as the correction.
  - KEY is what her answer must say: groups separated by ";", every group
    needed; within a group, alternatives separated by "/" ("saturday/sat").
    Words are matched whole and without regard to case.
  - NOT (optional) is what her answer must not say, alternatives with "/".
  - A line starting with # is a comment. Questions are separated by a blank
    line or by the next Q after an A.

Nothing in a file is run or evaluated: KEY and NOT are words, made into
whole-word patterns here (re.escape), so a file cannot make a check that
does something else. Limits: 256 KB a file, 300 questions a file, 20 files,
500 questions in all.

Where they are asked: in a stage of their own, "yours", after the four trust
levels, up to TURNS of them a round, and spaced like the rest once she has
them right three times running. They are NOT counted in her run's score and
earn no trust level: a level is about whether she can be trusted, and a
steward's quiz about his garden is not that.
"""
import hashlib
import json
import os
import re
import time

STAGE = "yours"
TURNS = 10                      # questions of the steward's per round
MAX_BYTES = 256 * 1024
MAX_PER_FILE = 300
MAX_FILES = 20
MAX_TOTAL = 500
MAX_LINE = 400                  # characters of a question or an answer

_FIELD = re.compile(r"^\s*(title|document|q|a|key|not)\s*:\s*(.*)$", re.I)


def _words_pattern(alt: str) -> str:
    """A KEY or NOT word as a whole-word, case-blind pattern. The check
    lower-cases the answer, so the pattern is lower-case too."""
    w = " ".join(alt.lower().split())
    return r"(?<!\w)%s(?!\w)" % re.escape(w).replace(r"\ ", r"\s+")


def parse(text: str):
    """(meta, items, errors). meta = {title, document}; each item =
    {say: [...], answer, key: [[pattern, ...], ...], never: [...], line}."""
    meta, items, errors = {"title": "", "document": ""}, [], []
    cur = None

    def close():
        nonlocal cur
        if cur is None:
            return
        n = cur["line"]
        if not cur["say"]:
            errors.append("question at line %d has no Q" % n)
        elif not cur["answer"]:
            errors.append("question at line %d (%s) has no A" % (n, cur["say"][0][:40]))
        elif not cur["key"]:
            errors.append("question at line %d (%s) has no KEY" % (n, cur["say"][0][:40]))
        else:
            items.append(cur)
        cur = None

    for no, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            if not line and cur is not None and cur["answer"]:
                close()
            continue
        m = _FIELD.match(line)
        if not m:
            errors.append("line %d is not a field (Q:, A:, KEY:, NOT:, title:, document:)" % no)
            continue
        field, value = m.group(1).lower(), " ".join(m.group(2).split())
        if len(value) > MAX_LINE:
            errors.append("line %d is longer than %d characters" % (no, MAX_LINE))
            continue
        if field in ("title", "document"):
            meta[field] = value[:120]
            continue
        if field == "q":
            if cur is not None and cur["answer"]:
                close()
            if cur is None:
                cur = {"say": [], "answer": "", "key": [], "never": [], "line": no}
            if value:
                cur["say"].append(value)
            continue
        if cur is None:
            errors.append("line %d: %s: comes before any Q:" % (no, field.upper()))
            continue
        if field == "a":
            cur["answer"] = value
        elif field == "key":
            groups = [[_words_pattern(a) for a in g.split("/") if a.strip()]
                      for g in value.split(";")]
            cur["key"] = [g for g in groups if g]
        elif field == "not":
            cur["never"] = [_words_pattern(a) for a in value.split("/") if a.strip()]
    close()
    if len(items) > MAX_PER_FILE:
        errors.append("%d questions: at most %d in a file" % (len(items), MAX_PER_FILE))
    if not items and not errors:
        errors.append("there are no questions in it")
    return meta, items, errors


class Files:
    """The steward's training files on this unit: TRAINING_DIR/yours/."""

    def __init__(self, directory: str):
        self.dir = directory

    def _all(self):
        out = []
        try:
            names = sorted(os.listdir(self.dir))
        except OSError:
            return out
        for n in names:
            if not n.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.dir, n), encoding="utf-8") as f:
                    out.append(json.load(f))
            except (OSError, ValueError):
                continue
        return out

    def listing(self):
        return [{"id": d["id"], "name": d["name"], "title": d["meta"].get("title") or d["name"],
                 "document": d["meta"].get("document", ""), "questions": len(d["items"]),
                 "added": d["added"]} for d in self._all()]

    def add(self, name: str, raw: bytes):
        """(entry, None) or (None, [errors])."""
        if len(raw) > MAX_BYTES:
            return None, ["the file is larger than %d KB" % (MAX_BYTES // 1024)]
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None, ["the file is not plain text (UTF-8)"]
        meta, items, errors = parse(text)
        if errors:
            return None, errors[:12]
        have = self._all()
        if len(have) >= MAX_FILES:
            return None, ["%d training files are on this unit already: remove one first" % MAX_FILES]
        if sum(len(d["items"]) for d in have) + len(items) > MAX_TOTAL:
            return None, ["more than %d questions in all: remove a file first" % MAX_TOTAL]
        fid = hashlib.sha256(raw).hexdigest()[:12]
        if any(d["id"] == fid for d in have):
            return None, ["this file is on the unit already"]
        entry = {"id": fid, "name": (name or "training file")[:120], "meta": meta,
                 "items": items, "added": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        os.makedirs(self.dir, exist_ok=True)
        tmp = os.path.join(self.dir, fid + ".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=1)
        os.replace(tmp, os.path.join(self.dir, fid + ".json"))
        return entry, None

    def remove(self, fid: str) -> bool:
        if not isinstance(fid, str) or not re.fullmatch(r"[0-9a-f]{12}", fid):
            return False
        try:
            os.unlink(os.path.join(self.dir, fid + ".json"))
            return True
        except OSError:
            return False

    def tasks(self):
        """Every question of every file, in the training key's shape (the
        caller makes them with training.q)."""
        out = []
        for d in self._all():
            for n, it in enumerate(d["items"], 1):
                out.append({"id": "you.%s.%d" % (d["id"], n), "say": it["say"],
                            "need": it["key"], "truth": it["answer"],
                            "topic": it["say"][0][:80], "never": it["never"]})
        return out
