"""Her workspace: a folder for each trust level, the to-do list editable, and
the steward's editor.

The steward opens the workspace by saying "open your workspace" and edits it
with mouse and keyboard.

THE FOLDERS

    observer/    writer/    builder/    autonomous/      each with a README.md

She reaches a folder when her trust level is that folder's or higher: at
writer she reaches observer/ and writer/, not builder/ - she is not told it
is there. The rule is in one place (may_reach) and every tool of hers that
names a path goes through it: reading a file, listing, searching, counting,
comparing. The files at the top of the workspace (todo.md, notes/, supplies)
are open at every level, as they were.

THE STEWARD is not held to the ladder: from the console he sees and edits all
four folders and everything else, whatever level she has earned. The ladder
is hers.

THE EDITOR (steward only, over the console): list, read, save, make a folder,
rename, delete. Text only, 200 KB a file; a name stays inside the workspace
(no "..", no absolute path, no symbolic link out); the four level folders
cannot be deleted or renamed; a folder is deleted only when empty. Every
change is one line in workspace.log, chained, with the path and the size -
not the text.

THE TO-DO LIST: items are the "- ..." lines of todo.md. "Remove 2 from my
to-do list", "remove 'milk' from my to-do list", "edit to-do 2: buy oat
milk", "clear my to-do list". An item is picked by its place among the items
(1 is the first) or by the words it holds; a word that fits two items picks
neither and she lists both. The file before the change is kept as
todo.md.bak.
"""
import os
import re
from pathlib import Path

from logic.levels import LADDER, PERMISSIONS, POINTS

MAX_BYTES = 200_000
MAX_ENTRIES = 600
MAX_DEPTH = 5
TODO = "todo.md"

_TOOLS_OPENED = {
    "observer": "read: list, read and search files, her health and trust",
    "writer": "notes and the to-do list (writes)",
    "builder": "the exact tools: calculate, count, compare",
    "autonomous": "reserved; nothing more opens here yet - nothing leaves the unit",
}


def readme(level):
    i = LADDER.index(level)
    lower = LADDER[:i]
    reach = (", ".join(lower + (level,)) if lower else level)
    return (
        "# %s\n\n"
        "This folder is for the **%s** trust level (from %d points).\n\n"
        "- What opens at this level: %s.\n"
        "- Tool tiers at this level: %s.\n"
        "- Who can reach this folder: me at %s or higher%s. My steward can always.\n"
        "- Folders I reach at this level: %s.\n\n"
        "Put here what belongs to this level. A file in a higher folder is out of my reach until I earn that level; "
        "a file in a lower one is always open to me.\n"
    ) % (level.capitalize(), level, POINTS[level], _TOOLS_OPENED[level],
         ", ".join(str(t) for t in PERMISSIONS[level]), level,
         "" if level == LADDER[-1] else " (" + ", ".join(LADDER[i + 1:]) + ")",
         reach)


def ensure(ws):
    """The four folders with their READMEs, in the workspace `ws`. An existing
    file is never touched; a deleted README is written again."""
    root = Path(ws)
    root.mkdir(parents=True, exist_ok=True)
    made = []
    for level in LADDER:
        d = root / level
        try:
            d.mkdir(exist_ok=True)
            f = d / "README.md"
            if not f.exists():
                with open(f, "x", encoding="utf-8") as fh:
                    fh.write(readme(level))
                made.append(f.relative_to(root).as_posix())
        except OSError:
            continue
    return made


# ---- who reaches what --------------------------------------------------------
def rank(level):
    from logic.levels import canonical
    level = canonical(level)
    return LADDER.index(level) if level in LADDER else 0


def folder_level(rel):
    """The level whose folder `rel` is in (or is), or None."""
    parts = Path(str(rel).replace("\\", "/")).parts
    if ".." in parts:
        # "observer/../builder/x" is builder/x: the highest level folder named
        # anywhere in a path that climbs is the one it is read as reaching
        named = [p.lower() for p in parts if p.lower() in LADDER]
        return max(named, key=LADDER.index) if named else None
    first = parts[0].lower() if parts else ""
    return first if first in LADDER else None


