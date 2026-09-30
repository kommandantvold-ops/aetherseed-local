"""Guided correction: the steward supports or corrects what the companion
remembers, from the console (build log 50).

Andreas, 30 Sep 2026: "I want a guided correction where I can see and select
memories and consolidations and make suggestions and support." Asked, he
chose: a correction takes effect AT ONCE AND IS REVERSIBLE, and support is
MARKED AND COUNTS TOWARD TRUST.

The design is the one written down on 25 Sep (handover 4d/4e, "cognitive first
aid"): guided, not a free-text box, because a comment cannot aid a process that
does not reason - so the correction is STRUCTURED:

  1. what is wrong   - one of REASONS
  2. what is true    - the steward's words, where needed (not for "never
                       happened"), checked like any fact the steward enters
  3. what will change - shown before it is confirmed (the console's job)

WHAT A CORRECTION DOES - and nothing more:
  - a turn: its mode becomes 'unverified', the existing "never used as
    memory" (it drops out of retrieval and out of every future ring); the mode
    it had is kept in the note, so undo puts it back;
  - a ring: it is left out of retrieval while the note stands;
  - what the steward wrote is kept as a fact, word for word, attributed -
    it comes back as "[Steward told you] ...", never as something the companion
    knows itself (logic/facts.py);
  - nothing is deleted or rewritten; every step goes to corrections.log.

WHAT SUPPORT DOES: marks a turn or ring as right, on the console, and adds
SUPPORT_POINTS to her resonance - at most SUPPORT_DAILY_CAP a day, once per
turn or ring. A new rung takes effect at the next start, as every rung does.
The points and the cap are this build's choice, not Andreas's; he chose that
support counts. Undoing a support takes its points back.

The earlier barrier - "the owner must not be able to tamper with the node's
memory from the console" (Andreas, 23 Sep; tools/correct_memory.py) - is
superseded by his decision of 30 Sep. What it protected is kept by other
means: nothing is erased, everything is reversible, attributed and recorded.
"""
import json
import os
from datetime import datetime, timezone

from logic.facts import validate_fact

REASONS = {
    "never": "this never happened",
    "part": "part of it is wrong",
    "about": "this was about something else",
    "detail": "a name or detail is wrong",
}
# A correction that only says "never happened" needs nothing written; the
# others say what is true instead.
TEXT_OPTIONAL = frozenset({"never"})

SUPPORT_POINTS = 2
SUPPORT_DAILY_CAP = 10
UNVERIFIED = "unverified"
TARGETS = ("turn", "ring")

ERRORS = {
    "bad_target": "that is neither a turn nor a ring",
    "not_found": "there is no such turn or ring",
    "bad_reason": "choose what is wrong",
    "text_required": "say what is true",
    "already_corrected": "this is already corrected - undo that first",
    "already_supported": "this is already supported",
    "corrected": "a corrected memory cannot be supported - undo the correction first",
    "no_note": "there is nothing to undo",
    "too_many_facts": "the companion holds as many of your facts as it can",
}


class StewardError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code = code
        self.detail = detail or ERRORS.get(code, code)


def _now():
    return datetime.now(timezone.utc)


def _log(path, entry):
    if not path:
        return
    entry = dict(entry, at=_now().isoformat(timespec="seconds"), by="steward (console)")
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[steward] could not write the corrections log: {e!r}", flush=True)


def _target(store, target, target_id):
    if target not in TARGETS:
        raise StewardError("bad_target")
    try:
        target_id = int(target_id)
    except (TypeError, ValueError):
        raise StewardError("not_found")
    row = store.episode(target_id) if target == "turn" else store.ring_by_id(target_id)
    if not row or (target == "ring" and row.get("ring_no") is None):
        raise StewardError("not_found")
    return target_id, row


def _active(store, target, target_id, action=None):
    notes = store.steward_notes(target=target, target_ids=[target_id])
    return [n for n in notes if action is None or n["action"] == action]


def points_today(store):
    today = _now().date().isoformat()
    return sum(n["trust_points"] for n in store.steward_notes(target=None)
               if n["action"] == "support" and n["created_at"][:10] == today)


def status_for(store, target, ids):
    """{target_id: {"support": note|None, "correction": note|None}} for the console."""
    out = {}
    for n in store.steward_notes(target=target, target_ids=ids):
        slot = out.setdefault(n["target_id"], {"support": None, "correction": None})
        slot["support" if n["action"] == "support" else "correction"] = public(n)
    return out


