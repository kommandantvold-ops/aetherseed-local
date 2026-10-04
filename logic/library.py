"""The library: passages she shows word for word, with their source (build logs 57, 58).

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
Kiwix ZIM, or from chosen documents of several (library/NAME.json) -
passages, the document and place each came from, a full-text index - in
/var/lib/aetherseed/library/. Read-only. Python's own sqlite3 is all this
needs.

WHEN SHE ANSWERS FROM IT.
  - Asked to ("look up ...", "what does the library say about ...", "search
    the library for ..."): the best passage, or plainly that the library has
    nothing on it, and what it holds.
  - Unasked, only when she is sure (find): the passage is ABOUT the
    question by its own title or heading - a rare word of the question that
    a title or heading says, or a title or heading that the question itself
    says ("Hurricanes", "SNOW CAVE") - and what is about it says every
    other word that carries the question. A question about her, or about
    what she was told, is never the library's ("you", "your", "let's").
    Tried 4 Oct 2026 with the reader's own search: "make water safe to
    drink", asked of a medicines collection, returned an acne medicine. A
    library that always answers is worse than none.

It never says more than the passage. What it cannot do: judge whether the
passage is right, or whether it fits the person asking. And it matches words,
not meaning (build log 58): "How do I treat hypothermia?" finds nothing
unasked, because the section is headed "FIRST AID FOR HYPOTHERMIA" and never
says "treat"; "Where is the north pole?" is shown "LOCATING THE NORTH STAR",
which says both words. Asked to look it up, she shows the best there is.
"""
import glob
import math
import os
import re
import sqlite3
import threading
from typing import Dict, List, Optional

LIBRARY_DIR = os.environ.get("AETHERSEED_LIBRARY", "/var/lib/aetherseed/library")

RARE = 0.03          # a word in at most this share of a collection's passages is "about" something
NEAR = 30            # tokens: words that only meet in the running text must stand this close
LEAFLET = 60         # passages: a document this short is about its title on every page
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
make made take taken use used using go goes going
""".split())

# A question about her, or about what she was told, is not the library's.
PERSONAL = re.compile(r"\b(you|your|yours|yourself|we|our|ours|us|let's|let’s|lets)\b", re.I)
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


_STEM_LOCK = threading.Lock()
_STEM_DB = None
_STEMS: Dict[str, str] = {}


def _crude(w: str) -> str:
    for end in ("ies", "es", "ing", "ed", "s"):
        if w.endswith(end) and len(w) - len(end) >= 3:
            w = w[:len(w) - len(end)]
            break
    return w[:-1] if w.endswith("e") and len(w) > 3 else w


def stem(word: str) -> str:
    """The form the index itself keeps the word in: "hurricanes" and
    "hurricane" are one word there, and must be one word here. The first
    measurement on Ready.gov missed every page titled in the plural ending
    -es ("Hurricanes", "Earthquakes") because a home-made rule cut them
    differently from the index. So the index's own tokenizer is asked."""
    global _STEM_DB
    w = (word or "").lower()
    if w in _STEMS:
        return _STEMS[w]
    out = None
    with _STEM_LOCK:
        try:
            if _STEM_DB is None:
                db = sqlite3.connect(":memory:", check_same_thread=False)
                db.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='porter unicode61')")
                db.execute("CREATE VIRTUAL TABLE v USING fts5vocab(t, 'instance')")
                _STEM_DB = db
            _STEM_DB.execute("DELETE FROM t")
            _STEM_DB.execute("INSERT INTO t(rowid, x) VALUES (1, ?)", (w,))
            out = "-".join(r[0] for r in _STEM_DB.execute("SELECT term FROM v ORDER BY offset"))
        except sqlite3.Error:
            out = None
    if not out:
        out = _crude(w)
    if len(_STEMS) < 20000:
        _STEMS[w] = out
    return out


def stems(text: str) -> set:
    """The words of a title or a heading, as the index keeps them."""
    out = set()
    for w in re.findall(r"[A-Za-z][A-Za-z0-9'’-]*|\d+", (text or "").lower()):
        w = re.sub(r"'s$", "", w.strip("'’-").replace("’", "'"))
        if len(w) >= 2 and w not in FUNCTION:
            out.add(stem(w))
    return out


