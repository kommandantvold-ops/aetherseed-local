"""The manual, on her shelf and in the console.



One source, two languages: gui/manual.en.md and gui/manual.nb.md. The
console's Help panel shows them (gui/serve.py, /aetherseed/manual), and the
proxy keeps them as one built-in collection of her library,
manual.lib.sqlite, so "look up training files" shows the passage word for
word - to the steward, and to a guest too: the manual is nobody's private
document.

The collection is built here, from the two files, whenever their contents
differ from what it was built from (their hash is in its meta). On a unit
the library is root's and only read by her (INSTALL §15), so the install
builds it, as root:

    sudo /usr/bin/python3 -m logic.manual          # from /opt/aetherseed

and the proxy, at start, only says whether the manual on her shelf is the
one in this build. Where the library can be written (a laptop, the tests),
the proxy builds it itself.
"""
import hashlib
import os
import sqlite3

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = (("en", "AetherSeed manual"), ("nb", "AetherSeed-manual"))
FILE = "manual.lib.sqlite"


def source_path(lang: str) -> str:
    return os.path.join(APP, "gui", "manual.%s.md" % lang)


def _sources():
    out = []
    for lang, title in SOURCES:
        p = source_path(lang)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                out.append((lang, title, f.read()))
    return out


def digest(sources) -> str:
    h = hashlib.sha256()
    for lang, _, text in sources:
        h.update(lang.encode() + b"\0" + text.encode("utf-8") + b"\0")
    return h.hexdigest()


def built_from(path: str):
    try:
        db = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        try:
            row = db.execute("SELECT value FROM meta WHERE key = 'source_sha256'").fetchone()
        finally:
            db.close()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def ensure(library_dir: str) -> bool:
    """Build the manual's collection in `library_dir` if it is missing or was
    built from other text. True if it was (re)built."""
    from logic import own_shelf
    sources = _sources()
    if not sources:
        return False
    want = digest(sources)
    out = os.path.join(library_dir, FILE)
    if built_from(out) == want:
        return False
    lb = own_shelf.converter()
    os.makedirs(library_dir, exist_ok=True)
    tmp = out + ".tmp"
    db = lb.fresh(tmp)
    try:
        for lang, title, text in sources:
            cur = db.execute("INSERT INTO docs(title, author, locator, note) VALUES (?,?,?,?)",
                             (title, "AetherSeed", "manual.%s.md" % lang, lang))
            for seq, (heading, place, passage) in enumerate(own_shelf.text_passages(text), 1):
                lb.add(db, cur.lastrowid, seq, title, heading, place, passage)
        lb.finish(db, {"id": "aetherseed-manual", "title": "AetherSeed manual", "own": "0",
                       "description": "how to use the companion and its console",
                       "language": "en, nb", "kind": "manual", "creator": "AetherSeed",
                       "publisher": "AetherSeed", "date": "",
                       "licence": "part of the build", "source_file": "gui/manual.*.md",
                       "source_bytes": str(sum(len(t.encode()) for _, _, t in sources)),
                       "source_sha256": want})
    finally:
        db.close()
    os.replace(tmp, out)
    return True


def current(library_dir: str) -> bool:
    """Is the manual on the shelf the one this build's text makes?"""
    sources = _sources()
    return bool(sources) and built_from(os.path.join(library_dir, FILE)) == digest(sources)


def sections(lang: str):
    """The manual for the console: [{"title", "lines"}], lines as written
    (the page sets them as text, never markup)."""
    p = source_path(lang if lang in dict(SOURCES) else "en")
    if not os.path.exists(p):
        p = source_path("en")
    with open(p, encoding="utf-8") as f:
        text = f.read()
    out, cur = [], None
    for line in text.splitlines():
        if line.startswith("# "):
            out.append({"title": line[2:].strip(), "lines": [], "top": True})
            cur = out[-1]
        elif line.startswith("## "):
            out.append({"title": line[3:].strip(), "lines": []})
            cur = out[-1]
        elif cur is not None:
            cur["lines"].append(line)
    for s in out:
        while s["lines"] and not s["lines"][0].strip():
            s["lines"].pop(0)
        while s["lines"] and not s["lines"][-1].strip():
            s["lines"].pop()
    return out


def main(argv=None) -> int:
    import sys
    args = sys.argv[1:] if argv is None else argv
    sys.path.insert(0, APP)
    from logic import library as lib
    where = args[0] if args else lib.LIBRARY_DIR
    built = ensure(where)
    print("%s: %s" % (os.path.join(where, FILE),
                      "built" if built else ("up to date" if current(where) else "no manual text")))
    return 0 if current(where) else 1


if __name__ == "__main__":
    raise SystemExit(main())
