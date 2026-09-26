"""Does an answer that credits the owner have the owner behind it?

Decided by Andreas on 26 September 2026 (build log 40i, decision 2; step 41):
an answer that credits the owner with no owner fact shown, or with content
that is not in what was shown, is tagged and kept out of memory.

Why (build log 38f, 40c): over the 24-hour reading soak, 254 answers said
"my owner told me". Read by hand, 83 of them put something in the owner's
mouth that he never entered - 59 an invented or false fact, 24 an
interpretation - and without the right verse in front of the model, half of
them were inventions (43 of 85). The phrase the mechanism asks for is not
evidence that the owner said it:

    "My owner told me that after Enoch's death, Methuselah lived to be 195
    years old."   Genesis 5:27 says nine hundred sixty-nine; 5:24 says God
    took Enoch. The verses shown on that turn gave neither.

What this checks, and only this: the sentences of an answer that credit the
owner - "my owner told me...", the copied "[Owner told you]", and the
"According to them..." / "They said..." that continue such a sentence -
against the owner's facts that were shown on that turn, word for word:

  - no owner fact shown at all              -> unbacked
  - a figure the shown facts do not contain -> unbacked ("195" against
                                               "nine hundred sixty-nine")
  - a sentence whose content words are mostly not in the shown facts
                                            -> unbacked

It is mechanical and it can be wrong in both directions: a faithful answer in
other words than the owner's can be flagged, and a miscopy that changes only
a small word ("there were morning") passes. The thresholds were set against
the 254 hand-labelled answers of the soak (build log 41). An owner who tells
the node something in conversation rather than as an entered fact is not
covered here: "you told me" is not checked, because the speaker's own words
live in the episodes, not in the fact store.
"""
import re

from logic.facts import FACT_TAG

# ---------------------------------------------------------------------------
# Who is credited
# ---------------------------------------------------------------------------

# Third person only. "You told me" is the speaker, not the owner: when the
# owner is speaking it is backed by the episodes, which this does not read.
_OWNER_CREDIT = re.compile(
    r"\b(?:my|our|the)\s+owner(?:['’]s)?\b"
    r"|\bowner\s+(?:has\s+|had\s+)?(?:told|said|says|shared|mentioned|taught|"
    r"entered|gave|explained)\b"
    r"|" + re.escape(FACT_TAG.lower()),
    re.I)

# "According to them, ..." / "They said ..." - the owner again, by pronoun,
# once the answer has named the owner.
_PRONOUN_CREDIT = re.compile(
    r"\baccording\s+to\s+(?:them|him|her)\b"
    r"|\b(?:they|he|she)\s+(?:also\s+)?(?:said|say|says|mentioned|told|shared|"
    r"explained|added|noted|described|consider|considers|believe|believes)\b",
    re.I)

# A sentence that gives its content to somebody else - its own knowledge, the
# Bible, "some cultures" - is not the owner's, and it ends the owner's run.
_OTHER_SOURCE = re.compile(
    r"\baccording\s+to\s+(?:the\s+|my\s+|biblical\s+|this\s+|some\s+|many\s+|"
    r"what\s+i\s+know|other\s+)?(?:bible|biblical|knowledge|account|accounts|"
    r"scripture|scriptures|text|texts|story|stories|genesis|tradition|"
    r"traditions|memory|sources?|records?|sources|legend|legends|history)\b"
    r"|\b(?:the\s+bible|genesis|scripture|the\s+text|the\s+story)\s+"
    r"(?:says|states|describes|mentions|tells|records|recounts)\b"
    r"|\bin\s+the\s+bible\b|\bmy\s+(?:own\s+)?knowledge\b"
    r"|\bI\s+(?:also\s+)?know\s+that\b"
    r"|\b(?:some|many|other)\s+(?:people|cultures|scholars|traditions|sources)\b",
    re.I)

# The node talking about its own knowing - "I don't know...", "I may be
# incomplete...", "(Note: ...)". It asserts nothing about the world, so it is
# not checked; it does not end the owner's run either. A sentence that names
# the owner is always checked, hedge or not: "My owner told me that she was
# stoned to death..., but I couldn't find any reliable sources" is the case
# that has to be caught (build log 40f).
_HEDGE = re.compile(
    r"\bI\s*(?:do\s+not|don['\u2019]?t|did\s+not|didn['\u2019]?t|can['\u2019]?t|"
    r"cannot|could\s+not|couldn['\u2019]?t|am\s+not|['\u2019]m\s+not|may|might|"
    r"have\s+no|am\s+unsure|['\u2019]m\s+unsure|was\s+just|wasn['\u2019]?t)\b"
    r"|\b(?:my|your|this)\s+answer\s+(?:may|might)\b"
    r"|^\W*\(?\s*note\b"
    # talk to the person rather than about the world
    r"|\byour\s+turn\b|\bask\s+(?:me\s+)?(?:another|a|any)\s+question"
    r"|\bfeel\s+free\b|\blet\s+me\s+know\b|\banything\s+else\b",
    re.I)

