"""Answer-gate implementation. See the package docstring for the design."""

from __future__ import annotations

import dataclasses
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

#: The exact field set `SocraticLLMInput` is allowed to have. Adding a
#: field here without reading the package docstring is how this guarantee
#: would get quietly broken, so the set is asserted in the test suite.
ALLOWED_SOCRATIC_FIELDS: frozenset[str] = frozenset(
    {
        "student_message",
        "step_prompt",
        "step_index",
        "total_steps",
        "hint_text",
        "manual_excerpt",
        "attempts_on_this_step",
        "conversation_history",
    }
)

#: Field names that must never appear on a Socratic prompt object.
FORBIDDEN_FIELD_HINTS: tuple[str, ...] = (
    "answer",
    "expected",
    "final",
    "solution",
    "correct_value",
    "true_value",
    "key",
)

_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


class PrematureRevealError(RuntimeError):
    """Raised on any attempt to reveal before step verification completes.

    This is a programming error, not a user-facing condition: the gate is
    the only thing that can construct a reveal, and it refuses.
    """


@dataclass(frozen=True, slots=True)
class SocraticLLMInput:
    """The complete set of things a Socratic prompt may contain.

    There is no answer field. There is no room for one: `slots=True` and
    `frozen=True` mean an answer cannot be attached to an instance later
    either.
    """

    student_message: str
    step_prompt: str
    step_index: int
    total_steps: int
    hint_text: str = ""
    manual_excerpt: str = ""
    attempts_on_this_step: int = 0
    #: Prior turns of this same chat thread, plain text, context only. It
    #: can never carry the final answer because nothing upstream of this
    #: object ever computes one to put here (see property 1 in the
    #: package docstring) -- it is exactly the same class of text as
    #: `student_message`, just from earlier turns.
    conversation_history: str = ""

    def as_prompt_fields(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class GateDecision:
    """What the gate did to an outbound message."""

    text: str
    redacted: bool = False
    redacted_tokens: tuple[str, ...] = ()
    reason: str = ""


def assert_gate_invariant() -> None:
    """Fail loudly if the prompt object has grown a way to carry the answer.

    Called at application startup as well as from the test suite, so a
    regression cannot reach production quietly.
    """
    actual = {f.name for f in dataclasses.fields(SocraticLLMInput)}
    if actual != set(ALLOWED_SOCRATIC_FIELDS):
        added = actual - ALLOWED_SOCRATIC_FIELDS
        removed = set(ALLOWED_SOCRATIC_FIELDS) - actual
        raise AssertionError(
            "SocraticLLMInput field set changed -- the answer-gate guarantee "
            f"depends on it. Added: {sorted(added)}. Removed: {sorted(removed)}. "
            "Read backend/answer_gate/__init__.py before changing this."
        )
    for name in actual:
        lowered = name.lower()
        for bad in FORBIDDEN_FIELD_HINTS:
            if bad in lowered:
                raise AssertionError(
                    f"SocraticLLMInput field '{name}' looks like it carries the "
                    "answer into prompt context, which the gate forbids."
                )


def prepare_socratic_input(
    *,
    student_message: str,
    step_prompt: str,
    step_index: int,
    total_steps: int,
    hint_text: str = "",
    manual_excerpt: str = "",
    attempts_on_this_step: int = 0,
    conversation_history: str = "",
) -> SocraticLLMInput:
    """Build the only object permitted into a Socratic LLM prompt.

    Callers cannot pass an answer through here because there is no
    parameter for one. Anything a caller wants the model to see must be
    added to `ALLOWED_SOCRATIC_FIELDS` deliberately.
    """
    assert_gate_invariant()
    return SocraticLLMInput(
        student_message=student_message,
        step_prompt=step_prompt,
        step_index=step_index,
        total_steps=total_steps,
        hint_text=hint_text,
        manual_excerpt=manual_excerpt,
        attempts_on_this_step=attempts_on_this_step,
        conversation_history=conversation_history,
    )


def may_reveal(*, all_steps_complete: bool) -> bool:
    """Whether a reveal is permitted.

    The only input is the server-side step-verification flag, set by Tier 1
    math in `socratic_engine`. Nothing a student says can change it, and no
    LLM output is consulted.
    """
    return bool(all_steps_complete)


def build_reveal(
    *,
    all_steps_complete: bool,
    computed_value: float,
    label: str = "",
    units: str = "",
    student_value: float | None = None,
    tolerance_description: str = "",
) -> str:
    """The separate, non-LLM reveal path.

    A plain template filled from the Tier-1-computed value. No model is
    called here and no model output reaches this string, which is why the
    reveal cannot be talked into happening early -- the only way to reach
    this function is with the verification flag already set.
    """
    if not may_reveal(all_steps_complete=all_steps_complete):
        raise PrematureRevealError(
            "Refusing to build a reveal: server-side step verification has not "
            "confirmed every step is complete."
        )

    name = label or "the final result"
    unit_suffix = f" {units}" if units else ""
    lines = [
        f"Every step is verified, so here is {name} computed from your own data: "
        f"{computed_value:g}{unit_suffix}."
    ]
    if student_value is not None:
        lines.append(
            f"You derived {student_value:g}{unit_suffix}."
        )
        if tolerance_description:
            lines.append(f"Agreement was assessed at {tolerance_description}.")
    return " ".join(lines)


#: Longest student-facing message the gate will emit. A model talked into
#: producing a wall of text should not become a wall of text on a phone in
#: a lab.
MAX_OUTBOUND_CHARS = 8000


def sanitise_outbound(text: str) -> str:
    """Strip anything that should never reach a student's screen.

    Control characters and direction overrides can come back out of a
    model that was fed them, and would render as invisible or
    right-to-left text in the UI. Applied to every outbound message
    regardless of mode.
    """
    if not text:
        return ""
    cleaned = "".join(
        ch for ch in text if ch in "\n\t" or not unicodedata.category(ch).startswith("C")
    )
    cleaned = cleaned.replace("‮", "").replace("‭", "")
    if len(cleaned) > MAX_OUTBOUND_CHARS:
        cleaned = cleaned[:MAX_OUTBOUND_CHARS].rstrip() + " […]"
    return cleaned.strip()


def filter_outbound(
    text: str,
    *,
    mode: str,
    all_steps_complete: bool = False,
    permitted_sources: tuple[str, ...] = (),
) -> GateDecision:
    """The single entry point every student-facing message passes through.

    Two modes, because the two have genuinely different disclosure rules:

    ``socratic``
        The student is mid-experiment. Numbers they have not already seen
        are stripped (`scrub_outbound`), because the whole point is that
        they derive the value themselves.

    ``diagnostic``
        The student has finished and submitted. The recomputed value is
        theirs to see -- withholding it here would defeat the purpose --
        so numbers are left alone and only sanitisation applies.

    Routing both through one function is what makes "every outbound
    response passes through the gate" a fact about the code rather than a
    claim about intent.
    """
    if mode not in ("socratic", "diagnostic"):
        raise ValueError(f"unknown gate mode: {mode!r}")

    cleaned = sanitise_outbound(text)

    if mode == "diagnostic":
        return GateDecision(text=cleaned, reason="diagnostic_disclosure_permitted")

    return scrub_outbound(
        cleaned,
        all_steps_complete=all_steps_complete,
        permitted_sources=permitted_sources,
    )


def scrub_outbound(
    text: str,
    *,
    all_steps_complete: bool,
    permitted_sources: tuple[str, ...] = (),
    redaction: str = "[a number has been withheld]",
) -> GateDecision:
    """Final filter on model-produced text headed for a student.

    While a session is incomplete, a hint may restate numbers the student
    or the manual step already put on the table, but it may not introduce
    a new one. A hint that needs a number the student has not seen is
    giving away the answer, whatever it claims to be doing.

    Once the session is complete this is a no-op: the reveal path is
    authoritative from that point, and it does not go through a model.
    """
    if all_steps_complete:
        return GateDecision(text=text, reason="session_complete")

    permitted: set[str] = set()
    for source in permitted_sources:
        permitted.update(_normalise(m) for m in _NUMBER_RE.findall(source or ""))

    removed: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if _normalise(token) in permitted:
            return token
        # Small integers are step numbers, counts and ordinals in ordinary
        # prose ("step 2 of 5"), not answers.
        if _is_structural_number(token):
            return token
        removed.append(token)
        return redaction

    scrubbed = _NUMBER_RE.sub(_replace, text)
    return GateDecision(
        text=scrubbed,
        redacted=bool(removed),
        redacted_tokens=tuple(removed),
        reason="novel_number_in_hint" if removed else "clean",
    )


def _normalise(token: str) -> str:
    try:
        return f"{float(token):.10g}"
    except ValueError:
        return token


def _is_structural_number(token: str) -> bool:
    """Small non-negative integers used for navigation, not measurement."""
    try:
        value = float(token)
    except ValueError:
        return False
    return value.is_integer() and 0 <= value <= 20 and "." not in token
