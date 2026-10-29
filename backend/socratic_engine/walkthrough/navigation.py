"""Deterministic step navigation: next, back, repeat, and go to step N.

One parser, consulted before anything grades a message or hands it to a
model, so "next", "go to step 5" or "say that again" can never be taken as an
answer to the question on screen, and never reach the Q&A path to be answered
as if they were questions. Pure functions over strings; no model, no DB. A
test asserts this module imports neither.

The meaning of a command (which list "step 5" points into, what "next" skips)
is decided by the caller, from where the student is: a software walkthrough
step, a key-ideas part, or the phone-only procedure overview.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Nav(str, Enum):
    NEXT = "next"
    BACK = "back"
    REPEAT = "repeat"
    GOTO = "goto"


@dataclass(frozen=True)
class NavCommand:
    kind: Nav
    #: 1-based target for GOTO; None otherwise.
    target: int | None = None
    #: The unit the student named ("step", "part"), if any. "next part" in a
    #: key-ideas session moves to the next part rather than the next question.
    unit: str | None = None


_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
    "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12,
}
_ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth",
             "tenth", "eleventh", "twelfth")
_CARDINALS = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
              "eleven", "twelve", "thirteen", "fourteen", "fifteen")

_UNIT = r"(?P<unit>step|part|stage|item|section)"
_NUM = r"(?P<num>\d{1,2}|" + "|".join(_CARDINALS) + r")"
_ORD = r"(?P<ord>" + "|".join(_ORDINALS) + r"|\d{1,2}(?:st|nd|rd|th))"
# "step 5", "step no. 5", "step number five", "the fifth step", "5th step".
_TARGET = rf"(?:the\s+)?(?:{_UNIT}\s*(?:no\.?|number|#)?\s*{_NUM}|{_ORD}\s+(?P<unit2>step|part|stage|item|section))"

# Politeness and filler around a command: "ok", "please", "can you", "now".
_LEAD = (
    r"^(?:(?:ok|okay|okk|alright|right|so|now|then|yes|yeah|yep|please|pls|plz|cool|great|fine|good|"
    r"thanks|thank you|and|hmm+|bro|bhai|sir|ma.?am)[\s,.!]+)*"
)
_ASK = r"(?:(?:can|could|would|will)\s+(?:you|we|i)\s+|let'?s\s+|lets\s+|i\s+(?:want|wanna|would like|need)\s+to\s+)?"
_TAIL = r"(?:[\s,]+(?:please|pls|plz|now|then|thanks|thank you|sir|bro|bhai))*[\s.!?]*$"

_GOTO_RES = [
    re.compile(
        _LEAD + _ASK
        + r"(?:go|jump|skip|move|head|get|return|come|switch|navigate)"
        r"(?:\s+(?:back|forward|ahead|straight|directly))?\s+(?:to|on\s+to|onto)\s+" + _TARGET + _TAIL
    ),
    re.compile(_LEAD + _ASK + r"(?:take|bring|send)\s+me\s+(?:back\s+)?to\s+" + _TARGET + _TAIL),
    re.compile(_LEAD + _ASK + r"(?:show|open|start|do|begin|display|give)(?:\s+me)?\s+" + _TARGET + r"(?:\s+again)?" + _TAIL),
    re.compile(
        _LEAD + r"(?:what(?:'s|\s+is|\s+was|\s+happens\s+in|\s+do\s+i\s+do\s+in)|explain|tell\s+me(?:\s+about)?|describe)\s+"
        + _TARGET + r"(?:\s+about)?" + _TAIL
    ),
    re.compile(_LEAD + _TARGET + _TAIL),
]

_NEXT_UNIT = r"(?:\s+(?:to\s+)?(?:the\s+)?(?:next\s+)?(?P<unit>step|part|stage|one|item|question|section))?"
_NEXT_RES = [
    re.compile(
        _LEAD + _ASK + r"(?:go\s+)?(?:next|move\s+on|move\s+ahead|proceed|go\s+forward|forward)" + _NEXT_UNIT + _TAIL
    ),
    re.compile(
        _LEAD + _ASK + r"(?:go|move|skip|jump|take\s+me|get)\s+(?:on\s+)?to\s+(?:the\s+)?next"
        r"(?:\s+(?P<unit>step|part|stage|one|item|question|section))?" + _TAIL
    ),
]

_BACK_RES = [
    re.compile(
        _LEAD + _ASK + r"(?:(?:go|move|step|jump|take\s+me)\s+)?back(?:\s+(?:a|one)\s+(?P<unit>step|part|stage))?" + _TAIL
    ),
    re.compile(
        _LEAD + _ASK + r"(?:(?:go|move|jump|take\s+me)\s+(?:back\s+)?to\s+)?(?:the\s+)?(?:previous|prev|last|earlier)"
        r"(?:\s+(?P<unit>step|part|stage|one|item|question|section))?" + _TAIL
    ),
]

_REPEAT_RES = [
    re.compile(
        _LEAD + _ASK
        + r"(?:repeat(?:\s+(?:that|this|it|the\s+(?:step|question|part|stage)))?(?:\s+again)?"
        r"|(?:say|show|read|give)\s+(?:me\s+)?(?:that|it|this|the\s+(?:step|question|part|stage))\s+again"
        r"|again"
        r"|show\s+(?:me\s+)?(?:the\s+)?(?:current\s+)?(?:step|question|part|stage)(?:\s+again)?"
        r"|where\s+(?:am|was|were)\s+(?:i|we)"
        r"|(?:which|what)\s+(?:step|part|stage)\s+(?:am\s+i\s+on|are\s+we\s+on|is\s+this))"
        + _TAIL
    ),
]

# Looser: anything that NAMES a step to go to, even inside a longer sentence.
# Used only to stop such a message counting as an answer (grader.grade); it
# never moves anything by itself.
_MENTION_RE = re.compile(
    r"\b(?:go|jump|skip|move|take\s+me|bring\s+me|head)\s+(?:back\s+|forward\s+|ahead\s+)?to\s+(?:the\s+)?"
    r"(?:next|previous|(?:step|part|stage)\b|(?:" + "|".join(_ORDINALS) + r")\s+(?:step|part|stage))"
    r"|\b(?:step|part|stage)\s*(?:no\.?|number|#)?\s*\d{1,2}\b"
)


def _norm(text: str) -> str:
    text = (text or "").lower().replace("’", "'")
    text = re.sub(r"[`*_#>\"]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _number(match: re.Match[str]) -> int | None:
    raw = match.groupdict().get("num") or match.groupdict().get("ord") or ""
    raw = re.sub(r"(?<=\d)(?:st|nd|rd|th)$", "", raw)
    if raw.isdigit():
        return int(raw)
    return _WORDS.get(raw)


def _unit(match: re.Match[str]) -> str | None:
    unit = match.groupdict().get("unit") or match.groupdict().get("unit2")
    if unit in ("part", "stage", "section"):
        return "part"
    if unit in ("step", "item"):
        return "step"
    return None


def parse(text: str) -> NavCommand | None:
    """The navigation command in `text`, or None if it is not one. Anchored on
    the whole message (apart from filler), so a sentence that merely contains
    "next" or "step 3" is never a command."""
    t = _norm(text)
    if not t or len(t.split()) > 12:
        return None
    for pattern in _GOTO_RES:
        m = pattern.match(t)
        if m:
            n = _number(m)
            if n is not None:
                return NavCommand(Nav.GOTO, n, _unit(m))
    for pattern in _NEXT_RES:
        m = pattern.match(t)
        if m:
            return NavCommand(Nav.NEXT, None, _unit(m))
    for pattern in _BACK_RES:
        m = pattern.match(t)
        if m:
            return NavCommand(Nav.BACK, None, _unit(m))
    for pattern in _REPEAT_RES:
        if pattern.match(t):
            return NavCommand(Nav.REPEAT)
    return None


def mentions_navigation(text: str) -> bool:
    """True when `text` names a step to move to, even inside a longer
    sentence ("can we go to step 5 now and skip these"). Such a message is
    never an answer to the question on screen."""
    return parse(text) is not None or bool(_MENTION_RE.search(_norm(text)))
