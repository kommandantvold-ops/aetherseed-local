"""What the date is - said by the unit, from its own clock (build log 67).

Andreas, 8 Oct 2026, to the proposal that the unit answer "What's the date?"
itself: "Yes to all three." Read beside a post on a model asked the date
with nothing in front of it to say it ("What's the date?", LessWrong, 1 Oct
2026).

She cannot know the date. What she can be told is what the unit's clock
says, and the unit's clock is only as good as the last time it was set: the
board has no battery on its clock and the unit asks no network for the time
(build log 55), so after a power cut it starts again from the minute it
stopped - behind by as long as it was off. A model asked the date guesses,
or repeats a date from its training ("my knowledge is limited to December
2023"), or says the clock's date as if it were certain. So the unit answers,
word for word, model not called: what its clock says, and how far that is
to be believed.

A question about a date in a document, a birthday, "update", "a date with":
none of these is asked here. Only the date or the time NOW.
"""
import re
from datetime import datetime

_ASK = [re.compile(p, re.I) for p in (
    r"\bwhat(?:['’]s| is)\s+(?:the\s+|today['’]s\s+)?date\b(?!\s+(?:of|on|in|for|when)\b)",
    r"\bwhat\s+date\s+is\s+(?:it|today)\b",
    r"\bwhat\s+day\s+is\s+(?:it|today)\b",
    r"\bwhich\s+day\s+is\s+(?:it|today)\b",
    r"\btoday['’]s\s+date\b",
    r"\bwhat(?:['’]s| is)\s+the\s+time\b(?!\s+(?:of|in|on|for|when)\b)",
    r"\bwhat\s+time\s+is\s+it\b",
    r"\bwhat\s+year\s+is\s+(?:it|this)\b",
    r"\b(?:do\s+you\s+know|can\s+you\s+tell\s+me)\s+(?:the\s+|today['’]s\s+)?(?:date|time)\b(?!\s+(?:of|in|on|for|when)\b)",
    # Norwegian
    r"\bhvilken\s+dato\s+er\s+det\b", r"\bhva\s+er\s+datoen\b", r"\bdagens\s+dato\b",
    r"\bhvilken\s+dag\s+er\s+det\b", r"\bhva\s+er\s+klokk(?:a|en)\b",
    r"\bhvor\s+mye\s+er\s+klokk(?:a|en)\b", r"\bhvilket\s+år\s+er\s+det\b",
)]

_DAYS = {"en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
         "nb": ("mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag")}
_MONTHS = {"en": ("January", "February", "March", "April", "May", "June", "July", "August",
                  "September", "October", "November", "December"),
           "nb": ("januar", "februar", "mars", "april", "mai", "juni", "juli", "august",
                  "september", "oktober", "november", "desember")}


def is_date_question(text):
    t = " ".join((text or "").split())
    return len(t) <= 120 and any(p.search(t) for p in _ASK)


def date_text(now=None, language="en"):
    """The unit's own answer: its clock, and how far to believe it."""
    now = now or datetime.now()
    lang = language if language in _DAYS else "en"
    day, month = _DAYS[lang][now.weekday()], _MONTHS[lang][now.month - 1]
    if lang == "nb":
        return ("Etter min egen klokke er det %s %d. %s %d, kl. %02d.%02d. Jeg har ikke "
                "klokkebatteri og spør ikke noe nettverk om tiden: har jeg vært uten strøm, "
                "går klokka mi etter med like lenge." % (day, now.day, month, now.year,
                                                         now.hour, now.minute))
    return ("By my own clock it is %s %d %s %d, %02d:%02d. I have no clock battery and ask "
            "no network for the time: if I have been without power, my clock is behind by "
            "as long as that lasted." % (day, now.day, month, now.year, now.hour, now.minute))
