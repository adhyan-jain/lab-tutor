"""Deterministic triage of an incoming student message.

Runs *before* any model call, for the same reason Tier 1 does: some
answers must not depend on a model being reachable, correctly prompted,
or in a good mood.

The case that forced this module into existence: with the inference
backend down -- a documented, expected degraded mode -- every message got
the current step's hint re-served verbatim. "i spilled acid on my hand"
was answered with "Check the label on the standard solution again." In a
room containing acid and glassware, that is not a wording problem.

Three intents short-circuit the normal path:

``SAFETY_INCIDENT``  something has already happened to a person
``SAFETY_QUESTION``  the student is asking whether something is safe to do
``DISTRESS``         the student is struggling in a way a hint will not fix

Everything else -- including basic questions, vague confusion, nonsense
and meta questions -- flows to the ordinary hint path. A first-year asking
"what is a burette" is the tool working, not a misuse of it, and must
never be brushed off.

**Precision over recall, deliberately.** A missed off-scope question costs
nothing: it falls through to a model already instructed to stay on task.
A false positive refuses a legitimate chemistry question and teaches the
student the tool is broken. Every pattern below is therefore narrow, and
`tests/test_student_questions.py` asserts that no genuine lab question in
the golden dataset trips any of them.
"""

from __future__ import annotations

import enum
import re


class Intent(str, enum.Enum):
    LAB_QUESTION = "lab_question"
    SAFETY_INCIDENT = "safety_incident"
    SAFETY_QUESTION = "safety_question"
    DISTRESS = "distress"
    OFF_SCOPE = "off_scope"


#: Something has happened to a person, or a hazard is active right now.
#: Each pattern requires a personal referent or an unmistakable hazard, so
#: that ordinary chemistry vocabulary ("burette", "burner", "acid") cannot
#: trigger it on its own.
_SAFETY_INCIDENT_PATTERNS: tuple[str, ...] = (
    # Something reached a person. Anchored to a body part rather than to a
    # bare "my", so "the acid went into the flask" and "hold it in my hand"
    # stay ordinary questions, while "acid went on my arm" -- which has no
    # spill verb at all, and which an earlier version missed -- does not.
    r"\b(?:spill|spilt|spilled|splash(?:ed)?|poured|went|got|landed|dripped|leaked|sprayed|dropped)\b"
    r"[^.]{0,30}\b(?:on|in|into|onto|over)\b[^.]{0,12}"
    r"\b(?:me|myself|(?:my|his|her|their)\s+(?:hand|hands|arm|arms|skin|face|"
    r"eye|eyes|finger|fingers|leg|legs|foot|feet|neck|mouth|lip|lips|"
    r"clothes|clothing|lab\s*coat|shirt|sleeve))\b",
    r"\bin\s+(?:my|his|her|their)\s+(?:eye|eyes|mouth|face)\b",
    r"\b(?:my|his|her|their)\s+\w{0,12}\s*(?:is|are|feels?)\s+burning\b",
    r"\b(?:i|we|he|she|they)\s+(?:think\s+)?(?:i\s+)?(?:just\s+)?burn(?:ed|t)\b",
    r"\bburn(?:ed|t)\s+(?:my|myself|his|her|their|him|them)\b",
    r"\b(?:swallow(?:ed)?|ingested|drank|tasted)\b[^.]{0,20}\b(?:it|some|this|chemical)\b",
    r"\binhal(?:ed|ing)\b",
    r"\bbreath(?:ed|ing)\s+in\b",
    r"\b(?:cut|sliced)\s+(?:my|myself|his|her|their)\b",
    # "Bleeding" needs a person attached to it. Bleeding air out of a
    # burette tip is ordinary titration vocabulary, and an early version of
    # this pattern matched it -- sending a student to fetch a demonstrator
    # because they asked how to start correctly.
    r"\b(?:i'?m|i am|im)\s+bleeding\b",
    r"\b(?:my|his|her|their)\s+\w{0,12}\s*(?:is\s+|are\s+)?bleeding\b",
    r"\bbleeding\s+(?:a\s+lot|badly|everywhere)\b",
    r"\bon\s+fire\b",
    r"\b(?:there(?:'s| is)\s+)?smoke\s+(?:coming|from)\b",
    r"\bfeel(?:ing)?\s+(?:faint|dizzy|sick|nauseous|light[- ]?headed)\b",
    r"\b(?:can'?t|cannot)\s+breathe\b",
    r"\b(?:not|isn'?t)\s+responding\b",
    r"\b(?:passed\s+out|fainted|collapsed)\b",
    r"\b(?:blister|rash)\b",
    r"\b(?:glass|beaker|flask|tube)\b[^.]{0,20}\b(?:broke|cracked|shattered)\b",
)

#: The student is asking whether an action is safe. Never improvise an
#: answer to these -- a plausible-sounding wrong one is worse than none.
_SAFETY_QUESTION_PATTERNS: tuple[str, ...] = (
    r"\bwhat\s+happens\s+if\s+(?:i|we)\s+(?:mix|combine|add|pour|heat)\b",
    r"\bis\s+it\s+safe\s+to\b",
    r"\b(?:can|should)\s+(?:i|we)\s+(?:mix|combine)\b[^.]{0,30}\b(?:with|and)\b",
    r"\bpour\b[^.]{0,25}\b(?:down\s+the\s+(?:sink|drain)|in\s+the\s+bin)\b",
    r"\b(?:can|should)\s+(?:i|we)\s+(?:taste|drink|smell|touch)\b",
    r"\bhow\s+do\s+(?:i|we)\s+dispose\b",
    r"\bis\s+this\s+(?:dangerous|toxic|corrosive|flammable)\b",
)

