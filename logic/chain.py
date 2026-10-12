"""Records that show whether they were changed (build log 72, G2).

The node keeps its own account in plain JSON lines:
- provenance.log: every turn;
- corrections.log: every correction, every steward fact added, revoked or
  restored, every cap changed;
- trust_events.log: every event that moved her standing, and every grant;
- control.log: every brake and every release (G3);
- growth.log: every ring closed, and every wipe of her memory.

Until step 72 a line could be changed, removed or added afterwards and
nothing would show it. Now every line written through append() carries two
fields:

    "prev"  the hash before it
    "hash"  sha256 of prev followed by the line's own content (its JSON with
            sorted keys, without "hash")

so changing any line breaks its own hash, and removing or inserting one breaks
the next line's prev. verify() walks a file and names the first line that does
not hold.

Nothing written before this step is rewritten. The first line written through
append() takes as its prev the sha256 of every byte before it, which fixes
the old lines as they stood that day. The same happens after any line that is
not part of the chain: a line written by an older tool, or a line torn by a
power cut. A line that is part of the chain is always followed from its own
hash, never re-fixed, so an edit to it cannot be blessed by a later line.

What a chain cannot show by itself: the whole file rewritten from some line
on, every hash recomputed. That is what the journal is for. A writer that is
given announce= prints "[chain] <name> <hash>" to stdout, which for the
proxy is the system journal, kept by root and outside the node's own
files. tools/verify_chain.py --journal checks that every head the journal
saw is still in the file.

Appends take an exclusive lock on the file (flock), so the proxy's threads
and a steward's tool cannot interleave. Each line is fsynced before the lock
is released.
"""
import fcntl
import hashlib
import json
import os

ZERO = "0" * 64
_TAIL = 1 << 16          # lines are far shorter; a longer one re-anchors
_HEX = set("0123456789abcdef")


def canonical(entry):
    """The bytes a line's hash is taken over: its JSON without "hash"."""
    body = {k: v for k, v in entry.items() if k != "hash"}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def line_hash(prev, entry):
    return hashlib.sha256((prev + canonical(entry)).encode("utf-8")).hexdigest()


def _is_hash(v):
    return isinstance(v, str) and len(v) == 64 and set(v) <= _HEX


def _chained(raw):
    """The line as a dict if it is part of a chain, else None."""
    try:
        e = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if isinstance(e, dict) and _is_hash(e.get("hash")) and _is_hash(e.get("prev")):
        return e
    return None


def _whole(f):
    f.seek(0)
    h = hashlib.sha256()
    for block in iter(lambda: f.read(1 << 20), b""):
        h.update(block)
    return h.hexdigest()


def _prev_for_next(f):
    """The prev the next line takes. Called holding the lock, the file at its end."""
    size = f.seek(0, os.SEEK_END)
    if size == 0:
        return ZERO
    f.seek(max(0, size - _TAIL))
    tail = f.read()
    if not tail.endswith(b"\n"):
        # A torn last line (a cut mid-write): it is closed, and the next line
        # fixes everything before it, the torn piece included.
        f.write(b"\n")
        f.flush()
        return _whole(f)
    lines = tail[:-1].split(b"\n")
    last = lines[-1] if (len(lines) > 1 or size <= _TAIL) else b""
    e = _chained(last) if last else None
    if e is not None:
        return e["hash"]
    return _whole(f)


def append(path, entry, announce=None):
    """Write entry as one chained line at the end of path. Returns its hash.

    entry must be JSON-serialisable; "prev" and "hash" are set here, and any
    the caller passed are replaced. announce: a short name printed with the
    hash ("[chain] provenance.log 1a2b...") - give it where stdout is the
    journal. Raises OSError like any write; callers that must not fail catch
    it, as they did before.
    """
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    entry = {k: v for k, v in dict(entry).items() if k not in ("prev", "hash")}
    with open(path, "a+b") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            prev = _prev_for_next(f)
            entry["prev"] = prev
            entry["hash"] = line_hash(prev, entry)
            f.seek(0, os.SEEK_END)
            f.write((json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    if announce:
        print("[chain] %s %s" % (announce, entry["hash"][:16]), flush=True)
    return entry["hash"]


def verify(path):
    """Walk path. Returns a dict:

    ok          True if every chained line holds
    lines       lines in the file
    chained     lines that are part of the chain
    started     the line number where the chain starts (None: no chain yet)
    anchors     chained lines that fix everything before them (the first,
                and one after each line outside the chain)
    outside     lines after the start that are not part of the chain
                (an older writer, a torn line) - each is fixed by the next
                chained line, and listed by number
    head        the last chained line's hash
    heads       every chained line's hash, in order
    first_bad   the first line that does not hold (None if ok)
    why         what is wrong with it
    """
    res = {"ok": True, "lines": 0, "chained": 0, "started": None, "anchors": 0,
           "outside": [], "head": None, "heads": [], "first_bad": None, "why": ""}
    running = hashlib.sha256()
    offset = 0
    last = None                       # the previous line's hash, if it was chained
    try:
        f = open(path, "rb")
    except FileNotFoundError:
        return res
    with f:
        for n, raw in enumerate(f, start=1):
            res["lines"] = n
            before = ZERO if offset == 0 else running.hexdigest()
            running.update(raw)
            offset += len(raw)
            e = _chained(raw.rstrip(b"\n"))
            if e is None:
                if res["started"] is not None:
                    res["outside"].append(n)
                last = None
                continue
            if res["ok"]:
                if e["hash"] != line_hash(e["prev"], e):
                    res.update(ok=False, first_bad=n,
                               why="its content is not what was written: its hash does not match")
                elif last is not None and e["prev"] != last:
                    res.update(ok=False, first_bad=n,
                               why="the line before it is not the one it followed: "
                                   "a line was changed, removed or put in")
                elif last is None and e["prev"] != before:
                    res.update(ok=False, first_bad=n,
                               why="what stands before it is not what stood when it "
                                   "was written")
            if last is None:
                res["anchors"] += 1
            if res["started"] is None:
                res["started"] = n
            res["chained"] += 1
            res["heads"].append(e["hash"])
            res["head"] = e["hash"]
            last = e["hash"]
    return res
