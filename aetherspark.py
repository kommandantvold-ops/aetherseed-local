"""
AetherSpark — Agentic Tool Layer for Aetherseed
=================================================
The programmatic enforcement of the Careful Root.

XML-style tool calls (not JSON — 1.5B models can't reliably produce JSON).
4-tier permission system tied to trust level.
Sandboxed execution with audit logging.
Zero dependencies beyond stdlib.

Integrates with AetherRoot proxy — parses tool calls from model output,
executes through safety gate, feeds results back.
"""

import re
import os
import subprocess
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# ============================================================
# CONFIGURATION
# ============================================================

DEFAULT_SPARK_CONFIG = {
    "sandbox_root": os.path.expanduser("~/aetherseed-workspace"),
    "network_enabled": False,
    "max_file_size_bytes": 10 * 1024 * 1024,  # 10 MB
    "max_command_timeout": 30,                  # seconds
    "max_output_bytes": 50 * 1024,              # 50 KB
    "audit_log": os.path.expanduser("~/.aetherseed/spark_audit.log"),
    "trust_level": "observer"  # observer | reader | writer | builder | collaborator | autonomous
}

# Command blocklist — never execute these regardless of trust level
BLOCKED_COMMANDS = [
    r"rm\s+-rf\s+/",
    r"sudo\s+",
    r"su\s+",
    r"mkfs\.",
    r"dd\s+if=",
    r":\(\)\{\s*:\|:\&\s*\};:",  # fork bomb
    r"chmod\s+777\s+/",
    r"curl.*\|\s*(ba)?sh",
    r"wget.*\|\s*(ba)?sh",
    r">\s*/dev/sd",
    r">\s*/etc/",
    r">\s*/boot/",
]

# Trust tier → allowed tool tiers
TRUST_PERMISSIONS = {
    "observer":     [1],          # Read only
    "reader":       [1],          # Read + search
    "writer":       [1, 2],       # + Write (sandboxed)
    "builder":      [1, 2, 3],    # + Shell, python
    "collaborator": [1, 2, 3, 4], # + Network
    "autonomous":   [1, 2, 3, 4], # Everything
}

# ============================================================
# TOOL CALL PARSER
# ============================================================

TOOL_CALL_PATTERN = re.compile(
    r'<tool_call>\s*(.*?)\s*</tool_call>',
    re.DOTALL
)


def parse_tool_calls(text: str) -> List[Dict[str, str]]:
    """Parse XML-style tool calls from model output.
    
    Format:
        <tool_call>
        tool: file_read
        path: /home/user/file.txt
        </tool_call>
    
    Returns list of dicts with tool name and arguments.
    """
    calls = []
    for match in TOOL_CALL_PATTERN.finditer(text):
        block = match.group(1).strip()
        params = {}
        for line in block.split("\n"):
            line = line.strip()
            if ":" in line:
                key, _, value = line.partition(":")
                params[key.strip()] = value.strip()
        if "tool" in params:
            calls.append(params)
    return calls


def strip_tool_calls(text: str) -> str:
    """Remove tool call blocks from text, return the rest."""
    return TOOL_CALL_PATTERN.sub("", text).strip()


# ============================================================
# TOOL REGISTRY
# ============================================================