def public(note):
    return {k: note[k] for k in ("id", "created_at", "action", "reason", "text",
                                 "trust_points")} if note else None


def support(store, trust, target, target_id, log_path=None):
    target_id, _ = _target(store, target, target_id)
    if _active(store, target, target_id, "correct"):
        raise StewardError("corrected")
    if _active(store, target, target_id, "support"):
        raise StewardError("already_supported")
    points = max(0, min(SUPPORT_POINTS, SUPPORT_DAILY_CAP - points_today(store)))
    note_id = store.add_steward_note(target, target_id, "support", trust_points=points)
    if points and trust is not None:
        trust.record_event("steward_support", f"{target} {target_id}")
    _log(log_path, {"action": "support", "target": target, "target_id": target_id,
                    "note": note_id, "trust_points": points})
    return {"note": public(store.steward_note(note_id)), "trust_points": points,
            "capped": points < SUPPORT_POINTS}


def correct(store, target, target_id, reason, text="", facts_max=250,
            trust=None, log_path=None):
    target_id, row = _target(store, target, target_id)
    if reason not in REASONS:
        raise StewardError("bad_reason")
    if _active(store, target, target_id, "correct"):
        raise StewardError("already_corrected")
    text = (text or "").strip()
    if not text and reason not in TEXT_OPTIONAL:
        raise StewardError("text_required")
    source = ("Steward's correction of turn %d" % target_id if target == "turn"
              else "Steward's correction of ring %d" % row["ring_no"])
    if text:
        text, source, err = validate_fact(text, source)
        if err:
            raise StewardError(err, "what is true: " + err)
        if store.fact_count(active_only=True) >= facts_max:
            raise StewardError("too_many_facts")

    # A support of the same memory goes: it cannot be right and wrong at once.
    withdrawn = 0
    for n in _active(store, target, target_id, "support"):
        withdrawn += _undo(store, trust, n, log_path)

    fact_id = store.add_fact(text, source, entered_by="steward") if text else None
    prior = ""
    if target == "turn":
        prior = row["mode"]
        store.set_episode_mode(target_id, UNVERIFIED)
    note_id = store.add_steward_note(target, target_id, "correct", reason=reason,
                                     text=text, fact_id=fact_id, prior_mode=prior)
    _log(log_path, {"action": "correct", "target": target, "target_id": target_id,
                    "note": note_id, "reason": reason, "text": text, "fact": fact_id,
                    "mode_before": prior, "mode_after": UNVERIFIED if target == "turn" else ""})
    return {"note": public(store.steward_note(note_id)), "fact_id": fact_id,
            "support_withdrawn": withdrawn}


def _undo(store, trust, note, log_path):
    """Undo one active note; returns the trust points taken back."""
    taken = 0
    if note["action"] == "support":
        if note["trust_points"] and trust is not None:
            trust.record_event("steward_support_withdrawn",
                               f"{note['target']} {note['target_id']}")
            taken = note["trust_points"]
    else:
        if note["fact_id"]:
            store.set_fact_revoked(note["fact_id"], True)
        if note["target"] == "turn":
            ep = store.episode(note["target_id"])
            # Put the mode back only if nothing else has changed it since.
            if ep and ep["mode"] == UNVERIFIED and note["prior_mode"]:
                store.set_episode_mode(note["target_id"], note["prior_mode"])
    store.undo_steward_note(note["id"])
    _log(log_path, {"action": "undo", "undone": note["action"], "target": note["target"],
                    "target_id": note["target_id"], "note": note["id"],
                    "fact_revoked": note["fact_id"] if note["action"] == "correct" else None,
                    "mode_restored": note["prior_mode"] if note["target"] == "turn"
                    and note["action"] == "correct" else "",
                    "trust_points_taken_back": taken})
    return taken


def undo(store, trust, note_id, log_path=None):
    try:
        note = store.steward_note(int(note_id))
    except (TypeError, ValueError):
        note = None
    if not note or note["undone_at"]:
        raise StewardError("no_note")
    taken = _undo(store, trust, note, log_path)
    out = {"undone": note["id"], "trust_points_taken_back": taken}
    if note["target"] == "turn":
        ep = store.episode(note["target_id"])
        out["mode"] = ep["mode"] if ep else None
    return out
