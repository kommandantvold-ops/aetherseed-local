"""The library: passages she shows word for word, with their source (build log 57).

Andreas, 4 Oct 2026: "A library she answers from with a knowledge base like
that of nomad (content) so it can be a disaster relief and offgrid rural
survival aid." And, asked whether passages should be shown word for word
rather than retold: "Yes! Perfect!"

WHY WORD FOR WORD. Build log 38d: with a verse verbatim in front of her the
model answered "the second day" for "the first". Build log 23 Sep: with the
contact address at the top of its context it returned two other people's
domains. For a dose, or how much bleach makes water safe, that is the failure
to design out - so the model is not called. She finds the passage; the source
speaks. The same treatment the to-do list gets (build log 51): the file is the
answer, and nothing a model adds to it helps.

WHAT A COLLECTION IS. One SQLite file made by tools/library_build.py from a
Kiwix ZIM - passages, the document and place each came from, a full-text
index - in /var/lib/aetherseed/library/. Read-only. Python's own sqlite3 is
all this needs.

WHEN SHE ANSWERS FROM IT.
  - Asked to ("look up ...", "what does the library say about ...", "search
    the library for ..."): the best passage, or plainly that the library has
    nothing on it, and what it holds.
  - Unasked, only when she is sure (find): every word that carries the
    question is in the passage, and the passage is about it - a word of the
    question is rare in that collection or stands in the document's title -
    and the words stand together, not scattered. A question about her, or
    about what she was told, is never the library's ("you", "your").
    Tried 4 Oct 2026 with the reader's own search: "make water safe to
    drink", asked of a medicines collection, returned an acne medicine. A
    library that always answers is worse than none.

It never says more than the passage. What it cannot do: judge whether the
passage is right, or whether it fits the person asking.
"""
import glob
import math
import os
import re
import sqlite3
from typing import Dict, List, Optional

LIBRARY_DIR = os.environ.get("AETHERSEED_LIBRARY", "/var/lib/aetherseed/library")

RARE = 0.03          # a word in at most this share of a collection's passages is "about" something
NEAR = 30            # tokens: words that only meet in the running text must stand this close
SHOWN_MAX = 1200     # characters of a passage put on the screen

STOP = set("""
a about above after again all also am an and any are as at be because been before being
below between both but by can cannot could did do does doing down during each few for from
further had has have having he her here hers him his how i if in into is it its itself just
me more most my myself no nor not now of off on once only or other our ours out over own
same she should so some such than that the their them then there these they this those
through to too under until up very was we were what when where which while who whom why
will with would you your yours yourself
tell say said please know want need like get got give let lets us ok okay hi hello thanks
thank much many long often best way good right kind sort thing things something anything
make made take taken use used using
""".split())

# A question about her, or about what she was told, is not the library's.
PERSONAL = re.compile(r"\b(you|your|yours|yourself|we|our|ours|us)\b", re.I)
# Something the steward says about themselves, with no question in it, is
# something told - not something asked: "I drink a lot of water every day".
TOLD = re.compile(r"^\s*(?:i|i'm|i’m|im|my|me)\b", re.I)

LOOKUP = [re.compile(p, re.I) for p in (
    r"^\s*(?:please\s+)?look\s*up\s+(?P<q>.+?)\s*(?:in\s+the\s+library)?\s*[?.!]*\s*$",
    r"^\s*(?:please\s+)?(?:search|check|ask)\s+the\s+library\s+(?:for|about|on)\s+(?P<q>.+?)\s*[?.!]*\s*$",
    r"^\s*what\s+does\s+the\s+library\s+say\s+(?:about|on)\s+(?P<q>.+?)\s*[?.!]*\s*$",
    r"^\s*(?:in|from)\s+the\s+library\s*[:,]\s*(?P<q>.+?)\s*[?.!]*\s*$",
    r"^\s*library\s*:\s*(?P<q>.+?)\s*[?.!]*\s*$",
)]
CONTENTS = re.compile(r"^\s*(?:what(?:'s|’s|\s+is)\s+in\s+(?:the|your)\s+library|"
                      r"what\s+(?:does|do)\s+(?:the|your)\s+library\s+(?:hold|have|contain)|"
                      r"(?:show|list)\s+(?:me\s+)?the\s+library)\s*[?.!]*\s*$", re.I)


