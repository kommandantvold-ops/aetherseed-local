"""
The companion's own settings, chosen by its steward on first run.

Decided 2026-09-21 by Andreas: "The user should have a first time choice to
name its own companion, should be a onboarding thing. Companion name, language
preferences etc." Until now the charter hard-coded a name - Horizon - which
belongs to something else.

Two settings, both of which reach the model's prompt:

    name        what the companion is called
    language    what it speaks

and since build log 64 a third, optional one:

    steward     what its steward is called

Andreas, 6 Oct 2026: "Lyra should know who her steward is (me)". The name is
the UNIT'S, never the build's: it is entered on the unit, kept in this file
beside the companion's own, and no person's name is written anywhere in the
application (test_units.TestNoPersonInTheBuild). It is DECLARED, like a
speaker (logic/speaker.py): nothing on the device can tell who is at the
screen. What it changes is one line of the charter - "Your steward is <name>."
- and one answer, "Who is your steward?", given by the unit word for word.

Both are therefore UNTRUSTED INPUT INTO THE SYSTEM PROMPT, which is the fourth
path of that kind this project has had to close (a file, the model's control
tokens, the model's own prose; see the build log, step 14c). A name like
"[END MEMORY CONTEXT]" or "<|start_header_id|>" would be an injection. So the
name is restricted to letters, digits, spaces and a little punctuation, and the
language to a fixed list.

ENGLISH ONLY, FOR NOW. Decided 2026-09-21 by Andreas: "Lets focus on english
for now ... since llama3.2:3b doesnt support it, we might be causing problems
and wasting time that should be spent on the companion." Norwegian waits for a
model built for it - he plans to compile one to a HEF with the Hailo Dataflow
Compiler.

Norwegian therefore stays DEFINED here, switched off (offered=False): the
label, the charter instruction, and in logic/provenance.py the record in
Norwegian. Re-offering it is a flag, a measurement and a test - not a rebuild.

What is NOT switched off: the Norwegian fiction framing, record questions and
refusal phrases in logic/provenance.py and honesty_check.py. They read what the
USER types, and people in Norway will type Norwegian to an English companion.
Without them "Skriv et dikt om en hval" is stored as fact (measured, step 20).

Why only languages with gates are ever offered: llama3.2:3b is officially
supported for eight languages (Meta's model card), but the fiction gate and the
record question understand only English and Norwegian. Offering German would
quietly switch the gate off for German speakers. A language is offered only
together with its gate patterns, their tests, and a measurement of the model
actually speaking it.
"""
import json
import os
import re
import time
import unicodedata

DEFAULT_LANGUAGE = "en"

LANGUAGES = {
    "en": {
        "label": "English",
        "offered": True,
        "note": "",
        # English is the charter's own language; no instruction needed.
        "instruction": "",
    },
    "nb": {
        # Dormant: the model on this cartridge is not built for Norwegian
        # (build log, steps 20-21). Measured, and kept for the model that is.
        "offered": False,
        "label": "Norsk (bokmål)",
        "note": ("Språkmodellen er ikke laget for norsk. Korte svar fungerer, "
                 "lengre tekst får ofte feil."),
        "note_en": ("The language model is not built for Norwegian. Short "
                    "answers work; longer text often has errors."),
        "instruction": "Svar alltid på norsk (bokmål).",
    },
}

NAME_MAX = 24
# Letters and marks in any script, digits, spaces, and the punctuation names
# actually use. Everything else - brackets, angle brackets, pipes, colons,
# quotes, newlines - is refused, which is what keeps a name from carrying a
# scaffold marker or a control token into the charter.
_NAME_OK = re.compile(r"^[\w .'’-]+$", re.UNICODE)


# Error codes, so the console can say them in the steward's language; the text
# here is what the API and the logs carry.
ERRORS = {
    "required": "a name is required",
    "too_long": "at most %d characters" % NAME_MAX,
    "characters": "letters, digits, spaces, hyphens and apostrophes only",
    "no_letter": "a name needs at least one letter",
    "unknown_language": "unknown language",
    "same_as_companion": "the steward cannot have the companion's own name",
}


