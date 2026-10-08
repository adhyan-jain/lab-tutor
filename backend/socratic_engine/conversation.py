"""Conversation-level intent and mode for one chat thread.

Two things live here, both pure and deterministic (no model, no DB):

1. `classify` -- what the student wants *right now*, independent of which
   step they are on. The step a student is on never outranks what they say:
   "I don't want to draw, I want the theory" is a mode switch, not a wrong
   answer to the drawing step, and "it's not working" is a problem report,
   not a completion. Patterns are built from small families (a negation, a
   want-verb, a theory noun...) rather than a list of exact sentences, so
   paraphrases land in the same intent.

2. `ConversationState` -- the thread's mode (initial / theory / practice)
   plus the context needed to come back from a detour. It is stored as
   JSON on `ChatThread.state`, so it is scoped to exactly one thread: a new
   chat starts in `initial` and never sees another thread's step.

   The practical workflow's own position (step, tries, facts) stays where
   it already lived -- the walkthrough row or the Socratic session -- now
   linked to this thread. This file only decides which of theory or
   practice is in charge of the next turn.

Action chips are produced here too (`actions`), with one rule enforced for
every caller: a response never offers the action that produced it, never
offers an action already used on the same question, and never offers the
same action twice.
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable

log = logging.getLogger("labtutor.conversation")


class Intent(str, Enum):
    ANSWER = "answer"  # an attempt at whatever was asked; the caller grades it
    STEP_SKIPPED = "step_skipped"
    STEP_REFUSED = "step_refused"
    SWITCH_TO_THEORY = "switch_to_theory"
    SWITCH_TO_PRACTICE = "switch_to_practice"
    GUIDED_CONCEPTS = "guided_concepts"  # "guide me through the key ideas" (phone-only Exp7)
    USER_REQUESTED_HINT = "user_requested_hint"
    USER_REQUESTED_EXPLANATION = "user_requested_explanation"
    TROUBLESHOOTING = "troubleshooting"
    PROBLEM_RESOLVED = "problem_resolved"
    USER_QUESTION = "user_question"


class Mode(str, Enum):
    INITIAL = "initial"
    THEORY = "theory"
    PRACTICE = "practice"


# --------------------------------------------------------------- patterns

_NEG = r"(?:don.?t|do not|dont|won.?t|will not|not going to|rather not|no longer|can.?t be bothered to)"
_WANT = r"(?:want|wanna|would like|.d like|like|prefer|rather|need|feel like|wish)"

_THEORY_NOUN = r"(?:theory|theoretical|theoretically|concepts?|conceptual|principles?|the science|background|study|learn(?:ing)?)"
_THEORY_RE = re.compile(
    rf"\b{_WANT}\b[^.?!]{{0,30}}\b{_THEORY_NOUN}\b"
    rf"|\b(?:switch|go|move|take me|let.?s go|back)\s+(?:to\s+)?(?:the\s+)?{_THEORY_NOUN}\b"
    rf"|\b(?:let.?s|can we|could we|shall we|i.?ll|i will|instead)\b[^.?!]{{0,20}}\b(?:study|learn)\b"
    rf"|\b(?:just|only)\s+(?:the\s+)?{_THEORY_NOUN}\b"
    rf"|\b{_THEORY_NOUN}\s+(?:instead|mode|first)\b"
    rf"|^\s*(?:theory|study|theory\s*/\s*study|study theory|theory please|learn)\s*[.!]*\s*$",
    re.IGNORECASE,
)

# Leaving a procedure, in the ways people actually say it. All of these are
# switches to theory; a message that ALSO contains a real question ("forget the
# steps, explain why optimisation works") is answered, not just acknowledged
# (see `theory.has_substance`).
_EXIT_VERB = r"(?:forget|ignore|drop|stop|leave|exit|quit|cancel|bypass)"
_PROC_NOUN = r"(?:steps?|procedures?|walk-?through|instructions?|practical|lab)"
# "skip" is special: "skip this step" skips ONE step (STEP_SKIPPED), while
# "skip the steps" / "skip the procedure" leaves the procedure.
_SKIP_PROC_NOUN = r"(?:steps|procedures?|walk-?through|instructions?|practical|lab)"
_EXIT_RE = re.compile(
    rf"\b{_EXIT_VERB}\s+(?:all\s+)?(?:about\s+)?(?:the\s+|these\s+|those\s+|this\s+|that\s+|any\s+)?{_PROC_NOUN}\b"
    rf"|\bskip\s+(?:all\s+)?(?:the\s+|these\s+|those\s+)?{_SKIP_PROC_NOUN}\b"
    rf"|\b(?:don.?t|do not|dont|no)\s+(?:want|need|wish)\s+(?:to\s+(?:do|follow|see)\s+)?(?:the\s+|any\s+|a\s+)?{_PROC_NOUN}\b"
    r"|\b(?:explain|teach|tell me|show me|help me understand|just explain)\b[^.?!]{0,30}\b(?:the\s+)?"
    r"(?:theory|concepts?|chemistry|science|ideas?|principles?)\b"
    r"|\bwhy\s+does\s+(?:this|it|that)\s+work\b",
    re.IGNORECASE,
)

_GUIDED_RE = re.compile(
    r"\b(?:guide|walk|take)\s+me\s+through\s+(?:the\s+)?(?:key\s+|main\s+)?(?:ideas|concepts)\b"
    r"|\b(?:quiz|test)\s+me\b|\btest\s+my\s+understanding\b",
    re.IGNORECASE,
)

# A STRICT request for the practical procedure. Deliberately narrow: a how-to
# that is really about an idea ("how do we choose a basis set?", "how do I
# interpret the HOMO?") is a theory question, and "help me" or "procedure"
# alone are not requests to be walked through anything.
_PROCEDURE_RE = re.compile(
    r"\b(?:walk|guide|take)\s+me\s+through\s+(?:the\s+|this\s+)?(?:procedure|experiment|lab|practical|steps?|workflow|process)\b"
    r"|\bhow\s+(?:do|can|should|would|could)\s+(?:i|we)\s+(?:actually\s+|really\s+|even\s+)?"
    r"(?:perform|conduct|carry\s+out|do|run|complete|execute|start|begin|set\s+up|use)\b[^.?!]{0,50}?"
    r"\b(?:experiment|practical|lab|exp(?:eriment)?\s*\d*|procedure|orca|gabedit|avogadro)\b"
    r"|\b(?:what\s+are|what\s+is|what.?s|give\s+me|show\s+me|tell\s+me|list|explain|describe|outline)\s+(?:me\s+)?"
    r"(?:all\s+)?(?:the\s+)?(?:practical\s+|lab\s+|experimental\s+)?(?:steps?|procedure|workflow)\b"
    r"|\bwhere\s+do\s+i\s+start\b"
    r"|\blet.?s\s+(?:start|begin|do)\s+(?:the\s+)?(?:experiment|lab|practical|procedure)\b"
    r"|\bstart\s+the\s+(?:experiment|lab|practical)\b"
    r"|\b(?:i\s+)?(?:want|need|would like|.d like)\s+to\s+(?:do|perform|run|start|conduct)\s+(?:the\s+|this\s+)?(?:experiment|lab|practical)\b",
    re.IGNORECASE,
)


def is_procedure_request(text: str) -> bool:
    """True only when the student explicitly asks how the practical is
    performed or to be walked through it. Theory questions are not."""
    return bool(_PROCEDURE_RE.search(text or "")) and not _EXIT_RE.search(text or "")


def exit_spans(text: str) -> list[str]:
    """The phrases in `text` that switch to theory (for stripping them to see
    whether a real question remains)."""
    spans = [m.group(0) for m in _EXIT_RE.finditer(text or "")]
    spans += [m.group(0) for m in _THEORY_RE.finditer(text or "")]
    return spans


_PRACTICE_NOUN = r"(?:experiment|practical|practice|lab|procedure|walkthrough|guide|steps?|hands.on)"
_PRACTICE_RE = re.compile(
    rf"\b(?:back to|return to|resume|continue(?: with)?|go on with|start|begin|do|get to|carry on with|switch to)\s+"
    rf"(?:the\s+|my\s+|with the\s+)?{_PRACTICE_NOUN}\b"
    rf"|\b{_WANT}\b[^.?!]{{0,25}}\b(?:do|perform|run|start)\s+(?:the\s+)?{_PRACTICE_NOUN}\b"
    rf"|\blet.?s\s+(?:do|start|begin|continue)\s+(?:the\s+)?{_PRACTICE_NOUN}\b"
    rf"|^\s*(?:practical|practice|experiment|practical\s*/\s*experiment|lab)\s*[.!]*\s*$",
    re.IGNORECASE,
)

_REFUSE_RE = re.compile(
    rf"\b(?:i\s+)?{_NEG}\s+(?:{_WANT}\s+)?(?:to\s+)?(?:do|draw|build|make|run|open|use|install|follow|continue|this|that|it)\b"
    rf"|\b(?:i\s+)?{_NEG}\s+{_WANT}\b"
    r"|\b(?:no thanks|not this (?:step|one)|not interested|i refuse|nope)\b",
    re.IGNORECASE,
)

_SKIP_RE = re.compile(
    r"^\s*(?:please\s+)?(?:skip|skip (?:this|it|that|this step|the step|step)|move on|next step|pass)(?:\s+please)?\s*[.!]*\s*$",
    re.IGNORECASE,
)

_HINT_RE = re.compile(r"\b(?:hint|clue|nudge)\b", re.IGNORECASE)

_EXPLAIN_RE = re.compile(
    r"\bwhy\s+(?:do|should|must|would|are|am|is)\s+(?:i|we)\s+(?:need\s+to\s+|have\s+to\s+|supposed\s+to\s+)?(?:do(?:ing)?|follow|perform)\s+(?:this|that|it)\b"
    r"|\bwhy\s+(?:do|should|must)\s+(?:i|we)\s+need\s+(?:this|that|it)\b"
    r"|\bwhy\s+(?:this|that)\s+step\b|\bwhy\s+do\s+this(?:\s+step)?\b|\bwhy\s+(?:is\s+)?this\s+(?:step\s+)?(?:needed|necessary|important)\b"
    r"|\b(?:point|purpose|reason)\s+(?:of|for|behind)\s+(?:this|that|the)\s+step\b"
    r"|\b(?:don.?t|do not|dont)\s+(?:understand|get)\s+(?:this|that|the|what)(?:\s+(?:step|part|instruction|means))?\b",
    re.IGNORECASE,
)

_MISSING_UI_RE = re.compile(
    r"\b(?:i\s+)?(?:don.?t|do not|dont|can.?t|cannot)\s+(?:have|see|find|get)\b"
    r"|\b(?:isn.?t|is not|aren.?t|are not|not)\s+(?:there|showing|visible|appearing|available|present)\b"
    r"|\bno\s+(?:such\s+)?(?:option|button|menu|tab|window|field|item)\b"
    r"|\b(?:missing|greyed|grayed|disabled)\b",
    re.IGNORECASE,
)

_TROUBLE_RE = re.compile(
    r"\b(?:error|errors|not working|doesn.?t work|does not work|didn.?t work|isn.?t working|won.?t work|"
    r"broken|bug|crash(?:ed|es)?|failed|fails|stuck|frozen|freez(?:e|es|ing)|hang(?:s|ing)?|"
    r"(?:won.?t|doesn.?t|does not|didn.?t|did not|isn.?t|is not|can.?t|cannot) (?:open|run|start|load|show|appear|respond|save)|"
    r"not (?:opening|loading|running|showing|coming|responding|appearing|saving)|"
    r"nothing (?:happens|happened|shows|showed)|"
    r"look(?:s|ing)? (?:different|wrong|weird|off|strange)|something.{0,12}(?:different|wrong|off)|"
    r"(?:i\s+)?can.?t do (?:this|it|that)|(?:i\s+)?(?:can.?t|cannot|unable to) (?:get|make) it)\b",
    re.IGNORECASE,
)

_RESOLVED_RE = re.compile(
    r"\b(?:it works now|works now|working now|fixed( it)?|solved|resolved|found it|got it working|"
    r"it.?s (?:there|showing) now|never ?mind|nvm)\b",
    re.IGNORECASE,
)

_QUESTION_START_RE = re.compile(
    r"^\s*(?:what|why|how|when|where|which|who|can|could|should|is|are|does|do|will|explain|"
    r"tell me (?:about|what|why|how)|kya|kyu|kyun|kaise|kaun)\b",
    re.IGNORECASE,
)


_NEGATIVE_RE = re.compile(
    r"\b(?:no|not|nothing|none|nope|still|never|neither|nah)\b|n.?t\b", re.IGNORECASE
)


def is_negative(text: str) -> bool:
    """"still nothing", "hmm no": a report that the problem persists."""
    return bool(_NEGATIVE_RE.search(text or ""))


def is_missing_ui(text: str) -> bool:
    """"I don't have that option", "the button isn't there": the student is
    telling us what is NOT on their screen. The reply must not insist it is."""
    return bool(_MISSING_UI_RE.search(text or ""))


def classify(text: str) -> Intent:
    """One intent per message, most specific first. A message that names a
    destination ("...I want to study theory") is a switch even when it also
    refuses; a bare refusal is STEP_REFUSED, which never means "done"."""
    t = (text or "").strip()
    if not t:
        return Intent.ANSWER
    if _GUIDED_RE.search(t):
        return Intent.GUIDED_CONCEPTS
    if _THEORY_RE.search(t) or _EXIT_RE.search(t):
        return Intent.SWITCH_TO_THEORY
    if _PRACTICE_RE.search(t) and not _REFUSE_RE.search(t):
        return Intent.SWITCH_TO_PRACTICE
    if _RESOLVED_RE.search(t):
        return Intent.PROBLEM_RESOLVED
    if _HINT_RE.search(t):
        return Intent.USER_REQUESTED_HINT
    if _EXPLAIN_RE.search(t):
        return Intent.USER_REQUESTED_EXPLANATION
    if _TROUBLE_RE.search(t) or is_missing_ui(t):
        return Intent.TROUBLESHOOTING
    if _SKIP_RE.match(t):
        return Intent.STEP_SKIPPED
    if _REFUSE_RE.search(t):
        return Intent.STEP_REFUSED
    if _QUESTION_START_RE.match(t) or ("?" in t and len(t.split()) >= 6):
        return Intent.USER_QUESTION
    return Intent.ANSWER


# ---------------------------------------------------------------- actions

#: Every chip the tutor can offer: id -> the text it sends when tapped.
#: The text is what `classify` maps back to the same id, so a tapped chip
#: and the same words typed by hand behave identically.
ACTIONS: dict[str, str] = {
    "theory": "Theory / Study",
    "practice": "Practical / Experiment",
    "hint": "Give me a hint",
    "why": "Why do this step?",
    "different": "Something looks different",
    "study_theory": "Study theory",
    "continue": "Continue",
    "back_to_step": "Back to step",
    "skip": "Skip this step",
    "back_to_experiment": "Back to the experiment",
    "just_tell": "Just tell me",
    "skip_quiz": "Skip quiz",
    "guide_concepts": "Guide me through the key ideas",
    "explain_theory": "Explain the theory instead",
    "skip_concept": "Skip this question",
    "resume": "Resume",
    "resume_previous": "Resume previous session",
}

#: Which intent each action expresses. Two actions with the same intent are
#: the same action for the non-recursion rule ("Study theory" and
#: "Theory / Study" both switch to theory).
ACTION_INTENT: dict[str, Intent] = {
    "theory": Intent.SWITCH_TO_THEORY,
    "study_theory": Intent.SWITCH_TO_THEORY,
    "practice": Intent.SWITCH_TO_PRACTICE,
    "guide_concepts": Intent.GUIDED_CONCEPTS,
    "explain_theory": Intent.SWITCH_TO_THEORY,
    "back_to_experiment": Intent.SWITCH_TO_PRACTICE,
    "hint": Intent.USER_REQUESTED_HINT,
    "why": Intent.USER_REQUESTED_EXPLANATION,
    "different": Intent.TROUBLESHOOTING,
    "skip": Intent.STEP_SKIPPED,
}


def action_for_intent(intent: Intent) -> str | None:
    """The action id a message with this intent stands for (None for an
    answer or a free question -- those are not actions)."""
    for action_id, action_intent in ACTION_INTENT.items():
        if action_intent is intent:
            return action_id
    return None


# Chip display text (lowercased) → forced intent. A tapped chip sends its
# display text verbatim; this lookup is more reliable than classify() for
# short strings like "Continue" that have no practice noun to anchor to.
_CHIP_FORCED_INTENTS: dict[str, Intent] = {
    text.lower(): ACTION_INTENT[aid]
    for aid, text in ACTIONS.items()
    if aid in ACTION_INTENT
}
# "Continue" and "Back to step" are resume chips; classify("Continue")
# returns ANSWER (no practice noun follows), so we force it explicitly.
_CHIP_FORCED_INTENTS["continue"] = Intent.SWITCH_TO_PRACTICE
_CHIP_FORCED_INTENTS["back to step"] = Intent.SWITCH_TO_PRACTICE


def intent_for_chip_text(text: str) -> Intent | None:
    """If *text* is the exact display string of a known chip, return its
    forced intent.  Returns None for free-form messages so classify() runs."""
    return _CHIP_FORCED_INTENTS.get((text or "").strip().lower())


def actions(
    candidates: Iterable[str],
    *,
    source: str | None = None,
    consumed: Iterable[str] = (),
) -> tuple[list[str], dict[str, Any]]:
    """Filter a candidate chip list by the non-recursion rule and return
    (chip texts, action_context). Never returns the source action, anything
    with the same intent as the source, anything already consumed on this
    question, or a duplicate."""
    consumed_set = set(consumed)
    blocked_intents = {ACTION_INTENT[a] for a in consumed_set | ({source} if source else set()) if a in ACTION_INTENT}
    out: list[str] = []
    suppressed: list[str] = []
    seen: set[str] = set()
    for action_id in candidates:
        intent = ACTION_INTENT.get(action_id)
        if (
            action_id in seen
            or action_id == source
            or action_id in consumed_set
            or (intent is not None and intent in blocked_intents)
        ):
            if action_id not in suppressed:
                suppressed.append(action_id)
            continue
        seen.add(action_id)
        out.append(action_id)
    context = {"source_action": source, "depth": 1 if source else 0, "suppressed": suppressed}
    if source:
        log.debug("[UI ACTION] source=%s depth=1 suppressed=%s", source, suppressed)
    return [ACTIONS[a] for a in out], context


# ------------------------------------------------------------------ state


@dataclass
class ConversationState:
    mode: str = Mode.INITIAL.value
    previous_mode: str | None = None
    #: What the theory side is about, when known (a step title on a
    #: practice -> theory switch). Used to expand a bare "explain this".
    topic: str | None = None
    #: Where practice was when the student left it, for the way back.
    previous_step: str | None = None
    last_intent: str | None = None
    #: Consecutive turns the tutor had to ask "what would you like?";
    #: the second one is phrased differently instead of repeating the menu.
    clarify_count: int = 0
    #: The legacy Socratic session this thread started, if any. Lookups go
    #: through this id only, so another thread's session is never resumed.
    socratic_session_id: str | None = None
    #: Theory-mode concept understanding for THIS thread (pedagogy.state
    #: ConceptStates as a dict) and the one short Socratic question currently
    #: awaiting the student's answer. Thread-local like everything else here:
    #: a new chat starts with neither.
    concepts: dict[str, Any] = field(default_factory=dict)
    pending: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ConversationState":
        base = cls()
        for key, value in (data or {}).items():
            if hasattr(base, key):
                # copy: the dict comes straight from the DB column and this
                # state mutates its own copies in place (see WalkState.from_dict)
                setattr(base, key, copy.deepcopy(value) if isinstance(value, (dict, list)) else value)
        if base.mode not in {m.value for m in Mode}:
            base.mode = Mode.INITIAL.value
        return base

    def switch(self, mode: Mode, reason: str, *, topic: str | None = None, step: str | None = None) -> None:
        """The one place a thread's mode changes, so every transition is
        logged the same way."""
        before = f"{self.mode.upper()}(step={self.previous_step or '-'})"
        if mode.value != self.mode:
            self.previous_mode = self.mode
        self.mode = mode.value
        if topic is not None:
            self.topic = topic
        if step is not None:
            self.previous_step = step
        self.clarify_count = 0
        log.info("[STATE] %s -> %s(topic=%s) reason=%s", before, mode.value.upper(), self.topic or "-", reason)


GREETING = "Hi! What would you like to do today?"
GREETING_DETAIL = (
    "**Theory / Study**: understand the concepts behind this experiment.\n"
    "**Practical / Experiment**: work through the experiment itself, one step at a time."
)


def greeting_ui() -> dict[str, Any]:
    chips, ctx = actions(["theory", "practice"])
    return {"kind": "greeting", "chips": chips, "action_context": ctx, "mode": Mode.INITIAL.value}


GREETING_DETAIL_CONCEPTUAL = (
    "**Theory / Study**: understand the concepts behind this experiment.\n"
    "**Practical / Experiment**: reason through the key ideas of the experiment, one short question at a time."
)


def greeting_text(experiment_title: str = "", *, conceptual: bool = False) -> str:
    head = GREETING if not experiment_title else f"{GREETING} We're on **{experiment_title}**."
    return f"{head}\n\n{GREETING_DETAIL_CONCEPTUAL if conceptual else GREETING_DETAIL}"


# "can you help me?" on its own is an opener, not a question. Answering it with
# a flat "Yes" reads cold; a student should hear a friend say "of course, I'm
# right here". Authored text chosen by code, never a model call.
_HELP_OPENER = re.compile(
    r"^\W*(?:hey\W+|hi\W+|hello\W+)?(?:please\W+)?"
    r"(?:can|could|will|would)\s+(?:you|u)\s+(?:please\s+)?help(?:\s+me)?(?:\s+out)?"
    r"(?:\s+(?:please|pls|plz))?\W*$"
    r"|^\W*(?:i\s+)?need\s+(?:some\s+)?help(?:\s+please)?\W*$"
    r"|^\W*help(?:\s+me)?(?:\s+(?:please|pls|plz))?\W*$",
    re.IGNORECASE,
)


def is_help_opener(message: str) -> bool:
    return bool(_HELP_OPENER.match(message or ""))


def help_opener_text(experiment_title: str = "", *, conceptual: bool = False) -> str:
    on = f" with **{experiment_title}**" if experiment_title else ""
    return (
        f"Of course, I'm right here and happy to help{on}! Tell me what's going on and "
        "we'll sort it out together, no question is too small.\n\n"
        f"{GREETING_DETAIL_CONCEPTUAL if conceptual else GREETING_DETAIL}"
    )
