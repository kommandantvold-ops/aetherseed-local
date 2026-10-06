"""Three tools whose answer is the unit's, not the model's (build log 64).

    calculate   arithmetic, exactly
    count       the lines, words and characters of a workspace file - or how
                often one word is in it
    compare     two workspace files: the same, or where they first differ

Andreas, 6 Oct 2026, asked what the upper trust levels should open for the
training loop: "A safe calculator and file tools for builder". Builder is
tier 3. What AetherSpark keeps at tier 3 - a shell and Python - is still not
reachable from a conversation, and nothing here runs either: no eval, no
subprocess, no import of what the steward typed. The arithmetic is read by a
small parser of its own (numbers, + - * / % ** and brackets) and worked in
fractions, so 0.1 + 0.2 is 0.3 and not 0.30000000000000004.

Why the unit and not the model: these are answers that are right or wrong.
Measured on this model again and again (38d, 49, 51) - shown the right
figure, it retypes another. So, like the to-do list and the refusals, the
result is served word for word and the model is not called.

A tool here runs only when it is asked for BY NAME ("calculate", "compute",
"work out"; "count"; "compare") - the rule of intent_detection.py. "What is
17 times 23?" is a question, and goes where it always went.
"""
import re
from fractions import Fraction
from pathlib import Path

MAX_EXPRESSION = 120
MAX_DEPTH = 24
MAX_EXPONENT = 200
MAX_DIGITS = 400
MAX_FILE_BYTES = 1_000_000
LINE_SHOWN = 120


class ToolError(Exception):
    """Something the tool cannot do, said in words the steward can read."""


# ---------------------------------------------------------------------------
# calculate
# ---------------------------------------------------------------------------
_WORDS = (
    (r"\bto\s+the\s+power\s+of\b", "**"),
    (r"\b(?:multiplied\s+by|times)\b", "*"),
    (r"\b(?:divided\s+by|over)\b", "/"),
    (r"\bplus\b", "+"),
    (r"\bminus\b", "-"),
    (r"\bsquared\b", "**2"),
    (r"\bcubed\b", "**3"),
)
_PERCENT_OF = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent)\s+of\s+", re.I)
_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?|\.\d+)|(\*\*|[-+*/%()]))")
_ALLOWED = re.compile(r"^[\d\s.+\-*/%()]+$")


def normalise(text: str) -> str:
    """The expression as the parser reads it: words and other signs made into
    + - * / ** . Raises ToolError for what it will not guess at."""
    t = (text or "").strip().strip("?!").strip().rstrip(".").strip()
    t = t.rstrip("=").strip()
    if not t:
        raise ToolError("There is nothing to calculate.")
    if len(t) > MAX_EXPRESSION:
        raise ToolError("That is too long for me to calculate.")
    if "," in t:
        # 1,500 is fifteen hundred to one reader and one and a half to another.
        raise ToolError("I can't tell what a comma in a number means. "
                        "Write 1500 for fifteen hundred and 1.5 for one and a half.")
    t = t.replace("×", "*").replace("·", "*").replace("÷", "/").replace("^", "**")
    t = t.replace("−", "-").replace("–", "-")
    t = _PERCENT_OF.sub(lambda m: "(%s/100)*" % m.group(1), t)
    for pattern, sign in _WORDS:
        t = re.sub(pattern, sign, t, flags=re.I)
    t = re.sub(r"(?<=\d)\s*x\s*(?=\d)", "*", t, flags=re.I)      # 3 x 4
    return " ".join(t.split())


def looks_like_arithmetic(text: str) -> bool:
    """Numbers and signs and nothing else - "calculate the odds" is a
    question for the model, not for this."""
    try:
        t = normalise(text)
    except ToolError as e:
        return "comma" in str(e)          # arithmetic, and it will be told why not
    return bool(_ALLOWED.match(t)) and bool(re.search(r"\d", t))


class _Parser:
    def __init__(self, text):
        self.tokens, pos = [], 0
        while pos < len(text):
            if text[pos:].strip() == "":
                break
            m = _TOKEN.match(text, pos)
            if not m:
                raise ToolError("I can't read that as arithmetic.")
            self.tokens.append(m.group(1) or m.group(2))
            pos = m.end()
        self.i = 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expr(self, depth=0):
        if depth > MAX_DEPTH:
            raise ToolError("That has too many brackets for me.")
        v = self.term(depth)
        while self.peek() in ("+", "-"):
            op = self.take()
            r = self.term(depth)
            v = v + r if op == "+" else v - r
        return v

    def term(self, depth):
        v = self.unary(depth)
        while self.peek() in ("*", "/", "%"):
            op = self.take()
            r = self.unary(depth)
            if op == "*":
                v = v * r
            else:
                if r == 0:
                    raise ToolError("That divides by zero, so there is no answer.")
                v = v / r if op == "/" else v % r
            _bounded(v)
        return v

    def unary(self, depth):
        if self.peek() in ("+", "-"):
            op = self.take()
            v = self.unary(depth)
            return -v if op == "-" else v
        return self.power(depth)

    def power(self, depth):
        base = self.atom(depth)
        if self.peek() == "**":
            self.take()
            exp = self.unary(depth)            # right-associative: 2**3**2
            if exp.denominator != 1:
                raise ToolError("I can only raise to a whole-number power.")
            if abs(exp) > MAX_EXPONENT:
                raise ToolError("That power is too large for me.")
            if base == 0 and exp < 0:
                raise ToolError("That divides by zero, so there is no answer.")
            base = base ** int(exp)
            _bounded(base)
        return base

    def atom(self, depth):
        tok = self.take()
        if tok is None:
            raise ToolError("That stops in the middle; I can't calculate it.")
        if tok == "(":
            v = self.expr(depth + 1)
            if self.take() != ")":
                raise ToolError("A bracket is opened and not closed.")
            return v
        if re.match(r"^(?:\d+(?:\.\d+)?|\.\d+)$", tok):
            return Fraction(tok)
        raise ToolError("I can't read that as arithmetic.")