def terms(question: str) -> List[str]:
    """The words that carry the question, in order, once each."""
    out = []
    for w in re.findall(r"[A-Za-z][A-Za-z0-9'’-]*|\d+", (question or "").lower()):
        w = w.strip("'’-").replace("’", "'")
        w = re.sub(r"'s$", "", w)
        if len(w) < 2 or w in STOP or w in out:
            continue
        out.append(w)
    return out[:8]


# Words that carry no meaning at all. Everything else in the question helps
# choose WHICH passage of the right document is shown: "how LONG does
# ibuprofen TAKE to WORK" is answered under a heading that says so.
FUNCTION = set("""
a an and are as at be but by do does did for from had has have he her his i if in into is
it its me my of on or our she so than that the their them then there these they this those
to us was we were will with would you your can could should shall may might must am been
being what who whom which when where why how
""".split())


def all_words(question: str) -> List[str]:
    out = []
    for w in re.findall(r"[A-Za-z][A-Za-z0-9'’-]*|\d+", (question or "").lower()):
        w = re.sub(r"'s$", "", w.strip("'’-").replace("’", "'"))
        if len(w) < 2 or w in FUNCTION or w in out:
            continue
        out.append(w)
    return out[:12]


def lookup_query(text: str) -> Optional[str]:
    """What she was asked to look up, when she was asked to."""
    for p in LOOKUP:
        m = p.match(text or "")
        if m and terms(m.group("q")):
            return m.group("q")
    return None


def asks_contents(text: str) -> bool:
    return bool(CONTENTS.match(text or ""))


def _q(term: str) -> str:
    return '"%s"' % term.replace('"', "")


