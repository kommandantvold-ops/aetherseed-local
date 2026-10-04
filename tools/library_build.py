#!/usr/bin/env python3
"""Build a library collection the companion can answer from (build log 57).

Andreas, 4 Oct 2026, pointing at Project NOMAD: "A library she answers from
with a knowledge base like that of nomad (content) so it can be a disaster
relief and offgrid rural survival aid."

    tools/library_build.py SOURCE.zim OUT.lib.sqlite [--licence TEXT]

SOURCE is a Kiwix ZIM file, of either kind NOMAD's collections come in:

  - a web site saved as pages (NHS Medicines A to Z): every page is cut into
    passages at its own headings;
  - a "zimgit" shelf of PDF documents (the Water Treatment Library): each
    document's text is taken out page by page with `pdftotext` - as they come,
    a search of such a file finds nothing (tried 4 Oct 2026).

OUT is one SQLite file: the passages word for word, where each came from, and
a full-text index over them. That file is all the unit needs - Python's own
sqlite3 reads it; the ZIM reader (libzim) and pdftotext are needed here only.
It runs off the unit: a unit cannot fetch anything (build log 55), so a
collection is built where the source can be had and carried to it.

What "word for word" means here, exactly: the words and their order are the
source's. Line breaks inside a paragraph are joined; a word split by a hyphen
at a line end in a PDF is put back together; page furniture (menus, cookie
notices, scripts) is left out. Nothing is summarised or reworded.
"""
import argparse
import ast
import hashlib
import html
import html.parser
import os
import re
import sqlite3
import subprocess
import sys
import tempfile

PASSAGE_MAX = 900          # characters; a section longer than this is cut at paragraphs
PASSAGE_MIN = 200          # a shorter piece is joined to its neighbour under the same heading
SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE docs(id INTEGER PRIMARY KEY, title TEXT, author TEXT, locator TEXT);
CREATE TABLE passages(id INTEGER PRIMARY KEY, doc INTEGER, seq INTEGER,
                      heading TEXT, place TEXT, text TEXT);
CREATE VIRTUAL TABLE passages_fts USING fts5(title, heading, text, content='',
                                             tokenize='porter unicode61');
CREATE VIRTUAL TABLE passages_vocab USING fts5vocab(passages_fts, 'row');
"""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def squeeze(text):
    return re.sub(r"[ \t\r\f\v ]+", " ", text).strip()


# ---------------------------------------------------------------------------
# A web page -> (title, [(heading, [paragraph, ...]), ...])
# ---------------------------------------------------------------------------

SKIP = {"script", "style", "nav", "header", "footer", "noscript", "svg", "form",
        "button", "iframe", "template", "aside"}
BLOCK = {"p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "blockquote",
         "pre", "figcaption", "summary", "caption", "div", "section", "article", "br",
         "table", "ul", "ol", "main"}
# <summary> and <dt> head what follows them: on NHS pages every question in
# "Common questions about ..." is a <summary>, and its answer the rest.
HEAD = {"h1", "h2", "h3", "h4", "summary", "dt"}
VOID = {"br", "img", "hr", "input", "meta", "link", "source", "track", "wbr", "area",
        "base", "col", "embed"}


class Page(html.parser.HTMLParser):
    """The readable text of a page, block by block, under its headings."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.sections = "", []
        self._skip, self._in_title, self._head = 0, False, None
        self._buf, self._main, self._has_main = [], 0, False
        self._cell = False

    def feed_page(self, text):
        self._has_main = bool(re.search(r"<main[\s>]", text, re.I))
        self.feed(text)
        self._flush()
        return self

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag == "main":
            self._main += 1
        if tag in SKIP and tag not in VOID:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in ("td", "th"):
            if self._cell:
                self._buf.append(" | ")
            self._cell = True
        if tag in BLOCK:
            if tag == "tr":
                self._cell = False
            self._flush()
            if tag in HEAD:
                self._head = tag
            if tag == "li":
                self._buf.append("- ")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in SKIP and tag not in VOID:
            self._skip = max(0, self._skip - 1)
            return
        if tag == "main":
            self._flush()
            self._main = max(0, self._main - 1)
        if self._skip:
            return
        if tag in BLOCK:
            self._flush(heading=tag in HEAD)
            if tag in HEAD:
                self._head = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._skip or (self._has_main and not self._main):
            return
        self._buf.append(data)

    def _flush(self, heading=False):
        text = squeeze("".join(self._buf))
        self._buf = []
        if not text or text == "-":
            return
        if heading or self._head:
            self.sections.append((text, []))
        else:
            if not self.sections:
                self.sections.append(("", []))
            self.sections[-1][1].append(text)


