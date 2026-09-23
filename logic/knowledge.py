"""
knowledge.py — the curriculum: what a Companion knows before anyone speaks to it
================================================================================

A unit ships knowing what it is, what it cannot do, and what AetherSeed is.
Without this a 3B model answers those questions from training, where AetherSeed
does not exist, and invents a company. The curriculum is a small, authored,
read-only file; its lines enter the prompt as `[Known] ...` inside the same
[MEMORY CONTEXT] block AetherRoot already builds.

Three properties, all deliberate:

  read-only        The file lives in the application tree, which the service
                   mounts read-only (ProtectSystem=strict) and the cartridge
                   hashes into app.digest. A state reset does not touch it and
                   nothing at runtime can rewrite it.
  no new markers   Lines go inside [MEMORY CONTEXT], so honesty_check gets them
                   in its haystack for free (a line naming contact@aetherseed.ai
                   grounds the address the node is repeating from its own build)
                   and token_budget's trimmer already knows how to cut the block.
  no shared state  This module never touches AetherRoot's embedder, database or
                   IDF statistics. It reads one file and matches words.

WHY WORDS AND NOT THE EMBEDDER
------------------------------
The plan was to embed the curriculum with AetherRoot's TFIDFEmbedder. Measured
on 2026-09-23 against all 21 entries and 44 probe questions, at dim=64 on both a
fresh unit and Lyra's live state, that does not work:

    intended entry ranked top-1          15/34 (fresh)   13/34 (live)
    top-1 similarity, on-topic  median   0.412           0.401
    top-1 similarity, off-topic median   0.410           0.353
    off-topic questions that still
      pulled a line, at any threshold
      that answered most questions       10/10           10/10

The two distributions sit on top of each other. At 64 dimensions hash collisions
are certain, so "similarity" over 21 short documents is mostly collision noise;
"what is the capital of France" scored 0.411 against "AetherSeed builds AI that
earns what it is allowed to do". There is no threshold that separates them, so
this is not a tuning problem and no amount of rewording fixes it.

The curriculum is 21 authored sentences, not a corpus. For that, word overlap
weighted by how distinctive a word is WITHIN the curriculum is both better and
inspectable — you can read a line and see why it fired. Measured the same way,
same probe set:

    intended entry ranked top-1                       34/42
    intended entry among the two lines shown          37/42
    off-topic questions that pulled any line           0/14

Honest caveat, because the number flatters us: the probes and the curriculum
were written by the same hand on the same day. 37/42 is a self-graded exam. The
real figure is what the soak and the owner produce.

HOW A LINE IS CHOSEN
--------------------
    score  = (sum of idf over query words the entry contains)
             / (sum of idf over all content words in the query)
    weight =  sum of idf over query words the entry contains

`score` asks what fraction of the question this entry accounts for; it keeps a
long message about a radiator from pulling a line because it happens to contain
one curriculum word. `weight` asks whether what matched was distinctive; it lets
a long, rambling question through when it lands on something specific ("sent",
"server"), where the fraction is necessarily small. A line is shown if EITHER
passes. idf is computed over the 21 entries themselves - a word in every entry
("i", "trust") carries almost nothing, a word in one ("cartridge", "poem")
carries the most.

`trigger` handles the questions that survive no stopword list at all: "what are
you" and "who made you" have no content words, and are the two questions a
companion in a living room is asked most.

At most two lines per turn, and at most half the memory budget, because the
other half is what its owner actually said to it.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

__all__ = ["Knowledge", "load_knowledge", "KNOWN_PREFIX", "CONTACT_ENTRY",
           "is_contact_question", "SCORE_THRESHOLD", "WEIGHT_FLOOR",
           "MAX_LINES", "MAX_TEXT_CHARS"]

# The third kind of line in the block, beside [Episode] and [Pattern]. Not a
# scaffold marker: it never starts a line on its own and never closes a block,
# so opening_may_be_artefact() and the stream guard are unaffected.
KNOWN_PREFIX = "[Known] "

# Chosen from the sweep in the docstring: the widest setting that pulled a line
# on none of the 14 off-topic probes. Loosening WEIGHT_FLOOR to 3.0 answers
# three more questions and starts quoting "my answers are short on purpose" at
# someone drafting a letter to their landlord - the kind of noise that teaches a
# user to stop reading the thing entirely.
SCORE_THRESHOLD = 0.30
WEIGHT_FLOOR = 4.0
MAX_LINES = 2
MAX_TEXT_CHARS = 200        # one entry may not eat the whole block

_TOK = re.compile(r"[a-z0-9]+")

# Words that carry no signal about WHICH entry is wanted. Deliberately small:
# every word removed here is a word that can never distinguish two entries, and
# an over-eager list is how "what are you" ends up with nothing to match on.
_STOP = frozenset("""
a an the and or but if then so of to in on at by for with from as is are was were be been being
do does did doing have has had having i me my we our you your he she it its they them their
this that these those can could will would shall should may might must about into over under
again more most other some such no nor not only own same too very s t just now here there
when where why how what which who whom all any both each few please tell say said give get got
go going one two
""".split())


def _tokens(text: str) -> List[str]:
    return _TOK.findall((text or "").lower())


def _content_words(text: str) -> List[str]:
    """Query words that could distinguish one entry from another, in order,
    without repeats — a word said three times is not three times the evidence."""
    return [t for t in dict.fromkeys(_tokens(text))
            if t not in _STOP and len(t) > 1]


class Knowledge:
    """The loaded curriculum. Immutable after construction."""

    def __init__(self, entries: List[Dict], source: Optional[Path] = None,
                 errors: Optional[List[str]] = None):
        self.entries = entries
        self.source = source
        self.errors = errors or []

        n = len(entries) or 1
        df: Dict[str, int] = {}
        self._entry_words: List[frozenset] = []
        self._triggers: List[List[str]] = []
        for e in entries:
            words = frozenset(_tokens(e["text"] + " " + e.get("match", "")))
            self._entry_words.append(words)
            self._triggers.append(
                [" " + " ".join(_tokens(t)) + " " for t in e.get("trigger", [])])
            for w in words:
                df[w] = df.get(w, 0) + 1
        self._df = df
        self._n = n
        # A word the curriculum has never seen scores as if it appeared in half
        # an entry: higher than any real word, so a question made mostly of such
        # words drives `score` down. That is what makes silence the default.
        self._idf_unseen = math.log(n / 0.5)

    def _idf(self, word: str) -> float:
        d = self._df.get(word, 0)
        return self._idf_unseen if d == 0 else math.log(self._n / d)

    def rank(self, query: str) -> List[Dict]:
        """Every entry, best first, with the arithmetic that put it there.

        Ties break on the entry's position in the file: the curriculum's order
        is the author's order of preference, and a tie broken on id would sort
        "seed.nofield" above "seed.layers" for no reason a reader could defend.
        """
        words = _content_words(query)
        denom = sum(self._idf(w) for w in words)
        norm_q = " " + " ".join(_tokens(query)) + " "

        out = []
        for i, e in enumerate(self.entries):
            triggered = any(t in norm_q for t in self._triggers[i] if t.strip())
            matched = [w for w in words if w in self._entry_words[i]]
            weight = sum(self._idf(w) for w in matched)
            score = weight / denom if denom else 0.0
            if triggered:
                score, weight = 1.0, max(weight, self._idf_unseen * 4)
            out.append({"id": e["id"], "text": e["text"], "score": score,
                        "weight": weight, "matched": matched,
                        "triggered": triggered, "order": i})
        out.sort(key=lambda r: (-r["score"], -r["weight"], r["order"]))
        return out

    def by_id(self, entry_id: str):
        """One entry's text, verbatim, or None. The single source of truth for
        an answer that is served from the build rather than generated."""
        for e in self.entries:
            if e["id"] == entry_id:
                return e["text"]
        return None

    def lines_for(self, query: str, max_lines: int = MAX_LINES,
                  max_chars: Optional[int] = None) -> List[str]:
        """The `[Known] ...` lines this question earns — usually none."""
        if not self.entries or not (query or "").strip():
            return []
        lines, used = [], 0
        for r in self.rank(query):
            if len(lines) >= max_lines:
                break
            if r["score"] < SCORE_THRESHOLD and r["weight"] < WEIGHT_FLOOR:
                break                      # ranked, so nothing below qualifies
            line = KNOWN_PREFIX + r["text"]
            if max_chars is not None and used + len(line) > max_chars:
                break
            lines.append(line)
            used += len(line)
        return lines


# ---------------------------------------------------------------------------
# The one answer that must be exact
# ---------------------------------------------------------------------------
# Measured on the device 23 Sep, twice, with the correct line at the top of the
# model's context: asked how to contact AetherSeed it answered
# "contact@aethersed.ai", and then "contact@aethersseed.ai". A 3B model cannot
# reliably copy an eleven-character domain, and a wrong address is not a vague
# answer - it is a live domain belonging to somebody else.
#
# So this question is answered the way a record question is: from the file,
# with the model never called. The precedent is deliberate. `is_record_question`
# exists because a model summarising its own mistakes is the least reliable
# possible narrator of them; this exists because a model retyping an address is
# the least reliable possible copier of it.
#
# The predicate is phrase-based and deliberately narrow, because intercepting
# the wrong question is worse than not intercepting: "can you help me contact
# my landlord" must reach the model, and it does - it contains "contact my
# landlord", and none of the phrases below. A phrase names its target; a bag of
# words ("contact", "email", "you") does not.
CONTACT_ENTRY = "as.contact"

# Anything naming AetherSeed is safe by construction - a landlord is not
# AetherSeed - so there the rule can be a word pair. Anything naming only "you"
# or "the team" has to be a phrase, because those words point at whoever the
# sentence is about.
_CONTACT_WORDS = ("contact", "email", "mail", "reach", "touch", "write", "get")
_CONTACT_PHRASES = (
    "contact you", "contact the team", "reach you", "reach the team",
    "get in touch with you", "in touch with the team",
    "your email", "your e mail", "email you", "write to you",
)

# A second gate, so a statement is not mistaken for a question: "I'll reach you
# tomorrow" contains a phrase and asks nothing.
_ASKING = ("how ", "what ", "where ", "which ", "who ", "can ", "could ",
           "is ", "are ", "do ", "does ", "may ", "please ")


def is_contact_question(user_msg: str) -> bool:
    """Is this someone asking how to reach AetherSeed?

    Narrow on purpose. A false yes hands out one true sentence to somebody who
    did not ask for it; a false no costs nothing, because the model still gets
    the question with the right line in its context.
    """
    text = " " + " ".join(_tokens(user_msg)) + " "
    named_us = " aetherseed " in text and any(
        (" " + w + " ") in text for w in _CONTACT_WORDS)
    if not named_us and not any((" " + p + " ") in text for p in _CONTACT_PHRASES):
        return False
    raw = (user_msg or "").strip().lower()
    return "?" in raw or raw.startswith(_ASKING) or " how do i " in text or " how can i " in text


def _default_path() -> Path:
    return Path(__file__).resolve().parent.parent / "knowledge" / "companion.en.jsonl"


def load_knowledge(path=None) -> Optional[Knowledge]:
    """Load the curriculum, or return None if there is none.

    None is a legitimate state: a unit with no curriculum file still remembers,
    still checks provenance, still answers. It simply has not been told anything
    about itself. Returning None rather than raising keeps a mangled file from
    taking the companion off the air — but every rejected line is counted in
    `.errors` and printed once, so a build that shipped a broken curriculum says
    so in the journal instead of quietly knowing less than it should.
    """
    if path is None:
        path = os.environ.get("AETHERSEED_KNOWLEDGE") or _default_path()
    path = Path(path)
    if not path.is_file():
        return None

    try:
        from logic.token_budget import sanitize_injected
    except Exception:
        sanitize_injected = lambda s: s   # noqa: E731

    entries, errors, seen = [], [], set()
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"[knowledge] {path} could not be read: {exc!r}", flush=True)
        return None

    for lineno, raw_line in enumerate(raw.splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            e = json.loads(raw_line)
        except Exception as exc:
            errors.append(f"line {lineno}: not JSON ({exc})")
            continue
        eid = str(e.get("id") or f"line{lineno}")
        text = (e.get("text") or "").strip()
        if not text:
            errors.append(f"line {lineno} ({eid}): empty text")
            continue
        if "\n" in text or "\r" in text:
            errors.append(f"line {lineno} ({eid}): text spans lines")
            continue
        if len(text) > MAX_TEXT_CHARS:
            errors.append(f"line {lineno} ({eid}): {len(text)} chars, "
                          f"over the {MAX_TEXT_CHARS} limit")
            continue
        if eid in seen:
            errors.append(f"line {lineno}: duplicate id {eid}")
            continue
        seen.add(eid)
        # Defence in depth: the file is ours and hashed, but a curriculum line
        # containing "[END MEMORY CONTEXT]" would close the block early and have
        # whatever followed read as trusted prompt. Same treatment as a file the
        # node did not write.
        entries.append({"id": eid, "text": sanitize_injected(text),
                        "match": str(e.get("match") or ""),
                        "trigger": [str(t) for t in (e.get("trigger") or [])]})

    if errors:
        print(f"[knowledge] {path.name}: {len(errors)} entr"
              f"{'y' if len(errors) == 1 else 'ies'} rejected: "
              f"{'; '.join(errors[:5])}", flush=True)
    if not entries:
        return None
    return Knowledge(entries, source=path, errors=errors)