class Collection:
    def __init__(self, path: str):
        self.path = path
        self.db = sqlite3.connect("file:%s?mode=ro&immutable=1" % path, uri=True,
                                  check_same_thread=False)
        self.meta: Dict[str, str] = dict(self.db.execute("SELECT key, value FROM meta"))
        self.n = int(self.meta.get("passages") or 0) or 1
        self._df: Dict[str, int] = {}

    @property
    def name(self) -> str:
        t = self.meta.get("title") or self.meta.get("id") or os.path.basename(self.path)
        d = (self.meta.get("date") or "")[:7]
        return "%s (%s)" % (t, d) if d else t

    def count(self, match: str) -> int:
        try:
            return self.db.execute("SELECT count(*) FROM passages_fts WHERE passages_fts MATCH ?",
                                   (match,)).fetchone()[0]
        except sqlite3.Error:
            return 0

    def df(self, term: str) -> int:
        if term not in self._df:
            self._df[term] = self.count(_q(term))
        return self._df[term]

    def rows(self, match: str, limit: int) -> List[int]:
        try:
            return [r[0] for r in self.db.execute(
                "SELECT rowid FROM passages_fts WHERE passages_fts MATCH ? "
                "ORDER BY bm25(passages_fts, 6.0, 4.0, 1.0) LIMIT ?", (match, limit))]
        except sqlite3.Error:
            return []

    def passage(self, rowid: int) -> Optional[dict]:
        r = self.db.execute(
            "SELECT p.id, p.doc, p.seq, p.heading, p.place, p.text, d.title, d.author, d.locator, "
            "(SELECT max(seq) FROM passages WHERE doc = p.doc) "
            "FROM passages p JOIN docs d ON d.id = p.doc WHERE p.id = ?", (rowid,)).fetchone()
        if not r:
            return None
        return {"id": r[0], "doc": r[1], "seq": r[2], "heading": r[3] or "", "place": r[4] or "",
                "text": r[5], "title": r[6] or "", "author": r[7] or "", "locator": r[8] or "",
                "last": r[9], "collection": self.name, "collection_id": self.meta.get("id", ""),
                "licence": self.meta.get("licence", "")}

    # -- unasked: only when sure ------------------------------------------
    def sure(self, ts: List[str], words: List[str] = None) -> Optional[dict]:
        """The passage this collection is sure answers `ts`, or None.

        Sure means two things. Every word that carries the question is in the
        passage. And the passage is ABOUT it, by its own title or heading:
          - a site (pages with headings): one of the words - a rare one, or
            one that stands in a title - is in that passage's own title or
            heading;
          - a shelf of documents (no headings to go by): one of the words is
            in that document's title, and all of them stand close together in
            the text.
        Rare alone is not about: "What happened in the beginning?" found
        "happen" and "begin" side by side in a thyroid medicine's warnings
        (measured 4 Oct 2026, the first version of this rule).
        """
        if not ts or any(self.df(t) == 0 for t in ts):
            return None                      # a word of the question is not in it at all
        in_title = [t for t in ts if self.count("title:" + _q(t))]
        rare = [t for t in ts if self.df(t) / self.n <= RARE]
        every = " AND ".join(_q(t) for t in ts)
        if self.meta.get("kind") == "documents":
            if not in_title:
                return None
            titled = " OR ".join("title:%s" % _q(t) for t in in_title)
            # the words the title does not say must stand close together in
            # the text; the ones it does say need only be there
            loose = [t for t in ts if t not in in_title]
            match = "(%s) AND (%s)" % (every, titled)
            if len(loose) > 1:
                match += " AND (text:NEAR(%s, %d))" % (" ".join(_q(t) for t in loose), NEAR)
            elif len(loose) == 1:
                match += " AND (text:%s)" % _q(loose[0])
            cands = self.rows(match, 200)
            one_title = self.rows(" AND ".join("title:%s" % _q(t) for t in ts), 1)
            if cands and not loose and one_title:
                cands = one_title
                # The question is the document's own subject ("What is
                # giardia?" - "Giardia: Drinking Water Factsheet"): it is
                # read from its top.
                first = self.db.execute(
                    "SELECT q.id FROM passages p JOIN passages q ON q.doc = p.doc "
                    "WHERE p.id = ? ORDER BY q.seq LIMIT 1", (cands[0],)).fetchone()
                cands = [first[0]]
            elif cands:
                # Otherwise by what the text says, the title left out of it:
                # every passage of a document shares its title.
                try:
                    cands = [r[0] for r in self.db.execute(
                        "SELECT rowid FROM passages_fts WHERE passages_fts MATCH ? "
                        "AND rowid IN (%s) ORDER BY bm25(passages_fts, 0.0, 0.0, 1.0), rowid"
                        % ",".join("?" * len(cands)),
                        ["text:(%s)" % " OR ".join(_q(t) for t in ts)] + cands)] or cands
                except sqlite3.Error:
                    pass
        else:
            # What the question is about: a rare word that a title or a
            # heading of this collection says. A word that is merely rare is
            # not enough ("beginning"), nor one that titles say but is common
            # ("drink").
            anchors = [t for t in rare if t in in_title or self.count("heading:" + _q(t))]
            if not anchors:
                return None
            if len(ts) == 1 and anchors[0] not in in_title:
                # One word decides alone only when a document is named for
                # it: "metformin", not "night" ("Good night" found "Strange
                # dreams or night sweats" - the held-out run, 4 Oct).
                return None
            about = " OR ".join("({title heading}:%s)" % _q(t) for t in anchors)
            # ... and every other word must be said somewhere in what is
            # about it - not necessarily in the same passage: "Is it SAFE to
            # drink alcohol with metronidazole?" is answered by a passage
            # that never says "safe".
            docs = " OR ".join("title:%s" % _q(t) for t in anchors if t in in_title) or about
            for t in ts:
                if t not in anchors and not self.count("(%s) AND %s" % (docs, _q(t))):
                    return None
            cands = self.rows(about, 40)
        if not cands:
            return None
        hit = self.passage(self.choose(cands, ts, words or ts))
        if hit:
            hit["weight"] = (len(in_title) / len(ts), sum(self.df(t) / self.n for t in ts))
        return hit

    def choose(self, cands: List[int], ts: List[str], words: List[str]) -> int:
        """Of passages that all qualify, the one to show first.

        On a shelf of documents there are no headings to go by, and the order
        the words themselves gave stands.

        On a site, the passage is looked for again in every document about
        the subject, by all the words of the question and not only the ones
        that decided it. Each word counts by how rare it is, twice when the
        passage's own title or heading says it and once when its text does:
        "Is it safe to DRINK ALCOHOL with METRONIDAZOLE?" belongs under "Can
        I drink alcohol while taking metronidazole?", which never says
        "safe". Between equals, a title that names nothing rare that was not
        asked ("Ibuprofen and codeine" is another medicine), then the earlier
        passage: a page is read from its top.

        It is words that are matched, not meaning: the right document is
        found far more surely than the right passage in it. "more" walks on.
        """
        if self.meta.get("kind") == "documents" or len(cands) == 0:
            return cands[0]
        asked = set(words) | set(ts)
        subject = [t for t in ts if self.df(t) / self.n <= RARE and self.count("title:" + _q(t))]
        if not subject:
            return cands[0]
        about = " OR ".join("title:" + _q(t) for t in subject)
        score: Dict[int, float] = {}

        def mark(match, worth):
            try:
                for (rowid,) in self.db.execute(
                        "SELECT rowid FROM passages_fts WHERE passages_fts MATCH ?", (match,)):
                    score[rowid] = score.get(rowid, 0.0) + worth
            except sqlite3.Error:
                pass

        for w in [w for w in words if self.df(w)]:
            rarity = math.log(self.n / (1.0 + self.df(w))) + 0.1
            mark("(%s) AND ({title heading}:%s)" % (about, _q(w)), 2.0 * rarity)
            mark("(%s) AND (text:%s)" % (about, _q(w)), rarity)
        if not score:
            return cands[0]
        top = max(score.values())
        best = [r for r, v in score.items() if v >= top - 1e-9]

        def extra(rowid):
            title = self.db.execute(
                "SELECT d.title FROM passages p JOIN docs d ON d.id = p.doc WHERE p.id = ?",
                (rowid,)).fetchone()[0] or ""
            return sum(1 for w in set(all_words(title)) - asked
                       if 0 < self.df(w) / self.n <= RARE and not self._asked_stem(w, asked))
        return min(best, key=lambda r: (extra(r), r))

    def _asked_stem(self, word: str, asked) -> bool:
        """Is `word` one of the asked words in another form (adult/adults)?"""
        return any(word.startswith(a[:max(4, len(a) - 2)]) or a.startswith(word[:max(4, len(word) - 2)])
                   for a in asked)

    # -- asked to look it up: the best there is ---------------------------
    def best(self, ts: List[str], words: List[str] = None) -> Optional[dict]:
        known = [t for t in ts if self.df(t)]
        if not known:
            return None
        idf = {t: math.log(self.n / (1.0 + self.df(t))) + 0.1 for t in known}
        missing = sum(math.log(self.n) + 0.1 for t in ts if t not in known)
        if sum(idf.values()) < missing:
            return None                      # most of what was asked is not in it
        for match in (" AND ".join(_q(t) for t in known), " OR ".join(_q(t) for t in known)):
            rows = self.rows(match, 40)
            if rows:
                hit = self.passage(self.choose(rows, known, words or known))
                if hit:
                    # between collections: the one that says more about it.
                    # "bleach" is in 3 of 12313 medicine passages (it can
                    # bleach your hair) and 26 of 897 on water.
                    hit["weight"] = (len(known) / len(ts),
                                     sum(self.df(t) / self.n for t in known))
                return hit
        return None


