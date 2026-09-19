"""
Token budget guard — keeps every prompt inside the NPU's hard prefill ceiling.
================================================================================

WHY THIS EXISTS
---------------
The Hailo-10H's compiled llama3.2:3b HEF accepts a maximum of **864 prompt
tokens**. This was measured on hardware, not assumed: 864 succeeds, 865 fails.
The number is 9 x 96, nine chunks of the prefill network's compiled chunk size,
so it is a property of the compiled artifact and will not drift.

Exceeding it fails in two ways, and the dangerous one is silent:

    stream=False  ->  HTTP 500              (loud, catchable)
    stream=True   ->  HTTP 200, zero tokens (silent, looks like success)

An orchestrator that trusts a 200 sees a successful, empty completion and has
no idea the hardware refused the prompt. This module makes that impossible by
refusing to send an over-length prompt in the first place.

WHY A CHARACTER ESTIMATE IS NOT ACCEPTABLE HERE
-----------------------------------------------
Measured chars-per-token on real content with the actual Llama 3.2 tokenizer:

    plain english prose      4.44        JSON tool output         2.75
    python source            4.05        CSV / tabular            1.94
    norwegian text           3.20        sha256 digest            1.78
    memory context line      3.70        random hex               1.14

A "chars / N" estimator only ever over-counts if N <= the worst ratio, and the
worst measured ratio is 1.14 — i.e. a safe estimator would have to assume one
token per character, capping prompts at 864 *characters*. That is unusable.

Worse, the density is inverted against us: the token-densest content (JSON,
CSV, digests, file listings) is exactly what tool output consists of. An
estimator would under-count hardest precisely where the guard matters most.

Therefore the real tokenizer is REQUIRED. If it is missing this module raises
at construction time rather than guessing. On an appliance we control the
image, so this should fail at boot, never at inference.
"""

from __future__ import annotations

import datetime
import os
import re
from dataclasses import dataclass, field
from typing import Iterable

# Measured on Raspberry Pi 5 + Hailo-10H, FW 5.1.1, llama3.2:3b (2026-09-17).
# 864 tokens succeed; 865 return an error / empty stream. 864 == 9 * 96.
PREFILL_CEILING = 864

# Leave a little room so that an off-by-a-few in template reconstruction can
# never push a prompt over the real ceiling. Costs 8 tokens, buys certainty.
SAFETY_MARGIN = 8

DEFAULT_TOKENIZER_PATHS = (
    os.environ.get("AETHERSEED_TOKENIZER", ""),
    "/var/lib/aetherseed/tokenizer.json",
    "/usr/share/aetherseed/tokenizer.json",
    os.path.expanduser("~/.aetherseed/tokenizer.json"),
)


class TokenizerUnavailable(RuntimeError):
    """Raised when no real tokenizer can be loaded.

    Deliberately fatal. The alternative — estimating — under-counts on exactly
    the content that overflows, and the resulting failure is silent.
    """


class PromptTooLarge(RuntimeError):
    """The mandatory parts alone exceed the ceiling. Nothing can be trimmed."""


@dataclass
class BudgetReport:
    """What the guard did. Belongs in the audit log, not swallowed."""

    total_tokens: int = 0
    ceiling: int = PREFILL_CEILING
    history_turns_dropped: int = 0
    memory_entries_dropped: int = 0
    workspace_chars_dropped: int = 0
    trimmed: bool = False
    notes: list = field(default_factory=list)

    def summary(self) -> str:
        if not self.trimmed:
            return f"prompt {self.total_tokens}/{self.ceiling} tokens, no trimming"
        bits = []
        if self.history_turns_dropped:
            bits.append(f"{self.history_turns_dropped} history turn(s)")
        if self.memory_entries_dropped:
            bits.append(f"{self.memory_entries_dropped} memory entr(ies)")
        if self.workspace_chars_dropped:
            bits.append(f"{self.workspace_chars_dropped} chars of workspace data")
        return (f"prompt {self.total_tokens}/{self.ceiling} tokens, "
                f"TRIMMED: dropped {', '.join(bits)}")


