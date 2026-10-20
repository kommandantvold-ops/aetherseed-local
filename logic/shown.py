"""What was in front of her: the memory block as sent, not as retrieved.
.

The proxy builds her prompt and logic/token_budget.enforce_budget then makes it
fit the model's prefill ceiling. It drops the oldest history first, then memory
lines from the tail of the block, then the end of a file (cut and marked).
Until everything read after the turn used the block as it was
retrieved, before that trimming:
- the honesty check;
- the steward check;
- the trust scorer;
- the answer's tag;
- the training loop's record of what she was shown.

That had two effects:
- X9: a line the model never saw still counted as backing for what it said.
- X8: a note explaining a tag ("Lines marked [Steward told you] ...") stayed
  in the prompt after every line it explained had been dropped.

Neither has happened on a unit yet. No turn on a unit was trimmed between 6 and, the whole of her journal, because retrieval keeps the block under
max_context_chars. It is a fault in waiting: a long file, a long question,
or a model with a lower ceiling brings it in.

settle reads the fitted system text and returns three things, all cut to
the lines that are left: the block as sent, the same block without its
tagged lines, and the retrieval report.

drop_notes takes out the notes whose lines are gone. Nothing here trims: it
only reads what enforce_budget left, and a dropped line is not put back.
"""
from collections import Counter

from logic.token_budget import _split_block, _MEM_OPEN, _MEM_CLOSE, _WS_OPEN
from logic.facts import FACT_TAG, FACT_NOTE, FACT_TAG_UNCHECKED, FACT_NOTE_UNCHECKED
from logic.provenance import TAG_NOTE
from logic.prompt_builder import DATA_NOTE

__all__ = ["settle", "drop_notes", "memory_lines"]


def memory_lines(text):
    """The lines of the memory block in text, in order. [] if there is none.

    The block's markers are found as token_budget finds them: the last
    line-initial opening, because the charter mentions [MEMORY CONTEXT] in
    prose."""
    parts = _split_block(text or "", _MEM_OPEN, _MEM_CLOSE)
    if parts is None:
        return []
    return [line for line in parts[1].split("\n") if line.strip()]


def _block(lines):
    return "\n".join([_MEM_OPEN] + list(lines) + [_MEM_CLOSE]) if lines else ""


def _line_initial(text, tag):
    """Where tag starts a line in text, the last such place, or -1."""
    k = len(text)
    while True:
        k = text.rfind(tag, 0, k)
        if k <= 0:
            return k
        if text[k - 1] == "\n":
            return k


