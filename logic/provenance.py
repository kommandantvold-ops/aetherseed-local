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

    # ---- Norwegian (bokmål). Added with the language option, 2026-09-21.
    # Measured before adding them: "Skriv et kort dikt om en hval som heter
    # Bjørn" was read as FACTUAL, so the poem would have been stored as fact -
    # the harm this module exists to prevent, switched off for anyone speaking
    # the language the device offers. Reasons are in Norwegian because the
    # console shows them.
    (r"\b(?:skriv|lag|dikt|fortell|komponer|gi)\s+(?:meg\s+)?(?:en|et|ei|noen|flere)?\s*"
     r"(?:[\w-]+\s+){0,2}"
     r"(?:historie|historier|historien|fortelling|fortellinger|eventyr|dikt|diktet|sang|sanger|"
     r"vise|viser|vits|vitser|rim|regle|limerick|haiku|manus|sonett|gåte|gåter|novelle|fabel)\b",
     "ber om noe oppdiktet"),
    (r"\b(?:finn|finne|fant)\s+på\b", "ber deg finne på noe"),
    (r"\bdikt(?:e|er)?\s+opp\b", "ber deg dikte opp noe"),
    (r"\b(?:lat|late)\s+som\b", "ber deg late som"),
    (r"\b(?:tenk|forestill|se\s+for)\s+deg\b", "ber deg forestille deg noe"),
    (r"\brollespill\b", "ber om rollespill"),
    (r"\bi\s+(?:stilen|stemmen|rollen)\s+til\b", "ber om en annen stemme"),
    (r"\bsom\s+om\s+(?:du|han|hun|de|den|det|jeg|vi)\b", "ber om et som-om"),
    (r"\b(?:oppdiktet|oppdiktede|fiktiv|fiktive|fiksjon|påfunnet|påfunnede|hypotetisk)\b",
     "kaller det selv oppdiktet"),
    (r"\bhva\s+om\b", "spør hva om"),
    (r"\btil\s+(?:min|mitt|mi|en|et|ei)\s+(?:historie|roman|bok|spill|film|manus|tegneserie)\b",
     "nevner et kreativt verk som mål"),
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
    # Norwegian (bokmål), added with the language option. Without these the
    # question went to the model - the least reliable narrator of its own
    # failures - for anyone asking in the language the device speaks.
    r"|hva har du (?:tatt|fått|gjort|sagt) feil"
    r"|hvilke feil har du (?:gjort|begått)"
    r"|har du (?:noen gang |noensinne )?(?:tatt feil|gjort (?:noen )?feil|funnet på noe|diktet opp noe|løyet)"
    r"|hva har du (?:funnet på|diktet opp)"
    r"|vis (?:meg )?(?:loggen|feilene|oversikten)(?: din| dine)?"
    r"|(?:din|dine) (?:logg|feil)"
    r")\b", re.I)


def is_record_question(user_msg: str) -> bool:
    """True if the user is asking the node about its own record."""
    return bool(user_msg) and _RECORD_QUESTION.search(user_msg) is not None


