"""Deterministic matching of a student's message against authored answers.

Pure functions over strings. This module must never import an LLM client:
whether an answer is right is decided here by regex and exact comparison
against a key a person wrote, and a test asserts the import stays out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.socratic_engine.walkthrough.types import Choice, Question

_MINUS = str.maketrans({"−": "-", "–": "-", "—": "-"})
_NUMBER_RE = re.compile(r"(?<![\w.])[-+]?(?:\d+(?:[.,]\d+)*|\.\d+)(?:[eE][-+]?\d+)?")

_CONFIRM_WORDS = {
    "done", "ok", "okay", "okk", "okkk", "k", "kk", "yes", "yep", "yeah", "yup", "ya",
    "finished", "completed", "complete", "did", "sure", "fine", "next",
    "continue", "go", "on", "got", "it", "haan", "ha", "hogaya", "ho", "gaya", "thik",
    "theek", "hai", "ready", "cool", "great", "nice", "alright", "right", "correct",
    "understood", "i", "its", "it's", "all",
}

_WANTS_ANSWER_RE = re.compile(
    r"\b(just tell me|tell me the answer|give me the answer|show me the answer|"
    r"what.s the answer|reveal|i give up|i don.?t know|no idea|idk|skip (the )?(question|hook)|"
    r"just (give|show) me)\b",
    re.IGNORECASE,
)
_SKIP_RE = re.compile(r"^\s*(skip|skip this|skip step|skip it|move on|next step)\s*[.!]*\s*$", re.IGNORECASE)
_BACK_RE = re.compile(
    r"^\s*(back|go back|previous( step)?|last step|repeat|repeat (that|the step)|"
    r"say that again|again)\s*[.!]*\s*$",
    re.IGNORECASE,
)
_STOP_RE = re.compile(
    r"\b(stop (the )?(guide|guidance|walkthrough|steps)|exit (the )?(guide|walkthrough)|"
    r"end (the )?(guide|walkthrough)|pause( the)? (guide|walkthrough)|quit (the )?(guide|walkthrough))\b",
    re.IGNORECASE,
)
_RESUME_RE = re.compile(
    r"\b(resume|continue (the )?(guide|walkthrough|steps)|carry on|where (was|were) i|"
    r"back to (the )?(guide|walkthrough|steps))\b",
    re.IGNORECASE,
)
_RESTART_RE = re.compile(
    r"\b(start (over|again|from the (top|beginning))|restart|begin again|from scratch)\b",
    re.IGNORECASE,
)
_SKIP_QUIZ_RE = re.compile(r"\b(skip (the )?(quiz|checkpoint)|no quiz|not now)\b", re.IGNORECASE)
_PROBLEM_RE = re.compile(
    r"\b(error|errors|not working|doesn.?t work|does not work|can.?t find|cannot find|"
    r"can.?t see|cannot see|couldn.?t|unable|won.?t (open|run|start|load)|"
    r"not (opening|loading|running|showing|coming)|failed|crash(ed)?|stuck|"
    r"nothing (happens|happened|shows|showed)|missing|greyed|grayed|different)\b",
    re.IGNORECASE,
)
_QUESTION_START_RE = re.compile(
    r"^\s*(what|why|how|when|where|which|who|can|could|should|is|are|does|do|will|explain|"
    r"tell me (about|what|why|how)|kya|kyu|kyun|kaise|kaun)\b",
    re.IGNORECASE,
)
_START_RE = re.compile(
    r"\b(how (do|can|should|would) (i|we)\b|how to\b|steps? (to|for)|procedure|"
    r"walk me|guide me|guidance|help me|where do i start|let.?s (start|begin)|"
    r"start the (experiment|lab)|explain the (experiment|procedure)|"
    r"what do i (do|need to do)|what should i do)",
    re.IGNORECASE,
)


def normalise(text: str) -> str:
    text = (text or "").translate(_MINUS).lower()
    text = re.sub(r"[`*_#>]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", normalise(text))


def is_bare_confirmation(text: str) -> bool:
    """True for "ok", "done done", "yes" -- a message that claims progress
    but carries no fact. Never advances a step that asks for evidence."""
    toks = _tokens(text)
    if not toks or len(toks) > 5:
        return False
    return all(t in _CONFIRM_WORDS for t in toks)


def wants_answer(text: str) -> bool:
    return bool(_WANTS_ANSWER_RE.search(text or ""))


def is_skip(text: str) -> bool:
    return bool(_SKIP_RE.match(text or ""))


def is_back(text: str) -> bool:
    return bool(_BACK_RE.match(text or ""))


def is_stop(text: str) -> bool:
    return bool(_STOP_RE.search(text or ""))


def is_resume(text: str) -> bool:
    return bool(_RESUME_RE.search(text or ""))


def is_restart(text: str) -> bool:
    return bool(_RESTART_RE.search(text or ""))


def is_skip_quiz(text: str) -> bool:
    return bool(_SKIP_QUIZ_RE.search(text or ""))


def is_problem(text: str) -> bool:
    return bool(_PROBLEM_RE.search(text or ""))


def is_question(text: str) -> bool:
    text = (text or "").strip()
    return text.endswith("?") or bool(_QUESTION_START_RE.match(text))


_WH_START_RE = re.compile(
    r"^\s*(what|why|how|when|where|which|who|can|could|should|is|are|does|do|will|explain|"
    r"tell me (about|what|why|how)|kya|kyu|kyun|kaise|kaun)\b",
    re.IGNORECASE,
)


def is_side_question(text: str) -> bool:
    """A real question, as opposed to a short answer that happens to end in
    "?" ("tetrahedral?"). Only these are handed to the grounded Q&A path."""
    text = (text or "").strip()
    if _WH_START_RE.match(text):
        return True
    return "?" in text and len(_tokens(text)) >= 6


_RESUME_PHRASES_RE = re.compile(
    r"\b(next step|what now|what next|where was i|where do i start|guide me|what should i do|"
    r"what do i do( now| next)?|how do i (start|begin|proceed|do this)|continue)\b",
    re.IGNORECASE,
)


def is_resume_phrase(text: str) -> bool:
    """A "where am I" style message: show the current step again rather than
    treat it as an answer or a new question."""
    return bool(_RESUME_PHRASES_RE.search(text or "")) and len(_tokens(text)) <= 6


def is_start_request(text: str) -> bool:
    """A how-to or guidance prompt: the walkthrough opens with a curiosity
    question instead of a wall of procedure."""
    return bool(_START_RE.search(text or ""))


def extract_numbers(text: str) -> list[float]:
    out: list[float] = []
    for match in _NUMBER_RE.findall((text or "").translate(_MINUS)):
        raw = match.replace(",", "") if re.search(r",\d{3}\b", match) else match.replace(",", ".")
        try:
            out.append(float(raw))
        except ValueError:
            continue
    return out


_CHOICE_LEAD_RE = re.compile(
    r"^\s*(?:option|answer|ans|choice)?\s*[\(\[]?([a-d])([\)\]\.:\-])?(?:\s+|$)", re.IGNORECASE
)


def parse_choice(text: str, choices: tuple[Choice, ...]) -> str | None:
    """Map a message to an option key: a leading letter ("b", "B. ...",
    "option c") or the option's own text. None if it is neither."""
    raw = (text or "").strip()
    if not raw or not choices:
        return None
    keys = {c.key.lower() for c in choices}
    lead = _CHOICE_LEAD_RE.match(raw)
    if lead and lead.group(1).lower() in keys:
        # A lone letter, or a letter with punctuation ("B. Restricted ...");
        # not a sentence that happens to begin with the word "a".
        if lead.group(2) or len(_tokens(raw)) <= 2:
            return lead.group(1).lower()
    norm = normalise(raw)
    for c in choices:
        opt = normalise(c.text)
        if opt and (norm == opt or (len(norm) >= 12 and (opt in norm or norm in opt))):
            return c.key.lower()
    return None


@dataclass(frozen=True)
class Verdict:
    correct: bool
    chosen: str | None = None
    values: tuple[float, ...] = ()
    # False when the message did not even attempt an answer (a bare "ok").
    attempted: bool = True


def grade(question: Question, text: str) -> Verdict:
    if question.kind == "mcq":
        chosen = parse_choice(text, question.choices)
        if chosen is None:
            return Verdict(correct=False, chosen=None, attempted=False)
        return Verdict(correct=chosen == question.correct.lower(), chosen=chosen)

    if question.kind == "number":
        nums = extract_numbers(text)
        if not nums:
            return Verdict(correct=False, attempted=False)
        ok = any(abs(n - want) <= question.tol for n in nums for want in question.numbers)
        return Verdict(correct=ok, values=tuple(nums))

    if question.kind == "report":
        nums = extract_numbers(text)
        if not nums:
            return Verdict(correct=False, attempted=False)
        return Verdict(correct=True, values=tuple(nums))

    norm = normalise(text)
    if is_bare_confirmation(text) or not norm:
        return Verdict(correct=False, attempted=False)
    hits = sum(1 for group in question.groups if any(re.search(p, norm) for p in group))
    return Verdict(correct=hits >= max(1, question.need), attempted=True)