def parts(heading: str) -> List[str]:
    """A heading, and each of the headings it is put together from: the
    converter writes a lesser heading after the one it stands under
    ("MAN-MADE SHELTERS: Snow Cave", "Chapter 11: HEAT STROKE")."""
    bits = [b.strip() for b in re.split(r":\s+", heading or "") if b.strip()]
    return [heading] + (bits if len(bits) > 1 else [])


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

        Sure means two things: the passage is ABOUT the question, by its own
        title or heading, and what is about it says every word that carries
        the question. Tried in this order:

          1. A rare word of the question in a TITLE - "metronidazole" on a
             medicines site: the documents titled for it are looked through
             whole. A word that is merely rare is not enough ("beginning"),
             nor one that titles say but is common ("drink"). One word decides
             alone only when a document is named for it: "metformin", not
             "night" ("Good night" found "Strange dreams or night sweats").
          2. A rare word in a HEADING of which the question says half or more
             - "FROSTBITE" over a section of a cold-weather manual: only what
             stands under such headings is looked through, and it must say
             the rest.
          3. A short document with no headings to go by (a leaflet): words of
             the question in its title, and the rest close together in its
             text.
          4. A title or a heading that the question itself says (said()).
        """
        if not ts or any(self.df(t) == 0 for t in ts):
            return None                      # a word of the question is not in it at all
        words = words or ts
        if len(ts) == 1 and not self._names_a_title(ts[0]):
            # One word decides alone only when a document is named for it:
            # "metformin", "giardia", "tornado" - not "weather", which a
            # cold-weather manual's long title also says ("What is the
            # weather like?" was shown that manual's title page).
            return self.said(ts, words)
        in_title = [t for t in ts if self.count("title:" + _q(t))]
        rare = [t for t in ts if self.df(t) / self.n <= RARE]
        asked = {stem(w) for w in words} | {stem(t) for t in ts}
        heads = {t: self._heads(t, asked) for t in rare if t not in in_title}
        anchors = [t for t in rare if t in in_title or heads.get(t)]
        about, only = None, None
        cands: List[int] = []
        if anchors:
            # ONE of them must say what the passage is about, and what is
            # about it must say every other word - not necessarily in the
            # same passage: "Is it SAFE to drink alcohol with metronidazole?"
            # is answered by a passage that never says "safe". A document
            # titled for the word is looked through whole; a section headed
            # by it, only itself. Two headings that each say one word are
            # not one subject: "Where is the north pole?" found "LOCATING
            # THE NORTH STAR" and "SPRING POLE".
            good, under = [], set()
            for t in [t for t in anchors if t in in_title]:
                scope = "title:%s" % _q(t)
                if all(o == t or self.count("(%s) AND %s" % (scope, _q(o))) for o in ts):
                    good.append(scope)
            if good:                                     # titles before headings
                about = " OR ".join("(%s)" % g for g in good)
                cands = self.rows(about, 40)
            else:
                for t in [t for t in anchors if t not in in_title]:
                    ids = heads[t]
                    marks = ",".join("?" * len(ids))
                    if all(o == t or self.db.execute(
                            "SELECT 1 FROM passages_fts WHERE passages_fts MATCH ? AND rowid IN (%s) "
                            "LIMIT 1" % marks, [_q(o)] + ids).fetchone() for o in ts):
                        good.append("heading:%s" % _q(t))
                        under.update(ids)
                if good:
                    about = " OR ".join("(%s)" % g for g in good)
                    cands, only = sorted(under), under
            # if none, a heading the question says outright may still be it
            # ("How do I build a snow CAVE?" - nothing under "SNOW CAVE" says
            # "build"): said(), below
        elif self.meta.get("kind") == "documents" and in_title:
            every = " AND ".join(_q(t) for t in ts)
            titled = " OR ".join("title:%s" % _q(t) for t in in_title)
            # the words the title does not say must stand close together in
            # the text; the ones it does say need only be there
            loose = [t for t in ts if t not in in_title]
            match = "(%s) AND (%s)" % (every, titled)
            if len(loose) > 1:
                match += " AND (text:NEAR(%s, %d))" % (" ".join(_q(t) for t in loose), NEAR)
            elif len(loose) == 1 and len(in_title) >= 2:
                match += " AND (text:%s)" % _q(loose[0])
            elif len(loose) == 1:
                # one word, somewhere in a document whose title says one
                # other: too little to be sure on ("What should I PLANT in
                # SPRING?" - "Plants as Indicator of Ground Water", page 100;
                # "a good BOOK about SURVIVAL" - a log book, page 175)
                match = ""
            cands = [r for r in (self.rows(match, 200) if match else []) if self._leaflet(r)]
            one_title = self.rows(" AND ".join("title:%s" % _q(t) for t in ts), 1)
            if cands and not loose and one_title:
                # The question is the document's own subject ("What is
                # giardia?" - "Giardia: Drinking Water Factsheet"): it is
                # read from its top.
                first = self.db.execute(
                    "SELECT q.id FROM passages p JOIN passages q ON q.doc = p.doc "
                    "WHERE p.id = ? ORDER BY q.seq LIMIT 1", (one_title[0],)).fetchone()
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
            cands = []
        if not cands:
            # ... or a title or a heading that the question itself says
            return self.said(ts, words)
        return self._weigh(self.passage(self.choose(cands, ts, words, about, only)), asked, ts)

    def _weigh(self, hit: Optional[dict], asked: set, ts: List[str]) -> Optional[dict]:
        """Between collections: the hit whose own title and heading say more
        of the question, then the collection that says more about it. "How
        do I build a fire?": "FIRES: Building the Fire" says two words, a
        medicine's "Fire warning" one."""
        if hit:
            own = stems(hit["title"]) | stems(hit["heading"])
            hit["weight"] = (len(own & asked), len(own & asked) / max(1, len(own)),
                             sum(self.df(t) / self.n for t in ts))
        return hit

    def _leaflet(self, rowid: int) -> bool:
        """Is this passage in a short document - one whose title is the
        subject of every page of it? "Purifying Water During an Emergency" is
        two pages on that. A handbook of two hundred is about its title only
        loosely: "How do I store my WINTER clothes?" found "store" and
        "clothes" near each other under "COOKING OF MEATS", in the Winter
        Survival Course Handbook."""
        if not hasattr(self, "_sizes"):
            self._sizes = dict(self.db.execute("SELECT doc, count(*) FROM passages GROUP BY doc"))
        doc = self.db.execute("SELECT doc FROM passages WHERE id = ?", (rowid,)).fetchone()
        return bool(doc) and self._sizes.get(doc[0], 0) <= LEAFLET

    def _heads(self, term: str, asked: set) -> List[int]:
        """The passages under a heading that says this word, of which the
        question says half or more: "FROSTBITE", "SIGNS AND SYMPTOMS OF
        HYPOTHERMIA" for "the signs of hypothermia", "Snow Cave" under
        "MAN-MADE SHELTERS". A word that is one among several is not what the
        section is about: "list my files" was shown "If you have insurance,
        contact your insurance agent to file a claim"; "How do I BUILD a
        snow shelter?", "3-6. BUILDING ARCTIC TENTS"."""
        out: List[int] = []
        for (heading,) in self.db.execute(
                "SELECT DISTINCT heading FROM passages WHERE id IN "
                "(SELECT rowid FROM passages_fts WHERE passages_fts MATCH ? LIMIT 400)",
                ("heading:" + _q(term),)):
            for part in parts(heading or ""):
                said = stems(part)
                if stem(term) in said and 2 * len(said & asked) >= len(said):
                    out += [r[0] for r in self.db.execute(
                        "SELECT id FROM passages WHERE heading = ? LIMIT 60", (heading,))]
                    break
        return sorted(set(out))[:300]

    def _names_a_title(self, term: str) -> bool:
        """Does some document's title open with this word, or consist of it?"""
        for (title,) in self.db.execute(
                "SELECT DISTINCT d.title FROM passages p JOIN docs d ON d.id = p.doc "
                "WHERE p.id IN (SELECT rowid FROM passages_fts WHERE passages_fts MATCH ? LIMIT 400)",
                ("title:" + _q(term),)):
            ws = [stem(w) for w in all_words(title)]
            if ws and (ws[0] == stem(term) or set(ws) == {stem(term)}):
                return True
        return False

    def said(self, ts: List[str], words: List[str]) -> Optional[dict]:
        """The passage under a title or heading that the question itself says.

        "What should I do during a flood?" names the page "Floods"; "How do I
        prepare for a hurricane?" names the section "Prepare for Hurricanes".
        Neither word is rare on a site about disasters, so rarity cannot see
        them - the first measurement on Ready.gov found 6 of 20.

          - a document's TITLE whose every word the question says: "Floods",
            "Extreme Heat", "Power Outages";
          - a title or HEADING of which the question says at least two words
            and at least three in five: "Staying Safe After a Flood".
        One word of a longer title, or a one-word heading inside a manual
        ("WEATHER", "WATER", "TIME"), is not the question's subject: "What is
        the weather like?" is not "Severe Weather".
        And every word that carries the question must be said somewhere in
        that document.
        """
        asked = {stem(w) for w in words} | {stem(t) for t in ts}
        known = [w for w in words if self.df(w)]
        if not known:
            return None
        try:
            rows = self.db.execute(
                "SELECT rowid FROM passages_fts WHERE passages_fts MATCH ? "
                "ORDER BY bm25(passages_fts, 6.0, 4.0, 0.0) LIMIT 300",
                ("{title heading}:(%s)" % " OR ".join(_q(w) for w in known),)).fetchall()
        except sqlite3.Error:
            return None
        best, seen = None, set()
        for (rowid,) in rows:
            r = self.db.execute("SELECT p.doc, p.heading, d.title FROM passages p JOIN docs d "
                                "ON d.id = p.doc WHERE p.id = ?", (rowid,)).fetchone()
            for kind, text in (("heading", r[1] or ""), ("title", r[2] or "")):
                key = (r[0], kind, text)
                if not text or key in seen:
                    continue
                seen.add(key)
                said, hit = set(), set()
                for part in (parts(text) if kind == "heading" else [text]):
                    s_, h_ = stems(part), stems(part) & asked
                    ok = (kind == "title" and s_ and s_ <= asked) or \
                         (len(h_) >= 2 and len(h_) >= 0.6 * len(s_))
                    if ok and (len(h_), len(h_) / len(s_)) > (len(hit), len(hit) / max(1, len(said))):
                        said, hit = s_, h_
                if not hit:
                    continue
                lo, hi = self.db.execute("SELECT min(id), max(id) FROM passages WHERE doc = ?",
                                         (r[0],)).fetchone()
                if any(not self.db.execute(
                        "SELECT 1 FROM passages_fts WHERE passages_fts MATCH ? AND rowid BETWEEN ? "
                        "AND ? LIMIT 1", (_q(t), lo, hi)).fetchone() for t in ts):
                    continue
                rank = (len(hit), len(hit) / len(said), kind == "heading")
                if best is None or rank > best[0]:
                    best = (rank, r[0], kind, text, lo, hi)
        if best is None:
            return None
        _, doc, kind, text, lo, hi = best
        if kind == "heading":
            first = self.db.execute("SELECT min(id) FROM passages WHERE doc = ? AND heading = ?",
                                    (doc, text)).fetchone()[0]
        else:
            # in a document named for a word, that word chooses no passage:
            # every passage of "Earthquakes" is about earthquakes
            named = stems(text)
            first = self.within(lo, hi, [w for w in words if stem(w) not in named])
        return self._weigh(self.passage(first), asked, ts)

    def within(self, lo: int, hi: int, words: List[str]) -> int:
        """In one document, the passage the words point at - a word in its
        own heading twice a word in its text, each by how rare it is - or its
        first passage: a page is read from its top."""
        score: Dict[int, float] = {}
        for w in [w for w in words if self.df(w)]:
            rarity = math.log(self.n / (1.0 + self.df(w))) + 0.1
            for col, worth in (("heading", 2.0), ("text", 1.0)):
                try:
                    for (rowid,) in self.db.execute(
                            "SELECT rowid FROM passages_fts WHERE passages_fts MATCH ? "
                            "AND rowid BETWEEN ? AND ?", ("%s:%s" % (col, _q(w)), lo, hi)):
                        score[rowid] = score.get(rowid, 0.0) + worth * rarity
                except sqlite3.Error:
                    pass
        if not score:
            return lo
        top = max(score.values())
        return min(r for r, v in score.items() if v >= top - 1e-9)

    def choose(self, cands: List[int], ts: List[str], words: List[str],
               about: Optional[str] = None, only: Optional[set] = None) -> int:
        """Of passages that all qualify, the one to show first.

        With nothing to say what it is about (`about` is None: a shelf of
        leaflets, or a look-up of loose words) the order the words themselves
        gave stands.

        Otherwise the passage is looked for among everything that is about
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
        if not about or not cands:
            return cands[0]
        asked = set(words) | set(ts)
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
        if only is not None:
            score = {r: v for r, v in score.items() if r in only}
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
        # All of them in one passage, or it is not about that: "the capital of
        # France" found "capital" in one manual's passage and "France" in
        # none. When every word is in the collection but no one passage says
        # them all, the commonest are let go one at a time - never below two
        # together: "finding north without a compass" is answered where
        # "north" and "compass" meet.
        keep = sorted(known, key=lambda t: self.df(t))
        while keep:
            rows = self.rows(" AND ".join(_q(t) for t in keep), 40)
            if rows:
                hit = self.passage(rows[0])
                if hit:
                    # between collections: the one that says more of it, then
                    # more about it. "bleach" is in 3 of 12313 medicine
                    # passages (it can bleach your hair) and 26 of 897 on water.
                    hit["weight"] = (len(keep) / len(ts),
                                     sum(self.df(t) / self.n for t in keep))
                return hit
            if len(known) < len(ts) or len(keep) <= 2:
                return None
            keep = keep[:-1]
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
