"""
Intent Detection — Aetherseed Agent Layer
===========================================
Bridges natural language to tool execution for small models.

Instead of expecting the model to produce <tool_call> XML,
we detect intent from the user's message, execute tools
through AetherSpark's safety gate, and inject results into
the model's context so it can respond informatively.

The model stays conversational. The proxy handles the doing.
"""

import re
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List, Tuple

WORKSPACE = os.path.expanduser("~/aetherseed-workspace")


# ============================================================
# INTENT PATTERNS
# ============================================================
#
# A tool runs only when the message asks for it by name: a file (named, or
# with an extension), the workspace, a note with a colon, the to-do list, the
# system's health, the trust level, the growth log. An ordinary verb never
# does - not "read", "open", "find", "remember", "I need to" - and every
# keyword is bounded by \b, so "spread" is not "read".
#
# Why (build log, step 40g): in 24 hours of love poetry the old patterns ran a
# tool 193 times and not once because anyone asked. "My perfume spread its
# fragrance" ran file_read('its'), "I didn't find him" ran file_search('him.'),
# "Open to me" ran file_read('to'), and "What do you remember of the song...?"
# matched note_write 49 times - refused only because the unit was at observer.
# At builder it would have written 49 notes. Output from a tool goes into the
# prompt as workspace data, so a false match also changes the answer.
#
# test_intent_detection.py holds both halves: every message of that soak, the
# whole Song of Songs and all of Genesis produce no intent; the explicit
# requests below still do. Order matters only where two could match: the
# writes (todo_add, note_write) are checked before the reads of the same thing.

_Q = "['\"‘“]?"                # an optional opening quote
_APOS = "['’]"                      # what's / what’s
_NAME = r"([\w](?:[\w./-]*[\w])?)"       # a file name, never ending in "." or "/"
_EXT = r"(?:txt|md|py|json|log|csv)"
_NAME_EXT = r"([\w](?:[\w./-]*[\w])?\." + _EXT + r")\b"
_TODO = r"(?:to-?do|todo)"