def may_reach(rel, level):
    f = folder_level(rel)
    return f is None or rank(f) <= rank(level)


def closed_text(rel, level):
    """What she says when a path is in a folder above her level."""
    f = folder_level(rel)
    return "The %s folder opens at the %s trust level, and I am at %s. Nothing was opened." % (f, f, level)


# ---- the editor's paths ------------------------------------------------------
class WorkspaceError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def clean(rel):
    """A relative path inside the workspace, as posix text, or an error."""
    if not isinstance(rel, str) or not rel.strip() or len(rel) > 300 or "\x00" in rel:
        raise WorkspaceError("path", "a path inside the workspace")
    rel = rel.replace("\\", "/").strip().strip("/")
    parts = rel.split("/")
    if any(p in ("", ".", "..") or p.startswith("~") for p in parts) or re.match(r"^[A-Za-z]:", rel):
        raise WorkspaceError("path", "a path inside the workspace")
    if len(parts) > MAX_DEPTH:
        raise WorkspaceError("depth", "folders only go %d deep" % MAX_DEPTH)
    return "/".join(parts)


def resolve(ws, rel):
    rel = clean(rel)
    root = Path(ws).resolve()
    p = (root / rel)
    # the folder it would be in must really be inside: a link out is refused
    probe = p
    while not probe.exists() and probe != root:
        probe = probe.parent
    try:
        probe.resolve().relative_to(root)
        if p.exists():
            p.resolve().relative_to(root)
    except ValueError:
        raise WorkspaceError("outside", "a path inside the workspace")
    return root, p, rel


def tree(ws):
    root = Path(ws)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        depth = len(d.relative_to(root).parts)
        dirnames[:] = sorted(n for n in dirnames if not n.startswith("."))
        if depth >= MAX_DEPTH:
            dirnames[:] = []
        for n in dirnames:
            out.append({"path": (d / n).relative_to(root).as_posix(), "folder": True, "size": None})
        for n in sorted(filenames):
            if n.startswith("."):
                continue
            f = d / n
            try:
                size = f.stat().st_size
            except OSError:
                continue
            out.append({"path": f.relative_to(root).as_posix(), "folder": False, "size": size})
        if len(out) >= MAX_ENTRIES:
            break
    out.sort(key=lambda e: e["path"].lower())
    return {"levels": list(LADDER), "entries": out[:MAX_ENTRIES], "truncated": len(out) > MAX_ENTRIES}


