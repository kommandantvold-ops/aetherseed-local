"""The steward's own documents (build log 62).

Andreas, 5 Oct 2026: "I want a file upload button in the gui, that adds
documents to the library/workspace, and a way for Lyra to process that
information. Lets say I want to upload a pdf on basic physics so Lyra can help
me study." Asked how she should help: "Find and show passages" and "Explain a
passage". Asked where he uploads from: a phone or laptop on her own Wi-Fi.

WHAT HAPPENS TO A DOCUMENT. It is kept as it came, and read into a collection
of its own with the same converter the built-in library is made with
(tools/library_build.py): its text page by page, cut at its own headings into
passages, with a full-text index. From then on it is part of the library
(logic/library.py): asked or sure, she shows a passage of it word for word,
with the document's name and the page. A PDF needs `pdftotext` on the unit
(poppler-utils); a text file needs nothing.

WHAT IT IS NOT. Not memory: nothing of the document is stored as something
said to her, and nothing she says about it is put back into it. Not the
built-in library either: that is the cartridge's, the same on every unit and
read-only; this shelf is the steward's, like the workspace, and the cartridge
does not describe it.

Each document is three files in the shelf, named by one id:
  files/<id>.<ext>      the document as it came
  <id>.json             what the console lists: its title, its state
  <id>.lib.sqlite       the collection, once it is read
"""
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import threading
import time
from typing import Callable, List, Optional, Tuple

SHELF_DIR = os.environ.get("AETHERSEED_SHELF", os.path.expanduser("~/aetherseed-shelf"))

MAX_BYTES = 60 * 1024 * 1024      # one document
MAX_DOCUMENTS = 40
MAX_PAGES = 2000
KINDS = (".pdf", ".txt", ".md")

READING, READY, FAILED = "reading", "ready", "failed"

_lock = threading.Lock()
_converter = None


def converter():
    """tools/library_build.py - the one converter, for the built-in library
    and for this shelf. Loaded by its path: tools/ is not a package, and the
    unit's own code must not need libzim, which that file asks for only when a
    ZIM is opened."""
    global _converter
    if _converter is None:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(here, "tools", "library_build.py")
        spec = importlib.util.spec_from_file_location("library_build", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _converter = mod
    return _converter


def can_read_pdf() -> bool:
    from shutil import which
    return bool(which("pdftotext") and which("pdfinfo"))


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def title_of(filename: str) -> str:
    """What the document is called on the screen: its file name, without the
    ending, with the marks people put where spaces would be taken out."""
    base = os.path.basename((filename or "").replace("\\", "/"))
    stem = os.path.splitext(base)[0]
    stem = re.sub(r"[_\-.]+", " ", stem)
    stem = re.sub(r"[^\w \(\)'’,&+]", " ", stem, flags=re.UNICODE)
    return re.sub(r"\s+", " ", stem).strip()[:120] or "Document"


def make_id(filename: str, taken) -> str:
    """A name for the three files: plain letters and digits, never the name as
    it came (a file name from a phone is not a path to trust)."""
    stem = os.path.splitext(os.path.basename((filename or "").replace("\\", "/")))[0]
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:48] or "document"
    out, n = slug, 2
    while out in taken:
        out, n = "%s-%d" % (slug, n), n + 1
    return out


def _paths(shelf: str, doc_id: str, ext: str = ""):
    return (os.path.join(shelf, "files", doc_id + ext), os.path.join(shelf, doc_id + ".json"),
            os.path.join(shelf, doc_id + ".lib.sqlite"))


def _write_entry(shelf: str, entry: dict):
    path = os.path.join(shelf, entry["id"] + ".json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def listing(shelf: str = None) -> List[dict]:
    """Every document on the shelf, oldest first."""
    shelf = shelf or SHELF_DIR
    out = []
    try:
        names = sorted(os.listdir(shelf))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(shelf, name), encoding="utf-8") as f:
                e = json.load(f)
            if isinstance(e, dict) and e.get("id"):
                out.append(e)
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda e: (e.get("added") or "", e["id"]))


# ---------------------------------------------------------------------------
# Taking a document in
# ---------------------------------------------------------------------------