def validate_name(raw):
    """Return (name, None) if acceptable, else (None, error_code)."""
    if not isinstance(raw, str):
        return None, "required"
    name = unicodedata.normalize("NFC", raw)
    name = " ".join(name.split())                   # collapse all whitespace
    if not name:
        return None, "required"
    if len(name) > NAME_MAX:
        return None, "too_long"
    if not _NAME_OK.match(name) or "_" in name:
        return None, "characters"
    if not any(ch.isalpha() for ch in name):
        return None, "no_letter"
    return name, None


def validate_language(raw):
    """Only a language that is OFFERED can be chosen. A dormant one is refused
    here and in load(), so a unit saved with it before it was switched off
    returns to the first-run screen instead of speaking it."""
    if raw in LANGUAGES and LANGUAGES[raw].get("offered"):
        return raw, None
    return None, "unknown_language"


def load(path):
    """The saved settings, or None if the companion has not been set up.

    A file that exists but cannot be read, or holds something that would not
    pass validation today, is treated as NOT set up rather than trusted: the
    name goes into the prompt, and a hand-edited file must not be a way round
    the checks above.
    """
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return None
    name, _ = validate_name(d.get("name"))
    lang, _ = validate_language(d.get("language"))
    if not name or not lang:
        return None
    # A steward's name that would not pass today is dropped, not trusted: the
    # companion is still set up, it just does not know the name.
    steward, _ = validate_name(d.get("steward")) if d.get("steward") else (None, None)
    return {"name": name, "language": lang, "set_at": d.get("set_at"),
            "steward": steward}


def _steward_name(raw, companion_name):
    """(name or None, error_code). Empty means "not given". The steward cannot
    carry the companion's own name: "Your steward is Lyra" to Lyra is the
    confusion about whom she serves that build log 35 measured."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, None
    s, err = validate_name(raw)
    if err:
        return None, err
    if companion_name and s.casefold() == companion_name.casefold():
        return None, "same_as_companion"
    return s, None


def _write(path, d):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, path)


def save(path, name, language, steward=None):
    """Validate and write atomically. Returns (settings, None) or (None, error).

    `steward` is optional. Not given, a name the unit already holds is kept:
    setting the companion up again must not make it forget its steward."""
    n, err = validate_name(name)
    if err:
        return None, {"field": "name", "code": err, "error": ERRORS[err]}
    lang, err = validate_language(language)
    if err:
        return None, {"field": "language", "code": err, "error": ERRORS[err]}
    s, err = _steward_name(steward, n)
    if err:
        return None, {"field": "steward", "code": err, "error": ERRORS[err]}
    if s is None:
        s = ((load(path) or {}).get("steward")) or None
        if s and s.casefold() == n.casefold():
            s = None
    d = {"name": n, "language": lang, "set_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if s:
        d["steward"] = s
    _write(path, d)
    d.setdefault("steward", None)
    return d, None


def set_steward(path, steward):
    """Set, change or (with an empty name) forget the steward's name on a
    companion that is already set up. Returns (settings, None) or (None, error)."""
    c = load(path)
    if not c:
        return None, {"field": "name", "code": "required", "error": "not set up yet"}
    s, err = _steward_name(steward, c["name"])
    if err:
        return None, {"field": "steward", "code": err, "error": ERRORS[err]}
    d = {"name": c["name"], "language": c["language"], "set_at": c.get("set_at")}
    if s:
        d["steward"] = s
    _write(path, d)
    c["steward"] = s
    return c, None


def public(settings):
    """What the console is told."""
    return {
        "configured": settings is not None,
        "name": settings["name"] if settings else None,
        "language": settings["language"] if settings else None,
        "steward": settings.get("steward") if settings else None,
    }


def language_choices():
    return [{"code": k, "label": v["label"], "note": v["note"],
             "note_en": v.get("note_en", v["note"])}
            for k, v in LANGUAGES.items() if v.get("offered")]