def read(ws, rel):
    root, p, rel = resolve(ws, rel)
    if not p.is_file():
        raise WorkspaceError("none", "no such file", 404)
    if p.stat().st_size > MAX_BYTES:
        raise WorkspaceError("big", "that file is over %d KB; the editor opens text up to that" % (MAX_BYTES // 1000), 413)
    data = p.read_bytes()
    if b"\x00" in data:
        raise WorkspaceError("binary", "that is not a text file", 415)
    return {"path": rel, "text": data.decode("utf-8", errors="replace"), "size": len(data)}


def save(ws, rel, text):
    if not isinstance(text, str):
        raise WorkspaceError("text", "text to save")
    data = text.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise WorkspaceError("big", "over %d KB" % (MAX_BYTES // 1000), 413)
    if b"\x00" in data:
        raise WorkspaceError("binary", "text only")
    root, p, rel = resolve(ws, rel)
    if p.is_dir():
        raise WorkspaceError("dir", "that is a folder")
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    tmp = p.with_name(".%s.tmp" % p.name)
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    return {"path": rel, "size": len(data), "created": new}


def mkdir(ws, rel):
    root, p, rel = resolve(ws, rel)
    if p.exists():
        raise WorkspaceError("exists", "that already exists", 409)
    p.mkdir(parents=True)
    return {"path": rel}


def _protected(rel):
    return rel.lower() in LADDER


def delete(ws, rel):
    root, p, rel = resolve(ws, rel)
    if _protected(rel):
        raise WorkspaceError("level", "the four trust-level folders stay", 403)
    if p.is_dir():
        if any(p.iterdir()):
            raise WorkspaceError("full", "a folder is deleted only when it is empty", 409)
        p.rmdir()
    elif p.is_file():
        p.unlink()
    else:
        raise WorkspaceError("none", "no such file", 404)
    return {"path": rel}


def rename(ws, src, dst):
    root, p, a = resolve(ws, src)
    _, q, b = resolve(ws, dst)
    if _protected(a) or _protected(b):
        raise WorkspaceError("level", "the four trust-level folders stay", 403)
    if not p.exists():
        raise WorkspaceError("none", "no such file", 404)
    if q.exists():
        raise WorkspaceError("exists", "that name is taken", 409)
    q.parent.mkdir(parents=True, exist_ok=True)
    os.rename(p, q)
    return {"from": a, "to": b}


# ---- the to-do list -----------------------------------------------------------
def _read_lines(path):
    try:
        return Path(path).read_text(encoding="utf-8").split("\n")
    except OSError:
        return None


def items(path):
    """[(line index, text)] of the "- ..." lines."""
    lines = _read_lines(path) or []
    return [(i, l[2:].strip()) for i, l in enumerate(lines) if l.startswith("- ") and l[2:].strip()]


def _pick(path, sel):
    """(line index, text) of the one item `sel` picks - a place ("2") or words
    - or (None, message)."""
    its = items(path)
    if not its:
        return None, "Your to-do list is empty."
    s = (sel or "").strip().strip("'\"‘“’”").strip()
    if s.isdigit():
        n = int(s)
        if 1 <= n <= len(its):
            return its[n - 1], None
        return None, "There is no item %d on your to-do list; it has %d." % (n, len(its))
    low = s.lower()
    exact = [it for it in its if it[1].lower() == low]
    fits = exact or [it for it in its if low and low in it[1].lower()]
    if len(fits) == 1:
        return fits[0], None
    if not fits:
        return None, "I found no item like \"%s\" on your to-do list." % s
    names = "; ".join("%d. %s" % (its.index(it) + 1, it[1]) for it in fits[:6])
    return None, "More than one item fits \"%s\": %s. Say which by its number." % (s, names)


def _backup_and_write(path, lines):
    p = Path(path)
    try:
        old = p.read_bytes()
        with open(str(p) + ".bak", "wb") as f:
            f.write(old)
    except OSError:
        pass
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.flush()
        os.fsync(f.fileno())


def todo_remove(path, sel):
    it, why = _pick(path, sel)
    if it is None:
        return why
    lines = _read_lines(path)
    n = items(path).index(it) + 1
    del lines[it[0]]
    _backup_and_write(path, lines)
    return "Removed from your to-do list: %s (it was item %d)" % (it[1], n)


def todo_edit(path, sel, text):
    text = " ".join((text or "").split())
    if not text:
        return "Tell me what the item should say instead."
    it, why = _pick(path, sel)
    if it is None:
        return why
    lines = _read_lines(path)
    n = items(path).index(it) + 1
    lines[it[0]] = "- " + text
    _backup_and_write(path, lines)
    return "Changed on your to-do list: item %d was \"%s\" and now says \"%s\"" % (n, it[1], text)


def todo_clear(path):
    its = items(path)
    if not its:
        return "Your to-do list is already empty."
    lines = [l for l in (_read_lines(path) or []) if not (l.startswith("- ") and l[2:].strip())]
    _backup_and_write(path, lines)
    return "Cleared your to-do list: %d item%s removed. The list before is kept as todo.md.bak." % (
        len(its), "" if len(its) == 1 else "s")