# ---------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------

_REFERENCE = re.compile(
    r"\(?\s*\b(?:genesis|gen\.?)\s*\d+(?:\s*:\s*\d+)?(?:\s*[-–]\s*\d+)?"
    r"(?:\s*(?:,|and)\s*\d+)*\s*\)?"
    r"|\b(?:chapters?|verses?)\s+\d+(?:\s*[-–]\s*\d+)?"
    r"|\b\d+\s*:\s*\d+(?:\s*[-–]\s*\d+)?",
    re.I)

_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
          "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
          "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
          "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
          "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
             "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
             "eleventh": 11, "twelfth": 12, "twentieth": 20, "hundredth": 100}
_SCALES = {"hundred": 100, "thousand": 1000}
NUMBER_WORDS = frozenset(_UNITS) | frozenset(_TENS) | frozenset(_ORDINALS) | frozenset(_SCALES)

# Function words, and the words an answer uses to talk about its own knowing
# and telling rather than about the world. Neither is content.
_STOP = frozenset("""
a about above across after again against all almost along also although always am
among an around beside beyond near onto per via
and another any anyone anything are around as at away be because been before
being below between both but by can cannot could did do does doing done down
during each either else even ever every for from further had has have having he
her here hers herself him himself his how however i if in into is it its itself
just least less let like made make many may me might mine more most much must my
myself neither never no nor not now of off often on once one only or other our
ours ourselves out over own perhaps quite rather really same shall she should
since so some something such than that the their theirs them themselves then
there therefore these they this those though through thus to too toward towards
under until up upon us very was we were what whatever when where whether which
while who whom whose why will with within without would yet you your yours
yourself yourselves s t d ll m re ve isn aren wasn weren don doesn didn won
wouldn shouldn couldn can't it's that's there's what's i'm i've i'd i'll
owner owners told tell tells telling said say says saying shared share sharing
mentioned mention according memory context know known knew knowledge sure
unsure think thought believe details detail specific specifically information
info answer answers question questions missing incomplete complete perspective
understanding provided provide providing claim claiming based sources source
reliable find found note noted remember recall recalled seems seem seemingly
maybe possibly probably actually exactly basically generally mostly certain
simply wait sorry please thanks okay ok yes well something someone
bible biblical scripture scriptures account accounts book story stories event
events happen happened passage verse verses translation translations version
versions depending exact specific additional similar different alternative
accurate clear type kind sort specified incomplete interpretation
interpretations age
""".split())


def _stem(w):
    """Crude and the same on both sides, which is all it has to be:
    "languages" and "language" both become "languag"."""
    for suf, rep in (("ies", "y"), ("ing", ""), ("ion", ""), ("ed", ""),
                     ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: len(w) - len(suf)] + rep
            break
    if w.endswith("e") and len(w) > 4:
        w = w[:-1]
    return w


def _tokens(text):
    text = text.lower().replace("’", "'")
    return re.findall(r"[a-z]+(?:'[a-z]+)?", text)


def content_words(text):
    """The words that carry what a sentence says, stemmed: no function words,
    no numbers, no talk about knowing or telling, no chapter and verse."""
    text = _REFERENCE.sub(" ", text.replace(FACT_TAG, " "))
    out = []
    for w in _tokens(text):
        if w.endswith("'s"):
            w = w[:-2]
        if "'" in w or "genesis" in w:
            continue                      # don't, I'm, you're; "ofGenesis"
        if w in _STOP or w in NUMBER_WORDS or len(w) < 2:
            continue
        out.append(_stem(w))
    return out


def numbers(text):
    """Every figure in the text, as integers: digits, words ("nine hundred
    sixty-nine"), and ordinals ("seventh", "7th"). Chapter and verse are not
    figures, and neither is 1: "another one", "the first light" and "at first"
    are how English talks, not counts."""
    text = _REFERENCE.sub(" ", text).lower().replace("’", "'")
    found = set()
    for d in re.findall(r"\b\d[\d,]*\b", text):
        try:
            found.add(int(d.replace(",", "")))
        except ValueError:
            pass
    for d in re.findall(r"\b(\d+)(?:st|nd|rd|th)\b", text):
        found.add(int(d))
    words = re.findall(r"[a-z]+", text.replace("-", " "))
    total, current, in_number = 0, 0, False
    for w in words + ["."]:
        if w in _UNITS:
            current += _UNITS[w]
            in_number = True
        elif w in _TENS:
            current += _TENS[w]
            in_number = True
        elif w in _SCALES and in_number:
            current = max(current, 1) * _SCALES[w]
            if w == "thousand":
                total, current = total + current, 0
        elif w == "hundred":               # "a hundred"
            current, in_number = 100, True
        elif w == "and" and in_number:
            continue
        else:
            if in_number:
                found.add(total + current)
            total, current, in_number = 0, 0, False
            if w in _ORDINALS:
                found.add(_ORDINALS[w])
    found.discard(1)
    return found


