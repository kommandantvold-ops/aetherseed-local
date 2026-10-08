"""How far she trusts a person: their record, counted from her memory (build log 67).

Andreas, 8 Oct 2026: "there should also be a trust level from unit to user, an
interaction for Lyra to measure how much she trusts me and you". Asked, he
chose:
  - it rests on THE PERSON'S TRACK RECORD - counted by the unit from her
    memory, and shown with the evidence; not her opinion of them;
  - it CHANGES HOW FACTS COME BACK: what a person whose word has often been
    withdrawn told her comes back marked so;
  - "you" is Claude: the training loop's turns and marks, and a speaker of
    its own, "Claude", for what Claude says to her directly;
  - a correction the training made that its key now passes - the key was
    wrong - is withdrawn at his word (training/withdraw_corrections.py), and
    then counts against Claude.

WHAT IS COUNTED is what each person ASSERTED to her and whether it STILL
STANDS - not whether it was true, which the unit cannot know:

  her steward   facts he told her (the facts table, his own entries), his
                corrections of her, his "It's right" - each standing, or
                withdrawn (retracted, undone);
  Claude        the training key's corrections of her and its passes -
                standing, or withdrawn (undone: at his word, when the key was
                found wrong); and turns said to her as "Claude", counted only.
                Claude's builds are not in her memory and are not counted.

A share of what still stands, over enough of it to say anything
(MIN_RECORD), gives a word: high, some, low. These thresholds are this
build's choice, not his. A record is never a judgement of the person; she
says what it counts and how.
"""
from logic.speaker import is_steward

CLAUDE = "Claude"
TRAINING = "training"
MIN_RECORD = 5          # fewer than this, and there is too little to say
HIGH, SOME = 0.9, 0.7   # share standing for "high" and for "some"


def _level(standing, total):
    if total < MIN_RECORD:
        return "too little"
    share = standing / total
    return "high" if share >= HIGH else "some" if share >= SOME else "low"


def steward_record(store):
    notes = store.steward_notes(target=None, active_only=False)
    mine = [n for n in notes if (n.get("by") or "steward") != TRAINING]
    from_notes = {n["fact_id"] for n in notes if n.get("fact_id")}
    facts = [f for f in store.facts(active_only=False)
             if f["id"] not in from_notes and (f.get("entered_by") or "steward") in ("steward", "owner")]
    corrections = [n for n in mine if n["action"] == "correct"]
    supports = [n for n in mine if n["action"] == "support"]
    rec = {
        "who": "steward",
        "facts": len(facts), "facts_withdrawn": sum(1 for f in facts if f.get("revoked_at")),
        "corrections": len(corrections),
        "corrections_withdrawn": sum(1 for n in corrections if n.get("undone_at")),
        "marked_right": len(supports),
        "marked_right_withdrawn": sum(1 for n in supports if n.get("undone_at")),
    }
    total = rec["facts"] + rec["corrections"] + rec["marked_right"]
    withdrawn = rec["facts_withdrawn"] + rec["corrections_withdrawn"] + rec["marked_right_withdrawn"]
    rec.update(total=total, standing=total - withdrawn, level=_level(total - withdrawn, total))
    return rec


def claude_record(store):
    notes = [n for n in store.steward_notes(target=None, active_only=False)
             if (n.get("by") or "") == TRAINING]
    corrections = [n for n in notes if n["action"] == "correct"]
    passes = [n for n in notes if n["action"] == "support"]
    said = store.conn.execute("SELECT COUNT(*) FROM episodes WHERE speaker = ?",
                              (CLAUDE,)).fetchone()[0]
    trainer = store.conn.execute("SELECT COUNT(*) FROM episodes WHERE speaker = 'Trainer'"
                                 ).fetchone()[0]
    rec = {
        "who": "claude",
        "corrections": len(corrections),
        "corrections_withdrawn": sum(1 for n in corrections if n.get("undone_at")),
        "passes": len(passes),
        "passes_withdrawn": sum(1 for n in passes if n.get("undone_at")),
        "trainer_turns": trainer, "said_as_claude": said,
    }
    total = rec["corrections"] + rec["passes"]
    withdrawn = rec["corrections_withdrawn"] + rec["passes_withdrawn"]
    rec.update(total=total, standing=total - withdrawn, level=_level(total - withdrawn, total))
    return rec