def page_sections(text):
    p = Page().feed_page(text)
    return squeeze(p.title), [(h, paras) for h, paras in p.sections if paras]


# ---------------------------------------------------------------------------
# Paragraphs -> passages
# ---------------------------------------------------------------------------

def passages_from(paragraphs, limit=PASSAGE_MAX, least=PASSAGE_MIN):
    """Join paragraphs into passages of at most `limit` characters, never
    cutting inside a paragraph unless it alone is longer than the limit (then
    at a sentence end)."""
    out, cur = [], ""
    for para in paragraphs:
        pieces = [para]
        if len(para) > limit:
            pieces, rest = [], para
            while len(rest) > limit:
                cut = max(rest.rfind(". ", 0, limit), rest.rfind("; ", 0, limit),
                          rest.rfind(" - ", 0, limit))
                cut = cut + 1 if cut > limit // 3 else rest.rfind(" ", 0, limit)
                cut = cut if cut > 0 else limit
                pieces.append(rest[:cut].strip())
                rest = rest[cut:].strip()
            if rest:
                pieces.append(rest)
        for piece in pieces:
            if cur and len(cur) + 1 + len(piece) > limit:
                out.append(cur)
                cur = ""
            cur = (cur + "\n" + piece) if cur else piece
    if cur:
        if out and len(cur) < least and len(out[-1]) + 1 + len(cur) <= limit + least:
            out[-1] += "\n" + cur
        else:
            out.append(cur)
    return out


# ---------------------------------------------------------------------------
# A PDF's text, page by page -> paragraphs
# ---------------------------------------------------------------------------

def pdf_pages(path):
    """[(page number, text)] with pdftotext, reading order, one page at a
    time so that the page number is certain."""
    info = subprocess.run(["pdfinfo", path], capture_output=True, text=True, timeout=120).stdout
    m = re.search(r"^Pages:\s+(\d+)", info, re.M)
    pages = []
    for i in range(1, (int(m.group(1)) if m else 0) + 1):
        t = subprocess.run(["pdftotext", "-enc", "UTF-8", "-nopgbrk", "-q", "-f", str(i),
                            "-l", str(i), path, "-"], capture_output=True, timeout=300).stdout
        pages.append((i, t.decode("utf-8", "replace")))
    return pages


def page_paragraphs(text):
    """Paragraphs of one PDF page: blank lines part them; lines inside one are
    joined, and a word hyphenated across a line end is put back together."""
    out = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        lines = [squeeze(l) for l in block.split("\n")]
        lines = [l for l in lines if l]
        if not lines:
            continue
        para = lines[0]
        for l in lines[1:]:
            if re.search(r"[A-Za-z]{2}-$", para) and re.match(r"[a-z]", l):
                para = para[:-1] + l
            else:
                para += " " + l
        # a page number or a running head on its own carries nothing to quote
        if len(para) < 4 or re.fullmatch(r"[\divxlc\s.\-|]+", para, re.I):
            continue
        out.append(para)
    return out


# ---------------------------------------------------------------------------
# The two kinds of ZIM
# ---------------------------------------------------------------------------

def zim_meta(z):
    out = {}
    for key in ("Title", "Description", "Creator", "Publisher", "Date", "Language",
                "Name", "License", "Source"):
        try:
            out[key.lower()] = z.get_metadata(key).decode("utf-8", "replace").strip()
        except Exception:
            out[key.lower()] = ""
    return out


def items(z):
    for i in range(z.all_entry_count):
        e = z._get_entry_by_id(i)
        if e.is_redirect:
            continue
        yield e, e.get_item()


