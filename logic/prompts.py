"""Every prompt the model was given, word for word, and what came back
(build log 72, G4).

The question from the trust-architecture comparison (Andreas, 11 Oct 2026):
can a turn be reproduced without asking the model? Before this, no. What a
turn was shown is built at that moment from things that change after it:
- her memory (every stored turn, ring, correction and steward fact);
- the word statistics the retrieval ranks by, updated with every turn;
- recency, which is measured from the moment of asking;
- the file read for it, which may have changed since.
provenance.log kept the first 160 characters of the question and of the
answer. So the prompt could not be rebuilt from parts, and the plan's "a hash
of the prompt, plus whatever is needed to rebuild it" is the prompt itself.

So every request to the model - a turn, homework, an explanation of a
passage, a ring's own sentence - is kept in prompts.log, one chained line
each (logic/chain.py):
- "sha256": the hash of the exact bytes sent to hailo-ollama;
- "body": those bytes, as text - the hash can be checked against them;
- "reply": what the unit kept of the answer, after its stops;
- "outcome": answered, braked, or failed (and why).
The turn's own line in provenance.log carries the same "prompt_sha256", so
from either side the other can be found.

What it cannot do: say what the model would answer again. The server samples
(temperature 0.4, top_p 0.9) and its template adds the day's date (not in
the body; the line's "at" has it), so the same prompt can be answered
differently. This is the record of what was asked and what was said, not a
way to ask again.

Size, for Lyra - estimated from her bounds, not yet measured on her: a
prompt of at most 864 tokens and an answer of at most 80; with her memory
budget (800 characters) about 2.5 KB a line, at most about 4 KB. Her busiest
day in provenance.log (2,809 requests, 9 Oct) would be some 7 MB; her card
had 208 GB free on 12 Oct.

Nothing here may stop a turn: a record that cannot be written is said in
the journal, and the answer goes out.
"""
import hashlib
import json
import threading
from datetime import datetime, timezone

from logic import chain

_LAST = threading.local()


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def forget():
    """A turn starts with no prompt of its own yet."""
    _LAST.sha256 = None


def last_sha256():
    """The hash of the last prompt this thread sent - the turn's own, read
    after its call. None when the model was not asked."""
    return getattr(_LAST, "sha256", None)


class Call:
    """One request to the model: begun with the bytes about to be sent, done
    with what came back. The hash is this thread's from the start, so a
    failed call still names the prompt that failed."""

    def __init__(self, path, body: bytes):
        self.path = path
        self.body = body
        self.sha256 = digest(body)
        _LAST.sha256 = self.sha256

    def done(self, outcome: str, reply: str = "") -> str:
        try:
            chain.append(self.path, {
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "sha256": self.sha256,
                "outcome": str(outcome)[:200],
                "reply": reply or "",
                "body": self.body.decode("utf-8", errors="replace"),
            }, announce="prompts.log")
        except Exception as e:
            print(f"[prompts] the prompt could not be kept: {e!r}", flush=True)
        return self.sha256


def find(path, sha256):
    """The first record of this prompt, or None. The hash names the prompt,
    not the call: the same words sent twice have one hash (tools/show_prompt.py
    shows every call)."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if sha256 in line:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("sha256") == sha256:
                        return rec
    except FileNotFoundError:
        pass
    return None


def body_holds(rec) -> bool:
    """Is the body the bytes whose hash it carries?"""
    try:
        return digest(rec["body"].encode("utf-8")) == rec["sha256"]
    except Exception:
        return False


def verify(path) -> dict:
    """The chain (logic/chain.verify), and each body against its own hash."""
    out = chain.verify(path)
    bad = []
    try:
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if "sha256" in rec and not body_holds(rec):
                    bad.append(n)
    except FileNotFoundError:
        pass
    out["bodies_not_holding"] = bad
    if bad and out.get("ok"):
        out["ok"] = False
        out["why"] = "line %d: the body is not what its hash says" % bad[0]
    return out