def _bounded(v):
    if len(str(abs(v.numerator))) > MAX_DIGITS or len(str(v.denominator)) > MAX_DIGITS:
        raise ToolError("That number is too large for me.")


def _terminates(d: int) -> bool:
    for p in (2, 5):
        while d % p == 0:
            d //= p
    return d == 1


def _decimal(v: Fraction) -> str:
    """A fraction whose decimal ends, written out exactly."""
    sign = "-" if v < 0 else ""
    v = abs(v)
    whole, rest = divmod(v.numerator, v.denominator)
    digits = []
    while rest and len(digits) < 40:
        rest *= 10
        d, rest = divmod(rest, v.denominator)
        digits.append(str(d))
    return sign + str(whole) + ("." + "".join(digits) if digits else "")


def value_text(v: Fraction) -> str:
    """The value as it is said: whole, an exact decimal, or - when the decimal
    never ends - the fraction itself with a rounded decimal beside it."""
    if v.denominator == 1:
        return str(v.numerator)
    if _terminates(v.denominator):
        out = _decimal(v)
        if len(out.split(".")[1]) <= 12:
            return out
    return "%s/%s (about %s)" % (v.numerator, v.denominator, "%.6f" % float(v))


def evaluate(text: str) -> Fraction:
    t = normalise(text)
    if not _ALLOWED.match(t):
        raise ToolError("I can only calculate with numbers and + - * / % and brackets.")
    p = _Parser(t)
    v = p.expr()
    if p.peek() is not None:
        raise ToolError("I can't read that as arithmetic.")
    return v


def calculate(text: str) -> str:
    """The answer in words, or the reason there is none. Never raises."""
    try:
        v = evaluate(text)
        shown = " ".join((text or "").strip().strip("?!").rstrip(".=").split())
        return "%s = %s" % (shown, value_text(v))
    except ToolError as e:
        return str(e)
    except (ZeroDivisionError, OverflowError, RecursionError, ValueError):
        return "I can't calculate that."


# ---------------------------------------------------------------------------
# count and compare: files of the workspace, and nowhere else
# ---------------------------------------------------------------------------
def _file(workspace, name):
    """(path, text) of a workspace file, or ToolError."""
    if not name:
        raise ToolError("No file was named.")
    root = Path(workspace).resolve()
    try:
        path = (root / name).resolve()
        path.relative_to(root)
    except (ValueError, OSError, RuntimeError):
        raise ToolError("I can only reach files in my workspace.")
    if not path.is_file():
        raise ToolError("There is no file %s in my workspace." % name)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ToolError("%s is too large for me to read through." % name)
    raw = path.read_bytes()
    if b"\x00" in raw:
        raise ToolError("%s is not a text file." % name)
    return path, raw.decode("utf-8", errors="replace")


def _n(n, one, many=None):
    return "%d %s" % (n, one if n == 1 else (many or one + "s"))


def count(workspace, name, word=None) -> str:
    try:
        _, text = _file(workspace, name)
    except ToolError as e:
        return str(e)
    if word:
        hits = len(re.findall(r"(?<!\w)%s(?!\w)" % re.escape(word), text, flags=re.I))
        return ('The word "%s" is in %s %s.' % (word, name, _n(hits, "time"))
                if hits else 'The word "%s" is not in %s.' % (word, name))
    lines = text.splitlines()
    return "%s has %s, %s and %s." % (
        name, _n(len(lines), "line"), _n(len(text.split()), "word"),
        _n(len(text), "character"))


def _shown(line):
    line = line.rstrip("\r\n")
    return line if len(line) <= LINE_SHOWN else line[:LINE_SHOWN] + "..."


def compare(workspace, first, second) -> str:
    try:
        _, a = _file(workspace, first)
        _, b = _file(workspace, second)
    except ToolError as e:
        return str(e)
    la, lb = a.splitlines(), b.splitlines()
    if a == b:
        return "%s and %s are the same: %s, every one equal." % (
            first, second, _n(len(la), "line"))
    if la == lb:
        return ("%s and %s have the same %s; they differ only in how a line "
                "ends." % (first, second, _n(len(la), "line")))
    at = next((i for i, (x, y) in enumerate(zip(la, lb)) if x != y), min(len(la), len(lb)))
    out = ["%s and %s differ. %s has %s and %s has %s." % (
        first, second, first, _n(len(la), "line"), second, _n(len(lb), "line")),
        "The first difference is at line %d:" % (at + 1)]
    out.append("  %s: %s" % (first, _shown(la[at]) if at < len(la) else "(no such line)"))
    out.append("  %s: %s" % (second, _shown(lb[at]) if at < len(lb) else "(no such line)"))
    return "\n".join(out)
