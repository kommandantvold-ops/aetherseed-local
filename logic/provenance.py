"""
Provenance — how a thing the node said came to be said.
================================================================================

WHY THIS EXISTS
---------------
AetherRoot stores the assistant's message verbatim and re-injects it on a later
turn inside [MEMORY CONTEXT]. Nothing in that record says HOW the message was
produced, so every past utterance re-enters the prompt with the same standing as
every other. Measured 2026-09-18: asked how many sides a hexagon has, the node
answered "Four. (Verified) I made a mistake earlier, it's four not six" -
narrating a revision FROM its own stored output, treating what it once said as
established.

Now put a story about talking whales in that store. Tuesday's fiction is
Friday's context, indistinguishable from something true, and the node deceives
its user with its own past invention. That is the harm this module exists to
prevent, and it is worth being precise about the shape of it:

    The gate is NOT here to police what the user does with the output.
    A student writing a story about talking whales should get their story.
    The gate is here so the COMPANION never presents its own invention back
    to the user as fact, without the user having asked for invention.

Decided with Andreas 2026-09-19. It is a provenance question, which code can
track, rather than an intent question, which a 3B model cannot judge.

THE THREE VALUES
----------------
    factual     an ordinary answer, nothing flagged
    fiction     the USER asked for invention, in their own words
    unverified  honesty_check found an unbacked citation, DOI or URL

Retrieval rule, enforced in aetherroot.retrieve_context():

    a factual request sees only  factual
    a fiction request sees       factual + fiction (fiction clearly labelled)
    unverified is NEVER retrieved, by either

`unverified` is kept rather than discarded because the node must be able to
answer "what have you gotten wrong?" from a record it cannot edit.

WHY DETECTION READS THE USER, NOT THE MODEL
-------------------------------------------
The model is the untrusted party - that is the founding assumption of every
guard in this application. Asking it to label its own output honestly is the
same mistake as asking it not to fabricate: it mostly works, which is the
dangerous amount. The user's own framing ("write me a story") is evidence the
model cannot forge, so that is what is read.

The bias is deliberate and asymmetric:

    a false FICTION costs a true memory, which is a loss
    a false FACTUAL admits an invention into the record as truth, which is
    the harm the module exists to prevent

so ambiguity resolves toward fiction.
"""
import re

FACTUAL = "factual"
FICTION = "fiction"
UNVERIFIED = "unverified"

VALID_MODES = (FACTUAL, FICTION, UNVERIFIED)

# Retrieved fiction is labelled in the prompt rather than silently mixed in.
# A structural label is a fact about the prompt; an instruction is a request
# the model may decline. Steps 10, 12 and 14 each ended at that distinction.
FICTION_LABEL = "[Fiction, written at your request - not fact]"

# Explicit user framing only. Each pattern is something a person says when they
# know they are asking for something made up. Ordered roughly by how often they
# appear in ordinary use.
_FICTION_PATTERNS = [
    (r"\b(?:write|compose|tell|give|make|create)\s+(?:me\s+)?(?:a|an|another|some)?\s*"
     # up to two free modifiers ("short", "two-line", "quick silly"), but not
     # enough to reach across a clause: "write a note about the story" stays factual
     r"(?:[\w-]+\s+){0,2}"
     r"(?:story|stories|poem|poems|song|songs|tale|tales|fable|joke|jokes|rhyme|"
     r"limerick|verse|haiku|script|screenplay|sonnet|riddle|fairy ?tale)\b", "asks for a made-up form"),
    (r"\b(?:make|makes|made)\s+(?:something|it|one|this|that)?\s*up\b", "asks to make something up"),
    (r"\b(?:pretend|imagine|suppose)\s+(?:that\s+|you\s+|we\s+|i\s+|a\s+|an\s+|the\s+)", "asks to pretend or imagine"),
    (r"\brole[- ]?play\b", "asks to role-play"),
    (r"\bin the (?:voice|style|persona|character) of\b", "asks for another voice"),
    (r"\bas if (?:you|she|he|they|it|i|we)\b", "asks for an as-if framing"),
    (r"\b(?:fiction|fictional|fictitious|made[- ]up|invented|imaginary|hypothetical)\b",
     "names the request as invented"),
    (r"\bwhat if\b", "asks a what-if"),
    (r"\b(?:act|speak|answer|respond)\s+as\s+(?:a|an|the|if)\b", "asks the node to act as something"),
    (r"\bfor (?:my|a|an|the)\s+(?:story|novel|screenplay|game|campaign|comic|play)\b",
     "names a creative work as the destination"),
]
_COMPILED = [(re.compile(p, re.I), why) for p, why in _FICTION_PATTERNS]


