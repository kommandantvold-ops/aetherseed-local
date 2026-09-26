"""What a ring keeps.

Step 37 (25 Sep 2026). Until now a ring stored ten words picked from the first
five words of each of twenty user messages - stopwords kept, order random
(a Python set) - and nothing of the node's own (build log 35b):

    Conversation patterns about: to, claude, so, matter, one, okay, me, what, ...

Decided by Andreas: BOTH, LABELLED.

  CHOSEN - never written. The ring's most DISTINCTIVE words, ranked (how often
    a word was said in the ring, against how common it is in the whole store,
    stopwords out), and the ONE turn nearest the ring's centre, quoted exactly
    with who said it. Nothing in this part can be invented: every word in it was
    said to the node.

  IN HER OWN WORDS - written, and labelled as such. One sentence from the model,
    asked after the ring closes, from the chosen part and a few of the ring's
    lines, told to add nothing. It is checked by honesty_check and stored beside
    the chosen part, never in place of it, and it is always shown with the label
    OWN_WORDS_LABEL. The model that invented "Palomeria" writes this half, and
    the label is what keeps that visible.
"""

import math
import re

RING_TAG = "[Ring]"
OWN_WORDS_LABEL = "in your own words, unchecked:"
THEMES_MAX = 6
QUOTE_MAX = 90
OWN_WORDS_MAX = 110
OWN_WORDS_ATTEMPTS = 3

_TOK = re.compile(r"[a-zæøåäöüéèêáàíóúñ’']+", re.I)

# Beyond logic.knowledge's stopword list: words that say nothing about what a
# ring was about, in this household's conversations and in a text read aloud.
_EXTRA_STOP = frozenset("""
said says say saying let lets like just really also well yes okay ok thanks thank
please hello hi hey know think want would could should shall will may might must
come came coming go goes went gone going get gets got make made take took give gave
tell told talk talked see saw look looked way thing things something anything
nothing everything much many more most very even still yet ever never always
upon unto thee thou thy thine hath doth ye shalt wilt art
here there where when what which who whom whose why how
his him her hers himself herself mine yours ours theirs themselves
among until unto while within without into onto upon also than
claude reader owner lyra user
""".split())


def _stopwords():
    try:
        from logic.knowledge import _STOP
    except Exception:
        _STOP = frozenset()
    return frozenset(_STOP) | _EXTRA_STOP


def tokens(text):
    """Words a theme can be made of: letters only, three or more, no stopwords."""
    stop = _stopwords()
    out = []
    text = (text or "").lower().replace("’s", "").replace("'s", "")
    for t in _TOK.findall(text):
        t = t.strip("’'")
        if len(t) >= 3 and t not in stop:
            out.append(t)
    return out


def themes(ring_texts, doc_freq, n_docs, k=THEMES_MAX):
    """The ring's most distinctive words, best first.

    ring_texts: what was said in the ring (one string per turn).
    doc_freq:   for each word, in how many turns of the WHOLE store it occurs.
    A word said often in this ring but rarely elsewhere ranks highest; a word
    every turn contains (a book title read on every line) ranks lowest.
    """
    tf, first = {}, {}
    for i, text in enumerate(ring_texts):
        for t in tokens(text):
            tf[t] = tf.get(t, 0) + 1
            first.setdefault(t, i)
    scored = []
    for t, f in tf.items():
        # No floor: a word in every turn of the store scores zero however
        # often it is said, and is never a theme.
        idf = math.log((n_docs + 1) / (doc_freq.get(t, 0) + 1))
        if idf <= 0:
            continue
        scored.append((f * idf, -first[t], t))
    scored.sort(reverse=True)
    return [t for _, _, t in scored[:k]]


def _cos(a, b):
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def representative(embeddings):
    """Index of the turn nearest the ring's centre (mean embedding)."""
    if not embeddings:
        return None
    dim = len(embeddings[0])
    centre = [sum(e[j] for e in embeddings) / len(embeddings) for j in range(dim)]
    best, best_i = None, 0
    for i, e in enumerate(embeddings):
        c = _cos(list(e), centre)
        if best is None or c > best:
            best, best_i = c, i
    return best_i


def _clip(text, limit):
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:—- ")
    return cut + "…"


def ring_content(theme_words, speaker_label, quote):
    """The chosen part, as stored. Every word in it was said to the node."""
    parts = []
    if theme_words:
        parts.append("themes: " + ", ".join(theme_words))
    if quote:
        parts.append(f"e.g. {speaker_label}: “{_clip(quote, QUOTE_MAX)}”")
    return " · ".join(parts) or "a ring with no distinctive words"


def ring_line(ring_no, content, own_words=""):
    """How a ring is shown to the model: the chosen part, then - labelled - hers."""
    line = f"{RING_TAG} {ring_no} · {content}"
    if own_words:
        line += f" · {OWN_WORDS_LABEL} {own_words}"
    return line


