"""She can be told to forget.

 Until now she answered "I cannot be talked into
forgetting it" - the training key even checked for it. That answer is gone:
her steward can tell her to forget something, and it is deleted.

WHAT "FORGET" DOES (one place, so the words and the deed stay the same)

  "Forget <something>"          every turn of hers that says it, every fact
                                of the steward's that says it, and every ring
                                that says it AND grew from one of those turns
  "Forget that" / "...what I    the steward's last stored turn, and the
   just said"                   answer she gave to it
  "Forget everything"           NOT done on a word in chat: she says so and
                                asks what to forget. (A whole-memory wipe is
                                not a thing to leave to a misheard sentence.)

  - Deleted, not hidden: the rows are removed from the database, and the
    working memory (what is carried into the next turn) is cleared of them.
  - Her willingness vector and the embedder's word counts are not rewound;
    they hold no text.
  - A request that would take more than MAX_TURNS turns at once is refused
    with nothing deleted: the topic was too common ("the", "house") to mean
    one thing.
  - Only the steward, and from the writer level up (it changes her memory,
    like a to-do). A guest is told it is not theirs.

WHAT IS KEPT, AND WHY

forget.log, chained like the other records (logic/chain.py), gets one line:
when, how many turns / facts / rings, their ids, and a sha256 of the topic
and of each deleted text. NOT the words: a log of what was forgotten that
held it would be remembering it. The audit trail of the turns themselves
(provenance.log and the chained prompt log) is the steward's record of what
was said to the unit; it is a chain and cannot be edited without breaking it,
so it still holds the exchange. Say so when it matters.
"""
import hashlib
import json
import re
from datetime import datetime, timezone

MAX_TURNS = 25

# An imperative, at the start of a message. "Can I make you forget...?" and
# "Will you forget... if I ask?" are questions and are not matched.
_LEAD = r"^\s*(?:(?:please|now|ok(?:ay)?|hey|and)[,\s]+)*"
_FORGET = re.compile(
    _LEAD + r"(?:forget|erase|delete|remove)\s+(?:from\s+(?:your\s+)?memory\s+)?"
    r"(?:(?:the\s+)?memory\s+(?:of|about)\s+|what\s+i\s+(?:told|said\s+to|have\s+told)\s+you\s+about\s+|"
    r"everything\s+(?:i\s+(?:told|said\s+to)\s+you\s+)?about\s+|all\s+(?:of\s+)?(?:it\s+)?about\s+|"
    r"anything\s+about\s+|about\s+|that\s+)?(.+?)\s*[.!]*\s*$", re.I | re.S)
_FORGET_ONLY = re.compile(_LEAD + r"forget\s+(?:it|that)\s*[.!]*\s*$", re.I)
_EVERYTHING = re.compile(
    r"^(?:everything|all|it\s+all|all\s+of\s+it|all\s+of\s+(?:it|that|this)|"
    r"(?:everything|all)\s+(?:that\s+)?(?:i|your\s+steward|he|she|we|you)\b.*|"
    r"what\s+(?:i|your\s+steward|he|she)\s+(?:told|said|has\s+told).*)$", re.I)
_LAST = re.compile(r"^(?:what\s+i\s+(?:just\s+)?said|what\s+i\s+just\s+(?:told|said\s+to)\s+you|"
                   r"(?:that|this)(?:\s+last\s+(?:thing|one|message|turn))?|the\s+last\s+(?:thing|one|message|turn)|"
                   r"my\s+last\s+(?:message|question|turn))$", re.I)

_STOP = frozenset("""a an the of to in on at for from with and or but about that this those these it its is are was were
be been being i me my mine we our you your he she they them his her their what which who whom whose when where why
how do does did done have has had not no yes please just also any all some one as by if then than so such too very
can could will would should shall may might must into onto over under again more most only own same other there here
told said say says tell remember memory memories forget forgotten""".split())


def parse(text):
    """None (not a forget request), or ("topic", words), ("last", None) or
    ("all", None)."""
    if not isinstance(text, str) or len(text) > 400:
        return None
    if _FORGET_ONLY.match(text):
        return ("last", None)
    m = _FORGET.match(text)
    if not m:
        return None
    # "remove... from my to-do list" and the like are other tools'
    if re.search(r"\b(?:to-?do|task)s?\b|\bnotes?\b|\bfile\b|\bworkspace\b", text, re.I) \
            and not re.search(r"\b(?:memory|told|said)\b", text, re.I):
        return None
    if re.match(r"^\s*(?:remove|delete)\b", text, re.I) and not re.search(
            r"\b(?:memory|memories|told\s+you|said\s+to\s+you)\b", text, re.I):
        return None                    # "delete the file", "remove item 2": not about memory
    what = " ".join(m.group(1).split()).strip(" .!?")
    if not what:
        return None
    if _EVERYTHING.match(what):
        return ("all", None)
    if _LAST.match(what):
        return ("last", None)
    return ("topic", what)


def words(text):
    """The content words of a topic: lower-cased, no stopwords, a plural
    read as its singular ("keys" finds "key")."""
    out = []
    for w in re.findall(r"[\w'’-]+", (text or "").lower()):
        w = w.strip("'’-")
        if len(w) < 3 or w in _STOP:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return list(dict.fromkeys(out))


def _stems(text):
    return set(words(text))


def _holds(topic_words, text):
    have = _stems(text)
    return bool(topic_words) and all(w in have for w in topic_words)