def accept(filename: str, data: bytes, shelf: str = None) -> Tuple[Optional[dict], Optional[str]]:
    """Keep the document and list it as being read. (entry, None), or (None,
    why not) - in words for the screen."""
    shelf = shelf or SHELF_DIR
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in KINDS:
        return None, "I can take a PDF or a plain text file (.pdf, .txt, .md)."
    if not data:
        return None, "That file is empty."
    if len(data) > MAX_BYTES:
        return None, "That file is too large: %d MB is the most I take." % (MAX_BYTES // (1024 * 1024))
    if ext == ".pdf" and not data.lstrip()[:5].startswith(b"%PDF-"):
        return None, "That file is named .pdf but is not a PDF."
    if ext == ".pdf" and not can_read_pdf():
        return None, "This unit cannot read PDFs yet (pdftotext is not installed)."
    if ext != ".pdf":
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return None, "That text file is not UTF-8 text."
    digest = hashlib.sha256(data).hexdigest()
    with _lock:
        have = listing(shelf)
        for e in have:
            if e.get("sha256") == digest and e.get("state") != FAILED:
                return None, 'I already have that document: "%s".' % e.get("title", e["id"])
        if len(have) >= MAX_DOCUMENTS:
            return None, "The shelf is full (%d documents). Remove one first." % MAX_DOCUMENTS
        doc_id = make_id(filename, {e["id"] for e in have})
        os.makedirs(os.path.join(shelf, "files"), mode=0o750, exist_ok=True)
        kept, _, _ = _paths(shelf, doc_id, ext)
        fd = os.open(kept, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        entry = {"id": doc_id, "title": title_of(filename), "kind": ext[1:], "bytes": len(data),
                 "sha256": digest, "added": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                 "state": READING, "pages": None, "passages": None, "note": ""}
        _write_entry(shelf, entry)
    return entry, None


def text_passages(text: str):
    """[(heading, place, passage)] of a plain text or Markdown file: blank
    lines part paragraphs, a line of #'s or of capitals is a heading. There
    are no pages, so no place is given."""
    lb = converter()
    out, heading, paras = [], "", []

    def close():
        for p in lb.passages_from(paras):
            out.append((heading, "", p))

    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        lines = [lb.squeeze(l) for l in block.split("\n")]
        lines = [l for l in lines if l]
        if not lines:
            continue
        md = re.match(r"^#{1,6}\s+(.+?)\s*#*$", lines[0])
        if md or (len(lines) == 1 and lb.heading_line(lines[0])):
            close()
            heading, paras = (md.group(1) if md else lines[0]), []
            lines = lines[1:]
            if not lines:
                continue
        paras.append(" ".join(lines) if not any(re.match(r"([-*•]|\d+[.)])\s", l) for l in lines[1:])
                     else "\n".join(lines))
    close()
    return out


# ---------------------------------------------------------------------------
# A book of another make than the manuals
# ---------------------------------------------------------------------------
# The converter was written on field manuals: headings in capitals, the same
# head on every page. The first textbook tried (Crowell, "Conceptual Physics",
# 185 pages) has neither - its headings are "1.7 Equivalence of mass and
# energy", and each page ends "Section 1.7 / Equivalence of mass and energy /
# 29". Read as the manuals are, 119 of its 589 passages were headed "Section
# 6.3" - the foot of one page taken for the heading of the next - and the
# foot stood in the text of the passages. Two rules for the steward's own
# documents, then; the built-in library is made without them.

DOTTED = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){1,3})\.?\s+(?:[?*†‡⋆]\s+)?(\S.{2,80})$")
DIVISION = re.compile(r"^(?:chapter|section|part|appendix|unit|lesson)\s+[\dA-Z][\w.]*$", re.I)


def numbered_heading(line: str) -> Optional[str]:
    """"m" for a heading with a section number in front of it - "1.7
    Equivalence of mass and energy", "2.3.1 Units" - else None. A plain "3
    Something" is not taken: so begin the rows of a list and "2 kg of ...".
    Nor a line of a table of contents (it ends in its page number), a
    sentence, or a sum."""
    m = DOTTED.match((line or "").strip())
    if not m:
        return None
    title = m.group(2)
    if not title[0].isupper() or title.endswith((".", ",", ";", ":", "?", "!")) \
            or re.search(r"\d\s*$|[=<>×÷+±]|\.{3}|(?:\. ){2}", title):
        return None
    words = title.split()
    if len(words) > 12 or not any(re.fullmatch(r"[^\W\d_]{3,}[,]?", w) for w in words):
        return None
    return "m"