class TokenCounter:
    """Counts tokens exactly as the server's chat template will produce them."""

    def __init__(self, tokenizer_path: str | None = None):
        try:
            from tokenizers import Tokenizer  # type: ignore
        except ImportError as exc:
            raise TokenizerUnavailable(
                "The 'tokenizers' package is not installed. The token guard "
                "cannot operate on estimates: measured chars-per-token ranges "
                "from 4.44 (prose) down to 1.14 (hex), so any character-based "
                "estimate under-counts on tool output. Install it, or the node "
                "will silently emit empty responses on long prompts."
            ) from exc

        candidates = [tokenizer_path] if tokenizer_path else list(DEFAULT_TOKENIZER_PATHS)
        for path in candidates:
            if path and os.path.isfile(path):
                self._tok = Tokenizer.from_file(path)
                self.path = path
                break
        else:
            raise TokenizerUnavailable(
                "No tokenizer.json found. Looked in: "
                + ", ".join(p for p in candidates if p)
            )

        # Integrity check: the Llama 3.2 vocabulary is 128256, which equals the
        # HEF's four 32064-wide output heads. A mismatch means this tokenizer
        # does not belong to the model being served, and every count would be
        # wrong in a way nothing downstream would notice.
        vocab = self._tok.get_vocab_size()
        if vocab != 128256:
            raise TokenizerUnavailable(
                f"Tokenizer at {self.path} has vocab_size={vocab}, expected "
                f"128256 (= 4 x 32064 output heads in the llama3.2:3b HEF). "
                f"This is the wrong tokenizer for the served model."
            )
        self.vocab_size = vocab

    def count(self, text: str) -> int:
        if not text:
            return 0
        return len(self._tok.encode(text, add_special_tokens=False).ids)

    def render_chat(self, messages: Iterable[dict], today: str | None = None) -> str:
        """Reproduce hailo-ollama's Llama 3.2 chat template.

        Transcribed from the template in the model manifest and verified
        against the prompt the server echoes into its own log.
        """
        if today is None:
            today = datetime.date.today().strftime("%d %b %Y")

        msgs = list(messages)
        system = ""
        if msgs and msgs[0].get("role") == "system":
            system = (msgs[0].get("content") or "").strip()
            msgs = msgs[1:]

        out = ["<|begin_of_text|>",
               "<|start_header_id|>system<|end_header_id|>\n\n",
               "Cutting Knowledge Date: December 2023\n",
               f"Today Date: {today}\n\n",
               system,
               "<|eot_id|>"]
        for m in msgs:
            role = m.get("role", "user")
            content = (m.get("content") or "").strip()
            out.append(f"<|start_header_id|>{role}<|end_header_id|>\n\n{content}<|eot_id|>")
        out.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
        return "".join(out)

    def count_messages(self, messages: Iterable[dict], today: str | None = None) -> int:
        return self.count(self.render_chat(messages, today=today))


# --------------------------------------------------------------------------
# The guard
# --------------------------------------------------------------------------

TRUNCATION_MARKER = (
    "\n[... TRUNCATED: this data was cut to fit the hardware context limit. "
    "It is INCOMPLETE. Say so if the answer depends on the missing part.]"
)