_RECORD_TEXT = {
    "en": {
        "empty": ("I have no record yet - nothing has been asked of me since this "
                  "log began. What I can tell you from it, once there is one, is "
                  "when I used an unbacked source and when I was writing fiction. "
                  "It cannot tell you when I was simply wrong."),
        "span": "From my record, {n} {turns} between {first} and {last}.",
        "turn": ("turn", "turns"),
        "gave": "{times} I gave a source I could not have had:",
        "times": ("{n} time", "{n} times"),
        "asked": "  {at}  you asked: {prompt}",
        "said": "      I said: {answer}",
        "earlier": "  ... and {n} earlier.",
        "unchecked": "{times} I could not check an answer for invented sources.",
        "clean": "Nothing in it was flagged for an unbacked source.",
        "fiction": ("{what} you asked me to make up. {they} kept separately and "
                    "never used to answer a question of fact."),
        "fiction_what": ("1 turn was something", "{n} turns were things"),
        "fiction_they": ("It is", "They are"),
        "scope": ("What this record cannot tell you: whether I was simply wrong. "
                  "It catches invented sources, not ordinary mistakes. I can be "
                  "confidently wrong about a plain fact and nothing here will "
                  "show it."),
    },
    "nb": {
        "empty": ("Jeg har ingen logg ennå - ingen har spurt meg om noe siden "
                  "loggen begynte. Når det finnes en, kan den fortelle deg når jeg "
                  "brukte en kilde uten grunnlag, og når jeg skrev fiksjon. Den kan "
                  "ikke fortelle deg når jeg rett og slett tok feil."),
        "span": "Ifølge loggen min: {n} {turns} mellom {first} og {last}.",
        "turn": ("spørsmål og svar", "spørsmål og svar"),
        "gave": "{times} ga jeg en kilde jeg ikke kunne ha hatt:",
        "times": ("{n} gang", "{n} ganger"),
        "asked": "  {at}  du spurte: {prompt}",
        "said": "      jeg svarte: {answer}",
        "earlier": "  ... og {n} tidligere.",
        "unchecked": "{times} kunne jeg ikke sjekke et svar for oppdiktede kilder.",
        "clean": "Ingenting i den er merket for en kilde uten grunnlag.",
        "fiction": ("{what} du ba meg finne på. {they} holdt adskilt og brukes "
                    "aldri til å svare på et faktaspørsmål."),
        "fiction_what": ("1 av dem var noe", "{n} av dem var ting"),
        "fiction_they": ("Det er", "De er"),
        "scope": ("Det loggen ikke kan fortelle deg: om jeg rett og slett tok feil. "
                  "Den fanger opp oppdiktede kilder, ikke vanlige feil. Jeg kan ta "
                  "selvsikkert feil om et enkelt faktum uten at noe her viser det."),
    },
}


def summarise_record(entries, limit: int = 5, language: str = "en") -> str:
    """Render the provenance record as plain text, in the companion's language.
    Pure - takes the parsed lines, returns what the node says.

    The hard part is not counting. It is not claiming more than the record
    holds. This log knows about unbacked citations, DOIs and URLs, because
    honesty_check can detect those. It does NOT know about ordinary factual
    error: asked how many sides a hexagon has, the node answered "four" three
    times out of three, and nothing here would have flagged it. An answer that
    said "I have made no mistakes" would therefore be a new falsehood told in
    the course of accounting for the old ones, which is the exact failure this
    whole record exists to prevent. So the scope is stated every time, even
    when the count is zero - especially then - and in every language offered.
    """
    t = _RECORD_TEXT.get(language, _RECORD_TEXT["en"])

    def plural(pair, n):
        return (pair[0] if n == 1 else pair[1]).format(n=n)

    total = len(entries)
    if not total:
        return t["empty"]

    # An answer the check could not run on is not an invented source; it is
    # an unchecked one, and is accounted for as that.
    unchecked = [e for e in entries if e.get("checked") is False]
    flagged = [e for e in entries if e.get("checked") is not False
               and (e.get("honesty_high") or e.get("mode_stored") == UNVERIFIED)]
    fiction = [e for e in entries if e.get("mode_stored") == FICTION]

    lines = [t["span"].format(n=total, turns=plural(t["turn"], total),
                              first=entries[0].get("at", "?"),
                              last=entries[-1].get("at", "?")), ""]
    if flagged:
        lines.append(t["gave"].format(times=plural(t["times"], len(flagged))))
        for e in list(reversed(flagged))[:limit]:
            lines.append(t["asked"].format(at=e.get("at", "?"),
                                           prompt=(e.get("prompt") or "")[:90]))
            lines.append(t["said"].format(answer=(e.get("answer") or "")[:110]))
        if len(flagged) > limit:
            lines.append(t["earlier"].format(n=len(flagged) - limit))
    if unchecked:
        if flagged:
            lines.append("")
        lines.append(t["unchecked"].format(times=plural(t["times"], len(unchecked))))
    if not flagged and not unchecked:
        lines.append(t["clean"])

    if fiction:
        n = len(fiction)
        lines.append("")
        lines.append(t["fiction"].format(what=plural(t["fiction_what"], n),
                                         they=t["fiction_they"][0 if n == 1 else 1]))

    lines.append("")
    lines.append(t["scope"])
    return "\n".join(lines)