INTENT_PATTERNS = [
    # File listing (CHECK BEFORE file_read)
    {
        "intent": "file_list",
        "patterns": [
            r"\b(?:list|show)\s+(?:me\s+)?(?:the\s+|my\s+|your\s+)?(?:files|workspace)\b",
            r"\bwhat(?:" + _APOS + r"s|\s+is)\s+in\s+(?:the\s+|my\s+|your\s+)?(?:workspace|folder|directory)\b",
            r"\b(?:workspace|directory)\s+(?:list|listing|contents)\b",
            r"\b(?:can you see|do you have|what do you have)\s+(?:a\s+|any\s+)?(?:workspace|files)\b",
        ],
        "description": "List workspace files",
        "tier": 1,
    },
    # File reading: the word "file" and a name, or a name with an extension
    {
        "intent": "file_read",
        "patterns": [
            r"\b(?:read|show|open|display|cat|view)\s+(?:me\s+)?(?:the\s+|my\s+|your\s+)?file\s+" + _Q + _NAME,
            r"\b(?:read|show|open|display|cat|view)\s+(?:me\s+)?(?:the\s+|my\s+|your\s+)?" + _Q + _NAME_EXT,
            r"\b(?:what(?:" + _APOS + r"s|\s+is)\s+in|contents?\s+of)\s+(?:the\s+|my\s+)?(?:file\s+)?" + _Q + _NAME_EXT,
        ],
        "description": "Read a file",
        "tier": 1,
    },
    # Todo operations - the add first: an explicit "add" wins
    {
        "intent": "todo_add",
        "patterns": [
            r"\b(?:add|new)\s+(?:a\s+|an\s+)?(?:" + _TODO + r"|task)(?:\s+item)?\s*:\s*(.+)",
            r"\badd\s+['\"‘“](.+?)['\"’”]\s+to\s+(?:my\s+|the\s+)?(?:" + _TODO + r"|task)s?(?:\s+list)?\b",
            r"\badd\s+(.+?)\s+to\s+(?:my\s+|the\s+)(?:" + _TODO + r"|task)\s+list\b",
        ],
        "description": "Add to todo list",
        "tier": 2,
    },
    {
        "intent": "todo_read",
        "patterns": [
            r"\b(?:show|list|read|display|check)\s+(?:me\s+)?(?:my\s+|the\s+)?(?:" + _TODO + r"s?(?:\s+list)?|tasks|task\s+list)\b",
            r"\bwhat(?:" + _APOS + r"s|\s+is)\s+on\s+(?:my\s+|the\s+)?(?:" + _TODO + r"|task)\s+list\b",
        ],
        "description": "Read todo list",
        "tier": 1,
    },
    # Note operations - a verb, the word "note", and a colon
    {
        "intent": "note_write",
        "patterns": [
            r"\b(?:write|save|make|take|create|add)\s+(?:a\s+|this\s+|that\s+)?note\s*:\s*(.+)",
            r"\b(?:save|write)\s+(?:this|that)\s+as\s+a\s+note\b",
        ],
        "description": "Write a note",
        "tier": 2,
    },
    {
        "intent": "note_list",
        "patterns": [
            r"\b(?:show|list|read)\s+(?:me\s+)?(?:my\s+|the\s+|your\s+)?notes\b",
            r"\bwhat\s+notes\s+(?:do\s+you\s+have|have\s+you)\b",
        ],
        "description": "List notes",
        "tier": 1,
    },
    # System health
    {
        "intent": "system_health",
        "patterns": [
            r"\b(?:system|health)\s+(?:check|status|report)\b",
            r"\b(?:cpu|ram|disk)\s+(?:usage|status|temperature|temp|load)\b",
            r"\b(?:cpu|pi|system|board)\s+(?:temperature|temp)\b",
            r"\bhow(?:" + _APOS + r"s|\s+is)\s+(?:the\s+)?(?:pi|system|hardware)\s+(?:doing|running|performing)\b",
            r"\bcheck\s+(?:the\s+)?(?:system|hardware|temperature)\b",
        ],
        "description": "System health check",
        "tier": 1,
    },
    # Trust status - the words "trust" or "resonance" with what is asked about
    {
        "intent": "trust_status",
        "patterns": [
            r"\b(?:trust|resonance)\s+(?:level|status|score|tier)\b",
            r"\b(?:what(?:" + _APOS + r"s|\s+is)|show|check)\s+(?:me\s+)?(?:your|my|the)\s+(?:trust|resonance)\b",
        ],
        "description": "Show trust status",
        "tier": 1,
    },
    # File search: the word "file" and a name, a name with an extension, or
    # "search ... in my files"
    {
        "intent": "file_search",
        "patterns": [
            r"\b(?:find|search\s+for|look\s+for|locate|where\s+is)\s+(?:the\s+|my\s+)?file\s+" + _Q + _NAME,
            r"\b(?:find|search\s+for|look\s+for|locate)\s+(?:the\s+|my\s+)?" + _Q + _NAME_EXT,
            r"\b(?:search|grep)\s+(?:for\s+)?" + _Q + r"(.+?)['\"’”]?\s+in\s+(?:my\s+|the\s+)?(?:files|workspace|notes)\b",
        ],
        "description": "Search for files",
        "tier": 1,
    },
    # Log viewing
    {
        "intent": "log_read",
        "patterns": [
            r"\b(?:show|read|view|check)\s+(?:me\s+)?the\s+log\b",
            r"\b(?:growth|activity|event)\s+log\b",
        ],
        "description": "Read growth log",
        "tier": 1,
    },
]


# ============================================================
# INTENT DETECTOR
# ============================================================

