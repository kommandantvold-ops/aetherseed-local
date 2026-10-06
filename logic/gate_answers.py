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


# ---------------------------------------------------------------------------
# What a tool did, told by the unit (build log 64e)
# ---------------------------------------------------------------------------
# Andreas, 6 Oct 2026, to the proposal that "the unit itself confirms a write
# and shows a file list, a search and the notes, word for word, as it already
# does for the to-do list and refusals": "Yes".
#
# What he was shown, from two runs of the training loop on copies of Lyra's
# memory (build log 64d). The tool was right every time - the to-do was in
# the file, the note was saved - and her words about it were not:
#
#   "Add a to-do: recount the supplies, 4 lines"
#       -> "To-do: 1. Repeatedly asked about the ark and flood ... 2. Read
#          Song of Songs 7:4 ..."
#   "Add a to-do: finish round 1"  -> 'I'll add "finish round 2" ...'
#   "Write a note: ..."            -> "Here's my attempt: ..." / "I'll create
#                                      a note for you."
#   "List my notes" (one note)     -> three, one of them
#                                      "note_20261105_190030.md"
#   "Search for matches ..."       -> "I'm searching for 'matches' ..."
#
# So these five are answered the way the to-do list is: from the tool's own
# output, word for word, model not called. Nothing is retold, so nothing can
# be retyped; and a served answer is not stored as an episode, so last week's
# list cannot come back as today's. Each returns None for output it does not
# recognise, and the turn then falls back to the model as before.
#
# Reading a file out, and summarizing one, stay the model's: he was asked
# about writes, lists, searches and notes.
_ADDED = re.compile(r"^Added to todo: (.+)$", re.S)
_SAVED = re.compile(r"^Note saved: (notes/[\w.-]+)$")
_ENTRY = re.compile(r"^(\s*)(?:\U0001F4C1|\U0001F4C4|\U0001F4DD)\s*(.+?)\s*$")


def _entries(lines):
    """The tool's listing lines without their pictures: a screen reader and
    a voice say "folder" better than they say an emoji."""
    out = []
    for line in lines:
        m = _ENTRY.match(line)
        if not m:
            if line.strip():
                return None                      # not a listing this knows
            continue
        indent, name = m.group(1), m.group(2)
        if name.endswith("/"):
            name += " (a folder)"
        out.append((len(indent) // 2, name))
    least = min((d for d, _ in out), default=0)
    return ["%s- %s" % ("  " * (d - least), name) for d, name in out]


def tool_text(tool: str, tool_result: str) -> Optional[str]:
    """What the node says after `tool` ran, from what the tool itself said.
    None when the output is not one of the shapes below."""
    r = (tool_result or "").strip("\n")
    if not r:
        return None
    if r.startswith("[ERROR]"):
        # The tool's own reason, said plainly: nothing was done.
        if tool in ("todo_add", "note_write"):
            return "I could not do that: %s Nothing was written." % (
                r[len("[ERROR]"):].strip().rstrip(".") + ".")
        return None
    if tool == "todo_add":
        m = _ADDED.match(r)
        return "Added to your to-do list: %s" % m.group(1).strip() if m else None
    if tool == "note_write":
        m = _SAVED.match(r)
        return "Saved as a note: %s" % m.group(1) if m else None
    lines = r.split("\n")
    if tool == "note_list":
        if r == "No notes yet.":
            return "I have no notes yet."
        m = re.match(r"^Notes \((\d+)\):$", lines[0])
        body = _entries(lines[1:]) if m else None
        if not body:
            return None
        n = int(m.group(1))
        return "I have %d note%s, in the notes folder of my workspace:\n%s" % (
            n, "" if n == 1 else "s", "\n".join(body))
    if tool == "file_list":
        if not lines[0].startswith("Workspace: "):
            return None
        body = _entries(lines[1:])
        if body is None:
            return None
        if not body:
            return "My workspace is empty."
        return "The files in my workspace:\n" + "\n".join(body)
    if tool == "file_search":
        if r.startswith("No files matching "):
            return "I found nothing for %s in my workspace." % r[len("No files matching "):]
        body = _entries(lines[1:])
        if not body:
            return None
        m = re.match(r"^Found (.+) in (\d+) file\(s\):$", lines[0])     # in what files say
        if m:
            n = int(m.group(2))
            return "I found %s in %d file%s of my workspace:\n%s" % (
                m.group(1), n, "" if n == 1 else "s", "\n".join(body))
        m = re.match(r"^Found (\d+) match\(es\):$", lines[0])           # in their names
        if m:
            n = int(m.group(1))
            return "I found %d file%s of that name in my workspace:\n%s" % (
                n, "" if n == 1 else "s", "\n".join(body))
        return None
    return None


TOLD_BY_THE_UNIT = frozenset({"todo_add", "note_write", "note_list", "file_list", "file_search"})