class Library:
    def __init__(self, directory: str = None):
        self.dir = directory or LIBRARY_DIR
        self.collections: List[Collection] = []
        for path in sorted(glob.glob(os.path.join(self.dir, "*.lib.sqlite"))):
            try:
                self.collections.append(Collection(path))
            except sqlite3.Error as exc:
                print("[library] %s not opened: %r" % (path, exc), flush=True)

    def __bool__(self):
        return bool(self.collections)

    def holds(self) -> List[str]:
        return [c.name for c in self.collections]

    def _pick(self, hits: List[dict]) -> Optional[dict]:
        hits = [h for h in hits if h]
        return max(hits, key=lambda h: h["weight"]) if hits else None

    def find(self, question: str) -> Optional[dict]:
        """Unasked. None unless a collection is sure."""
        q = question or ""
        if not self.collections or PERSONAL.search(q):
            return None
        if TOLD.match(q) and "?" not in q:
            return None
        ts = terms(question)
        if not ts:
            return None
        words = all_words(question)
        return self._pick([c.sure(ts, words) for c in self.collections])

    def look_up(self, query: str) -> Optional[dict]:
        """Asked. The best passage there is, or None when there is nothing."""
        ts = terms(query)
        if not ts or not self.collections:
            return None
        words = all_words(query)
        sure = self._pick([c.sure(ts, words) for c in self.collections])
        return sure or self._pick([c.best(ts, words) for c in self.collections])

    def after(self, hit: dict) -> Optional[dict]:
        """The passage that follows `hit` in the same document."""
        for c in self.collections:
            if c.meta.get("id", "") == hit.get("collection_id"):
                r = c.db.execute("SELECT id FROM passages WHERE doc = ? AND seq = ?",
                                 (hit["doc"], hit["seq"] + 1)).fetchone()
                return c.passage(r[0]) if r else None
        return None


