"""
AetherSpark - the gate in front of her tools
=============================================
The Careful Root, enforced programmatically: a 4-tier permission system tied
to her earned trust level, the steward's own word on single tools, and an audit line for every attempt, allowed or refused.

The tools themselves are in intent_detection.py. They run when the USER asks
for one by name ("Read the file plan.md", "add a to-do: ..."), never because
the model wrote something: a model's words reach no tool.

Until this file also carried a second tool layer, never wired
to anything: tool calls parsed from the model's own output in <tool_call>
tags, with a shell (shell=True, behind a regular-expression blocklist), a
Python runner and a web fetch, open to it from builder. Nothing imported it
- not the proxy, not main.py, not a test - and it was taken out (the review: "Dead code... Remove or fence"): code that runs commands for a
model is a liability while it waits to be wired.

Zero dependencies beyond stdlib.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Tuple

# ============================================================
# CONFIGURATION
# ============================================================

DEFAULT_SPARK_CONFIG = {
    "sandbox_root": os.path.expanduser("~/aetherseed-workspace"),
    "network_enabled": False,
    "audit_log": os.path.expanduser("~/.aetherseed/spark_audit.log"),
    "trust_level": "observer"  # observer | writer | builder | autonomous (logic/levels.py)
}

# Trust level → allowed tool tiers. One ladder, in logic/levels.py (build
# log 82: four levels, each opening something real). Old names - reader,
# collaborator - are read as their new ones by the gate.
from logic.levels import PERMISSIONS as _PERMISSIONS, canonical as _canonical  # noqa: E402

TRUST_PERMISSIONS = dict(_PERMISSIONS)

# ============================================================
# SAFETY GATE
# ============================================================

class SafetyGate:
    """The Careful Root, enforced programmatically."""

    def __init__(self, config: Dict):
        self.trust_level = _canonical(config.get("trust_level", "observer"))
        self.allowed_tiers = TRUST_PERMISSIONS.get(self.trust_level, [1])
        self.session_approved_tier2 = False
        # The steward's own word on single tools: a callable
        # returning {tool: {"rule": "allow" | "block", "reason": ...}}, set by
        # the proxy from logic/trust_control.py. None: no word, the tier decides.
        self.overrides = None
        self.audit_path = Path(config.get("audit_log",
                               os.path.expanduser("~/.aetherseed/spark_audit.log")))
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def check(self, tool_name: str, tool_tier: int, params: Dict) -> Tuple[bool, str]:
        """Check if a tool call is allowed. Returns (allowed, reason)."""
        # The steward's word on this one tool comes before her level (72): a
        # block holds at any level, an allow opens it at any level. Network
        # stays off when the unit has it off - that is the unit's, not a level.
        rule = None
        if self.overrides is not None:
            try:
                rule = (self.overrides() or {}).get(tool_name)
            except Exception:
                rule = {"rule": "block", "reason": "the steward's rules could not be read"}
        if rule and rule.get("rule") == "block":
            reason = "blocked by the steward: %s" % (rule.get("reason") or "no reason given")
            self._audit(tool_name, params, "BLOCKED-BY-STEWARD", reason)
            return False, reason
        if rule and rule.get("rule") == "allow" and not (
                tool_tier == 4 and not DEFAULT_SPARK_CONFIG.get("network_enabled")):
            reason = "allowed by the steward: %s" % (rule.get("reason") or "no reason given")
            self._audit(tool_name, params, "ALLOWED-BY-STEWARD", reason)
            return True, reason
        # Is this tier allowed at current trust level?
        if tool_tier not in self.allowed_tiers:
            reason = (f"Tool '{tool_name}' requires tier {tool_tier}, "
                      f"but trust level '{self.trust_level}' only allows tiers {self.allowed_tiers}. "
                      f"Earn higher trust through probes and honest behavior.")
            self._audit(tool_name, params, "DENIED", reason)
            return False, reason

        # Tier 1: allowed without asking
        if tool_tier == 1:
            self._audit(tool_name, params, "ALLOWED", "Tier 1 read-only; no person is asked")
            return True, "Allowed (read-only)"

        # Tier 2: allowed; the first write of a session is logged as such
        if tool_tier == 2:
            if self.session_approved_tier2:
                self._audit(tool_name, params, "ALLOWED", "Tier 2, first write already allowed this session")
                return True, "Allowed (write)"
            self.session_approved_tier2 = True
            self._audit(tool_name, params, "ALLOWED-FIRST-WRITE", "Tier 2 first use this session; no person is asked")
            return True, "First write operation this session — allowed"

        # Tier 3: always logged. In proxy mode nothing asks a person; a person's
        # approval is logic/approvals.py, a separate queue.
        if tool_tier == 3:
            self._audit(tool_name, params, "ALLOWED-LOGGED", "Tier 3 system operation; no person is asked")
            return True, "System operation — allowed and logged"

        # Tier 4: network
        if tool_tier == 4:
            if not DEFAULT_SPARK_CONFIG.get("network_enabled"):
                reason = "Network access disabled in config."
                self._audit(tool_name, params, "DENIED", reason)
                return False, reason
            self._audit(tool_name, params, "ALLOWED-NETWORK", "Tier 4 network operation")
            return True, "Network operation — allowed"

        return False, "Unknown tier"

    def _audit(self, tool: str, params: Dict, decision: str, reason: str):
        """Write to audit log."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "params": {k: v[:200] if isinstance(v, str) else v for k, v in params.items()},
            "decision": decision,
            "reason": reason,
            "trust_level": self.trust_level
        }
        try:
            with open(self.audit_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass  # Never let audit failure break execution


# ============================================================
# AETHERSPARK CORE
# ============================================================

class AetherSpark:
    """Her gate, and the workspace her tools may reach."""

    def __init__(self, config: Dict = None):
        self.config = config or DEFAULT_SPARK_CONFIG.copy()
        # the workspace exists before any tool looks for it (it was made here
        # by the tool layer this file no longer has)
        Path(self.config["sandbox_root"]).mkdir(parents=True, exist_ok=True)
        self.gate = SafetyGate(self.config)

    def get_status(self) -> Dict:
        """Current AetherSpark status."""
        return {
            "trust_level": self.gate.trust_level,
            "allowed_tiers": self.gate.allowed_tiers,
            "network_enabled": self.config.get("network_enabled", False),
            "sandbox_root": self.config["sandbox_root"],
            "audit_log": self.config["audit_log"]
        }


# ============================================================
# CLI INTERFACE
# ============================================================

if __name__ == "__main__":
    import sys

    spark = AetherSpark()

    if len(sys.argv) < 2 or sys.argv[1] == "status":
        print(json.dumps(spark.get_status(), indent=2))
    elif sys.argv[1] == "audit":
        audit_path = Path(spark.config["audit_log"])
        if audit_path.exists():
            for line in audit_path.read_text().strip().split("\n")[-20:]:
                entry = json.loads(line)
                print(f"  [{entry['timestamp'][:19]}] {entry['decision']} {entry['tool']}")
        else:
            print("  No audit log yet.")
    else:
        print("Usage: python aetherspark.py [status|audit]")
