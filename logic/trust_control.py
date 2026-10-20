"""Trust management: the steward's controls over what she may do.

 He chose
three things that are built here. All of them sit outside the model, and none
can be reached from what she says.

1. Standing and history: her level, the points to the next, and every event
   that moved them. The events are read from trust_events.log, the chained
   record, which is checked as it is read.
2. Grant, lower, freeze:
   - grant existed already; it raises her standing to a
     level's threshold and takes effect at the next start, as every level
     does;
   - lower is new: her standing is set to a lower level's threshold, and it
     takes effect AT ONCE on the unit's gate, since taking a permission away
     should not wait;
   - freeze is new: no automatic event moves her standing until it is lifted.
     His grant and his lowering still do.
3. Per-tool overrides: allow or block one tool regardless of her level,
   checked in the gate before her tier. A block holds at any level. Network
   stays off when the unit has it off. Stored in trust_control.json, outside
   her memory.

Every action needs a reason. Every action is recorded twice: in control.log
(chained, beside the brake) and, where it moves her standing, in
trust_events.log (chained) as well.

Nothing here asks a person: a tier-2 write is allowed on first use, and tier 3
is allowed and logged. The approvals queue (logic/approvals.py) is where a
person's approval is recorded.
"""
import json
import os
from datetime import datetime, timezone

from logic import chain

MAX_REASON = 200
RULES = ("allow", "block")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_reason(reason):
    """A reason, one line, at most 200 characters, or None if there is none."""
    r = " ".join(str(reason or "").split())[:MAX_REASON]
    return r or None


class Controls:
    """The steward's rules on single tools, and the record of every change.

    path:    trust_control.json (state, written atomically)
    log:     control.log (chained)
    """

    def __init__(self, path, log):
        self.path = path
        self.log = log
        self._cache = (None, {})

    # ---- the rules --------------------------------------------------------
    def _read(self):
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return {"overrides": {}}
        key = (st.st_mtime_ns, st.st_size)
        if self._cache[0] == key:
            return self._cache[1]
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not isinstance(data.get("overrides", {}), dict):
                raise ValueError("not the rules")
        except (OSError, ValueError) as e:
            # Unreadable rules fail closed: every rule there is unknown, so
            # every tool is held until the file is fixed (the gate's except).
            raise RuntimeError("trust_control.json could not be read: %r" % (e,))
        self._cache = (key, data)
        return data

    def overrides(self):
        """{tool: {"rule", "since", "by", "reason"}} - what the gate asks."""
        return dict(self._read().get("overrides", {}))

    def _write(self, data):
        from aetherroot import atomic_write
        atomic_write(self.path, json.dumps(data, indent=2))
        self._cache = (None, {})

    def _record(self, entry):
        entry = dict(entry, at=_now())
        chain.append(self.log, entry, announce=os.path.basename(self.log))
        print("[trust] %s%s by %s: %s" % (
            entry["action"], (" " + entry["tool"]) if entry.get("tool") else
            ((" " + entry["level"]) if entry.get("level") else ""),
            entry.get("by", "?"), entry.get("reason", "")), flush=True)

    def set_override(self, tool, rule, by, reason):
        data = dict(self._read())
        ov = dict(data.get("overrides", {}))
        ov[tool] = {"rule": rule, "since": _now(), "by": by, "reason": reason}
        data["overrides"] = ov
        self._write(data)
        self._record({"action": "tool_" + rule, "tool": tool, "by": by, "reason": reason})

    def clear_override(self, tool, by, reason):
        data = dict(self._read())
        ov = dict(data.get("overrides", {}))
        if tool not in ov:
            return False
        was = ov.pop(tool)
        data["overrides"] = ov
        self._write(data)
        self._record({"action": "tool_rule_cleared", "tool": tool, "was": was.get("rule"),
                      "by": by, "reason": reason})
        return True