def detect_intent(message: str) -> Optional[Dict]:
    """Detect the primary intent from a user message.
    Returns the intent dict with any captured groups, or None."""
    lower = message.lower().strip()

    for intent_def in INTENT_PATTERNS:
        for pattern in intent_def["patterns"]:
            match = re.search(pattern, lower)
            if match:
                return {
                    "intent": intent_def["intent"],
                    "description": intent_def["description"],
                    "tier": intent_def["tier"],
                    "match": match.group(0),
                    "captures": match.groups(),
                    "original": message,
                }
    return None


# ============================================================
# INTENT EXECUTORS
# ============================================================

def execute_intent(intent: Dict, spark) -> Optional[str]:
    """Execute a detected intent through AetherSpark's safety gate.
    Returns the result string to inject into context, or None."""

    name = intent["intent"]
    captures = intent.get("captures", ())

    # Check permission via safety gate
    allowed, reason = spark.gate.check(name, intent["tier"], {"intent": name})
    if not allowed:
        return f"[DENIED] {reason}"

    if name == "file_list":
        return _list_workspace()

    elif name == "file_read":
        filename = captures[0] if captures else None
        return _read_file(filename)

    elif name == "todo_read":
        return _read_file("todo.txt")

    elif name == "todo_add":
        item = captures[0] if captures else None
        if item:
            return _append_todo(item)
        return "[ERROR] No task specified."

    elif name == "note_write":
        content = captures[0] if captures else intent.get("original", "")
        return _write_note(content)

    elif name == "note_list":
        return _list_notes()

    elif name == "system_health":
        return _system_health()

    elif name == "trust_status":
        return _trust_status()

    elif name == "file_search":
        query = captures[0] if captures else None
        return _search_files(query)

    elif name == "log_read":
        return _read_file("logs/growth.log")

    return None


# ============================================================
# TOOL IMPLEMENTATIONS
# ============================================================

def _list_workspace() -> str:
    """List workspace contents recursively (2 levels)."""
    ws = Path(WORKSPACE)
    if not ws.exists():
        return "[Workspace not found]"

    lines = [f"Workspace: {ws}"]
    for item in sorted(ws.rglob("*")):
        rel = item.relative_to(ws)
        if len(rel.parts) > 2:
            continue
        indent = "  " * (len(rel.parts) - 1)
        if item.is_dir():
            lines.append(f"{indent}📁 {rel.name}/")
        else:
            size = item.stat().st_size
            lines.append(f"{indent}📄 {rel.name} ({size} bytes)")
    return "\n".join(lines)


def _read_file(filename: str) -> str:
    """Read a file from the workspace."""
    if not filename:
        return "[ERROR] No filename specified."

    path = Path(WORKSPACE) / filename
    # Security: resolve and check it's within workspace
    try:
        resolved = path.resolve()
        if not str(resolved).startswith(str(Path(WORKSPACE).resolve())):
            return "[ERROR] Path outside workspace."
    except Exception:
        return "[ERROR] Invalid path."

    if not path.exists():
        return f"[ERROR] File not found: {filename}"

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > 5000:
            content = content[:5000] + "\n... [truncated]"
        return f"File: {filename}\n---\n{content}"
    except Exception as e:
        return f"[ERROR] {e}"


def _append_todo(item: str) -> str:
    """Add an item to todo.txt."""
    path = Path(WORKSPACE) / "todo.txt"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"- {item.strip()}\n")
        return f"Added to todo: {item.strip()}"
    except Exception as e:
        return f"[ERROR] {e}"


def _write_note(content: str) -> str:
    """Write a timestamped note."""
    notes_dir = Path(WORKSPACE) / "notes"
    notes_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"note_{timestamp}.md"
    path = notes_dir / filename

    try:
        note_content = f"# Note — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n{content}\n"
        path.write_text(note_content, encoding="utf-8")
        return f"Note saved: notes/{filename}"
    except Exception as e:
        return f"[ERROR] {e}"


def _list_notes() -> str:
    """List all notes."""
    notes_dir = Path(WORKSPACE) / "notes"
    if not notes_dir.exists():
        return "No notes yet."

    notes = sorted(notes_dir.glob("*.md"))
    if not notes:
        return "No notes yet."

    lines = [f"Notes ({len(notes)}):"]
    for note in notes:
        size = note.stat().st_size
        lines.append(f"  📝 {note.name} ({size} bytes)")
    return "\n".join(lines)