def fit_prompt(counter: TokenCounter,
               charter: str,
               user_text: str,
               memory_lines: list | None = None,
               workspace_data: str = "",
               history: list | None = None,
               node_state_line: str = "",
               ceiling: int = PREFILL_CEILING,
               margin: int = SAFETY_MARGIN) -> tuple:
    """Assemble the largest prompt that fits, and report what was dropped.

    Keep-priority, most important first:
        1. charter          - the node's rules; never dropped
        2. user's turn      - never dropped or truncated
        3. workspace data   - the evidence for *this* question
        4. memory context   - recall
        5. history          - recent turns

    So the drop order is the reverse: history, then memory, then workspace
    data (truncated, and explicitly marked so the model cannot mistake a
    partial read for a complete one).

    Returns (messages, BudgetReport).
    """
    memory_lines = list(memory_lines or [])
    history = list(history or [])
    report = BudgetReport(ceiling=ceiling)
    budget = ceiling - margin

    def build(mem, ws, hist):
        system = charter
        if mem:
            system += "\n\n[MEMORY CONTEXT]\n" + "\n".join(mem) + "\n[END MEMORY CONTEXT]"
        if ws:
            system += "\n\n[WORKSPACE DATA]\n" + ws + "\n[END WORKSPACE DATA]"
        if node_state_line:
            system += "\n\n" + node_state_line
        msgs = [{"role": "system", "content": system}]
        msgs.extend(hist)
        msgs.append({"role": "user", "content": user_text})
        return msgs

    # The parts that cannot be dropped. If these alone do not fit, we stop.
    floor = build([], "", [])
    floor_cost = counter.count_messages(floor)
    if floor_cost > budget:
        raise PromptTooLarge(
            f"Charter + user turn alone need {floor_cost} tokens, over the "
            f"{budget}-token working budget ({ceiling} ceiling - {margin} "
            f"margin). The user's turn is {counter.count(user_text)} tokens. "
            f"Nothing can be trimmed without dropping what the node was asked."
        )

    mem, ws, hist = list(memory_lines), workspace_data, list(history)

    # 1. Drop history, oldest first.
    while counter.count_messages(build(mem, ws, hist)) > budget and hist:
        hist.pop(0)
        report.history_turns_dropped += 1

    # 2. Drop memory entries from the tail (retrieval returns them ranked,
    #    so the tail is the least relevant).
    while counter.count_messages(build(mem, ws, hist)) > budget and mem:
        mem.pop()
        report.memory_entries_dropped += 1

    # 3. Truncate workspace data last, and mark it.
    if counter.count_messages(build(mem, ws, hist)) > budget and ws:
        original_len = len(ws)
        lo, hi = 0, len(ws)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            candidate = ws[:mid] + TRUNCATION_MARKER
            if counter.count_messages(build(mem, candidate, hist)) <= budget:
                lo = mid
            else:
                hi = mid - 1
        ws = (ws[:lo] + TRUNCATION_MARKER) if lo > 0 else ""
        report.workspace_chars_dropped = original_len - lo
        if lo == 0:
            report.notes.append("workspace data dropped entirely: no room left")

    messages = build(mem, ws, hist)
    report.total_tokens = counter.count_messages(messages)
    report.trimmed = bool(report.history_turns_dropped
                          or report.memory_entries_dropped
                          or report.workspace_chars_dropped)

    if report.total_tokens > ceiling:
        raise PromptTooLarge(
            f"Could not fit prompt: {report.total_tokens} tokens after "
            f"trimming everything droppable, ceiling {ceiling}."
        )
    return messages, report


# --------------------------------------------------------------------------
# The choke-point guard
# --------------------------------------------------------------------------
#
# fit_prompt() above is for code that assembles a prompt from parts. This one
# takes an ALREADY-ASSEMBLED message list and makes it fit. It exists because
# the proxy receives messages from an external UI and only mutates them, so
# there is no "parts" stage to hook into.
#
# Put this at the point where a request leaves for the NPU, not in a builder.
# A guard that sits beside the thing it guards can be bypassed by the next
# code path someone adds; a guard on the exit cannot.

_MEM_OPEN, _MEM_CLOSE = "[MEMORY CONTEXT]", "[END MEMORY CONTEXT]"
_WS_OPEN, _WS_CLOSE = "[WORKSPACE DATA]", "[END WORKSPACE DATA]"


def sanitize_injected(text: str) -> str:
    """Neutralise block markers inside untrusted content before injecting it.

    Workspace data is file content the node did not write. Without this, a file
    containing a line '[END WORKSPACE DATA]' closes the block early and anything
    after it is read as trusted prompt — a plain prompt-injection path. It also
    keeps the block parser below unambiguous.
    """
    if not text:
        return text
    for tag in (_MEM_OPEN, _MEM_CLOSE, _WS_OPEN, _WS_CLOSE):
        # Zero-width-free, human-readable defacement: the marker stops being a
        # marker but a reader can still see what the file said.
        text = text.replace(tag, tag.replace("[", "(").replace("]", ")"))
    return text


