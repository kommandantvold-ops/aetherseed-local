"""The approvals queue: a request to the steward instead of a flat refusal.

 He chose the proposal over the alternative (every write waiting
for his OK, even when he is the one asking).

What it is:
- An action ABOVE her level, of a kind that leaves something behind (a to-do
  added, a note written), is no longer only refused. It is filed as a request
  to her steward. She says so, and says nothing has been done yet.
- He approves it once, and the unit does it then: the same tool, the same
  words, run by the unit and not by the model. Or he declines it.
- A request he does not answer expires after a day and is never done.
- Every step is a chained line in control.log: filed, approved (with what
  the tool did), declined, expired.

What it is not:
- Not for a tool her steward has BLOCKED: that is his word already, and it
  is told as his word.
- Not for answers (calculate, count, compare), which leave nothing behind,
  nor for reads, which are open at every level.
- Not for homework: a turn of the training loop is refused as before, or the
  loop would fill his queue.
- Not a way round her level for anything else: one request, one action,
  approved by a person.
"""
import json
import os
import threading
from datetime import datetime, timedelta, timezone

from logic import chain

QUEUEABLE = ("todo_add", "note_write")
EXPIRE_HOURS = 24
MAX_PENDING = 20
# What is approved is what was asked, word for word: never cut short. Longer
# than this, nothing is filed and the refusal is told as before.
MAX_WORDS = 4000
_LOCK = threading.Lock()


def words_of(intent):
    """What the tool would be given: the words after the colon, as typed. None
    when there are none ("save this as a note" names something said before,
    and the tool would write the request itself) - then nothing is filed and
    the refusal is told as before."""
    captures = (intent or {}).get("captures") or ()
    words = captures[0] if captures else None
    if isinstance(words, str) and words.strip() and len(words) <= MAX_WORDS:
        return words
    return None


def _now():
    return datetime.now(timezone.utc)


def _iso(t):
    return t.isoformat(timespec="seconds")


class Approvals:
    """approvals.json (state, written atomically) and control.log (chained)."""

    def __init__(self, path, log, clock=_now):
        self.path = path
        self.log = log
        self.clock = clock

    # ---- state ------------------------------------------------------------
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not isinstance(data.get("requests"), list):
                raise ValueError("not the queue")
            return data
        except FileNotFoundError:
            return {"next_id": 1, "requests": []}
        except (OSError, ValueError) as e:
            # An unreadable queue is set aside, never acted on: nothing in it
            # can be approved, and it is said.
            from aetherroot import set_aside
            set_aside(self.path, repr(e)[:120])
            print("[approvals] the queue could not be read; it is set aside and starts "
                  "empty", flush=True)
            return {"next_id": 1, "requests": []}

    def _save(self, data):
        from aetherroot import atomic_write
        atomic_write(self.path, json.dumps(data, indent=2, ensure_ascii=False))

    def _record(self, entry):
        entry = dict(entry, at=_iso(self.clock()))
        chain.append(self.log, entry, announce=os.path.basename(self.log))

    def _expire(self, data):
        """Requests past their day: expired, recorded once, never done."""
        now = self.clock()
        changed = False
        for r in data["requests"]:
            if r["status"] == "waiting" and datetime.fromisoformat(r["expires_at"]) <= now:
                r["status"] = "expired"
                r["resolved_at"] = _iso(now)
                self._record({"action": "request_expired", "request": r["id"], "tool": r["tool"]})
                changed = True
        return changed

    # ---- what the proxy does ----------------------------------------------
    def file(self, tool, args, speaker, said, level, opens_at):
        """File a request. Returns (request, how): how is "filed", "waiting"
        (the same request is already waiting) or "full"."""
        args = [str(a) for a in (args or ())]
        if not args or any(len(a) > MAX_WORDS for a in args):
            raise ValueError("a request holds the words to act on, at most %d characters"
                             % MAX_WORDS)
        with _LOCK:
            data = self._load()
            changed = self._expire(data)
            for r in data["requests"]:
                if r["status"] == "waiting" and r["tool"] == tool and r["args"] == args:
                    if changed:
                        self._save(data)
                    return r, "waiting"
            if sum(1 for r in data["requests"] if r["status"] == "waiting") >= MAX_PENDING:
                if changed:
                    self._save(data)
                return None, "full"
            now = self.clock()
            r = {"id": data["next_id"], "tool": tool, "args": args,
                 "speaker": speaker or "", "said": (said or "")[:200],
                 "level": level, "opens_at": opens_at,
                 "filed_at": _iso(now), "expires_at": _iso(now + timedelta(hours=EXPIRE_HOURS)),
                 "status": "waiting"}
            data["next_id"] += 1
            data["requests"].append(r)
            data["requests"] = data["requests"][-200:]
            self._save(data)
            self._record({"action": "request_filed", "request": r["id"], "tool": tool,
                          "args": args, "speaker": r["speaker"], "level": level})
            return r, "filed"

    def view(self, recent=10):
        with _LOCK:
            data = self._load()
            if self._expire(data):
                self._save(data)
            waiting = [r for r in data["requests"] if r["status"] == "waiting"]
            done = [r for r in data["requests"] if r["status"] != "waiting"][-recent:]
            return {"pending": waiting, "recent": list(reversed(done))}

    def pending_count(self):
        return len(self.view(recent=0)["pending"])

    def resolve(self, rid, approve, by, reason, do):
        """Approve (do(request) -> what the tool said) or decline one waiting
        request. Returns (request, error)."""
        with _LOCK:
            data = self._load()
            changed = self._expire(data)
            r = next((x for x in data["requests"] if x["id"] == rid), None)
            if r is None or r["status"] != "waiting":
                if changed:
                    self._save(data)
                return r, ("no such request" if r is None else "it is %s already" % r["status"])
            now = _iso(self.clock())
            reason = " ".join(str(reason or "").split())[:200]
            if approve:
                try:
                    result = str(do(r))[:300]
                except Exception as e:
                    result = "[ERROR] %r" % (e,)
                # Approved but not done (the tool said [ERROR]) is said as
                # that: "failed", never "approved" as if the to-do were there.
                done = not result.startswith("[ERROR]")
                r.update(status="approved" if done else "failed", resolved_at=now, by=by,
                         reason=reason, result=result)
                self._save(data)
                self._record({"action": "request_approved", "request": r["id"], "tool": r["tool"],
                              "args": r["args"], "by": by, "reason": reason, "done": done,
                              "result": result})
            else:
                r.update(status="declined", resolved_at=now, by=by, reason=reason)
                self._save(data)
                self._record({"action": "request_declined", "request": r["id"], "tool": r["tool"],
                              "by": by, "reason": reason})
            return r, None