def _search_files(query: str) -> str:
    """Search for files matching a pattern."""
    if not query:
        return "[ERROR] No search query."

    ws = Path(WORKSPACE)
    matches = list(ws.rglob(f"*{query}*"))[:20]

    if not matches:
        # Try content search
        content_matches = []
        for f in ws.rglob("*"):
            if f.is_file() and f.stat().st_size < 100000:
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                    if query.lower() in text.lower():
                        content_matches.append(f)
                except Exception:
                    pass
        if content_matches:
            lines = [f"Found '{query}' in {len(content_matches)} file(s):"]
            for m in content_matches[:10]:
                lines.append(f"  📄 {m.relative_to(ws)}")
            return "\n".join(lines)
        return f"No files matching '{query}'"

    lines = [f"Found {len(matches)} match(es):"]
    for m in matches:
        lines.append(f"  📄 {m.relative_to(ws)}")
    return "\n".join(lines)


def _system_health() -> str:
    """Run system health checks on the Pi."""
    lines = ["System Health Report:"]

    # CPU temperature
    try:
        temp = open("/sys/class/thermal/thermal_zone0/temp").read().strip()
        lines.append(f"  🌡️  CPU Temp: {int(temp) / 1000:.1f}°C")
    except Exception:
        lines.append("  🌡️  CPU Temp: unknown")

    # Memory
    try:
        with open("/proc/meminfo") as f:
            meminfo = f.read()
        total = int(re.search(r"MemTotal:\s+(\d+)", meminfo).group(1)) // 1024
        available = int(re.search(r"MemAvailable:\s+(\d+)", meminfo).group(1)) // 1024
        used = total - available
        lines.append(f"  💾 RAM: {used}MB / {total}MB ({used * 100 // total}% used)")
    except Exception:
        lines.append("  💾 RAM: unknown")

    # Disk
    try:
        result = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
        disk_line = result.stdout.strip().split("\n")[-1].split()
        lines.append(f"  💿 Disk: {disk_line[2]} / {disk_line[1]} ({disk_line[4]} used)")
    except Exception:
        lines.append("  💿 Disk: unknown")

    # Uptime
    try:
        uptime = open("/proc/uptime").read().split()[0]
        hours = int(float(uptime)) // 3600
        mins = (int(float(uptime)) % 3600) // 60
        lines.append(f"  ⏱️  Uptime: {hours}h {mins}m")
    except Exception:
        pass

    # Hailo device
    try:
        result = subprocess.run(["hailortcli", "fw-control", "identify"],
                                capture_output=True, text=True, timeout=10)
        if "HAILO10H" in result.stdout:
            lines.append("  🧠 Hailo-10H: detected and running")
        else:
            lines.append("  🧠 Hailo: " + result.stdout.strip()[:50])
    except Exception:
        lines.append("  🧠 Hailo: check failed")

    # Services
    for svc in ["hailo-ollama", "aetherseed-proxy"]:
        try:
            result = subprocess.run(["systemctl", "is-active", svc],
                                    capture_output=True, text=True, timeout=5)
            status = result.stdout.strip()
            emoji = "✅" if status == "active" else "❌"
            lines.append(f"  {emoji} {svc}: {status}")
        except Exception:
            lines.append(f"  ❓ {svc}: unknown")

    return "\n".join(lines)


def _trust_status() -> str:
    """Get current trust evolution status."""
    # No path manipulation here: this used to insert "~/aetherseed-ai" (the
    # v1 layout) on EVERY call - a directory the service can create and write,
    # first on the import path. trust_evolution sits beside this module, which
    # is already importable (build log, step 22).
    try:
        from trust_evolution import TrustEvolution
        trust = TrustEvolution()
        return trust.get_status_line()
    except Exception as e:
        return f"[ERROR] Could not load trust status: {e}"