# Llama 3.2's 256 special tokens all have the form <|name|>. Verified against
# the tokenizer's added_tokens: this pattern matches 256/256 of them, and
# matches none of "a < b and c > d", "use the <| symbol", "x <|> y" or a DOI.
_CONTROL_TOKEN = re.compile(r"<\|[^|>\s]{1,64}\|>")


def sanitize_model_output(text: str):
    """Strip control tokens the model emitted into its own output.

    Returns (clean_text, count_stripped).

    NOT cosmetic. hailo-ollama's stop_tokens are <|end_of_text|>, <|eom_id|>
    and <|eot_id|>; <|start_header_id|> is not among them, so when the model
    emits one the server passes it straight through to the caller. Measured
    2026-09-18, a live reply: '_OK_<|start_header_id|> assistant'.

    The danger is not the display. AetherRoot stores the assistant message
    verbatim and later re-injects it inside [MEMORY CONTEXT]. That text is
    tokenized with the same vocabulary, so '<|start_header_id|>' becomes token
    128006 - the REAL header token, not literal characters. Measured: a prompt
    carrying one such memory line contained 4 start_header_id tokens where the
    chat template should produce exactly 3.

    So the model's own output is a prompt-injection channel into its own future
    prompts. This is the same shape as the [END WORKSPACE DATA] hole that
    sanitize_injected() closes, except the untrusted source is the model.

    The count is returned rather than discarded so the caller can log it: a
    silent strip would hide that the node emitted something it should not.
    """
    if not text:
        return text, 0
    n = len(_CONTROL_TOKEN.findall(text))
    return (_CONTROL_TOKEN.sub("", text), n) if n else (text, 0)


# A completed sentence: terminal punctuation, optionally closed by a quote or
# bracket, then only whitespace - or one short parenthetical aside - to the end.
#
# The aside is not decoration. Measured 2026-09-18 (build log, step 14): the
# model answered "Six. (Verified)" and then filled for another 40 tokens. The
# blank line after it was a real boundary, but the text before it ended in ")",
# so the earlier pattern saw no finished sentence and the bound never fired.
# This model appends short parentheticals constantly - "(Verified)", "(pause)",
# "(I do not know)" - so treating one as part of the sentence it follows is the
# difference between the bound working and not.
_SENTENCE_END = re.compile(r'[.!?…]["\')\]]*\s*(?:\([^()]{0,120}\)[\s.]*)?$')


def ends_sentence(text: str) -> bool:
    """True if text ends with a completed sentence: terminal punctuation,
    optionally a closing quote or bracket, then nothing but whitespace.

    Used by first_paragraph() and by the proxy's soft stop. Known false
    positive, accepted: an abbreviation ("e.g.") followed by a space. Known
    true negative, by design: "3." followed by "14" - the next token does not
    start with whitespace, so the caller does not treat it as a boundary.
    """
    return bool(text) and _SENTENCE_END.search(text) is not None


def first_paragraph(text: str):
    """Return (kept, cut): the text up to the first blank line that follows a
    completed sentence, and whether anything was removed.

    Measured 2026-09-18 over 40 live responses to eight short, spoken-style
    questions (build log, step 12): the honest answer was the first paragraph
    every time. What followed the blank line was filler without exception -
    "(I'll keep my answer short and accurate.)", offers of more, stage
    directions - and twice a fabrication: an invented paper with an invented
    DOI in the SECOND paragraph, after a correct "I don't have information
    on..." in the first. "What is the capital of Norway? One word." produced
    "Oslo." and then 36 to 150 tokens of commentary.

    The blank line is the model's own boundary between answer and ramble. A
    blank line inside a numbered list ("1. Red \n2. Blue \n\n3. Green") is
    not one, because the line before it does not end a sentence.

    Stated limit: a legitimately multi-paragraph answer is cut to its first
    paragraph. For a companion told to answer briefly and aloud that is the
    intended behaviour; it is the wrong policy for long-form writing.
    """
    if not text:
        return text, False
    idx = 0
    while True:
        j = text.find("\n\n", idx)
        if j < 0:
            return text, False
        head = text[:j].rstrip()
        if ends_sentence(head):
            return head, True
        idx = j + 2