def settle(system, memory_context, trusted_context, retrieval):
    """The block, the trusted block and the report, as sent.

    system          the system message as it will be sent (after enforce_budget)
    memory_context  the block as retrieved
    trusted_context the block the checks were to read (the block without its
                    tagged lines, or the block itself when nothing was tagged)
    retrieval       the report retrieve_context filled

    Returns (memory_context, trusted_context, retrieval). The report is a new
    dict, never the one passed in. When nothing was trimmed the three come
    back as they were.
    """
    retrieval = dict(retrieval or {})
    retrieved = memory_lines(memory_context)
    if not retrieved:
        return memory_context, trusted_context, retrieval
    sent = memory_lines(system)
    if sent == retrieved:
        return memory_context, trusted_context, retrieval

    # What was sent, line by line. enforce_budget pops from the tail, so this
    # is normally the first len(sent) lines; counted by text all the same, so
    # nothing here rests on that.
    left = Counter(sent)
    kept = []
    for line in retrieved:
        if left[line] > 0:
            kept.append(True)
            left[line] -= 1
        else:
            kept.append(False)
    kept_lines = [line for line, k in zip(retrieved, kept) if k]

    # The trusted block: its lines that were sent.
    left = Counter(kept_lines)
    trusted = []
    for line in memory_lines(trusted_context):
        if left[line] > 0:
            trusted.append(line)
            left[line] -= 1

    # The report, cut to the lines left. Each kind keeps the first of its
    # entries, as many as were sent: facts, rings and known lines stand in
    # the block in the order the report lists them.
    kinds = retrieval.get("line_kinds")
    if isinstance(kinds, list) and len(kinds) == len(retrieved):
        sent_kinds = [kd for kd, k in zip(kinds, kept) if k]
        n_facts = sum(1 for kd in sent_kinds if kd == "fact")
        n_rings = sum(1 for kd in sent_kinds if kd in ("ring", "asked"))
        n_known = sum(1 for kd in sent_kinds if kd == "known")
        retrieval["line_kinds"] = sent_kinds
        for key in ("facts", "fact_sources", "fact_texts"):
            if key in retrieval:
                retrieval[key] = list(retrieval[key] or [])[:n_facts]
        if "rings" in retrieval:
            retrieval["rings"] = list(retrieval["rings"] or [])[:n_rings]
        if retrieval.get("known") is not None:
            retrieval["known"] = n_known
    else:
        # A report without the kinds of its lines (an older root, a stand-in):
        # a fact counts as sent when its words are in a line that was.
        texts = list(retrieval.get("fact_texts") or [])
        keep = [i for i, t in enumerate(texts) if any(t and t in line for line in kept_lines)]
        for key in ("facts", "fact_sources", "fact_texts"):
            if key in retrieval:
                vals = list(retrieval[key] or [])
                retrieval[key] = [vals[i] for i in keep if i < len(vals)]
        if retrieval.get("known") is not None:
            retrieval["known"] = sum(1 for line in kept_lines if line.startswith("- [Known]"))
    # A sent line is either trusted or tagged.
    no_tags = (trusted_context or "") == (memory_context or "")
    retrieval["tagged"] = 0 if no_tags else max(0, len(kept_lines) - len(trusted))
    retrieval["trusted_context"] = _block(kept_lines if no_tags else trusted)
    retrieval["lines_trimmed"] = len(retrieved) - len(kept_lines)

    block = _block(kept_lines)
    return block, (block if no_tags else _block(trusted)), retrieval


def drop_notes(system, memory_context, tagged):
    """system without the notes whose lines are no longer in it.

    memory_context is the block as sent (from settle), tagged the number of
    tagged lines in it. A note is taken out only when nothing it explains is
    left:
    - FACT_NOTE when no [Steward told you] line is left;
    - its unchecked half when no unchecked line is;
    - TAG_NOTE when no tagged line is;
    - DATA_NOTE when neither memory nor workspace data is.

    Returns (system, names of the notes taken out).
    """
    lines = memory_lines(memory_context)
    # The notes stand before the blocks. Only that part is searched, so the
    # words of a file or a memory can never be mistaken for a note.
    ends = [k for k in (_line_initial(system, _MEM_OPEN), _line_initial(system, _WS_OPEN))
            if k > 0]
    cut = min(ends) if ends else len(system)
    head, tail = system[:cut], system[cut:]
    has_data = bool(lines) or _line_initial(system, _WS_OPEN) > 0
    dropped = []

    def take(text, piece, name):
        k = text.rfind(piece)
        if k < 0:
            return text
        dropped.append(name)
        return text[:k] + text[k + len(piece):]

    if not any(FACT_TAG[:-1] in line for line in lines):
        before = head
        head = take(head, "\n" + FACT_NOTE + " " + FACT_NOTE_UNCHECKED, "FACT_NOTE")
        if head == before:
            head = take(head, "\n" + FACT_NOTE, "FACT_NOTE")
    elif not any(FACT_TAG_UNCHECKED in line for line in lines):
        head = take(head, " " + FACT_NOTE_UNCHECKED, "FACT_NOTE_UNCHECKED")
    if not tagged:
        head = take(head, "\n" + TAG_NOTE, "TAG_NOTE")
    if not has_data:
        head = take(head, "\n" + DATA_NOTE, "DATA_NOTE")
    return head + tail, dropped
