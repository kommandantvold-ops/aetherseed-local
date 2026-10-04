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
CREATE TABLE docs(id INTEGER PRIMARY KEY, title TEXT, author TEXT, locator TEXT, note TEXT);
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
HEAD = {"h1", "h2", "h3", "h4", "h5", "h6", "summary", "dt"}
VOID = {"br", "img", "hr", "input", "meta", "link", "source", "track", "wbr", "area",
        "base", "col", "embed"}


class Page(html.parser.HTMLParser):
    """The readable text of a page, block by block, under its headings."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.lang, self.sections = "", "", []
        self._skip, self._in_title, self._titled, self._head = [], False, False, None
        self._buf, self._main, self._has_main = [], 0, False
        self._cell = False
        self._a, self._plain = 0, 0       # inside a link; characters of this block outside one

    def feed_page(self, text):
        self._has_main = bool(re.search(r"<main[\s>]", text, re.I))
        m = re.search(r"<html[^>]*\blang=[\"']?([A-Za-z-]+)", text, re.I)
        self.lang = (m.group(1) if m else "").lower()
        self.feed(text)
        self._flush()
        return self

    def _foreign(self, attrs):
        """A link or a block marked as another language than the page's: the
        language switcher of a site in fourteen languages (Ready.gov)."""
        for key, value in attrs:
            if key in ("hreflang", "lang") and value and self.lang:
                if value.lower().split("-")[0] != self.lang.split("-")[0]:
                    return True
        return False

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self._main += 1
        if tag in VOID:
            if tag == "br" and not self._skip:
                self._flush()
            return
        if self._skip or tag in SKIP or self._foreign(attrs):
            self._skip.append(tag)
            return
        if tag == "title" and not self._titled:
            self._in_title = True
            return
        if tag == "a":
            self._a += 1
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
        if tag == "main":
            if not self._skip:
                self._flush()
            self._main = max(0, self._main - 1)
        if self._skip:
            # close the innermost open element of that name, and all inside it
            for k in range(len(self._skip) - 1, -1, -1):
                if self._skip[k] == tag:
                    del self._skip[k:]
                    break
            return
        if tag == "title" and self._in_title:
            self._in_title, self._titled = False, True
            return
        if tag == "a":
            self._a = max(0, self._a - 1)
        if tag in BLOCK:
            self._flush(heading=tag in HEAD)
            if tag in HEAD:
                self._head = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        if self._has_main and not self._main:
            return
        self._buf.append(data)
        if not self._a:
            self._plain += len(re.sub(r"[\W_]+", "", data))

    def _flush(self, heading=False):
        text = squeeze("".join(self._buf))
        plain, self._buf, self._plain = self._plain, [], 0
        if not text or text == "-":
            return
        if not plain and not (heading or self._head):
            # A paragraph or a list row that is nothing but a link is the
            # site's way around itself - "Prepare for a flood / During a
            # flood", "Français / Kreyòl / Tagalog" - and leads nowhere on a
            # unit with no site behind it. It was the first thing shown for
            # "look up flooding".
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


def page_lang(text):
    m = re.search(r"<html[^>]*\blang=[\"']?([A-Za-z-]+)", text, re.I)
    return (m.group(1) if m else "").lower()


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


NOT_A_HEADING = re.compile(r"^(figure|fig\.|table|note|notes|warning|caution|danger|legend|page)\b", re.I)
CHAPTER = re.compile(r"^(chapter|appendix|section|part)\s+([0-9]+|[A-Z]|[IVXLC]+)\b[\s.:\-–—]*(.*)$", re.I)


LEADER = re.compile(r"(?:\.\s?){5,}")          # the dots of a table of contents
RUN_IN_MAJOR = re.compile(r"^\d{1,2}\.\s+([A-Z][A-Z0-9 '’/&,-]{2,60}?)\.\s+\S")
RUN_IN_MINOR = re.compile(
    r"^\(?(?:[a-z]|\d{1,2})[.)]\s+((?:[A-Z][A-Za-z'’/-]*)"
    r"(?:\s+(?:[A-Z][A-Za-z'’/-]*|of|and|the|for|in|to|a|an|or|with|on|by)){0,5})"
    r"(?:\.\s+[A-Z(]|:\s*(?:$|[A-Z(]))")
BULLET = re.compile(r"^[\uf000-\uf8ff•▪■●◦]\s*")


def heading_line(line):
    """Is this line of a PDF a heading? Capitals throughout ("DETERMINING THE
    DISTANCE", "3-2. TENT GROUP EQUIPMENT") or a chapter line. A sentence in
    capitals, a figure caption, a code ("WSVX.02.04") and a line of a table
    of contents are not."""
    t = line.strip()
    if not 4 <= len(t) <= 90 or NOT_A_HEADING.match(t) or LEADER.search(t) \
            or t.startswith(("- ", "(")) or "[" in t:
        return False
    if CHAPTER.match(t) and len(t) <= 70:
        return True
    letters = [c for c in t if c.isalpha()]
    words = [w for w in t.split() if re.fullmatch(r"[A-Za-z'’()/&-]{3,}[,:]?", w)]
    if len(letters) < 4 or not words or t.endswith((".", ",", ";")):
        return False
    return all(c.isupper() for c in letters) and len(words) <= 12


def page_blocks(text, running=()):
    """One PDF page as [("h", heading) | ("m", lesser heading) | ("p", paragraph)].

    Blank lines part paragraphs. Inside one, a line is joined to the one
    before it only when that line ran to the margin - prose wraps, the rows of
    a list or a table do not, and a table read as one sentence is how "1
    gallon" loses its "1/4 teaspoon". A word hyphenated across a line end is
    put back together.

    A heading is looked for on every line, not only where a blank line stands
    before it: a handbook typed without blank lines kept the first line of
    each lesson - "UNITED STATES MARINE CORPS" - as the heading of all 532
    passages under it. And a heading that opens its own paragraph is one too:
    "2. STRESS. Stress has many ..." (h), "c. Snow Cave. A snow cave is ..."
    (m, the lesser kind - it stands under the heading above it).

    `running`: lines to leave out - the document's running heads and feet.
    A block of a table of contents (dots leading to page numbers) is left out
    whole: it says every word of the manual and answers nothing.
    """
    out = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        lines = [BULLET.sub("- ", squeeze(l)) for l in block.split("\n")]
        lines = [l for l in lines if l and l not in running]
        if sum(1 for l in lines if LEADER.search(l)) >= 2:
            continue
        lines = [l for l in lines if not LEADER.search(l)]
        if not lines:
            continue
        width = max(len(l) for l in lines)
        para, last = None, None

        def close():
            # a page number, a date or a running head on its own carries nothing to quote
            if para is not None and len(para) >= 4 and \
                    not re.fullmatch(r"[\divxlc\s.\-|/:]+", para, re.I):
                out.append(("p", para))

        for l in lines:
            major, minor = RUN_IN_MAJOR.match(l), RUN_IN_MINOR.match(l)
            # a line in capitals that only carries on the sentence before it
            # ("... see\nMCRP 2-10B.1") is not a heading
            carries_on = (last is not None and width >= 30 and len(last) >= 0.7 * width
                          and not last.endswith((".", ":", "?", "!")))
            if heading_line(l) and not carries_on:
                close()
                para, last = None, None
                out.append(("h", l))
                continue
            if major or minor:
                close()
                out.append(("h", major.group(1)) if major else ("m", minor.group(1)))
                para, last = l, l
                continue
            if para is None:
                para, last = l, l
                continue
            full = (width >= 30 and len(last) >= 0.7 * width
                    and not re.match(r"(\d+[.)]?\s|[•▪■*–-]\s|\(?[a-z0-9]{1,2}\)\s)", l))
            if full and re.search(r"[A-Za-z]{2}-$", para) and re.match(r"[a-z]", l):
                para = para[:-1] + l
            elif full:
                para += " " + l
            else:
                para += "\n" + l
            last = l
        close()
    return out


def page_paragraphs(text):
    """The paragraphs of one PDF page, headings among them as plain lines."""
    return [t for _, t in page_blocks(text)]


EDGE, EDGE_PAGES = 6, 3


def running_lines(pages):
    """The lines that head or foot a document's pages: among the first or
    last EDGE lines of at least EDGE_PAGES of them ("UNITED STATES MARINE
    CORPS", "Chapter 3", "TC 21-3", "WSVX 02.01")."""
    edge = {}
    for _, text in pages:
        ls = [squeeze(l) for l in text.replace("\r", "").split("\n")]
        ls = [l for l in ls if l]
        for l in set(ls[:EDGE] + ls[-EDGE:]):
            if len(l) <= 90:
                edge[l] = edge.get(l, 0) + 1
    return {l for l, c in edge.items() if c >= EDGE_PAGES}


def document_passages(pages, skip_under=(), not_headings=(), skip_paragraphs=()):
    """[(heading, place, text)] for a whole PDF: [(page number, text), ...].

    A line that heads or foots several pages, or a block that stands on many
    of them, is the document's running head ("TC 21-3", "GTA 05-02-013"), not
    its text. A chapter line takes the line after it as its title ("CHAPTER
    3" / "Tents and Heating Equipment"). A lesser heading is given with the
    one it stands under: "SURVIVAL SHELTERS: Snow Cave".

    What a recipe may say of one document (library/NAME.json):
      skip_under       headings whose passages are left out, and which are
                       not taken as headings: a course handbook's "ENABLING
                       LEARNING OBJECTIVES" lists every subject of the lesson
                       and teaches none of them;
      not_headings     lines in capitals that are not headings ("OUTLINE");
      skip_paragraphs  patterns; a paragraph that one of them opens is left out.
    """
    skip_under = tuple(x.upper().rstrip(":") for x in skip_under)
    not_headings = {x.upper().rstrip(":") for x in not_headings}
    skip_paragraphs = [re.compile(x) for x in skip_paragraphs]
    running = running_lines(pages) if len(pages) >= 2 * EDGE_PAGES else set()
    blocks = [(n, page_blocks(text, running)) for n, text in pages]
    seen = {}
    for _, bs in blocks:
        for t in {t for _, t in bs if len(t) <= 90}:
            seen[t] = seen.get(t, 0) + 1
    many = max(4, len(pages) // 7)
    furniture = {t for t, c in seen.items() if c >= many}
    out, major, minor, skipping = [], "", "", False
    for number, bs in blocks:
        paras = []
        where = "%s: %s" % (major, minor) if major and minor else (major or minor)

        def close():
            for text in passages_from(paras):
                out.append((where, "page %d" % number, text))
        k = 0
        while k < len(bs):
            kind, t = bs[k]
            k += 1
            if t in furniture:
                continue
            if kind in ("h", "m"):
                t = t.rstrip(" :")
                bare = t.upper()
                if bare.startswith(skip_under) and skip_under:
                    close()
                    paras, skipping = [], True
                    continue
                if bare in not_headings:
                    close()
                    paras, skipping = [], False
                    continue
                skipping = False
            elif skipping or any(p.match(t) for p in skip_paragraphs):
                continue
            if kind == "h" and minor:
                # A line in capitals that says again what the section in hand
                # is called is the caption of its drawing, not a new heading:
                # "b. Snow Cave. A snow cave is ..." / [figure] "SNOW CAVE".
                # Taken as one, it headed the NEXT section: "SNOW CAVE:
                # Tree-pit Snow Shelter".
                cap = set(re.findall(r"[a-z0-9]+", t.lower()))
                if cap and 2 * len(cap & set(re.findall(r"[a-z0-9]+", minor.lower()))) >= len(cap):
                    continue
            if kind == "h":
                m = CHAPTER.match(t)
                if m and not m.group(3) and k < len(bs) and len(bs[k][1]) <= 70 \
                        and not bs[k][1].endswith(".") and bs[k][1] not in furniture:
                    t = "%s: %s" % (t, bs[k][1].split("\n")[0])
                    k += 1
                close()
                paras, major, minor = [], t, ""
                where = major
            elif kind == "m":
                close()
                paras, minor = [], t
                where = "%s: %s" % (major, minor) if major else minor
            else:
                paras.append(t)
        close()
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


def from_site(z, db, log, lang="en", skip_titles="", skip_paragraphs=()):
    """skip_titles: pages whose title it finds are left out (a site's pages of
    posts to copy, graphics and games are not text to answer from).
    skip_paragraphs: a paragraph one of these opens is left out (a banner
    that stands on too few pages to be found as furniture)."""
    pages, other, unwanted = [], 0, 0
    skip_titles = re.compile(skip_titles) if skip_titles else None
    skip_paragraphs = [re.compile(x) for x in skip_paragraphs]
    for e, it in items(z):
        if it.mimetype != "text/html":
            continue
        text = bytes(it.content).decode("utf-8", "replace")
        if lang and page_lang(text) and page_lang(text).split("-")[0] != lang:
            other += 1                      # Ready.gov carries fourteen languages
            continue
        title, sections = page_sections(text)
        if skip_titles and skip_titles.search(title or e.title or ""):
            unwanted += 1
            continue
        if skip_paragraphs:
            sections = [(h, [t for t in paras if not any(p.match(t) for p in skip_paragraphs)])
                        for h, paras in sections]
        if sections:
            pages.append((title or e.title or e.path, e.path, sections))
    # Page furniture: a paragraph on more than a quarter of the pages ("Can you
    # answer a 5 minute survey about your visit today?" on 1546 of 1996; the
    # language menu; "Image") is the site's, not the page's.
    seen = {}
    for _, _, sections in pages:
        for text in {t for _, paras in sections for t in paras}:
            seen[text] = seen.get(text, 0) + 1
    furniture = {t for t, c in seen.items() if len(pages) >= 20 and c > len(pages) // 4}
    # The site's own name at the end of most of its titles ("- NHS",
    # "| Ready.gov") is the site's, too.
    tails = {}
    for title, _, _ in pages:
        m = re.search(r"\s[|–—-]\s([^|–—-]{2,30})$", title)
        if m:
            tails[m.group(0)] = tails.get(m.group(0), 0) + 1
    tail = max(tails, key=tails.get) if tails else ""
    if tail and tails[tail] > len(pages) // 2:
        pages = [(t[:-len(tail)] if t.endswith(tail) else t, p, sec) for t, p, sec in pages]
    docs = n = 0
    for title, path, sections in pages:
        passages = [(h, t) for h, paras in sections
                    for t in passages_from([x for x in paras if x not in furniture])]
        if not passages:
            continue
        cur = db.execute("INSERT INTO docs(title, author, locator) VALUES (?,?,?)",
                         (title, "", path))
        docs += 1
        for seq, (heading, text) in enumerate(passages, 1):
            n += 1
            add(db, cur.lastrowid, seq, title, heading, "", text)
    log("%d pages, %d passages; left out: %d paragraphs of page furniture, %d pages in "
        "another language, %d pages by their title" % (docs, n, len(furniture), other, unwanted))


def from_shelf(z, db, log):
    """A zimgit shelf: database.js names each document and its file."""
    listing = shelf_listing(z)
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
                for heading, place, text in document_passages(pages):
                    seq += 1
                    n += 1
                    add(db, doc, seq, row.get("ti") or fname, heading, place, text)
                docs += 1
                log("  %-45s %4d pages, %5d passages%s"
                    % ((row.get("ti") or fname)[:45], len(pages), n - before,
                       "" if n > before else "   <- NO TEXT (scanned?)"))
    log("%d documents, %d passages" % (docs, n))


def shelf_listing(z):
    raw = bytes(z.get_entry_by_path("database.js").get_item().content).decode("utf-8", "replace")
    return ast.literal_eval(raw[raw.index("["):raw.rindex("]") + 1])


def from_recipe(recipe, sources, db, log):
    """Chosen documents from one or more ZIMs, each under the title, author
    and release statement the recipe gives it. The recipe is the record of
    what was taken and why; what it does not name is not in the collection."""
    from libzim.reader import Archive
    archives, used, docs, n = {}, [], 0, 0
    with tempfile.TemporaryDirectory() as tmp:
        for d in recipe["documents"]:
            src = os.path.join(sources, d["source"])
            if d["source"] not in archives:
                archives[d["source"]] = Archive(src)
                used.append({"file": d["source"], "bytes": os.path.getsize(src),
                             "sha256": sha256_file(src)})
            z = archives[d["source"]]
            path = d.get("path")
            if not path:
                rows = [r for r in shelf_listing(z) if r.get("ti") == d["shelf_title"]]
                if not rows:
                    raise SystemExit("not on the shelf: %r" % d["shelf_title"])
                path = "files/" + rows[0]["fp"][0]
            pdf = os.path.join(tmp, "doc.pdf")
            with open(pdf, "wb") as f:
                f.write(bytes(z.get_entry_by_path(path).get_item().content))
            pages = pdf_pages(pdf)
            if d.get("pages"):
                # only the pages named: the chapter on the desert itself, not
                # the chapters on fighting in it
                pages = [(k, t) for k, t in pages
                         if any(lo <= k <= hi for lo, hi in d["pages"])]
            cur = db.execute("INSERT INTO docs(title, author, locator, note) VALUES (?,?,?,?)",
                             (d["title"], d.get("author", ""), path, d.get("release", "")))
            before = n
            taken = document_passages(pages, d.get("skip_under", ()), d.get("not_headings", ()),
                                      d.get("skip_paragraphs", ()))
            for seq, (heading, place, text) in enumerate(taken, 1):
                n += 1
                add(db, cur.lastrowid, seq, d["title"], heading, place, text)
            docs += 1
            log("  %-58s %4d pages, %5d passages%s"
                % (d["title"][:58], len(pages), n - before,
                   "" if n - before >= len(pages) // 3 else "   <- LITTLE TEXT (scanned or slides?)"))
    log("%d documents, %d passages" % (docs, n))
    return used


def add(db, doc, seq, title, heading, place, text):
    cur = db.execute("INSERT INTO passages(doc, seq, heading, place, text) VALUES (?,?,?,?,?)",
                     (doc, seq, heading, place, text))
    db.execute("INSERT INTO passages_fts(rowid, title, heading, text) VALUES (?,?,?,?)",
               (cur.lastrowid, title, heading, text))


def finish(db, meta):
    meta["docs"] = str(db.execute("SELECT count(*) FROM docs").fetchone()[0])
    meta["passages"] = str(db.execute("SELECT count(*) FROM passages").fetchone()[0])
    meta["passage_max"] = str(PASSAGE_MAX)
    meta["format"] = "1"
    db.executemany("INSERT INTO meta VALUES (?,?)", sorted(meta.items()))
    db.commit()
    db.execute("INSERT INTO passages_fts(passages_fts) VALUES ('optimize')")
    db.commit()
    db.execute("VACUUM")
    db.close()
    return meta


def fresh(out):
    if os.path.exists(out):
        os.remove(out)
    db = sqlite3.connect(out)
    db.executescript(SCHEMA)
    return db


def build(source, out, licence="", log=print, skip_titles="", skip_paragraphs=(), more=None):
    """One whole ZIM -> one collection."""
    from libzim.reader import Archive          # needed here only, never on the unit
    z = Archive(source)
    db = fresh(out)
    m = zim_meta(z)
    shelf = True
    try:
        z.get_entry_by_path("database.js")
    except Exception:
        shelf = False
    log("%s: %s" % (os.path.basename(source), "a shelf of documents" if shelf else "a site"))
    if shelf:
        from_shelf(z, db, log)
    else:
        from_site(z, db, log, lang=(m["language"] or "en")[:2], skip_titles=skip_titles,
                  skip_paragraphs=skip_paragraphs)
    return finish(db, dict(more or {}, **{
        "id": m["name"] or os.path.splitext(os.path.basename(source))[0],
        "title": m["title"], "description": m["description"], "creator": m["creator"],
        "publisher": m["publisher"], "date": m["date"], "language": m["language"],
        "kind": "documents" if shelf else "site",
        "licence": licence or m["license"] or "not stated in the source file",
        "source_file": os.path.basename(source),
        "source_bytes": str(os.path.getsize(source)),
        "source_sha256": sha256_file(source)}))


def build_recipe(recipe_path, sources, out, log=print):
    """A recipe (library/*.json) -> one collection: documents chosen from one
    or more ZIMs ("documents"), or one site with what is left out of it
    ("site")."""
    import json
    with open(recipe_path, encoding="utf-8") as f:
        recipe = json.load(f)
    if recipe.get("site"):
        return build(os.path.join(sources, recipe["site"]), out, recipe.get("licence", ""), log,
                     recipe.get("skip_titles", ""), recipe.get("skip_paragraphs", ()),
                     {"recipe": os.path.basename(recipe_path),
                      "recipe_sha256": sha256_file(recipe_path)})
    db = fresh(out)
    log("%s: %d documents by recipe" % (os.path.basename(recipe_path), len(recipe["documents"])))
    used = from_recipe(recipe, sources, db, log)
    return finish(db, {
        "id": recipe["id"], "title": recipe["title"], "description": recipe["description"],
        "creator": recipe.get("creator", ""), "publisher": "", "date": recipe["date"],
        "language": recipe.get("language", "eng"), "kind": "documents",
        "licence": recipe["licence"], "recipe": os.path.basename(recipe_path),
        "recipe_sha256": sha256_file(recipe_path),
        "sources": json.dumps(used, sort_keys=True)})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source", help="a ZIM file - or, with --recipe, the directory the ZIMs are in")
    ap.add_argument("out")
    ap.add_argument("--licence", default="", help="the collection's licence, once checked")
    ap.add_argument("--recipe", help="library/NAME.json: chosen documents, one or more ZIMs")
    a = ap.parse_args(argv)
    if a.recipe:
        meta = build_recipe(a.recipe, a.source, a.out)
    else:
        meta = build(a.source, a.out, a.licence)
    print("%s: %s docs, %s passages, %d bytes, sha256 %s"
          % (a.out, meta["docs"], meta["passages"], os.path.getsize(a.out), sha256_file(a.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