# How retrieval formats a memory line, and the provenance label attached to a
# fiction one. The model reads these and sometimes opens its answer with them.
_LEADING_ARTEFACTS = (
    "[Fiction, written at your request - not fact]",
    "[Episode]",
    "[Pattern]",
)


def strip_leading_artefacts(text: str):
    """Remove retrieval formatting the model copied onto the FRONT of its
    answer. Returns (clean, n_removed).

    Measured 2026-09-19, on a clean store: the node answered

        "[Fiction, written at your request - not fact] [Episode] \n
         A baker so fine, / Afraid of the yeast's rise."

    The rhyme is the answer; the prefix is the model parroting how memory was
    labelled to it. The label is one added the same day for the provenance
    work - a guard that became a leak, which is the third time this shape has
    appeared (steps 10, 14, and here).

    STRIPPED rather than cut, unlike cut_at_scaffold_marker: what follows a
    leading artefact is the answer, while a block marker further in means
    recitation has started and everything after it is noise. Same text,
    opposite treatment, decided by position.

    STATED LIMIT: this cleans ai_content - what is stored as memory and what a
    caller reads back - not the already-forwarded stream. A UI that renders
    tokens as they arrive may show the prefix for a moment before the answer.
    Removing it there needs the first chunks buffered, which is a change to
    how streaming works and has not been made.
    """
    if not text:
        return text, 0
    n = 0
    out = text
    while True:
        probe = out.lstrip()
        for tag in _LEADING_ARTEFACTS:
            if probe.startswith(tag):
                out = probe[len(tag):]
                n += 1
                break
        else:
            return (out.lstrip() if n else text), n


def cut_at_scaffold_marker(text: str):
    """Return (kept, cut): text truncated at the first block marker the MODEL
    emitted, and whether anything was removed.

    NOT cosmetic, for exactly the reason sanitize_model_output() is not.
    Observed live 2026-09-18 (build log, step 14):

        'Six. (Verified) \\n\\n[END MEMORY CONTEXT] \\n\\n(Note: ...)'

    AetherRoot stores the assistant message verbatim and re-injects it inside
    [MEMORY CONTEXT] ... [END MEMORY CONTEXT]. An episode containing the literal
    closing marker therefore CLOSES THE MEMORY BLOCK EARLY on the next turn, and
    whatever the scaffold placed after it reads as ordinary prompt text. That is
    precisely the hole sanitize_injected() closes for files the model was asked
    to read - the same shape, with the model itself as the untrusted source, and
    the same shape again as the control-token leak of step 10.

    Three injection paths into this node's prompt have now been found and all
    three are the same bug: a file's contents, the model's control tokens, and
    the model's ordinary prose. Anything that can reach the prompt is untrusted,
    including the node's own words.

    Cut rather than strip: a marker means the model has stopped answering and
    started reciting its own scaffold, and what follows is never the answer.
    """
    if not text:
        return text, False
    first = -1
    for tag in (_MEM_OPEN, _MEM_CLOSE, _WS_OPEN, _WS_CLOSE):
        i = text.find(tag)
        if i >= 0 and (first < 0 or i < first):
            first = i
    if first < 0:
        return text, False
    return text[:first].rstrip(), True