_SENTENCE_END = re.compile(
    r"(?<=[.!?])\s+"                       # after . ! ?
    r"|(?<=[.!?][\u201d\"'\)\]])\s+"          # ... or after the quote or bracket closing it
    r"|(?<=\))\s+(?=[A-Z\[])"               # "(Genesis 29:18) I don't know..."
    r"|\n+")


def _sentences(text):
    parts = _SENTENCE_END.split(text.strip())
    return [p.strip() for p in parts if p and p.strip()]


def credits_owner(reply):
    return bool(_OWNER_CREDIT.search(reply or ""))


def credited_sentences(reply):
    """The sentences that put something in the owner's mouth.

    A sentence naming the owner starts a run, and the sentences after it stay
    in it - "My owner told me that God called the light day. There was
    evening and there was morning, the second day." is one telling - until a
    sentence gives its content to somebody else ("According to my knowledge,
    ...", "The Bible says ..."). After that, "According to them" or "They
    said" brings the owner back. When the owner is credited with nothing of
    its own - "My owner told me that." or a closing "That's what my owner
    shared with me." - the credit can only be for the answer as a whole, and
    every sentence is returned.
    """
    sentences = _sentences(reply or "")
    out, in_run, named = [], False, False
    for s in sentences:
        if _OWNER_CREDIT.search(s):
            out.append(s)
            in_run = named = True
        elif named and _PRONOUN_CREDIT.search(s):
            out.append(s)
            in_run = True
        elif _OTHER_SOURCE.search(s):
            in_run = False
        elif in_run:
            out.append(s)
    if named and sum(len(set(content_words(s))) for s in out) < MIN_WORDS:
        return sentences
    return out


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

MIN_WORDS = 2          # a sentence with fewer content words says too little to judge
COVERAGE = 0.7         # of a sentence's content words, at least this share in what was shown
                       # (both set against the 254 hand-labelled answers of the soak, step 41)

_CLAUSE = re.compile(r",?\s+but\s+|;\s+|,\s+however,?\s+|,?\s+though\b", re.I)


def check(reply, shown_facts):
    """What the answer credits to the owner, against what the owner's facts
    shown on this turn contain.

    Returns {"credited": False} when the owner is not credited. Otherwise
    {"credited": True, "backed": bool, "why": str, "figures": [...],
     "words": [found, total]}.
    """
    if not credits_owner(reply):
        return {"credited": False}
    shown = [f for f in (shown_facts or []) if f and f.strip()]
    if not shown:
        return {"credited": True, "backed": False,
                "why": "no owner fact was shown", "figures": [], "words": [0, 0]}
    fact_words = set(content_words(" ".join(shown)))
    fact_numbers = set()
    for f in shown:
        fact_numbers |= numbers(f)

    unshown_figures, found_all, total_all, weak = [], 0, 0, []
    for s in credited_sentences(reply):
        # "Jacob was named instead of his twin brother, but I don't know what
        # the name was": the first half asserts, the second only hedges.
        claims = [c for c in _CLAUSE.split(s)
                  if c.strip() and not (_HEDGE.search(c) and not _OWNER_CREDIT.search(c))]
        if not claims:
            continue                     # about its own knowing, not the world
        claim = " ".join(claims)
        for n in sorted(numbers(claim)):
            if n not in fact_numbers and n not in unshown_figures:
                unshown_figures.append(n)
        words = set(content_words(claim))
        if len(words) < MIN_WORDS:
            continue
        found = len(words & fact_words)
        found_all += found
        total_all += len(words)
        if found / len(words) < COVERAGE:
            weak.append(s)

    if unshown_figures:
        why = "a figure the shown facts do not contain: " + ", ".join(
            str(n) for n in unshown_figures[:3])
        backed = False
    elif weak:
        why = "words that are not in what the owner told it"
        backed = False
    else:
        why = "in what was shown"
        backed = True
    return {"credited": True, "backed": backed, "why": why,
            "figures": unshown_figures[:5], "words": [found_all, total_all]}