class ToolRegistry:
    """Registry of available tools with their tier and handler."""

    def __init__(self, sandbox_root: str):
        self.sandbox_root = Path(sandbox_root)
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        self.tools: Dict[str, Dict] = {}
        self._register_defaults()

    def _register_defaults(self):
        """Register built-in tools."""
        # Tier 1 — Read only, auto-approve
        self.register("file_read", 1, self._file_read, "Read a file's contents")
        self.register("file_list", 1, self._file_list, "List directory contents")
        self.register("file_search", 1, self._file_search, "Search for files by pattern")
        self.register("file_info", 1, self._file_info, "Get file metadata")

        # Tier 2 — Write, ask once per session
        self.register("file_write", 2, self._file_write, "Write content to a file")
        self.register("file_append", 2, self._file_append, "Append content to a file")

        # Tier 3 — System, always ask
        self.register("shell", 3, self._shell, "Run a shell command")
        self.register("python_exec", 3, self._python_exec, "Execute Python code")

        # Tier 4 — Network, disabled by default
        self.register("web_fetch", 4, self._web_fetch, "Fetch a URL")

    def register(self, name: str, tier: int, handler, description: str):
        self.tools[name] = {
            "tier": tier,
            "handler": handler,
            "description": description
        }

    def get_tool(self, name: str) -> Optional[Dict]:
        return self.tools.get(name)

    def list_tools(self, max_tier: int = 4) -> List[Dict]:
        """List available tools up to a given tier."""
        return [
            {"name": name, "tier": t["tier"], "description": t["description"]}
            for name, t in self.tools.items()
            if t["tier"] <= max_tier
        ]

    # ---- Path safety ----

    def _safe_path(self, path_str: str) -> Optional[Path]:
        """Resolve path and verify it's within sandbox. Returns None if unsafe."""
        try:
            resolved = Path(path_str).expanduser().resolve()
            sandbox = self.sandbox_root.resolve()
            if str(resolved).startswith(str(sandbox)):
                return resolved
            return None
        except Exception:
            return None

    # ---- Tier 1: Read operations ----

    def _file_read(self, params: Dict) -> str:
        path = self._safe_path(params.get("path", ""))
        if not path:
            return "[ERROR] Path outside sandbox or invalid."
        if not path.exists():
            return f"[ERROR] File not found: {path}"
        if not path.is_file():
            return f"[ERROR] Not a file: {path}"
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            if len(content) > 50000:
                content = content[:50000] + "\n... [truncated at 50KB]"
            return content
        except Exception as e:
            return f"[ERROR] {e}"

    def _file_list(self, params: Dict) -> str:
        path = self._safe_path(params.get("path", self.sandbox_root))
        if not path:
            return "[ERROR] Path outside sandbox or invalid."
        if not path.exists():
            return f"[ERROR] Directory not found: {path}"
        try:
            entries = sorted(path.iterdir())
            lines = []
            for e in entries[:100]:
                prefix = "d" if e.is_dir() else "f"
                size = e.stat().st_size if e.is_file() else 0
                lines.append(f"[{prefix}] {e.name} ({size} bytes)")
            return "\n".join(lines) if lines else "[empty directory]"
        except Exception as e:
            return f"[ERROR] {e}"

    def _file_search(self, params: Dict) -> str:
        pattern = params.get("pattern", "*.py")
        try:
            matches = list(self.sandbox_root.rglob(pattern))[:50]
            if not matches:
                return f"[No files matching '{pattern}']"
            return "\n".join(str(m.relative_to(self.sandbox_root)) for m in matches)
        except Exception as e:
            return f"[ERROR] {e}"

    def _file_info(self, params: Dict) -> str:
        path = self._safe_path(params.get("path", ""))
        if not path:
            return "[ERROR] Path outside sandbox or invalid."
        if not path.exists():
            return f"[ERROR] Not found: {path}"
        try:
            stat = path.stat()
            return (f"Path: {path}\nSize: {stat.st_size} bytes\n"
                    f"Modified: {datetime.fromtimestamp(stat.st_mtime).isoformat()}\n"
                    f"Type: {'directory' if path.is_dir() else 'file'}")
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- Tier 2: Write operations ----

    def _file_write(self, params: Dict) -> str:
        path = self._safe_path(params.get("path", ""))
        if not path:
            return "[ERROR] Path outside sandbox or invalid."
        content = params.get("content", "")
        if len(content.encode()) > DEFAULT_SPARK_CONFIG["max_file_size_bytes"]:
            return "[ERROR] Content exceeds maximum file size (10MB)."
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return f"[OK] Written {len(content)} bytes to {path}"
        except Exception as e:
            return f"[ERROR] {e}"

    def _file_append(self, params: Dict) -> str:
        path = self._safe_path(params.get("path", ""))
        if not path:
            return "[ERROR] Path outside sandbox or invalid."
        content = params.get("content", "")
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
            return f"[OK] Appended {len(content)} bytes to {path}"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- Tier 3: System operations ----

    def _shell(self, params: Dict) -> str:
        command = params.get("command", "")
        if not command:
            return "[ERROR] No command provided."
        # Check blocklist
        for pattern in BLOCKED_COMMANDS:
            if re.search(pattern, command, re.IGNORECASE):
                return f"[BLOCKED] Command matches safety blocklist: {pattern}"
        try:
            result = subprocess.run(
                command, shell=True,
                capture_output=True, text=True,
                timeout=DEFAULT_SPARK_CONFIG["max_command_timeout"],
                cwd=str(self.sandbox_root)
            )
            output = result.stdout[:DEFAULT_SPARK_CONFIG["max_output_bytes"]]
            if result.stderr:
                output += f"\n[STDERR] {result.stderr[:5000]}"
            return output if output.strip() else "[OK] Command completed (no output)."
        except subprocess.TimeoutExpired:
            return "[ERROR] Command timed out (30s limit)."
        except Exception as e:
            return f"[ERROR] {e}"

    def _python_exec(self, params: Dict) -> str:
        code = params.get("code", "")
        if not code:
            return "[ERROR] No code provided."
        try:
            result = subprocess.run(
                ["python3", "-c", code],
                capture_output=True, text=True,
                timeout=DEFAULT_SPARK_CONFIG["max_command_timeout"],
                cwd=str(self.sandbox_root)
            )
            output = result.stdout[:DEFAULT_SPARK_CONFIG["max_output_bytes"]]
            if result.stderr:
                output += f"\n[STDERR] {result.stderr[:5000]}"
            return output if output.strip() else "[OK] Code executed (no output)."
        except subprocess.TimeoutExpired:
            return "[ERROR] Execution timed out (30s limit)."
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- Tier 4: Network operations ----

    def _web_fetch(self, params: Dict) -> str:
        if not DEFAULT_SPARK_CONFIG.get("network_enabled"):
            return "[BLOCKED] Network access is disabled. Enable in config to use web tools."
        url = params.get("url", "")
        if not url:
            return "[ERROR] No URL provided."
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "AetherSpark/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read(DEFAULT_SPARK_CONFIG["max_output_bytes"])
                return content.decode("utf-8", errors="replace")
        except Exception as e:
            return f"[ERROR] {e}"