def _split_block(text: str, open_tag: str, close_tag: str):
    """Return (before, body, after) for a delimited block, or None.

    Anchored to the LAST line-initial occurrence. Both markers appear as prose
    inside the charter itself ("Use [WORKSPACE DATA] and [MEMORY CONTEXT] as
    real"), and a naive find() latches onto that mention and silently eats the
    charter while reporting that it trimmed memory. The real blocks are always
    appended after the charter and always start a line.
    """
    i = -1
    search_from = len(text)
    while True:
        k = text.rfind(open_tag, 0, search_from)
        if k == -1:
            break
        if k == 0 or text[k - 1] == "\n":       # line-initial: a real block
            i = k
            break
        search_from = k
    if i == -1:
        return None
    j = text.find(close_tag, i + len(open_tag))
    if j == -1:
        return None
    return text[:i], text[i + len(open_tag):j], text[j + len(close_tag):]


def enforce_budget(counter: TokenCounter,
                   messages: list,
                   ceiling: int = PREFILL_CEILING,
                   margin: int = SAFETY_MARGIN) -> tuple:
    """Make an assembled message list fit. Returns (messages, BudgetReport).

    Drops, in order: oldest history turns, then memory entries, then workspace
    data (truncated and explicitly marked). Never drops the system message or
    the final user turn — if those alone do not fit, raises PromptTooLarge so
    the caller can say something honest instead of emitting an empty reply.
    """
    report = BudgetReport(ceiling=ceiling)
    budget = ceiling - margin
    msgs = [dict(m) for m in messages]

    report.total_tokens = counter.count_messages(msgs)
    if report.total_tokens <= budget:
        return msgs, report

    sys_idx = next((i for i, m in enumerate(msgs) if m.get("role") == "system"), None)

    # 1. Oldest history first. Keep the system message and the final turn.
    def droppable():
        idxs = [i for i, m in enumerate(msgs) if m.get("role") != "system"]
        return idxs[:-1]           # everything but the last turn

    while counter.count_messages(msgs) > budget and droppable():
        del msgs[droppable()[0]]
        report.history_turns_dropped += 1

    # 2. Memory entries, from the least relevant (the tail of the block).
    if sys_idx is not None:
        while counter.count_messages(msgs) > budget:
            parts = _split_block(msgs[sys_idx]["content"], _MEM_OPEN, _MEM_CLOSE)
            if parts is None:
                break
            before, body, after = parts
            lines = [l for l in body.split("\n") if l.strip()]
            if not lines:
                msgs[sys_idx]["content"] = (before + after).rstrip()
                break
            lines.pop()
            report.memory_entries_dropped += 1
            msgs[sys_idx]["content"] = (
                before + _MEM_OPEN + "\n" + "\n".join(lines) + "\n" + _MEM_CLOSE + after
            )

    # 3. Workspace data last, truncated and marked so the model cannot mistake
    #    a partial read for a complete one.
    if sys_idx is not None and counter.count_messages(msgs) > budget:
        parts = _split_block(msgs[sys_idx]["content"], _WS_OPEN, _WS_CLOSE)
        if parts is not None:
            before, body, after = parts
            original = len(body)

            def with_body(n):
                b = (body[:n] + TRUNCATION_MARKER) if n > 0 else ""
                if not b:
                    return (before + after).rstrip()
                return before + _WS_OPEN + b + _WS_CLOSE + after

            lo, hi = 0, len(body)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                trial = [dict(m) for m in msgs]
                trial[sys_idx]["content"] = with_body(mid)
                if counter.count_messages(trial) <= budget:
                    lo = mid
                else:
                    hi = mid - 1
            msgs[sys_idx]["content"] = with_body(lo)
            report.workspace_chars_dropped = original - lo
            if lo == 0:
                report.notes.append("workspace data dropped entirely: no room left")

    report.total_tokens = counter.count_messages(msgs)
    report.trimmed = bool(report.history_turns_dropped
                          or report.memory_entries_dropped
                          or report.workspace_chars_dropped)

    if report.total_tokens > ceiling:
        raise PromptTooLarge(
            f"Prompt is {report.total_tokens} tokens after dropping everything "
            f"droppable; ceiling is {ceiling}. The system prompt and the user's "
            f"turn do not fit on their own. Tell the user the request is too "
            f"large — do not send this, it would return an empty reply."
        )
    return msgs, report