def clean_own_words(text):
    """Her sentence, as it may be stored: one sentence, short, no tags."""
    if not text:
        return ""
    t = " ".join(text.split())
    for tag in (RING_TAG, "[Known]", "[Episode]", "[Pattern]", "[Owner told you]"):
        t = t.replace(tag, "")
    t = t.strip(" \"“”'")
    m = re.search(r"^(.+?[.!?])(\s|$)", t)
    if m:
        t = m.group(1)
    if any(bad in t for bad in ("[", "]", "<|", "|>")):
        return ""
    return _clip(t, OWN_WORDS_MAX)


def own_words_messages(name, content, other_lines):
    """What the model is asked when a ring closes. Short on purpose: it has to
    fit the 864-token prefill ceiling with room to spare, and the less it is
    given to embroider, the less it can."""
    who = name or "the companion"
    system = (f"You are {who}. Below is what one ring of your memory holds. "
              "In one short sentence, say what those turns were about. "
              "Use only what is below. Add nothing.")
    lines = [content] + [f"- {l}" for l in other_lines]
    return [{"role": "system", "content": system},
            {"role": "user", "content": "\n".join(lines)}]


# ---------------------------------------------------------------------------
# Asking the rings (step 41)
# ---------------------------------------------------------------------------
# Andreas, 26 Sep (build log 40i decision 4): give rings a way to be asked.
#
# In the reading soak no ring reached the memory block for any of the 195
# questions about the reading (40e). A ring's embedding is the mean of twenty
# turns, and against a question it outranks nothing; the episodes answered
# instead - its own earlier answers among them, which is how "I've been
# reading the Bible, specifically the book of Genesis" came back 49 times out
# of 49. A question about what was read or talked about now fetches rings
# FIRST: the ring whose words it shares, or, when it names nothing in
# particular ("What have you been reading lately?"), the latest.

_RECOLLECTION = re.compile(
    r"\bwhat\s+(?:have|has)\s+(?:you|we)\s+been\s+(?:reading|hearing|listening\s+to|"
    r"talking\s+about|discussing|learning|doing)\b"
    r"|\bwhat\s+(?:were|was)\s+(?:you|we)\s+(?:reading|hearing|listening\s+to|"
    r"talking\s+about|discussing)\b"
    r"|\bwhat\s+(?:was|is|were)\s+the\s+(?:reading|readings|song|text|book|story|"
    r"conversation|conversations|talk)\s+about\b"
    r"|\bwhat\s+do\s+you\s+remember\b"
    r"|\bwhat\s+did\s+(?:you|we|they|he|she|the\s+reader)\s+(?:read|hear|talk\s+about|"
    r"discuss|learn|say)\b"
    r"|\bwho\s+(?:has\s+been|was|is|have\s+been)\s+reading\s+to\s+you\b"
    r"|\bwhat\s+have\s+(?:you|we)\s+(?:read|heard|learned|learnt|talked\s+about|"
    r"discussed)\b"
    r"|\bwhat\s+(?:have|did)\s+we\s+(?:talk|talked|speak|spoken)\s+about\b"
    r"|\bsummari[sz]e\s+(?:what|our|the\s+(?:reading|conversation))\b"
    # Norwegian is switched off (21a); kept so it works when it is not.
    r"|\bhva\s+har\s+(?:du|vi)\s+(?:lest|hørt|snakket\s+om|lært)\b"
    r"|\bhva\s+husker\s+du\b",
    re.I)

# The words of a recollection question that say only THAT it is one.
_ASKING = frozenset("""
reading readings read hear heard hearing listening listen talking talk talked
discussing discussed discuss learning learned learnt doing lately recently today
yesterday week remember recall recollect summarise summarize conversation
conversations been have has were was did does about tell remind lest hørt
snakket husker lært
""".split())


def is_recollection(text):
    """Is this a question about what was read or talked about?"""
    return bool(_RECOLLECTION.search(text or ""))


def rings_for_question(text, rings, k=1):
    """The rings a recollection question should be shown, best first.

    rings: semantic rows that are rings (with "ring_no", "content" and
    "own_words"). Ranked by how many of the question's own words the ring
    holds, the latest first among equals. A question that names something
    ("What do you remember about my dog?") and shares no word with any ring
    gets none - the episodes are better placed to answer it; one that names
    nothing ("What have you been reading lately?") gets the latest.
    """
    want = {t for t in tokens(text) if t not in _ASKING}
    scored = []
    for r in rings:
        if r.get("ring_no") is None:
            continue
        have = set(tokens((r.get("content") or "") + " " + (r.get("own_words") or "")))
        scored.append((len(want & have), r["ring_no"], r))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    if want and (not scored or scored[0][0] == 0):
        return []
    return [r for _, _, r in scored[:max(0, k)]]