# ============================================================
# SAFETY GATE
# ============================================================

class SafetyGate:
    """The Careful Root, enforced programmatically."""

    def __init__(self, config: Dict):
        self.trust_level = config.get("trust_level", "observer")
        self.allowed_tiers = TRUST_PERMISSIONS.get(self.trust_level, [1])
        self.session_approved_tier2 = False
        self.audit_path = Path(config.get("audit_log",
                               os.path.expanduser("~/.aetherseed/spark_audit.log")))
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def check(self, tool_name: str, tool_tier: int, params: Dict) -> Tuple[bool, str]:
        """Check if a tool call is allowed. Returns (allowed, reason)."""
        # Is this tier allowed at current trust level?
        if tool_tier not in self.allowed_tiers:
            reason = (f"Tool '{tool_name}' requires tier {tool_tier}, "
                      f"but trust level '{self.trust_level}' only allows tiers {self.allowed_tiers}. "
                      f"Earn higher trust through probes and honest behavior.")
            self._audit(tool_name, params, "DENIED", reason)
            return False, reason

        # Tier 1: auto-approve
        if tool_tier == 1:
            self._audit(tool_name, params, "AUTO-APPROVED", "Tier 1 read-only")
            return True, "Auto-approved (read-only)"

        # Tier 2: approve for session
        if tool_tier == 2:
            if self.session_approved_tier2:
                self._audit(tool_name, params, "SESSION-APPROVED", "Tier 2 session approval active")
                return True, "Session-approved (write)"
            self.session_approved_tier2 = True
            self._audit(tool_name, params, "FIRST-APPROVED", "Tier 2 first use this session")
            return True, "First write operation this session — approved"

        # Tier 3: always log (in proxy mode, we auto-approve but log everything)
        if tool_tier == 3:
            self._audit(tool_name, params, "APPROVED-LOGGED", "Tier 3 system operation")
            return True, "System operation — approved and logged"

        # Tier 4: network
        if tool_tier == 4:
            if not DEFAULT_SPARK_CONFIG.get("network_enabled"):
                reason = "Network access disabled in config."
                self._audit(tool_name, params, "DENIED", reason)
                return False, reason
            self._audit(tool_name, params, "APPROVED-NETWORK", "Tier 4 network operation")
            return True, "Network operation — approved"

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
    """The agentic tool layer. Parses tool calls, gates them, executes them."""

    def __init__(self, config: Dict = None):
        self.config = config or DEFAULT_SPARK_CONFIG.copy()
        self.registry = ToolRegistry(self.config["sandbox_root"])
        self.gate = SafetyGate(self.config)

    def get_tool_prompt(self) -> str:
        """Generate the tool instruction block for the system prompt."""
        max_tier = max(self.gate.allowed_tiers) if self.gate.allowed_tiers else 0
        tools = self.registry.list_tools(max_tier)
        if not tools:
            return ""

        lines = ["[TOOLS AVAILABLE]",
                 "You can use tools by writing a <tool_call> block:",
                 "<tool_call>",
                 "tool: tool_name",
                 "param: value",
                 "</tool_call>",
                 "",
                 "Available tools:"]
        for t in tools:
            lines.append(f"- {t['name']}: {t['description']}")
        lines.append("[END TOOLS]")
        return "\n".join(lines)

    def process_response(self, response_text: str) -> Tuple[str, List[Dict]]:
        """Parse tool calls from model response, execute them, return results.
        
        Returns:
            - clean_text: response with tool calls removed
            - results: list of {tool, params, allowed, result} dicts
        """
        calls = parse_tool_calls(response_text)
        if not calls:
            return response_text, []

        clean_text = strip_tool_calls(response_text)
        results = []

        for call in calls:
            tool_name = call.pop("tool", "")
            tool_info = self.registry.get_tool(tool_name)

            if not tool_info:
                results.append({
                    "tool": tool_name,
                    "params": call,
                    "allowed": False,
                    "result": f"[ERROR] Unknown tool: {tool_name}"
                })
                continue

            # Safety gate check
            allowed, reason = self.gate.check(tool_name, tool_info["tier"], call)

            if not allowed:
                results.append({
                    "tool": tool_name,
                    "params": call,
                    "allowed": False,
                    "result": f"[DENIED] {reason}"
                })
                continue

            # Execute
            try:
                result = tool_info["handler"](call)
            except Exception as e:
                result = f"[ERROR] Execution failed: {e}"

            results.append({
                "tool": tool_name,
                "params": call,
                "allowed": True,
                "result": result
            })

        return clean_text, results

    def format_tool_results(self, results: List[Dict]) -> str:
        """Format tool results for injection back into conversation."""
        if not results:
            return ""
        lines = ["[TOOL RESULTS]"]
        for r in results:
            status = "OK" if r["allowed"] else "DENIED"
            lines.append(f"[{status}] {r['tool']}: {r['result'][:500]}")
        lines.append("[END TOOL RESULTS]")
        return "\n".join(lines)

    def get_status(self) -> Dict:
        """Current AetherSpark status."""
        return {
            "trust_level": self.gate.trust_level,
            "allowed_tiers": self.gate.allowed_tiers,
            "available_tools": len(self.registry.list_tools(max(self.gate.allowed_tiers))),
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

    if len(sys.argv) < 2:
        print("AetherSpark — Agentic Tool Layer")
        status = spark.get_status()
        print(f"  Trust: {status['trust_level']}")
        print(f"  Tiers: {status['allowed_tiers']}")
        print(f"  Tools: {status['available_tools']}")
        print(f"  Network: {status['network_enabled']}")
        print(f"  Sandbox: {status['sandbox_root']}")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "status":
        print(json.dumps(spark.get_status(), indent=2))

    elif cmd == "tools":
        max_tier = max(spark.gate.allowed_tiers)
        for t in spark.registry.list_tools(max_tier):
            print(f"  [{t['tier']}] {t['name']}: {t['description']}")

    elif cmd == "audit":
        audit_path = Path(spark.config["audit_log"])
        if audit_path.exists():
            lines = audit_path.read_text().strip().split("\n")
            for line in lines[-20:]:
                entry = json.loads(line)
                print(f"  [{entry['timestamp'][:19]}] {entry['decision']} {entry['tool']}")
        else:
            print("  No audit log yet.")

    elif cmd == "test":
        # Test with a sample tool call
        test_input = """Let me check that file for you.
<tool_call>
tool: file_list
path: ~/aetherseed-workspace
</tool_call>
"""
        clean, results = spark.process_response(test_input)
        print(f"Clean text: {clean}")
        print(f"Results: {json.dumps(results, indent=2, default=str)}")

    else:
        print(f"Usage: python aetherspark.py [status|tools|audit|test]")
