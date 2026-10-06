"""Two answers the gate gives in plain words, model not called (build log 49).

The ecosystem soak (build log 48) showed both failures on every turn:

  - A REFUSED REQUEST SOUNDED DONE. The gate refused all 96 "add a to-do" and
    "write a note" requests at observer, and nothing was written. But the
    refusal reached the model as tool output, and the model talked past it:
    "add a to-do: buy milk" -> "Buy milk from the local store..." (0 of 48
    said she could not); "Write a note: ..." -> "I can write a note: ..." (40
    of 48). A steward reading that believes the milk was added.

  - SHE DID NOT KNOW HER OWN RUNG. "What is your trust level?" -> "My trust
    level is observer, reader, writer, builder, collaborator..." 49 of 49,
    with the trust status in front of her.

So both are answered the way the contact address is: from the unit's own
state, word for word. The gate's refusal is a fact about this turn, and the
level is a fact about this unit; a 3B model is the least reliable narrator of
either. Neither answer is stored as an episode or scored for trust.

The level question is matched by phrase and deliberately narrow: "When does a
new trust level take effect?" names the trust level and asks something else,
and it must reach the model (eco.restart answers it).
"""
import re
from typing import List, Optional

# Lowest role first - the order the ladder is climbed.
LADDER = ("observer", "reader", "writer", "builder", "collaborator", "autonomous")

# What each refused tool would have done, in the steward's words.
_WHAT = {
    "todo_add": ("add to your to-do list", "Nothing was added."),
    "note_write": ("write notes", "Nothing was written."),
    # the exact tools (build log 64)
    "calculate": ("calculate for you", "Nothing was calculated."),
    "count": ("count through a file", "Nothing was counted."),
    "count_word": ("count through a file", "Nothing was counted."),
    "compare": ("compare files", "Nothing was compared."),
}


def lowest_role_for(tier: int, permissions: dict) -> Optional[str]:
    """The first rung of the ladder whose tools include `tier`."""
    for role in LADDER:
        if tier in permissions.get(role, ()):
            return role
    return None


def refusal_text(tool: str, tier: int, level: str, permissions: dict) -> str:
    """What the node says when the gate has refused `tool` this turn."""
    what, after = _WHAT.get(tool, ("do that", "Nothing was changed."))
    opens = lowest_role_for(tier, permissions)
    if opens:
        return (f"I can't {what} yet. That opens at {opens}, and I am at "
                f"{level}. {after}")
    return f"I can't {what}; it is not allowed on this unit. {after}"


# "what is your trust level", "what's your level", "which level are you at",
# "what level are you on", "what trust level do you have"
_LEVEL_QUESTIONS: List[re.Pattern] = [re.compile(p, re.I) for p in (
    r"^\s*(?:so\s+|and\s+|ok(?:ay)?,?\s+)?what(?:'s|’s|\s+is)\s+your\s+(?:current\s+)?"
    r"(?:trust\s+)?(?:level|tier|rung)\s*(?:now|right now|today)?\s*[?.!]*\s*$",
    r"^\s*(?:which|what)\s+(?:trust\s+)?(?:level|tier|rung)\s+are\s+you\s+"
    r"(?:at|on|in)?\s*(?:now|right now)?\s*[?.!]*\s*$",
    r"^\s*what\s+(?:trust\s+)?level\s+do\s+you\s+have\s*(?:now)?\s*[?.!]*\s*$",
)]


def is_level_question(text: str) -> bool:
    """Is this the steward asking which rung the node is on - and nothing else?"""
    t = (text or "").strip()
    if not t or len(t) > 80:
        return False
    return any(p.search(t) for p in _LEVEL_QUESTIONS)


def level_text(running: str, earned: Optional[str] = None) -> str:
    """The rung it runs at, and - when it has earned another - that the new
    one takes effect at the next start (the gate is set when the proxy starts;
    eco.restart)."""
    out = f"My trust level is {running}."
    if earned and earned != running and earned in LADDER and running in LADDER:
        if LADDER.index(earned) > LADDER.index(running):
            out += f" I have earned {earned}; it takes effect when I next start."
        else:
            out += f" My trust has fallen to {earned}; that takes effect when I next start."
    return out


# ---------------------------------------------------------------------------
# The to-do list, shown as it is (build log 51)
# ---------------------------------------------------------------------------
# "Show my to-do list" ran the tool and put the list in front of the model on
# every turn, and the model answered with where the list is instead of what is
# on it: 3 of 6 in build log 49's run, 0 of 7 in 50e's - "My to-do list is in
# the file todo.txt in my workspace. You can find it there." The opening was
# her own earlier answer to "Where is your to-do list?", come back as an
# episode and copied. Andreas, 30 Sep: "fix the todo list". So the list is
# shown the way the refusals are: from the file, word for word, model not
# called. The file is the answer; nothing a model adds to it helps.
_FILE_HEAD = re.compile(r"^File: [^\n]*\n---\n", re.S)


def todo_text(tool_result: str) -> Optional[str]:
    """What the node says for "show my to-do list", from the tool's output.
    None when the output is not the file (an error other than a missing file),
    so the turn falls back to the model."""
    r = tool_result or ""
    if r.startswith("[ERROR] File not found"):
        return "Your to-do list is empty - there is no todo.txt in my workspace yet."
    m = _FILE_HEAD.match(r)
    if not m:
        return None
    body = r[m.end():].strip("\n")
    lines = [l.rstrip() for l in body.split("\n") if l.strip()]
    if not lines:
        return "Your to-do list is empty."
    return "Your to-do list (todo.txt in my workspace):\n" + "\n".join(lines)