def apply(action, req, *, trust, gate, controls, tools, tiers, by="the steward"):
    """Do one of the steward's actions. Returns (result dict, error or None).

    action: grant | lower | freeze | unfreeze | allow | block | clear
    req:    {"reason": ..., "level": ... (grant, lower), "tool": ... (allow, block, clear)}
    trust:  the TrustEvolution; gate: the unit's SafetyGate (lower takes
    effect on it at once); controls: a Controls; tools: {name: tier};
    tiers: trust_evolution.TIERS.
    """
    reason = clean_reason(req.get("reason"))
    if not reason:
        return None, "a reason is needed for every change to what she may do"
    roles = [t["role"].lower() for t in tiers]

    if action in ("grant", "lower"):
        from logic.levels import canonical
        level = canonical(str(req.get("level") or ""))     # an old name, read as its new one (82)
        if level not in roles:
            return None, "no such level: %r" % (req.get("level"),)
        now = trust.get_trust_level_name()
        if action == "grant":
            if roles.index(level) <= roles.index(now):
                return None, "she is at %s already; a grant raises her" % now
            held = trust.grant_level(level, "granted %s by the steward: %s" % (level, reason))
            controls._record({"action": "grant", "level": level, "by": by, "reason": reason,
                              "takes_effect": "at the next start"})
            return {"level": held, "takes_effect": "at the next start"}, None
        if roles.index(level) >= roles.index(now):
            return None, "she is at %s; lowering takes her below it" % now
        held = trust.lower_level(level, "lowered to %s by the steward: %s" % (level, reason))
        # at once: a permission taken away does not wait for a restart
        if gate is not None:
            from aetherspark import TRUST_PERMISSIONS
            gate.trust_level = held
            gate.allowed_tiers = TRUST_PERMISSIONS.get(held, [1])
        controls._record({"action": "lower", "level": level, "by": by, "reason": reason,
                          "takes_effect": "now"})
        return {"level": held, "takes_effect": "now"}, None

    if action == "freeze":
        if trust.is_frozen():
            return None, "her standing is frozen already"
        f = trust.freeze(by, reason)
        controls._record({"action": "freeze", "by": by, "reason": reason})
        return {"frozen": f}, None

    if action == "unfreeze":
        if not trust.is_frozen():
            return None, "her standing is not frozen"
        trust.unfreeze(by, reason)
        controls._record({"action": "unfreeze", "by": by, "reason": reason})
        return {"frozen": None}, None

    if action in RULES:
        tool = str(req.get("tool") or "")
        if tool not in tools:
            return None, "no such tool: %r" % (req.get("tool"),)
        controls.set_override(tool, action, by, reason)
        return {"tool": tool, "rule": action}, None

    if action == "clear":
        tool = str(req.get("tool") or "")
        if tool not in tools:
            return None, "no such tool: %r" % (req.get("tool"),)
        if not controls.clear_override(tool, by, reason):
            return None, "there is no rule on %s" % tool
        return {"tool": tool, "rule": None}, None

    return None, "unknown action: %r" % (action,)


def view(*, trust, gate, controls, tools, descriptions, tiers, events_path, last=50):
    """Everything the trust panel shows, from the unit's own records."""
    tier = trust.get_tier()
    roles = [t["role"].lower() for t in tiers]
    events, ok, why = [], True, ""
    r = chain.verify(events_path)
    ok, why = r["ok"], r["why"]
    try:
        with open(events_path, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                events.append({k: e.get(k) for k in ("timestamp", "type", "score", "details",
                                                     "resonance_after", "applied", "by")})
    except FileNotFoundError:
        pass
    try:
        ov = controls.overrides()
        ov_error = None
    except RuntimeError as e:
        ov, ov_error = {}, str(e)
    allowed_tiers = getattr(gate, "allowed_tiers", [1]) if gate is not None else [1]
    tool_rows = []
    for name, tier_no in tools.items():
        rule = ov.get(name)
        if rule and rule.get("rule") == "block":
            now = False
        elif rule and rule.get("rule") == "allow":
            now = not (tier_no == 4)
        else:
            now = tier_no in allowed_tiers
        tool_rows.append({"name": name, "tier": tier_no, "description": descriptions.get(name, ""),
                          "allowed_now": now, "rule": rule})
    return {
        "level": trust.get_trust_level_name(),
        "running_level": getattr(gate, "trust_level", None),
        "resonance": tier["resonance"],
        "next": None if tier["next_tier"] == "MAX" else
                {"name": tier["next_tier"], "to_go": tier["resonance_to_next"]},
        "frozen": trust.state.get("frozen"),
        "levels": [{"role": t["role"].lower(), "name": t["name"], "at": t["min_resonance"],
                    "tiers": t["tiers"]} for t in tiers],
        "events": events[-last:],
        "events_total": len(events),
        "record": {"ok": ok, "why": why, "chained": r["chained"], "head": (r["head"] or "")[:16]},
        "tools": tool_rows,
        "rules_error": ov_error,
        "roles": roles,
    }