# ---------------------------------------------------------------------------
# What goes on the screen
# ---------------------------------------------------------------------------

def shown(hit: dict) -> str:
    """The passage, word for word, and where it is from."""
    text = hit["text"]
    cut = False
    if len(text) > SHOWN_MAX:
        end = max(text.rfind("\n", 0, SHOWN_MAX), text.rfind(". ", 0, SHOWN_MAX) + 1)
        text = text[:end if end > SHOWN_MAX // 2 else SHOWN_MAX].rstrip()
        cut = True
    where = [hit["collection"], '"%s"' % hit["title"]]
    if hit.get("author") and hit["author"].lower() not in ("various", "-", ""):
        where.append(hit["author"])
    if hit.get("heading"):
        where.append(hit["heading"])
    if hit.get("place"):
        where.append(hit["place"])
    lines = ["From the library, word for word:", "", text]
    if cut:
        lines.append("[the passage goes on]")
    lines += ["", "Source: " + " - ".join(where)]
    if hit.get("seq") and hit.get("last") and hit["seq"] < hit["last"]:
        lines.append('Say "more" for what follows it.')
    return "\n".join(lines)


def nothing(query: str, holds: List[str]) -> str:
    if not holds:
        return "I have no library on this unit."
    return ("The library has nothing I can show for that. It holds: %s."
            % "; ".join(holds))


def contents(lib: "Library") -> str:
    if not lib:
        return "I have no library on this unit."
    lines = ["The library on this unit:"]
    for c in lib.collections:
        lines.append("- %s: %s. %s documents, %s passages."
                     % (c.name, (c.meta.get("description") or "").rstrip("."),
                        c.meta.get("docs", "?"), c.meta.get("passages", "?")))
    lines.append('Ask me to "look up" something, and I show the passage word for word.')
    return "\n".join(lines)


_LIB: Optional[Library] = None


def library() -> Library:
    """The unit's library, opened once."""
    global _LIB
    if _LIB is None:
        _LIB = Library()
    return _LIB
