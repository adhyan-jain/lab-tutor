"""Phone-only gate: a student-facing question must be answerable by someone
with only a phone and this web page.

Tomorrow's students have no Gabedit, ORCA, Avogadro, second screen or output
file, so LabTutor must never ask them to look at, open, run or read something
outside the page, and must never imply they just saw something it did not show
them. Two independent, deterministic checks (no model involved):

1. `source` metadata on each question. Only THEORY, CONCEPTUAL_REASONING and
   GIVEN_DATA_INTERPRETATION are allowed (see types.PHONE_SOURCES).
2. A text scan of everything the student would read (`external_dependency`).
   The metadata says what a question is meant to be; the scan catches wording
   that contradicts it, in questions and in every authored line around them.

Both must pass. The scan is deliberately conservative: a false positive only
means a question is not asked in phone-only mode, never a wrong reply.
"""

from __future__ import annotations

import re

from .types import PHONE_SOURCES, ConceptQuestion

# Each pattern names an external-tool dependency or a claim about something
# the student supposedly saw. Word-boundaried and case-insensitive.
_EXTERNAL_PATTERNS: tuple[str, ...] = (
    r"\bscreens?\b",
    r"drawing (area|window)",
    r"\bterminal\b",
    r"\bgabedit\b",
    r"\bavogadro\b",
    r"\borca\b",
    r"\blaptops?\b",
    r"\bdesktop\b",
    r"\bcomputers?\b",
    r"\blook(ing)? at (the|your|this|that)\b",
    r"\bwhat (do|did|can) you see\b",
    r"\byou (can |could |just )?(see|saw|observe[d]?|noticed?)\b",
    r"\bon your\b",
    # "your <up to two words> <something the student would have produced or seen>"
    r"\byour\s+(?:[\w-]+\s+){0,2}(?:outputs?|files?|structures?|drawings?|results?|numbers|energ(?:y|ies)|"
    r"runs?|data|molecules?|calculations?|tables?|values|inputs?|answer sheet|visuali[sz]ations?)\b",
    r"\bcompare\s+your\b",
    r"\b(open|click|press|select|launch) (the|your|a|an|this)\b",
    r"\brun (the|this|that|it|a|another|your)\b",
    r"\b(check|read|find|copy|note) (the|your|this) (software|output|file|energy|value|number|result)\b",
    r"\btell me what (appears|changes|you|happens)\b",
    r"\b(output|results?) (file|window|panel)\b",
    r"\bin the output\b",
    r"\bcompare (your|the) (values|structures|results|runs)\b",
    r"\bcount the\b",
    r"\bnow in the\b",
)
_COMPILED = tuple(re.compile(p, re.IGNORECASE) for p in _EXTERNAL_PATTERNS)

# Bare nouns that only *name* a program or device. Fine inside a generated
# explanation ("ORCA is a quantum-chemistry program"); not fine in an authored
# question, which keeps using the strict scan above.
_BARE_NOUN_PATTERNS = frozenset({
    r"\bscreens?\b", r"\bterminal\b", r"\bgabedit\b", r"\bavogadro\b", r"\borca\b",
    r"\blaptops?\b", r"\bdesktop\b", r"\bcomputers?\b",
})
_INSTRUCTION_COMPILED = tuple(
    re.compile(p, re.IGNORECASE) for p in _EXTERNAL_PATTERNS if p not in _BARE_NOUN_PATTERNS
)


def external_dependency(text: str) -> str | None:
    """The first external-tool phrase found in `text`, or None if it is clean."""
    for pattern in _COMPILED:
        match = pattern.search(text or "")
        if match:
            return match.group(0)
    return None


def external_instruction(text: str) -> str | None:
    """Like `external_dependency` but ignores bare mentions of a program or
    device, so a generated explanation that merely names ORCA is not gutted.
    Still catches instructions and claims about what the student saw."""
    for pattern in _INSTRUCTION_COMPILED:
        match = pattern.search(text or "")
        if match:
            return match.group(0)
    return None


def question_texts(q: ConceptQuestion) -> tuple[str, ...]:
    """Everything of a question the student can read."""
    return (q.ask, q.scaffold, q.expected_reasoning)


def is_phone_safe(q: ConceptQuestion) -> bool:
    """True only if the metadata allows it AND no wording depends on external software."""
    if q.source not in PHONE_SOURCES:
        return False
    return all(external_dependency(t) is None for t in question_texts(q))


def why_not_phone_safe(q: ConceptQuestion) -> str | None:
    """A human-readable reason, for tests and logs; None if the question is safe."""
    if q.source not in PHONE_SOURCES:
        return f"source {q.source} is not allowed in phone-only mode"
    for t in question_texts(q):
        hit = external_dependency(t)
        if hit:
            return f"mentions {hit!r}"
    return None