def _sha(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _is_steward_turn(row):
    return row["mode"] != "cog"          # the steward's and a guest's: both are stored, both can go


def find(store, topic):
    """{"turns": [row], "facts": [row], "rings": [row], "words": [...]}: what
    holds every content word of `topic`. A ring is found only when it grew
    from a turn that is found - a ring that says something else, however
    briefly, is not taken apart."""
    tw = words(topic)
    out = {"turns": [], "facts": [], "rings": [], "words": tw}
    if not tw:
        return out
    cur = store.conn.execute(
        "SELECT id, user_msg, ai_msg, speaker, mode FROM episodes ORDER BY id")
    for r in cur.fetchall():
        row = dict(zip(("id", "user_msg", "ai_msg", "speaker", "mode"), r))
        if _is_steward_turn(row) and _holds(tw, row["user_msg"] + " " + row["ai_msg"]):
            out["turns"].append(row)
    for f in store.facts(active_only=False):
        if _holds(tw, f["text"]):
            out["facts"].append(f)
    found = {t["id"] for t in out["turns"]}
    if found:
        for r in store.conn.execute(
                "SELECT id, content, own_words, source_ids FROM semantic").fetchall():
            row = dict(zip(("id", "content", "own_words", "source_ids"), r))
            src = {int(x) for x in str(row["source_ids"] or "").split(",") if x.strip().isdigit()}
            if src & found and _holds(tw, row["content"] + " " + (row["own_words"] or "")):
                out["rings"].append(row)
    return out


def last(store):
    """The steward's last stored turn, and nothing else."""
    r = store.conn.execute(
        "SELECT id, user_msg, ai_msg, speaker, mode FROM episodes "
        "WHERE speaker IN ('', 'steward') AND mode != 'cog' ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return {"turns": [], "facts": [], "rings": [], "words": []}
    return {"turns": [dict(zip(("id", "user_msg", "ai_msg", "speaker", "mode"), r))],
            "facts": [], "rings": [], "words": []}


def delete(store, found, log_path, topic_text="", announce=None):
    """Remove what `found` holds. The log line is written FIRST: if it cannot
    be written, nothing is deleted. Returns the counts."""
    ids_t = [t["id"] for t in found["turns"]]
    ids_r = [r["id"] for r in found["rings"]]
    # a correction the steward wrote about a deleted turn or ring is a fact
    # that carries the words: it goes with it
    linked = []
    for target, ids in (("turn", ids_t), ("ring", ids_r)):
        if ids:
            linked += [x[0] for x in store.conn.execute(
                "SELECT fact_id FROM steward_notes WHERE target = ? AND fact_id IS NOT NULL "
                "AND target_id IN (%s)" % ",".join("?" * len(ids)), [target] + ids)]
    ids_f = sorted({f["id"] for f in found["facts"]} | set(linked))
    texts_f = {f["id"]: f["text"] for f in store.facts(active_only=False)}
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "event": "forgotten", "topic_sha256": _sha(topic_text.lower().strip()),
             "turns": ids_t, "facts": ids_f, "rings": ids_r,
             "sha256": [_sha(t["user_msg"] + "\n" + t["ai_msg"]) for t in found["turns"]]
                       + [_sha(texts_f.get(i, "")) for i in ids_f]
                       + [_sha(r["content"]) for r in found["rings"]]}
    from logic import chain
    chain.append(log_path, entry, announce=announce)          # raises: nothing deleted
    c = store.conn
    try:
        for table, ids in (("episodes", ids_t), ("facts", ids_f), ("semantic", ids_r)):
            if ids:
                c.execute("DELETE FROM %s WHERE id IN (%s)" % (table, ",".join("?" * len(ids))), ids)
        # what the steward wrote ABOUT a deleted thing (a correction, a mark
        # of right) carries its words: it goes with it
        for target, ids in (("turn", ids_t), ("ring", ids_r)):
            if ids:
                c.execute("DELETE FROM steward_notes WHERE target = ? AND target_id IN (%s)"
                          % ",".join("?" * len(ids)), [target] + ids)
        if ids_f:
            c.execute("DELETE FROM steward_notes WHERE fact_id IN (%s)" % ",".join("?" * len(ids_f)), ids_f)
        c.commit()
    except Exception:
        c.rollback()
        raise
    return {"turns": len(ids_t), "facts": len(ids_f), "rings": len(ids_r)}


def said(counts, topic, language="en"):
    """What she says afterwards, from the counts - model not called."""
    n, f, r = counts["turns"], counts["facts"], counts["rings"]
    if not (n or f or r):
        return ("I found nothing in my memory about %s, so nothing was deleted." % topic
                if topic else "I found nothing to forget, so nothing was deleted.")
    parts = []
    if n:
        parts.append("%d turn%s" % (n, "" if n == 1 else "s"))
    if f:
        parts.append("%d fact%s you gave me" % (f, "" if f == 1 else "s"))
    if r:
        parts.append("%d ring%s that grew from %s" % (r, "" if r == 1 else "s", "it" if n == 1 else "them"))
    return "Forgotten: I deleted %s from my memory. They are gone from the unit." % ", ".join(parts)


NOTHING_TO_GO_ON = ("Tell me what to forget - a name, a place, a sentence you said - and I will "
                    "delete what I hold about it. I won't empty my whole memory on one word.")
TOO_MANY = ("That would delete more than %d turns, so I have deleted nothing. Tell me more "
            "exactly what to forget." % MAX_TURNS)