#: Struggling in a way a hint about a meniscus will not address.
_DISTRESS_PATTERNS: tuple[str, ...] = (
    r"\b(?:i'?m|i am|im)\s+(?:going\s+to\s+)?fail",
    r"\b(?:i'?m|i am|im)\s+(?:crying|panicking|so\s+stressed|stressed|overwhelmed)\b",
    r"\bi\s+(?:hate|can'?t\s+do)\s+(?:this|chemistry)\b",
    r"\b(?:i'?ve|i have)\s+been\s+here\s+\w+\s+hours?\b",
    r"\beveryone\s+else\s+(?:finished|is\s+done|has\s+left)\b",
    r"\bcan\s+i\s+just\s+(?:leave|give\s+up|quit)\b",
    r"\bdoing\s+everything\b[^.]{0,30}\bi\s+understand\s+nothing\b",
    r"\bi\s+understand\s+nothing\b",
)

#: Clearly not about this experiment. Narrow on purpose.
_OFF_SCOPE_PATTERNS: tuple[str, ...] = (
    r"\bwrite\s+(?:my|me)\b[^.]{0,30}\b(?:report|introduction|essay|conclusion|assignment)\b",
    r"\bwrite\s+(?:me\s+)?a\s+(?:python|java|javascript|c\+\+)\b",
    r"\b(?:python|javascript)\s+(?:script|program|code)\b",
    r"\bcapital\s+of\s+\w+",
    r"\btell\s+me\s+a\s+joke\b",
    r"\bwho\s+won\b",
    r"\bweather\b",
    r"\bmy\s+(?:physics|maths|math|english|history)\s+(?:assignment|homework)\b",
    r"\bsummar(?:ise|ize)\s+chapter\b",
    r"\bfor\s+lunch\b",
    r"\bquantum\s+entanglement\b",
    r"\b(?:my\s+)?resume\b|\bcv\b",
    r"\bwhen\s+is\s+the\s+(?:exam|test|quiz)\b",
)


def _matches(message: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(p, message, re.IGNORECASE) for p in patterns)


def classify(message: str) -> Intent:
    """Classify one message. Order encodes priority: harm first.

    A message that looks like both an injury report and an off-scope
    request is treated as an injury report.
    """
    text = (message or "").strip()
    if not text:
        return Intent.LAB_QUESTION

    if _matches(text, _SAFETY_INCIDENT_PATTERNS):
        return Intent.SAFETY_INCIDENT
    if _matches(text, _SAFETY_QUESTION_PATTERNS):
        return Intent.SAFETY_QUESTION
    if _matches(text, _DISTRESS_PATTERNS):
        return Intent.DISTRESS
    if _matches(text, _OFF_SCOPE_PATTERNS):
        return Intent.OFF_SCOPE
    return Intent.LAB_QUESTION


#: Fixed responses. No model is consulted for any of these, so they are
#: identical whether inference is healthy or entirely unreachable.
_RESPONSES: dict[Intent, str] = {
    Intent.SAFETY_INCIDENT: (
        "Stop what you are doing and tell your demonstrator right now, in "
        "person. If anything is on your skin or in your eyes, go to the "
        "nearest wash station or eyewash while you call them. I am a "
        "tutoring tool and I am not able to advise on this -- a person in "
        "the room needs to look at it."
    ),
    Intent.SAFETY_QUESTION: (
        "Ask your demonstrator before you do that. Questions about mixing, "
        "heating or disposing of anything need someone who can see your "
        "bench and what is actually in front of you, so I am not going to "
        "guess at it."
    ),
    Intent.DISTRESS: (
        "That sounds genuinely frustrating, and it is worth telling your "
        "demonstrator -- being stuck for a long stretch is exactly what "
        "they are there for, and it is a normal thing to ask about. When "
        "you are ready, I can pick up from the step you are on."
    ),
    Intent.OFF_SCOPE: (
        "That one is outside what I can help with -- I only cover the "
        "experiment you are working on right now. Ask me about the current "
        "step and I will help with that."
    ),
}


def fixed_response(intent: Intent) -> str | None:
    """The deterministic reply for a short-circuited intent, or None."""
    return _RESPONSES.get(intent)


def short_circuits(intent: Intent) -> bool:
    """Whether this intent bypasses the model entirely."""
    return intent in _RESPONSES


def needs_staff_attention(intent: Intent) -> bool:
    """Whether staff should be able to see that this happened."""
    return intent in (Intent.SAFETY_INCIDENT, Intent.SAFETY_QUESTION, Intent.DISTRESS)


_GUIDANCE_RE = re.compile(
    r"\b(guide me|guidance|walk me through|help me (do|with|through)|"
    r"how do i (start|begin|do this|proceed)|what.s (the )?next step|"
    r"which step|step \d+|next step|stuck|i.m confused|i don.t know how)\b",
    re.IGNORECASE,
)


def is_guidance_request(text: str) -> bool:
    """Deterministic (no LLM) check for "help me work through this
    experiment / give me the current step's hint" phrasing, as opposed to
    a general factual question.

    `chat_routes` uses it to decide whether a first-time message should
    silently enrol a student into a guided Socratic session (only a
    guidance request should); a plain factual question falls through to
    grounded Q&A instead.
    """
    return bool(_GUIDANCE_RE.search(text))
