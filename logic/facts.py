"""What the owner told the node - kept word for word, and always attributed.

Step 37 (25 Sep 2026): the assertion half of `[fact - entered by user]` (4e).

WHY. A fact given in conversation is stored as a paraphrase, and the paraphrase
is what comes back (31g): the node rewrote its owner's radiator into "I have a
radiator at my apartment in Oslo". An assertion has to be stored VERBATIM as
entered, and it has to come back ATTRIBUTED - "your owner told you X", never
"X" - so that it can never be laundered into something the node claims to know.

WHAT PROTECTS IT. An owner's claim is unverifiable by construction, so the
protection is procedural, not epistemic (the 4e failsafes, handover 25 Sep):

  - attribution always: every line carries FACT_TAG, and FACT_NOTE tells the
    model what the tag means, on the turns that carry one;
  - it cannot change the trust level or unlock a tool - it is text in the memory
    block and nothing else reads it;
  - it cannot silence the build: [Known] lines go first in the block, facts
    after them, episodes last;
  - capped in number (the unit's `facts_max`) and in length (MAX_FACT_CHARS),
    at most MAX_FACT_LINES in one prompt, and nothing that could pass for a
    prompt marker - no brackets, pipes or line breaks - is accepted at all;
  - every answer that used one says so (`facts_used` on the terminator);
  - listable and revocable, and every change is in `corrections.log`
    (tools/owner_facts.py). A revoked fact is kept, never retrieved.

ENTRY. By an operator, on the owner's instruction, with a reason - the console
flow comes with guided correction (4d). The retraction half (an owner marking
an episode as never having happened) comes with it too.
"""

import re

FACT_TAG = "[Owner told you]"

# Appended to the system prompt only on a turn whose memory block carries a
# fact line - about 30 tokens, paid only when it means something.
FACT_NOTE = ("Lines marked [Owner told you] are things your owner told you. "
             "When you use one, say that your owner told you; never present "
             "it as something you know yourself.")

MAX_FACT_CHARS = 320        # Genesis in the World English Bible peaks at 296
MAX_SOURCE_CHARS = 60
MAX_FACT_LINES = 2          # per prompt
# Of the 800-character memory block. 340 so that every Genesis verse fits on its
# own, tag and source included (the longest line is 329); a fact whose line
# could never fit is refused at entry (validate_fact), so every stored fact can
# be shown.
FACTS_BUDGET_CHARS = 340
DEFAULT_CAP = 250           # per unit; `facts_max` in its config raises it

# WHEN A FACT IS SHOWN. By words, like the curriculum (logic/knowledge.py), but
# with its own threshold, because the curriculum's does not survive the size of
# this set. Measured 25 Sep 2026 on the 1533 verses of Genesis (WEB) against the
# 117 verses of the Song of Songs read as the reading soak reads them (off-topic:
# nothing should be shown) and the 26 questions in tools/texts/
# genesis-probes.json (on-topic):
#
#   - the curriculum's rule (score >= 0.30 OR weight >= 4.0) showed a Genesis
#     verse on 117 of 117 Song turns. With 1533 entries one uncommon shared word
#     ("myrrh", "flock", "songs") outweighs the floor; ANY weight floor up to 16
#     still showed facts on more than three Song turns. So facts use the score
#     alone - the share of the question's distinctive words a fact contains;
#   - score >= 0.45 is the lowest that showed nothing on the Song (0.40 showed
#     two: 2:6 and 8:3). At 0.45, within the budget below, the right verse was
#     among those shown for 15 of 26 plain questions ("What did the dove have
#     in her mouth?") and 17 of 26 asked as "What has your owner told you
#     about ...?" once the telling words below are left out of the query (3 of
#     26 with them in: "owner" occurs in no verse, and an unknown word counts
#     heavily against every entry). Most misses are a neighbouring verse on
#     the same subject shown instead (8:8 for the dove of 8:11).
#   - the curriculum's idf, log(n/d), gives a word in EVERY fact a weight of
#     zero - so a unit holding one fact could never show it (score 0.00 for
#     "What happened to Lot's wife?" against that very fact). Facts use
#     log(1 + n/d), which is never zero and on Genesis changed none of the
#     numbers above.
#
# The questions were written before the threshold was chosen and were not used
# to choose it; the Song was. The soak reads that same Song, so "nothing shown
# on a reading turn" holds there by construction - it is not evidence about
# other conversations.
FACT_SCORE_THRESHOLD = 0.45

# Words about the telling, not about what was told: left out of the query that
# looks for a fact, so "What has your owner told you about the dove?" looks for
# the dove.
FRAMING_WORDS = frozenset({"owner", "told", "tell", "taught", "remember"})

# A fact is shown to the model inside the memory block. Anything that could
# open or close a line, a tag or the block itself is refused outright rather
# than rewritten: a fact is stored exactly as entered or not at all.
_FORBIDDEN = ("[", "]", "<|", "|>", "\n", "\r", "|")


def validate_fact(text, source=""):
    """(text, source, None) if acceptable, else (None, None, error_code)."""
    if not isinstance(text, str) or not text.strip():
        return None, None, "empty"
    text = text.strip()
    if len(text) > MAX_FACT_CHARS:
        return None, None, "too_long"
    if any(bad in text for bad in _FORBIDDEN):
        return None, None, "characters"
    if source is None:
        source = ""
    if not isinstance(source, str):
        return None, None, "source"
    source = " ".join(source.split())
    if len(source) > MAX_SOURCE_CHARS or any(bad in source for bad in _FORBIDDEN):
        return None, None, "source"
    if len(fact_line(text, source)) > FACTS_BUDGET_CHARS:
        return None, None, "too_long"      # could never be shown
    return text, source, None


def fact_line(text, source=""):
    """How a fact is shown to the model."""
    return f"{FACT_TAG} {text}" + (f" ({source})" if source else "")


def fact_index(facts):
    """The active facts, indexed by words, or None when there are none.

    facts: rows with "id", "text" and "source". The source is indexed too, so
    "Genesis" or a chapter number can help find a verse.
    """
    import math
    from logic.knowledge import Knowledge

    class FactIndex(Knowledge):
        def _idf(self, word):            # log(1 + n/d): see above
            d = self._df.get(word, 0)
            return math.log(1 + self._n / (d if d else 0.5))

    if not facts:
        return None
    return FactIndex([{"id": f["id"], "text": f["text"], "match": f.get("source") or "",
                       "trigger": []} for f in facts])


def fact_query(user_msg):
    """The question with the telling words left out (FRAMING_WORDS)."""
    words = re.findall(r"\S+", user_msg or "")
    keep = [w for w in words
            if re.sub(r"[^a-z]", "", w.lower()) not in FRAMING_WORDS]
    return " ".join(keep)
