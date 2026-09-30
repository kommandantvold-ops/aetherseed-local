"""Who said it.

Step 36 (25 Sep 2026). Until now every stored turn read "User:" in the memory
block, whoever typed it. Two things came of that in one morning (build log 35):

  - a second speaker was enough to confuse the node about whom it serves -
    after 66 turns from Claude it said "I exist solely for Claude's use";
  - a teacher's mistakes were stored in the steward's voice - an error of
    Claude's, told to the node, became indistinguishable from something its
    steward had said. No check reads the teacher.

And the `[fact - entered by user]` mechanism (4e) rests on attribution - "you
told me X", never "X" - which cannot be done without knowing who "you" is.

WHAT A SPEAKER IS HERE: a name, stored with the turn and shown to the model in
front of what was said. It is DECLARED, never verified. Nothing on this device
can tell who is typing, so the protection is the same one 4e relies on:
procedural, not epistemic - the name travels with the words, and a declaration
can never take a label that means something else in the prompt.

  - A turn from the console declares nothing and is stored as STEWARD. The
    console is the steward's screen; a guest typing on it is stored as the steward
    until the screen offers a choice. That is a stated limit, not a claim.
  - A caller of /api/chat may declare `"speaker": "<name>"`. The name is
    untrusted input headed for the prompt - the fifth such path, after a
    file's contents, the model's control tokens, its own prose (build log 14c)
    and the companion's name (20d) - so it gets the companion-name rules (no colons, brackets,
    quotes, pipes or newlines; at most 24 characters; at least one letter).
  - Some names are RESERVED and can never be declared: the labels the prompt
    already gives meaning to (Steward, User, AI, Known, Episode, Pattern,
    Fiction...), and the companion's own name. A caller cannot speak as the
    steward, as the node, or as a line of its curriculum.

Rows from before this field existed carry UNKNOWN (an empty string) and render
exactly as they always did - "User" - so adding the column changes nothing a
unit already says. Filling them in is an operator act, with a reason and a
trail (tools/correct_memory.py --speaker), and only with the steward's say-so.
"""

import unicodedata

from logic.companion import validate_name

STEWARD = "steward"  # stored for a turn that declared no speaker (the console)
UNKNOWN = ""         # rows from before the field existed
# What the console's turns were stored as until 30 Sep 2026 (build log 50),
# when Andreas renamed the role: "everywhere in relation to the companions
# where owner is, should be replaced with steward. The name and role should
# reflect each other." Her memory is not rewritten (his choice): a row that
# says "owner" is the steward's, and is read and shown as the steward's.
LEGACY_STEWARD = "owner"

# Labels the memory block, the charter or the curriculum already use, and the
# roles a chat template knows. Compared case-folded.
RESERVED = frozenset({
    "steward", "owner", "user", "ai", "assistant", "system", "you", "me", "i",
    "known", "episode", "pattern", "fiction", "memory", "record",
    "companion", "unknown", "nobody", "everyone",
})

ERRORS = {
    "not_text": "a speaker must be a name",
    "reserved": "that name is reserved and cannot be declared",
}


def _fold(s):
    return unicodedata.normalize("NFC", s).casefold().strip()


def validate_speaker(raw, companion_name=None):
    """What to store for a turn. Returns (speaker, None) or (None, error_code).

    Absent (None) means the caller declared nothing: that is the console, and
    the turn is the steward's. Anything declared must be a clean name that is not
    reserved and is not the companion's own.
    """
    if raw is None:
        return STEWARD, None
    if not isinstance(raw, str):
        return None, "not_text"
    name, err = validate_name(raw)
    if err:
        return None, err
    folded = _fold(name)
    if folded in RESERVED:
        return None, "reserved"
    if companion_name and folded == _fold(companion_name):
        return None, "reserved"
    return name, None


def is_steward(speaker):
    """A stored speaker that is the steward's - including rows stored as
    "owner" before the rename."""
    return speaker in (STEWARD, LEGACY_STEWARD)


def label_for(speaker):
    """How a stored speaker is shown to the model in the memory block."""
    if not speaker:
        return "User"                 # UNKNOWN: exactly what it said before
    if is_steward(speaker):
        return "Steward"
    return speaker