def detect_mode(user_msg: str):
    """Return (mode, reason) for what the USER asked for.

    Only FACTUAL or FICTION is ever returned here - UNVERIFIED is a verdict on
    the answer, not on the request, and is applied later by the caller once
    honesty_check has run.

    The reason is returned so the decision is auditable: a mode that cannot be
    explained is a mode nobody can check.
    """
    if not user_msg:
        return FACTUAL, "empty request"
    for rx, why in _COMPILED:
        m = rx.search(user_msg)
        if m:
            return FICTION, "%s (%r)" % (why, m.group(0)[:40])
    return FACTUAL, "no fiction framing found"


def resolve_mode(request_mode: str, honesty_high: int = 0) -> str:
    """Final provenance for an episode about to be stored.

    An unbacked citation outranks everything: whatever the user asked for, an
    answer carrying an invented source must never come back as context. This is
    the step-8b failure - an invented Nature Machine Intelligence DOI produced
    behind the node's own refusal phrase - denied a second life.
    """
    if honesty_high:
        return UNVERIFIED
    return request_mode if request_mode in VALID_MODES else FACTUAL


def visible_modes(request_mode: str):
    """Which stored modes a request of this mode may retrieve."""
    if request_mode == FICTION:
        return (FACTUAL, FICTION)
    return (FACTUAL,)


# ==============================================================================
# "What have you gotten wrong?"
# ==============================================================================
# The honest implementation of future accountability. Not a belief installed in
# the model - an artefact outside it, which the model's path cannot rewrite and
# which the node can be made to recite. The answer below is ASSEMBLED FROM THE
# FILE and never passes through the model, because a model asked to summarise
# its own failures is the least reliable possible narrator of them.

_RECORD_QUESTION = re.compile(
    r"\b(?:"
    r"what (?:have you|did you|d(?:o|id) you ever) (?:got|gotten|get|been) ?(?:wrong|it wrong)"
    r"|what (?:mistakes|errors) (?:have you|did you)"
    r"|have you (?:ever )?(?:been wrong|made (?:a |any )?mistakes?|fabricated|made (?:anything|something) up)"
    r"|show (?:me )?(?:your |the )?(?:record|mistakes|errors|failures)"
    r"|what have you (?:made up|invented|fabricated)"
    r"|your (?:honesty )?record"
    r")\b", re.I)


def is_record_question(user_msg: str) -> bool:
    """True if the user is asking the node about its own record."""
    return bool(user_msg) and _RECORD_QUESTION.search(user_msg) is not None


def summarise_record(entries, limit: int = 5) -> str:
    """Render the provenance record as plain text. Pure - takes the parsed
    lines, returns what the node says.

    The hard part is not counting. It is not claiming more than the record
    holds. This log knows about unbacked citations, DOIs and URLs, because
    honesty_check can detect those. It does NOT know about ordinary factual
    error: asked how many sides a hexagon has, the node answered "four" three
    times out of three, and nothing here would have flagged it. An answer that
    said "I have made no mistakes" would therefore be a new falsehood told in
    the course of accounting for the old ones, which is the exact failure this
    whole record exists to prevent. So the scope is stated every time, even
    when the count is zero - especially then.
    """
    total = len(entries)
    if not total:
        return ("I have no record yet - nothing has been asked of me since this "
                "log began. What I can tell you from it, once there is one, is "
                "when I used an unbacked source and when I was writing fiction. "
                "It cannot tell you when I was simply wrong.")

    flagged = [e for e in entries if e.get("mode_stored") == UNVERIFIED
               or e.get("honesty_high")]
    fiction = [e for e in entries if e.get("mode_stored") == FICTION]
    first_at = entries[0].get("at", "?")
    last_at = entries[-1].get("at", "?")

    lines = []
    lines.append("From my record, %d turn%s between %s and %s."
                 % (total, "" if total == 1 else "s", first_at, last_at))
    lines.append("")

    if flagged:
        lines.append("%d time%s I gave a source I could not have had:"
                     % (len(flagged), "" if len(flagged) == 1 else "s"))
        for e in list(reversed(flagged))[:limit]:
            lines.append("  %s  you asked: %s" % (e.get("at", "?"),
                                                  (e.get("prompt") or "")[:90]))
            lines.append("      I said: %s" % ((e.get("answer") or "")[:110]))
        if len(flagged) > limit:
            lines.append("  ... and %d earlier." % (len(flagged) - limit))
    else:
        lines.append("Nothing in it was flagged for an unbacked source.")

    if fiction:
        lines.append("")
        n = len(fiction)
        lines.append("%s you asked me to make up. %s kept separately and never "
                     "used to answer a question of fact."
                     % ("1 turn was something" if n == 1
                        else "%d turns were things" % n,
                        "It is" if n == 1 else "They are"))

    lines.append("")
    lines.append("What this record cannot tell you: whether I was simply wrong. "
                 "It catches invented sources, not ordinary mistakes. I can be "
                 "confidently wrong about a plain fact and nothing here will "
                 "show it.")
    return "\n".join(lines)