def _titled(line: str) -> bool:
    return bool(line) and line[0].isupper() and len(line.split()) <= 12 \
        and not line.endswith((".", ",", ";", ":", "?", "!")) \
        and not re.search(r"[=<>×÷+±]", line)


def without_furniture(pages):
    """The pages without their running heads and feet.

    They cannot be looked for at the edge of the page: where a page has
    notes in its margin, pdftotext sets the foot between them ("Section 1.6"
    / a caption / "Noether's theorem for energy" / "27"). So a line that
    stands alone - blank lines around it - is furniture when it is
      - the page's number: a number in step with the pages, on a quarter of
        them or more (the 4 of "problem 4" is not in step);
      - a division that has stood before ("Chapter 2", again), or the number
        of a section that has a heading of its own ("Section 1.6", where
        "1.6 Noether's theorem for energy" heads the section);
      - the title of such a heading, alone ("Noether's theorem for energy");
      - a title that stands alone on three pages or more - but not where it
        stands under its chapter line, which is where the chapter opens.
    """
    if len(pages) < 4:
        return pages
    # A page of the table of contents - dots leading to page numbers, three
    # lines of them or more - is left out whole: it says every heading of the
    # book and answers nothing, and its "1.4 Conservation of energy" was
    # taken for the heading of the 44 passages after it.
    # So is the page its last lines run over to, and a page headed "Contents".
    leader = converter().LEADER
    dots = [sum(1 for l in text.split("\n") if leader.search(l)) for _, text in pages]
    contents = [d >= 3 or bool(re.match(r"\s*(?:brief\s+|table\s+of\s+)?contents\s*\n", text, re.I))
                for d, (_, text) in zip(dots, pages)]
    for i in range(1, len(pages)):
        contents[i] = contents[i] or (contents[i - 1] and dots[i] >= 1)
    pages = [(n, "" if c else text) for c, (n, text) in zip(contents, pages)]
    split = [(n, [b for b in re.split(r"\n\s*\n", text.replace("\r", "")) if b.strip()])
             for n, text in pages]

    def alone(block):
        t = block.strip()
        return " ".join(t.split()) if "\n" not in t and len(t) <= 90 else None

    step, on, titles, numbers = {}, {}, set(), set()
    for n, blocks in split:
        lone = {alone(b) for b in blocks} - {None}
        for t in lone:
            on[t] = on.get(t, 0) + 1
            if t.isdigit() and len(t) <= 4:
                step[int(t) - n] = step.get(int(t) - n, 0) + 1
        for b in blocks:
            for l in b.split("\n"):
                m = DOTTED.match(l.strip())
                if m and numbered_heading(l):
                    numbers.add(m.group(1))
                    titles.add(" ".join(m.group(2).split()))
    offset = max(step, key=step.get) if step else None
    if offset is not None and step[offset] < max(3, len(pages) // 4):
        offset = None

    out, stood = [], set()
    for n, blocks in split:
        kept, opened = [], False
        for b in blocks:
            t = alone(b)
            under_its_chapter, opened = opened, False
            if t is None:
                kept.append(b)
            elif t.isdigit() and offset is not None and int(t) == n + offset:
                continue
            elif DIVISION.match(t):
                number = t.split()[-1]
                if t in stood or (t.lower().startswith("section") and number in numbers):
                    continue
                stood.add(t)
                kept.append(b)
                opened = True
            elif t in titles or (on.get(t, 0) >= 3 and _titled(t) and not under_its_chapter
                                 and not numbered_heading(t)):
                continue
            else:
                kept.append(b)
        out.append((n, "\n\n".join(kept)))
    return out


def with_whole_headings(pages):
    """A heading set on two lines is put on one: "1.3 Review of the metric
    system and / conversions" (the second line of a heading begins small; a
    sentence does not), and the title under a chapter line - "Chapter 1" /
    "Conservation of Mass and / Energy" - is given a line and a paragraph of
    its own, where the converter looks for it."""
    out = []
    for number, text in pages:
        blocks = re.split(r"\n\s*\n", text.replace("\r", ""))
        for b, block in enumerate(blocks):
            lines = block.split("\n")
            if b and DIVISION.match(blocks[b - 1].strip()):
                k = 0
                while k < len(lines) and k < 3 and 0 < len(lines[k].strip()) <= 45 \
                        and _titled(lines[k].strip()) and not numbered_heading(lines[k]):
                    k += 1
                if k:
                    lines = [" ".join(l.strip() for l in lines[:k]), ""] + lines[k:]
            joined, k = [], 0
            while k < len(lines):
                l = lines[k]
                if numbered_heading(l) and k + 1 < len(lines):
                    nxt = lines[k + 1].strip()
                    if nxt and nxt[0].islower() and len(nxt) <= 60 \
                            and numbered_heading(l.strip() + " " + nxt):
                        l, k = l.strip() + " " + nxt, k + 1
                joined.append(l)
                k += 1
            blocks[b] = "\n".join(joined)
        out.append((number, "\n\n".join(blocks)))
    return out


def read(entry: dict, shelf: str = None, done: Callable[[], None] = None) -> dict:
    """Read the kept document into its collection. Sets the entry's state to
    ready or failed, and says why when it failed."""
    shelf = shelf or SHELF_DIR
    lb = converter()
    kept, _, coll = _paths(shelf, entry["id"], "." + entry["kind"])
    tmp = coll + ".tmp"
    try:
        if entry["kind"] == "pdf":
            pages = lb.pdf_pages(kept)
            if not pages:
                raise ValueError("it has no pages I can read")
            if len(pages) > MAX_PAGES:
                raise ValueError("it has %d pages; %d is the most I take" % (len(pages), MAX_PAGES))
            passages = lb.document_passages(without_furniture(with_whole_headings(pages)),
                                            heading=numbered_heading)
            n_pages = len(pages)
        else:
            with open(kept, encoding="utf-8") as f:
                passages, n_pages = text_passages(f.read()), None
        if not passages:
            raise ValueError("there is no text in it that I can read - a scan, perhaps: "
                             "pictures of pages, not their words")
        db = lb.fresh(tmp)
        cur = db.execute("INSERT INTO docs(title, author, locator, note) VALUES (?,?,?,?)",
                         (entry["title"], "", entry["id"] + "." + entry["kind"], ""))
        for seq, (heading, place, text) in enumerate(passages, 1):
            lb.add(db, cur.lastrowid, seq, entry["title"], heading, place, text)
        lb.finish(db, {"id": "own-" + entry["id"], "title": entry["title"], "own": "1",
                       "description": "your own document", "date": entry["added"][:10],
                       "language": "", "kind": "documents", "creator": "", "publisher": "",
                       "licence": "the steward's own document", "source_file": entry["id"] + "." + entry["kind"],
                       "source_bytes": str(entry["bytes"]), "source_sha256": entry["sha256"]})
        os.replace(tmp, coll)
        entry.update(state=READY, pages=n_pages, passages=len(passages), note="")
        if n_pages and len(passages) < n_pages // 3:
            entry["note"] = "little text was found: some pages may be pictures"
    except FileNotFoundError as e:
        tool = os.path.basename(str(getattr(e, "filename", "") or ""))
        entry.update(state=FAILED, note="this unit cannot read PDFs (pdftotext is not installed)"
                     if tool in ("pdfinfo", "pdftotext") else "the kept file is gone")
    except (ValueError, sqlite3.Error, OSError, RuntimeError) as e:
        entry.update(state=FAILED, note=str(e)[:200] or "it could not be read")
    except Exception as e:                      # a converter fault must not take the proxy with it
        entry.update(state=FAILED, note="it could not be read (%s)" % type(e).__name__)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
    with _lock:
        _write_entry(shelf, entry)
    if done:
        try:
            done()
        except Exception:
            pass
    return entry


def read_in_background(entry: dict, shelf: str = None, done: Callable[[], None] = None):
    """A book of three hundred pages takes a minute on the unit; the console
    is answered at once and asks again."""
    t = threading.Thread(target=read, args=(entry, shelf, done), daemon=True)
    t.start()
    return t


def remove(doc_id: str, shelf: str = None) -> bool:
    """Take a document off the shelf: its collection, the kept file, its
    entry. True if it was there."""
    shelf = shelf or SHELF_DIR
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", doc_id or ""):
        return False
    with _lock:
        entry = next((e for e in listing(shelf) if e["id"] == doc_id), None)
        if entry is None:
            return False
        kept, meta, coll = _paths(shelf, doc_id, "." + entry.get("kind", "pdf"))
        for path in (coll, coll + ".tmp", kept, meta):
            try:
                os.remove(path)
            except OSError:
                pass
    return True


def unfinished(shelf: str = None) -> List[dict]:
    """Documents left "reading" by a start in the middle of one: read again."""
    return [e for e in listing(shelf) if e.get("state") == READING]