def from_site(z, db, log):
    pages = []
    for e, it in items(z):
        if it.mimetype != "text/html":
            continue
        title, sections = page_sections(bytes(it.content).decode("utf-8", "replace"))
        if sections:
            pages.append((title or e.title or e.path, e.path,
                          [(h, t) for h, paras in sections for t in passages_from(paras)]))
    # Page furniture: the same words on more than a quarter of the pages
    # ("Can you answer a 5 minute survey about your visit today?", on 1546 of
    # 1996) are the site's, not the page's.
    seen = {}
    for _, _, passages in pages:
        for text in {t for _, t in passages}:
            seen[text] = seen.get(text, 0) + 1
    furniture = {t for t, c in seen.items() if len(pages) >= 20 and c > len(pages) // 4}
    docs = n = 0
    for title, path, passages in pages:
        passages = [(h, t) for h, t in passages if t not in furniture]
        if not passages:
            continue
        cur = db.execute("INSERT INTO docs(title, author, locator) VALUES (?,?,?)",
                         (title, "", path))
        docs += 1
        for seq, (heading, text) in enumerate(passages, 1):
            n += 1
            add(db, cur.lastrowid, seq, title, heading, "", text)
    log("%d pages, %d passages; left out as page furniture: %d texts"
        % (docs, n, len(furniture)))


def from_shelf(z, db, log):
    """A zimgit shelf: database.js names each document and its file."""
    raw = bytes(z.get_entry_by_path("database.js").get_item().content).decode("utf-8", "replace")
    listing = ast.literal_eval(raw[raw.index("["):raw.rindex("]") + 1])
    docs = n = 0
    with tempfile.TemporaryDirectory() as tmp:
        for row in listing:
            for fname in row.get("fp") or []:
                try:
                    blob = bytes(z.get_entry_by_path("files/" + fname).get_item().content)
                except Exception:
                    log("  missing: %s" % fname)
                    continue
                path = os.path.join(tmp, "doc.pdf")
                with open(path, "wb") as f:
                    f.write(blob)
                pages = pdf_pages(path)
                cur = db.execute("INSERT INTO docs(title, author, locator) VALUES (?,?,?)",
                                 (row.get("ti") or fname, row.get("aut") or "", fname))
                doc, seq, before = cur.lastrowid, 0, n
                for number, text in pages:
                    for text in passages_from(page_paragraphs(text)):
                        seq += 1
                        n += 1
                        add(db, doc, seq, row.get("ti") or fname, "", "page %d" % number, text)
                docs += 1
                log("  %-45s %4d pages, %5d passages%s"
                    % ((row.get("ti") or fname)[:45], len(pages), n - before,
                       "" if n > before else "   <- NO TEXT (scanned?)"))
    log("%d documents, %d passages" % (docs, n))


def add(db, doc, seq, title, heading, place, text):
    cur = db.execute("INSERT INTO passages(doc, seq, heading, place, text) VALUES (?,?,?,?,?)",
                     (doc, seq, heading, place, text))
    db.execute("INSERT INTO passages_fts(rowid, title, heading, text) VALUES (?,?,?,?)",
               (cur.lastrowid, title, heading, text))


def build(source, out, licence="", log=print):
    from libzim.reader import Archive          # needed here only, never on the unit
    z = Archive(source)
    if os.path.exists(out):
        os.remove(out)
    db = sqlite3.connect(out)
    db.executescript(SCHEMA)
    m = zim_meta(z)
    shelf = True
    try:
        z.get_entry_by_path("database.js")
    except Exception:
        shelf = False
    log("%s: %s" % (os.path.basename(source), "a shelf of documents" if shelf else "a site"))
    (from_shelf if shelf else from_site)(z, db, log)
    meta = {
        "format": "1",
        "id": m["name"] or os.path.splitext(os.path.basename(source))[0],
        "title": m["title"], "description": m["description"], "creator": m["creator"],
        "publisher": m["publisher"], "date": m["date"], "language": m["language"],
        "kind": "documents" if shelf else "site",
        "licence": licence or m["license"] or "not stated in the source file",
        "source_file": os.path.basename(source),
        "source_bytes": str(os.path.getsize(source)),
        "source_sha256": sha256_file(source),
        "docs": str(db.execute("SELECT count(*) FROM docs").fetchone()[0]),
        "passages": str(db.execute("SELECT count(*) FROM passages").fetchone()[0]),
        "passage_max": str(PASSAGE_MAX),
    }
    db.executemany("INSERT INTO meta VALUES (?,?)", sorted(meta.items()))
    db.commit()
    db.execute("INSERT INTO passages_fts(passages_fts) VALUES ('optimize')")
    db.commit()
    db.execute("VACUUM")
    db.close()
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source")
    ap.add_argument("out")
    ap.add_argument("--licence", default="", help="the collection's licence, once checked")
    a = ap.parse_args(argv)
    meta = build(a.source, a.out, a.licence)
    print("%s: %s docs, %s passages, %d bytes, sha256 %s"
          % (a.out, meta["docs"], meta["passages"], os.path.getsize(a.out), sha256_file(a.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