def steward_facts_checked(store):
    """Do her steward's facts come back as plain "[Steward told you]"? Yes,
    unless his record is LOW: then they come back marked as not checked."""
    return steward_record(store)["level"] != "low"


# ---- "How much do you trust me?" ------------------------------------------------
import re

_ASK = re.compile(
    r"\b(?:how\s+(?:much|far)\s+do\s+you\s+trust|do\s+you\s+trust|how\s+(?:much|far)\s+can\s+you\s+trust|"
    r"what\s+is\s+your\s+trust\s+in|how\s+much\s+trust\s+do\s+you\s+have\s+in|"
    r"hvor\s+(?:mye|langt)\s+stoler\s+du\s+på|stoler\s+du\s+på)\b", re.I)
_CLAUDE = re.compile(r"\bclaude\b", re.I)
_ME = re.compile(r"\b(?:me|meg)\b", re.I)
_STEWARD = re.compile(r"\b(?:(?:my|your|the)\s+steward|forvalter(?:en)?(?:\s+din)?)\b", re.I)


def trust_question(text, steward_name=None):
    """None, or whom it asks about: 'asker', 'steward' or 'claude'."""
    t = " ".join((text or "").split())
    if len(t) > 160 or not _ASK.search(t):
        return None
    if _CLAUDE.search(t):
        return "claude"
    if _STEWARD.search(t) or (steward_name and re.search(r"\b%s\b" % re.escape(steward_name), t, re.I)):
        return "steward"
    if _ME.search(t):
        return "asker"
    return None


def _n(n, one, many):
    return "%d %s" % (n, one if n == 1 else many)


_LEVEL_WORDS = {"high": "high", "some": "some, not high", "low": "low",
                "too little": "too little to say yet"}


def steward_text(rec, steward_name=None):
    who = steward_name or "my steward"
    you = "you" if steward_name is None else steward_name
    if rec["total"] == 0:
        return ("I have no record of %s yet: %s has told me no fact, corrected nothing and marked "
                "nothing as right. My trust in a person is a count of what they told me and "
                "what of it still stands." % (who, who))
    parts = []
    if rec["facts"]:
        parts.append("told me %s, and withdrew %d" % (_n(rec["facts"], "fact", "facts"), rec["facts_withdrawn"]))
    if rec["corrections"]:
        parts.append("corrected me %s, and undid %d" % (_n(rec["corrections"], "time", "times"),
                                                       rec["corrections_withdrawn"]))
    if rec["marked_right"]:
        parts.append("marked %s as right, and took back %d" % (
            _n(rec["marked_right"], "answer", "answers"), rec["marked_right_withdrawn"]))
    return ("My record of %s: %s has %s. Of those %d, %d still stand. My trust from that "
            "record: %s. It counts what %s told me and whether it still stands; it cannot "
            "tell whether it was true." % (who, who, "; ".join(parts), rec["total"],
                                           rec["standing"], _LEVEL_WORDS[rec["level"]], you))


def claude_text(rec):
    if rec["total"] == 0 and rec["trainer_turns"] == 0 and rec["said_as_claude"] == 0:
        return ("I have no record of Claude yet. Claude builds me and runs my training; what "
                "the training tells me and what Claude says to me as Claude would be counted.")
    out = ("My record of Claude: Claude's training spoke to me %s and its answer key "
           "corrected me %s - %d of those corrections were later withdrawn because the key was "
           "wrong - and passed %s. " % (
               _n(rec["trainer_turns"], "time", "times"), _n(rec["corrections"], "time", "times"),
               rec["corrections_withdrawn"], _n(rec["passes"], "answer", "answers")))
    if rec["said_as_claude"]:
        out += "Claude has also spoken to me as Claude %s. " % _n(rec["said_as_claude"], "time", "times")
    out += ("Of the %d corrections and passes, %d still stand. My trust from that record: %s. "
            "Claude's builds are not in my memory, and are not counted."
            % (rec["total"], rec["standing"], _LEVEL_WORDS[rec["level"]]))
    return out


def answer(store, about, speaker=None, steward_name=None):
    """The unit's answer to a trust question, model not called."""
    if about == "asker":
        if speaker is None or is_steward(speaker):
            about = "steward"
        elif speaker == CLAUDE:
            about = "claude"
        else:
            return ("I keep a record of trust for my steward and for Claude only. Of you, %s, "
                    "I have none." % speaker)
    if about == "claude":
        return claude_text(claude_record(store))
    return steward_text(steward_record(store), steward_name)
