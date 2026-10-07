"""Turn controller for a guided walkthrough.

`take_turn` is a pure function from (state, student message) to a reply and
the next state. It never calls a model. A message that is a genuine free-form
side question yields `reply=None` and the caller answers it with the normal
grounded Q&A path, then appends `resume_line`. Whether an answer is right is
decided only by grader.py against keys written in exp07_script.py.

Flow per step: instruction -> evidence question (only someone who did the
step can answer) -> optional cross-question -> next step. At the end of a
chapter (or every 6 steps in the long tables loop) a two-question checkpoint
asks one recall item and one preview item. A chapter opens with one ungraded
curiosity question.
"""

from __future__ import annotations

import copy
import hashlib
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.socratic_engine import conversation as conv
from backend.socratic_engine.conversation import Intent
from backend.socratic_engine.knowledge import get_knowledge, phone_safe
from backend.socratic_engine.pedagogy import policy, state as pstate
from backend.socratic_engine.walkthrough import grader
from backend.socratic_engine.walkthrough.exp07_script import (
    COMBOS,
    ELECTRONS,
    LINEAR_STEP_IDS,
    LOOP_STEP_IDS,
    MOLECULE_NAMES,
    SCRIPT,
)
from backend.socratic_engine.walkthrough.types import Chapter, Question, QuizItem

log = logging.getLogger("labtutor.walkthrough")

TRIES_ALLOWED = 2
QUIZ_EVERY_STEPS = 6


# ------------------------------------------------------------------ state


@dataclass
class WalkState:
    status: str = "active"  # active | paused | done
    phase: str = "hook"  # hook | step | quiz | done
    pending: str = "evidence"  # evidence | check (within a step)
    step_id: str = LINEAR_STEP_IDS[0]
    combo_index: int = 0
    tries: dict[str, int] = field(default_factory=dict)
    sanity_tries: dict[str, int] = field(default_factory=dict)
    bare: int = 0
    needs_help: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    predictions: dict[str, str] = field(default_factory=dict)
    hooked: list[str] = field(default_factory=list)
    extend_why: list[str] = field(default_factory=list)
    steps_done: int = 0
    steps_since_quiz: int = 0
    quiz: dict[str, Any] | None = None
    quiz_history: list[dict[str, Any]] = field(default_factory=list)
    asked_quiz: list[str] = field(default_factory=list)
    seed: int = 0
    # Actions already used on the question named by `consumed_for` (hint,
    # why, ...). A response never re-offers one of these: tapping "Give me
    # a hint" cannot produce another "Give me a hint" chip.
    consumed: list[str] = field(default_factory=list)
    consumed_for: str = ""
    # The student reported a problem with the current step. Until it is
    # resolved, a message is a report to diagnose, never a wrong answer.
    troubleshooting: bool = False
    # Consecutive "what would you like instead?" turns on this question.
    clarify: int = 0
    # Per-concept understanding (pedagogy.state.ConceptStates as a dict),
    # the "step:when" keys already used for a conceptual moment (once per
    # step, so the 12-run tables loop never nags), and the moment in flight.
    concepts: dict[str, Any] = field(default_factory=dict)
    intervened: list[str] = field(default_factory=list)
    concept: dict[str, Any] | None = None
    # Final reasoning/transfer assessment: {"queue": [question ids], "i": n}
    # while it runs; `assessed` once it has, so it is never asked twice.
    assess: dict[str, Any] | None = None
    assessed: bool = False
    # "software": the Gabedit/ORCA/Avogadro walkthrough. "concept": the
    # phone-only conceptual session (concept_session.py), which asks nothing
    # that needs software or output. `stage`/`stage_asked` track its parts.
    mode: str = "software"
    stage: int = 0
    stage_asked: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "WalkState":
        """Deep-copies every field: `data` is typically `row.state` fresh
        out of the DB session, and this state's own dicts/lists (quiz,
        tries, facts, needs_help, ...) get mutated in place turn by turn.
        Without a copy here, that mutation silently changes the same
        object SQLAlchemy still holds as the column's loaded value, so a
        later `row.state = state.to_dict()` compares equal to it and the
        write is dropped -- found live: a checkpoint quiz answer that
        never actually saved, looping the same question forever."""
        base = cls()
        for key, value in (data or {}).items():
            if hasattr(base, key):
                setattr(base, key, copy.deepcopy(value) if isinstance(value, (dict, list)) else value)
        if base.step_id not in SCRIPT.by_id:
            base.step_id = LINEAR_STEP_IDS[0]
        return base


@dataclass
class TurnResult:
    reply: str | None
    state: WalkState
    events: dict[str, Any] = field(default_factory=dict)
    ui: dict[str, Any] = field(default_factory=dict)
    resume_line: str = ""
    # Set when `reply` is the authored fallback for a free-text conceptual
    # answer the patterns could not classify. The caller may swap it for ONE
    # model-phrased reply (socratic_engine/realise.py); the controller never
    # calls a model itself.
    realise: dict[str, Any] | None = None


def topic_for(state: WalkState) -> tuple[str, str]:
    """(topic, label) naming where the student is, in the mode's own vocabulary."""
    if state.mode == "concept":
        from backend.socratic_engine.walkthrough import concept_session

        return concept_session.topic_label(state)
    step = SCRIPT.step(state.step_id)
    return step.title, f"{_progress(state)['label']}: {step.title}"


def new_state(student_key: str, mode: str = "software") -> WalkState:
    seed = int(hashlib.sha256(student_key.encode()).hexdigest()[:8], 16)
    return WalkState(seed=seed, mode=mode)


# ---------------------------------------------------------------- helpers


def _ctx(state: WalkState) -> dict[str, Any]:
    if state.step_id in LOOP_STEP_IDS:
        molecule, method, basis = COMBOS[min(state.combo_index, len(COMBOS) - 1)]
        return {
            "molecule": MOLECULE_NAMES[molecule], "method": method, "basis": basis,
            "n_elec": ELECTRONS[molecule], "run_no": state.combo_index + 1, "run_total": len(COMBOS),
        }
    molecule = "o2" if SCRIPT.step(state.step_id).chapter == "oxygen" else "ch4"
    return {
        "molecule": MOLECULE_NAMES[molecule], "method": "B3LYP", "basis": "6-31G",
        "n_elec": ELECTRONS[molecule], "run_no": 0, "run_total": len(COMBOS),
    }


def _fmt(text: str, state: WalkState) -> str:
    return text.format(**_ctx(state)) if text else ""


def _pick(options: tuple[str, ...], state: WalkState, salt: int = 0) -> str:
    return options[(state.seed + state.steps_done + salt) % len(options)]


def _molecule_key(state: WalkState) -> str:
    if state.step_id in LOOP_STEP_IDS:
        return COMBOS[min(state.combo_index, len(COMBOS) - 1)][0]
    return "o2" if SCRIPT.step(state.step_id).chapter == "oxygen" else "ch4"


def _progress(state: WalkState) -> dict[str, Any]:
    if state.mode == "concept":
        from backend.socratic_engine.walkthrough import concept_session

        return concept_session.progress(state)
    step = SCRIPT.step(state.step_id)
    total = len(LINEAR_STEP_IDS) + len(COMBOS) * len(LOOP_STEP_IDS)
    if state.step_id in LOOP_STEP_IDS:
        j = LOOP_STEP_IDS.index(state.step_id)
        return {
            "label": f"Table run {state.combo_index + 1} of {len(COMBOS)}, step {j + 1} of {len(LOOP_STEP_IDS)}",
            "index": len(LINEAR_STEP_IDS) + state.combo_index * len(LOOP_STEP_IDS) + j,
            "total": total,
            "chapter": step.chapter,
        }
    i = LINEAR_STEP_IDS.index(state.step_id)
    return {"label": f"Step {i + 1} of {len(LINEAR_STEP_IDS)}", "index": i, "total": total, "chapter": step.chapter}


def _chapter(state: WalkState) -> Chapter:
    return SCRIPT.chapter_of(state.step_id)


def _options_md(choices) -> str:
    return "\n".join(f"{c.key.upper()}. {c.text}" for c in choices)


def _options_ui(choices) -> list[dict[str, str]]:
    return [{"key": c.key, "text": c.text} for c in choices]


def _current_question(state: WalkState) -> Question | None:
    step = SCRIPT.step(state.step_id)
    if state.pending == "evidence" and step.evidence is not None:
        return step.evidence
    return step.check


def _consumed(state: WalkState, q: Question | None) -> list[str]:
    return list(state.consumed) if q is not None and state.consumed_for == q.id else []


def _consume(state: WalkState, q: Question, action: str) -> None:
    if state.consumed_for != q.id:
        state.consumed_for, state.consumed = q.id, []
    if action not in state.consumed:
        state.consumed.append(action)


def _reset_question(state: WalkState) -> None:
    """A new question is on screen: per-question detours start over."""
    state.troubleshooting = False
    state.clarify = 0


def _chips(state: WalkState, q: Question | None, source: str | None = None, candidates: list[str] | None = None) -> tuple[list[str], dict[str, Any]]:
    """The step card offers hint / why / something-different / theory; a
    reply produced by one of those offers the rest plus "Continue". The
    shared policy in conversation.actions drops the source action, anything
    already used on this question, and duplicates."""
    if candidates is None:
        base = (["hint"] if q is not None and q.hint else []) + ["why", "different"]
        candidates = base + (["continue"] if source else ["study_theory"])
    return conv.actions(candidates, source=source, consumed=_consumed(state, q))


def _base_ui(state: WalkState) -> dict[str, Any]:
    if state.mode == "theory":  # a theory follow-up is not a step in anything
        return {"phase": state.phase}
    return {"progress": _progress(state), "phase": state.phase}


def _question_ui(state: WalkState, q: Question, source: str | None = None, candidates: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    chips, ctx = _chips(state, q, source, candidates)
    ui = {**_base_ui(state), "kind": "step", "question_id": q.id, "chips": chips, "action_context": ctx, **extra}
    if q.kind == "mcq":
        ui["options"] = _options_ui(q.choices)
    return ui


def _with_options(text: str, q: Question) -> str:
    return f"{text}\n\n{_options_md(q.choices)}" if q.kind == "mcq" else text


def _step_message(state: WalkState, lead: str = "") -> tuple[str, dict[str, Any]]:
    """The step card: instruction, prerequisite, and the one question."""
    step = SCRIPT.step(state.step_id)
    prog = _progress(state)
    parts = [f"**{prog['label']}: {step.title}**", _fmt(step.do, state)]
    if step.prereq:
        parts.append(f"*{_fmt(step.prereq, state)}*")
    if step.id in state.extend_why:
        parts.append(f"**Why this matters:** {_fmt(step.why, state)}")
    state.pending = "evidence" if step.evidence is not None else "check"
    _reset_question(state)
    q = _current_question(state)
    ui = {**_base_ui(state), "kind": "step", "step_id": step.id, "title": step.title}
    if q is not None:
        label = "Question" if q.kind == "mcq" else "Tell me"
        parts.append(f"**{label}:** {_fmt(q.ask, state)}")
        if q.kind == "mcq":
            parts.append(_options_md(q.choices))
        ui.update(_question_ui(state, q, step_id=step.id, title=step.title))
    text = "\n\n".join(parts)
    return (f"{lead}\n\n{text}" if lead else text), ui


def _hook_message(state: WalkState, opener: str = "") -> tuple[str, dict[str, Any]]:
    chapter = _chapter(state)
    head = opener or "Let's do this together, one step at a time, and I'll ask you things along the way so it sticks."
    text = (
        f"{head}\n\n**A quick guess first.** {_fmt(chapter.hook, state)}\n\n"
        "*No right or wrong here; I only want your instinct.*"
    )
    chips, ctx = conv.actions(["just_tell"])
    return text, {**_base_ui(state), "kind": "hook", "chips": chips, "action_context": ctx}


# ------------------------------------------------------------ navigation


def _next_position(state: WalkState) -> tuple[str, int] | None:
    sid = state.step_id
    if sid in LINEAR_STEP_IDS:
        i = LINEAR_STEP_IDS.index(sid)
        if i + 1 < len(LINEAR_STEP_IDS):
            return LINEAR_STEP_IDS[i + 1], 0
        return LOOP_STEP_IDS[0], 0
    j = LOOP_STEP_IDS.index(sid)
    if j + 1 < len(LOOP_STEP_IDS):
        return LOOP_STEP_IDS[j + 1], state.combo_index
    if state.combo_index + 1 < len(COMBOS):
        return LOOP_STEP_IDS[0], state.combo_index + 1
    return None


def _prev_position(state: WalkState) -> tuple[str, int] | None:
    sid = state.step_id
    if sid in LINEAR_STEP_IDS:
        i = LINEAR_STEP_IDS.index(sid)
        return (LINEAR_STEP_IDS[i - 1], 0) if i > 0 else None
    j = LOOP_STEP_IDS.index(sid)
    if j > 0:
        return LOOP_STEP_IDS[j - 1], state.combo_index
    if state.combo_index > 0:
        return LOOP_STEP_IDS[-1], state.combo_index - 1
    return LINEAR_STEP_IDS[-1], 0


def _is_chapter_end(state: WalkState) -> bool:
    return state.step_id == _chapter(state).step_ids[-1]


# ------------------------------------------------------------------ quiz


def _ordered(items: list[QuizItem], state: WalkState) -> list[QuizItem]:
    return sorted(items, key=lambda it: hashlib.sha256(f"{state.seed}:{it.id}".encode()).hexdigest())


def _find_item(item_id: str) -> QuizItem:
    for chapter in SCRIPT.chapters:
        for it in chapter.recall + chapter.preview:
            if it.id == item_id:
                return it
    raise KeyError(item_id)


def _chapter_id_of_item(item_id: str) -> str:
    for chapter in SCRIPT.chapters:
        if any(it.id == item_id for it in chapter.recall + chapter.preview):
            return chapter.id
    return ""


def _select_quiz(state: WalkState) -> list[tuple[str, QuizItem]]:
    """One recall and one preview item, never repeating one already asked.
    A recall item missed earlier is followed up (once) with a sibling from
    that chapter before anything new."""
    chapter = _chapter(state)
    picks: list[tuple[str, QuizItem]] = []
    followup: list[QuizItem] = []
    for miss in (h for h in state.quiz_history if h["kind"] == "recall" and not h["correct"]):
        other = next((c for c in SCRIPT.chapters if c.id == miss["chapter"]), None)
        if other:
            followup += [it for it in other.recall if it.id not in state.asked_quiz]
    fresh = [it for it in chapter.recall if it.id not in state.asked_quiz]
    if followup:
        picks.append(("recall", followup[0]))
    elif fresh:
        picks.append(("recall", _ordered(fresh, state)[0]))
    previews = [it for it in chapter.preview if it.id not in state.asked_quiz]
    if previews:
        picks.append(("preview", _ordered(previews, state)[0]))
    return picks


def _quiz_message(state: WalkState, lead: str = "") -> tuple[str, dict[str, Any]]:
    quiz = state.quiz or {}
    blocks: list[str] = []
    ui_items: list[dict[str, Any]] = []
    for n, entry in enumerate(quiz.get("items", []), start=1):
        if str(n) in quiz.get("answers", {}):
            continue
        item = _find_item(entry["id"])
        tag = "Recall, from what we just did" if entry["kind"] == "recall" else "Preview, not covered yet, no penalty"
        blocks.append(f"**{n}. {tag}**\n{item.stem}\n{_options_md(item.choices)}")
        ui_items.append({"n": n, "kind": entry["kind"], "stem": item.stem, "options": _options_ui(item.choices)})
    text = (
        "**Checkpoint.** A quick one, no marks.\n\n" + "\n\n".join(blocks)
        + '\n\n*Answer like "1b" or "1b 2c", or tap an option.*'
    )
    if lead:
        text = f"{lead}\n\n{text}"
    chips, ctx = conv.actions(["skip_quiz"])
    return text, {**_base_ui(state), "kind": "quiz", "quiz": ui_items, "chips": chips, "action_context": ctx}


def _parse_quiz_answers(text: str, open_numbers: list[int]) -> dict[int, str]:
    found: dict[int, str] = {}
    for num, letter in re.findall(r"(?:^|[\s,;])([12])\s*[.:)\-]?\s*([a-dA-D])(?=$|[\s,;.)])", text or ""):
        found[int(num)] = letter.lower()
    if found:
        return {n: k for n, k in found.items() if n in open_numbers}
    stripped = re.sub(r"[\s,;.)(]", "", (text or "").lower())
    if stripped and re.fullmatch(r"[a-d]{1,2}", stripped) and len(stripped) <= len(open_numbers):
        return {n: k for n, k in zip(open_numbers, stripped)}
    lead = re.match(r"^\s*(?:option\s*)?[(\[]?([a-dA-D])[)\].:\-]\s", text or "")
    if lead and open_numbers:
        return {open_numbers[0]: lead.group(1).lower()}
    return {}


def _finish_quiz(state: WalkState) -> str:
    quiz = state.quiz or {}
    lines: list[str] = []
    for n, entry in enumerate(quiz.get("items", []), start=1):
        picked = quiz["answers"].get(str(n))
        if picked is None:
            continue
        item = _find_item(entry["id"])
        right = next(c for c in item.choices if c.key == item.correct)
        mine = next(c for c in item.choices if c.key == picked)
        correct = picked == item.correct
        state.quiz_history.append(
            {"item_id": item.id, "kind": entry["kind"], "correct": correct, "chapter": _chapter_id_of_item(item.id)}
        )
        if entry["kind"] == "recall":
            lines.append(
                f"**{n}. Correct.** {right.why}" if correct
                else f"**{n}. Not quite.** The answer is **{right.text}**. {right.why} Your option: {mine.why}"
            )
        elif correct:
            lines.append(f"**{n}. Good instinct.** {right.why} {item.teaser}".strip())
        else:
            lines.append(f"**{n}. Worth keeping in mind.** The answer is **{right.text}**. {right.why} {item.teaser}".strip())
            if item.teaser_step and item.teaser_step not in state.extend_why:
                state.extend_why.append(item.teaser_step)
    state.quiz = None
    state.steps_since_quiz = 0
    return "\n\n".join(lines)


# ------------------------------------------------------ conceptual moments
#
# A conceptual moment is one short authored question about *why* (or what
# to expect, or what the result means), raised only at the checkpoint steps
# in knowledge/exp07.py and only while the student has not shown
# understanding of the concept. Whether to raise one, which question, how an
# answer is classified and how concept state changes are all decided by
# pedagogy/policy.py with no model involved; a reply here is authored text.

_WHEN_TYPES = {"pre": policy.PRE_STEP_TYPES, "post": policy.POST_STEP_TYPES, "stage": None}


def _cs(state: WalkState) -> pstate.ConceptStates:
    return pstate.ConceptStates.from_dict(state.concepts)


def _save_cs(state: WalkState, cs: pstate.ConceptStates) -> None:
    state.concepts = cs.to_dict()


def _concept_moment(
    state: WalkState, when: str, lead: str, *, resume: str, step_id: str | None = None
) -> tuple[str, dict[str, Any]] | None:
    knowledge = get_knowledge("exp07")
    if knowledge is None:
        return None
    sid = step_id or state.step_id
    key = f"{sid}:{when}"
    if when != "stage" and key in state.intervened:
        return None
    cs = _cs(state)
    rows = _rows_recorded(state)
    phone_only = state.mode == "concept"
    decision = policy.decide(
        knowledge, sid, cs, blocked=state.troubleshooting, allowed=_WHEN_TYPES[when],
        # In phone-only mode a question must pass the phone-safety gate (source
        # metadata AND wording scan); a question about the student's own
        # recorded results is also unavailable, since there are none.
        available=lambda q: q.min_rows <= rows
        and (phone_only or not q.phone_only)  # phone-only stand-ins never appear at software steps
        and (not phone_only or phone_safe.is_phone_safe(q)),
    )
    if decision.action == "none" or decision.question is None:
        return None
    if when != "stage":
        state.intervened.append(key)
    pstate.introduce(cs, decision.concept_id)
    cs.get(decision.concept_id).last_seq = cs.seq
    _save_cs(state, cs)
    state.phase = "concept"
    state.concept = {
        "concept_id": decision.concept_id,
        "question_id": decision.question.id,
        "step_id": sid,
        "when": when,
        "resume": resume,
        "card": decision.action == "card_question",
    }
    return _concept_message(state, lead)


def _context_title(state: WalkState) -> str:
    """What part of the experiment the student is in, in the right vocabulary
    for the mode: a software step title, or a conceptual part title."""
    if state.mode == "concept":
        from backend.socratic_engine.walkthrough import concept_session

        return concept_session.stage_title(state)
    if state.mode == "theory":
        return "a theory discussion about Experiment 7"
    return SCRIPT.step(state.step_id).title


def _rows_recorded(state: WalkState) -> int:
    """Runs of the method/basis table the student has recorded a HOMO for."""
    return sum(1 for row in state.facts.get("table", {}).values() if row.get("homo") is not None)


def _data_view(state: WalkState, qid: str) -> str:
    """The student's OWN recorded numbers, laid out so a question about them
    can be answered by looking. Built only from `state.facts` (what they
    typed in); nothing is computed beyond a difference of their own values,
    and no reference value is ever shown."""
    facts = state.facts
    if qid in ("q_energy_lower", "q_opt_observe") and "e_first" in facts and "e_final" in facts:
        first, final = facts["e_first"], facts["e_final"]
        return (
            f"**Your numbers:** first energy {first:g} Eh, last energy {final:g} Eh "
            f"(change {final - first:+.6f} Eh)."
        )
    if qid == "q_pattern_interpret":
        rows = []
        for idx, row in sorted(facts.get("table", {}).items(), key=lambda kv: int(kv[0])):
            if row.get("homo") is None or int(idx) >= len(COMBOS):
                continue
            molecule, method, basis = COMBOS[int(idx)]
            lumo = row.get("lumo")
            gap = f"{lumo - row['homo']:.3f}" if lumo is not None else "-"
            lumo_s = f"{lumo:g}" if lumo is not None else "-"
            rows.append(f"| {MOLECULE_NAMES[molecule]} | {method} | {basis} | {row['homo']:g} | {lumo_s} | {gap} |")
        if rows:
            head = "| Molecule | Method | Basis | HOMO (eV) | LUMO (eV) | Gap (eV) |\n|---|---|---|---|---|---|\n"
            return "**Your results so far:**\n\n" + head + "\n".join(rows)
    if qid == "q_compare_ch4_o2" and {"homo_out", "lumo_out", "o2_homo", "o2_lumo"} <= facts.keys():
        return (
            "**Your numbers:**\n\n| Molecule | HOMO (eV) | LUMO (eV) |\n|---|---|---|\n"
            f"| {MOLECULE_NAMES['ch4']} | {facts['homo_out']:g} | {facts['lumo_out']:g} |\n"
            f"| {MOLECULE_NAMES['o2']} | {facts['o2_homo']:g} | {facts['o2_lumo']:g} |"
        )
    return ""


def _concept_message(state: WalkState, lead: str = "") -> tuple[str, dict[str, Any]]:
    info = state.concept or {}
    knowledge = get_knowledge("exp07")
    q = knowledge.question_by_id[info["question_id"]]
    concept = knowledge.concept_by_id[info["concept_id"]]
    parts = [lead] if lead else []
    card = None
    if info.get("card"):
        card = {"id": concept.id, "name": concept.name, "text": concept.description}
        parts.append(f"**Concept worth knowing: {concept.name}.** {concept.description}")
    label = "A quick prediction" if q.qtype == "PREDICTION" else "A quick thought"
    if state.mode == "theory":
        label = "Think about this"
    view = _data_view(state, q.id)
    if view:
        parts.append(view)
    parts.append(f"**{label}:** {q.ask}")
    chips, ctx = conv.actions(["just_tell", "skip_concept"])
    ui = {
        **_base_ui(state),
        "kind": "concept",
        "step_id": info.get("step_id", state.step_id),
        "concept_id": concept.id,
        "question_type": q.qtype,
        "chips": chips,
        "action_context": ctx,
    }
    if card:
        ui["concept_card"] = card
    # Research telemetry: take_turn copies this into the turn's events.
    ui["intervention"] = {
        "concept_id": concept.id, "question_id": q.id, "question_type": q.qtype,
        "when": info.get("when"), "step_id": info.get("step_id"), "card": bool(card),
        "concept_state": _cs(state).get(concept.id).state,
    }
    return "\n\n".join(parts), ui


def _finish_concept(state: WalkState, lead: str) -> tuple[str, dict[str, Any]]:
    resume = (state.concept or {}).get("resume", "enter")
    state.concept = None
    state.phase = "step"
    if resume == "theory":
        # A follow-up question asked after a theory answer: nothing comes next.
        return lead, {"kind": "theory_followup", "phase": "step", "chips": []}
    if resume == "stage":
        from backend.socratic_engine.walkthrough import concept_session

        return concept_session.after_moment(state, lead)
    if resume == "advance":
        return _after_concept_post(state, lead)
    return _step_message(state, lead)


def _turn_concept(state: WalkState, message: str) -> TurnResult:
    info = state.concept or {}
    knowledge = get_knowledge("exp07")
    q = knowledge.question_by_id.get(info.get("question_id", ""))
    cid = info.get("concept_id", "")
    if q is None or cid not in knowledge.concept_by_id:  # stale state: just carry on
        text, ui = _finish_concept(state, "")
        return TurnResult(text, state, {"step_id": state.step_id, "verdict": "concept_dropped"}, ui)

    cs = _cs(state)
    rec = cs.get(cid)
    before = rec.state
    pedagogy: dict[str, Any] = {
        "concept_id": cid, "question_id": q.id, "question_type": q.qtype, "when": info.get("when"),
        "state_before": before, "source": "deterministic",
    }
    events: dict[str, Any] = {"step_id": state.step_id, "phase": "concept", "pedagogy": pedagogy}

    def done(lead: str, verdict: str) -> TurnResult:
        pedagogy["state_after"] = cs.get(cid).state
        _save_cs(state, cs)
        text, ui = _finish_concept(state, lead)
        return TurnResult(text, state, {**events, "verdict": verdict}, ui)

    intent = conv.classify(message)
    if (
        message.strip().lower() == conv.ACTIONS["skip_concept"].lower()
        or grader.is_skip(message)
        or intent in (Intent.STEP_REFUSED, Intent.STEP_SKIPPED)
    ):
        state.skipped.append(f"concept:{cid}")
        pedagogy["classification"] = "SKIPPED"
        return done("No problem, we'll carry on.", "concept_skipped")

    if grader.wants_answer(message):
        pstate.apply_classification(cs, cid, "UNCLEAR", question_id=q.id, question_type=q.qtype, reason="asked_for_answer")
        pedagogy["classification"] = "UNCLEAR"
        return done(f"Here is the short version: {q.expected_reasoning}", "concept_explained")

    cls = policy.classify_answer(q, message, knowledge, step_id=info.get("step_id", ""))
    if grader.is_new_request(message) or (
        cls.label == "UNCLEAR" and not cls.dont_know and grader.is_side_question(message)
    ):
        # A real question, not an attempt ("Compare B3LYP and B3P" is never
        # graded, even if it happens to name a keyword): the grounded Q&A path
        # answers it, then the resume line brings the student back here.
        return TurnResult(None, state, {**events, "verdict": "side_question"}, {}, resume_line=_resume_line(state))

    rec = pstate.apply_classification(
        cs, cid, cls.label, question_id=q.id, question_type=q.qtype, misconception_id=cls.misconception_id
    )
    if cls.label == "CORRECT" and q.qtype == "TRANSFER" and before == "UNDERSTOOD":
        pstate.mark_mastered(cs, cid)
    pedagogy.update(classification=cls.label, misconception_id=cls.misconception_id)
    follow = policy.next_after_answer(knowledge, q, cls, rec)
    pedagogy["followup"] = follow.kind

    if follow.kind == "advance":
        return done(f"**Yes.** {q.expected_reasoning}", "concept_correct")
    if follow.kind == "explain":
        return done(f"Here is the short version: {follow.text or q.expected_reasoning}", "concept_explained")

    pedagogy["state_after"] = cs.get(cid).state
    _save_cs(state, cs)
    if follow.kind == "probe":
        note = f"That is a common way to think about it. {follow.text}"
    elif cls.label == "PARTIAL":
        note = f"You are part of the way there. {follow.text}"
    else:
        note = f"Let's come at it another way. {follow.text}"
    chips, ctx = conv.actions(["just_tell", "skip_concept"])
    ui = {
        **_base_ui(state), "kind": "concept", "step_id": state.step_id, "concept_id": cid,
        "question_type": q.qtype, "chips": chips, "action_context": ctx,
    }
    realise = None
    if cls.label == "UNCLEAR" and not cls.dont_know:
        concept = knowledge.concept_by_id[cid]
        realise = {
            "concept_id": cid, "question_id": q.id, "question_type": q.qtype,
            "step_title": _context_title(state), "concept_name": concept.name,
            "concept_description": concept.description, "question": q.ask,
            "expected_reasoning": q.expected_reasoning, "concept_state": rec.state,
            "misses": rec.misses.get(q.id, 0), "student_answer": message,
        }
    return TurnResult(note, state, {**events, "verdict": f"concept_{follow.kind}"}, ui, realise=realise)


# ------------------------------------------------------------- advancing


def _advance(state: WalkState, lead: str, completed: bool = True) -> tuple[str, dict[str, Any]]:
    """Leave the current step -- completed, or explicitly skipped by the
    student (`completed=False`: recorded in `skipped`, never counted as
    done). Nothing else may call this: a refusal, a problem report or a
    request for theory never leaves the step."""
    step = SCRIPT.step(state.step_id)
    log.info("[STATE] step=%s -> %s", step.id, "STEP_COMPLETED" if completed else "STEP_SKIPPED")
    if completed:
        state.steps_done += 1
        state.steps_since_quiz += 1
    state.tries.pop(step.id, None)
    state.bare = 0
    if completed:
        moment = _concept_moment(state, "post", lead, resume="advance")
        if moment is not None:
            return moment
    return _after_concept_post(state, lead)


def _after_concept_post(state: WalkState, lead: str) -> tuple[str, dict[str, Any]]:
    """The rest of leaving a step: checkpoint quiz, or the next step."""
    step = SCRIPT.step(state.step_id)
    trigger = _is_chapter_end(state) and (step.chapter != "tables" or state.steps_since_quiz >= QUIZ_EVERY_STEPS)
    if trigger:
        picks = _select_quiz(state)
        if picks:
            state.phase = "quiz"
            state.quiz = {"items": [{"id": it.id, "kind": kind} for kind, it in picks], "answers": {}}
            state.asked_quiz += [it.id for _, it in picks]
            return _quiz_message(state, lead)
    return _move_to_next(state, lead)


def _move_to_next(state: WalkState, lead: str) -> tuple[str, dict[str, Any]]:
    old_chapter = _chapter(state).id
    nxt = _next_position(state)
    if nxt is None:
        return _begin_assessment(state, lead)
    state.step_id, state.combo_index = nxt
    state.pending = "evidence"
    state.phase = "step"
    new_chapter = _chapter(state).id
    if new_chapter != old_chapter and new_chapter not in state.hooked:
        state.phase = "hook"
        state.hooked.append(new_chapter)
        return _hook_message(state, opener=lead)
    return _enter_step(state, lead)


def _enter_step(state: WalkState, lead: str) -> tuple[str, dict[str, Any]]:
    """Show a step, after a prediction-style conceptual moment if one is due."""
    moment = _concept_moment(state, "pre", lead, resume="enter")
    return moment if moment is not None else _step_message(state, lead)


# ------------------------------------------------- final assessment
#
# The procedure is complete; this checks understanding of the ideas, not the
# clicks. Every student gets the same authored questions (comparable data),
# each is skippable, and feedback is the authored key idea -- no model call.
# Classification is conservative: free text the patterns cannot place stays
# UNCLEAR, and the raw answer is kept in the event for later human review.


def _assessment_ids(state: WalkState | None = None) -> list[str]:
    knowledge = get_knowledge("exp07")
    if not knowledge:
        return []
    ids = list(knowledge.assessment)
    if state is not None and state.mode == "concept":
        ids = [q for q in ids if phone_safe.is_phone_safe(knowledge.question_by_id[q])]
    return ids


def _begin_assessment(state: WalkState, lead: str) -> tuple[str, dict[str, Any]]:
    queue = _assessment_ids(state)
    if not queue or state.assessed:
        return _closing_message(state, lead)
    state.assess = {"queue": queue, "i": 0}
    state.phase = "assess"
    if state.mode == "concept":
        intro = (
            "**That covers the main ideas of Experiment 7.** One last thing: "
            f"{len(queue)} short questions that check the ideas, not any procedure. "
            "Short answers are fine, and you can skip any."
        )
    else:
        intro = (
            "**That is the whole experiment.** One last thing before you write up: "
            f"{len(queue)} short questions on the ideas behind it, not the clicks. "
            "Short answers are fine, and you can skip any."
        )
    return _assess_message(state, "\n\n".join(p for p in (lead, intro) if p))


def _assess_message(state: WalkState, lead: str = "") -> tuple[str, dict[str, Any]]:
    info = state.assess or {"queue": [], "i": 0}
    q = get_knowledge("exp07").question_by_id[info["queue"][info["i"]]]
    n, total = info["i"] + 1, len(info["queue"])
    label = f"Final reflection {n} of {total}"
    view = _data_view(state, q.id)
    text = "\n\n".join(p for p in (lead, view, f"**{label}:** {q.ask}") if p)
    chips, ctx = conv.actions(["skip_concept"])
    ui = {
        "kind": "assessment", "phase": "assess", "chips": chips, "action_context": ctx,
        "progress": {"label": label, "index": n - 1, "total": total, "chapter": "final"},
        "question_type": q.qtype, "concept_id": q.concept_id,
    }
    return text, ui


def _concept_summary(state: WalkState) -> str:
    knowledge = get_knowledge("exp07")
    cs = _cs(state)
    asked = [cid for cid, rec in cs.records.items() if rec.attempts and cid in knowledge.concept_by_id]
    solid = [knowledge.concept_by_id[c].name for c in asked if cs.get(c).state in pstate.UNDERSTOOD_OR_BETTER]
    revisit = [knowledge.concept_by_id[c].name for c in asked if cs.get(c).state not in pstate.UNDERSTOOD_OR_BETTER]
    parts = []
    if solid:
        parts.append("Ideas you explained well: " + ", ".join(solid) + ".")
    if revisit:
        parts.append("Worth another look before you write up: " + ", ".join(revisit) + ".")
    return " ".join(parts)


def _turn_assess(state: WalkState, message: str) -> TurnResult:
    info = state.assess or {}
    knowledge = get_knowledge("exp07")
    queue = info.get("queue", [])
    q = knowledge.question_by_id.get(queue[info["i"]]) if queue and info.get("i", 0) < len(queue) else None
    if q is None:  # stale state: finish cleanly
        state.assess, state.assessed = None, True
        text, ui = _closing_message(state, "")
        return TurnResult(text, state, {"step_id": state.step_id, "verdict": "assessment_dropped"}, ui)

    cs = _cs(state)
    rec = cs.get(q.concept_id)
    pedagogy: dict[str, Any] = {
        "concept_id": q.concept_id, "question_id": q.id, "question_type": q.qtype, "when": "final",
        "state_before": rec.state, "source": "deterministic",
    }
    events: dict[str, Any] = {"step_id": state.step_id, "phase": "assess", "pedagogy": pedagogy}
    intent = conv.classify(message)
    skipped = (
        message.strip().lower() == conv.ACTIONS["skip_concept"].lower()
        or grader.is_skip(message)
        or intent in (Intent.STEP_REFUSED, Intent.STEP_SKIPPED)
    )
    if skipped:
        pedagogy["classification"] = "SKIPPED"
        state.skipped.append(f"assess:{q.id}")
        feedback, verdict = "Skipped.", "assessment_skipped"
    else:
        cls = policy.classify_answer(q, message, knowledge)
        if grader.is_new_request(message) or (
            cls.label == "UNCLEAR" and not cls.dont_know and grader.is_side_question(message)
        ):
            return TurnResult(None, state, {**events, "verdict": "side_question"}, {}, resume_line=_resume_line(state))
        before = rec.state
        pstate.apply_classification(
            cs, q.concept_id, cls.label, question_id=q.id, question_type=q.qtype,
            misconception_id=cls.misconception_id, reason="final_assessment",
        )
        if cls.label == "CORRECT" and q.qtype == "TRANSFER" and before == "UNDERSTOOD":
            pstate.mark_mastered(cs, q.concept_id, "final_transfer_correct")
        pedagogy.update(classification=cls.label, misconception_id=cls.misconception_id,
                        state_after=cs.get(q.concept_id).state, answer=message.strip()[:300])
        feedback = "**Yes.**" if cls.label == "CORRECT" else f"The key idea: {q.expected_reasoning}"
        verdict = "assessment_answered"
    _save_cs(state, cs)
    info["i"] += 1
    if info["i"] < len(queue):
        state.assess = info
        text, ui = _assess_message(state, feedback)
        return TurnResult(text, state, {**events, "verdict": verdict}, ui)
    state.assess, state.assessed = None, True
    text, ui = _closing_message(state, feedback)
    return TurnResult(text, state, {**events, "verdict": verdict, "assessment_done": True}, ui)


def _closing_message(state: WalkState, lead: str) -> tuple[str, dict[str, Any]]:
    state.status = "done"
    state.phase = "done"
    if state.mode == "concept":
        lines = [
            lead,
            "**That is the end of this session.** You reasoned through the ideas behind Experiment 7: the shape of "
            "methane, how a calculation is set up, geometry optimisation, orbitals and the HOMO and LUMO, oxygen "
            "compared with methane, and comparing methods.",
        ]
        if state.assessed:
            lines.append(_concept_summary(state))
        lines.append('Ask me anything about these ideas, or say "start over" to go through them again.')
        return "\n\n".join(p for p in lines if p), {**_base_ui(state), "kind": "done", "chips": []}
    lines = [
        lead,
        "**That is the whole experiment.** You built two molecules, optimised and analysed both, and ran all twelve method and basis combinations.",
    ]
    spreads = _table_spreads(state.facts.get("table", {}))
    if spreads:
        lines.append(spreads)
        guess = state.predictions.get("tables")
        if guess:
            lines.append(f'You guessed: "{guess}". Does your own data agree?')
    if state.needs_help:
        lines.append(f"There were {len(state.needs_help)} points where I helped you along. Those are worth revisiting before you write up.")
    if state.assessed:
        lines.append(_concept_summary(state))
    lines.append('Ask me anything about the results, or say "start over" to run the guide again.')
    return "\n\n".join(p for p in lines if p), {**_base_ui(state), "kind": "done", "chips": []}


def _table_spreads(table: dict[str, Any]) -> str:
    out: list[str] = []
    for first, name in ((0, "Methane"), (6, "Oxygen")):
        vals: dict[tuple[str, str], float] = {}
        for k, (_, method, basis) in enumerate(COMBOS[first : first + 6]):
            row = table.get(str(first + k))
            if not row or row.get("homo") is None:
                vals = {}
                break
            vals[(method, basis)] = float(row["homo"])
        if not vals:
            continue
        method_gap = max(abs(vals[("B3LYP", b)] - vals[("B3P", b)]) for b in ("6-31G", "6-31G*", "6-31G**"))
        basis_gap = max(abs(vals[(m, "6-31G")] - vals[(m, "6-31G**")]) for m in ("B3LYP", "B3P"))
        out.append(
            f"{name}: switching method moved your HOMO by at most {method_gap:.3f} eV; "
            f"switching 6-31G to 6-31G** moved it by at most {basis_gap:.3f} eV."
        )
    return "\n".join(out)


# ----------------------------------------------------------- sanity rules


def _sanity(names: list[str], values: list[float], state: WalkState) -> tuple[bool, str]:
    """(ok, note). ok=False is a determinate finding about the student's own
    numbers; the note is authored text, never a model's opinion."""
    from backend.tier1_compute.experiments import get_plugin

    plugin = get_plugin("exp07")
    data = dict(zip(names, values))
    first = names[0]
    if first.endswith("e_first"):
        if plugin._sanity_violations({"energy_before_opt": data[names[0]], "energy_after_opt": data[names[1]]}):
            return False, (
                "Your last energy is higher than your first, and optimisation only moves downhill. "
                "Check that you read the first cycle's FINAL SINGLE POINT ENERGY first and the last cycle's last."
            )
        if data[names[0]] > 0 or data[names[1]] > 0:
            return False, "Total energies in this output are large negative numbers in Eh. A positive value suggests you read a different line."
        return True, ""
    if first.endswith("homo") or first in ("homo_out", "homo_avo"):
        if plugin._sanity_violations({"homo_energy": data[names[0]], "lumo_energy": data[names[1]]}):
            return False, "The LUMO has to sit above the HOMO in energy, and your two numbers are the other way round or equal. Check which row is which."
        if first == "homo_avo" and "homo_out" in state.facts and abs(state.facts["homo_out"] - data[first]) > 0.05:
            return False, (
                "Avogadro and the ORCA table list the same orbitals in the same units, so the HOMO should match what you read from ORCA. "
                "Which file did you open in Avogadro?"
            )
        return True, ""
    if first == "shells_total":
        want = ELECTRONS[_molecule_key(state)]
        if abs(data[first] - want) > 0.5:
            return False, f"Electrons are conserved: summed over every atom and shell they should come to {want}. Check which block and which atoms you added."
        return True, ""
    return True, ""


def _store_values(names: list[str], values: list[float], state: WalkState) -> None:
    for name, value in zip(names, values):
        state.facts[name] = value
    if names and names[0] in ("homo", "shells_total"):
        row = state.facts.setdefault("table", {}).setdefault(str(state.combo_index), {})
        for name, value in zip(names, values):
            row[name] = value


# --------------------------------------------------------- answer handling


def _reveal_text(q: Question) -> str:
    if q.kind == "mcq":
        right = next(c for c in q.choices if c.key == q.correct)
        return f"The answer is **{right.text}**. {q.reveal or right.why}"
    return q.reveal or "Here is what I was looking for; make sure your screen shows the same."


def _flag_help(state: WalkState, qid: str) -> None:
    if qid not in state.needs_help:
        state.needs_help.append(qid)


def _after_question(state: WalkState, lead: str) -> tuple[str, dict[str, Any]]:
    """The current question is finished (answered or revealed): go to the
    cross-question, or complete the step."""
    step = SCRIPT.step(state.step_id)
    if state.pending == "evidence" and step.check is not None:
        state.pending = "check"
        _reset_question(state)
        q = step.check
        text = _with_options("\n\n".join(p for p in (lead, f"**Now a why-question:** {_fmt(q.ask, state)}") if p), q)
        return text, _question_ui(state, q, step_id=step.id)
    ack = _fmt(step.ack, state)
    chapter_id = _chapter(state).id
    if step.closes_hook and chapter_id in state.predictions:
        ack += f' Earlier you guessed: "{state.predictions[chapter_id]}". Compare that with what you just read.'
    return _advance(state, "\n\n".join(p for p in (lead, ack) if p))


_PROBE_OPENERS = (
    "Thanks, but I need to see it to know it worked.",
    'Good, though "done" does not tell me what is on your screen.',
    "Before we move on, one fact from your screen, please.",
)


def _correct_note(q: Question, verdict: grader.Verdict) -> str:
    if q.kind == "mcq":
        chosen = next((c for c in q.choices if c.key == verdict.chosen), None)
        return f"**Yes.** {chosen.why}" if chosen and chosen.why else "**Yes.**"
    return q.ok


def _resume_line(state: WalkState) -> str:
    if state.phase == "quiz":
        return "\n\n---\n*Back to the checkpoint:* answer whenever you are ready."
    if state.phase == "concept" and state.concept:
        cq = get_knowledge("exp07").question_by_id.get(state.concept.get("question_id", ""))
        return f"\n\n---\n*Back to my question:* {cq.ask}" if cq else ""
    if state.phase == "assess" and state.assess:
        aq = get_knowledge("exp07").question_by_id.get(state.assess["queue"][state.assess["i"]])
        return f"\n\n---\n*Back to the final question:* {aq.ask}" if aq else ""
    if state.phase == "hook":
        return '\n\n---\n*Back to my guess question:* say what you think, or "just tell me" to skip it.'
    step = SCRIPT.step(state.step_id)
    q = _current_question(state)
    ask = f" {_fmt(q.ask, state)}" if q is not None else ""
    return f"\n\n---\n*Back to {_progress(state)['label']}, {step.title}:*{ask}"


def _handle_report(state: WalkState, q: Question, verdict: grader.Verdict, events: dict[str, Any]) -> TurnResult:
    names = [n for n in q.capture.split(",") if n]
    values = list(verdict.values)
    if len(values) < len(names):
        text = f"I have {len(values)} of the {len(names)} numbers I need. {_fmt(q.ask, state)}"
        return TurnResult(text, state, {**events, "verdict": "report_incomplete"}, _question_ui(state, q))
    values = values[: len(names)]
    ok, note = _sanity(names, values, state)
    if not ok:
        tries = state.sanity_tries.get(q.id, 0) + 1
        state.sanity_tries[q.id] = tries
        if tries < TRIES_ALLOWED:
            text = f"{note}\n\nTake another look and give me the numbers again."
            return TurnResult(text, state, {**events, "verdict": "sanity_probe", "tries": tries}, _question_ui(state, q))
        _flag_help(state, q.id)
        _store_values(names, values, state)
        reply, ui = _after_question(state, f"I will take your numbers as they are, but keep this in mind: {note}")
        return TurnResult(reply, state, {**events, "verdict": "sanity_unresolved", "needed_help": True, "values": dict(zip(names, values))}, ui)
    _store_values(names, values, state)
    state.sanity_tries.pop(q.id, None)
    reply, ui = _after_question(state, "Recorded: " + ", ".join(f"{v:g}" for v in values) + ".")
    return TurnResult(reply, state, {**events, "verdict": "correct", "values": dict(zip(names, values))}, ui)


_TROUBLE_ASK = (
    "Sure, let's sort that out. Tell me what looks different, or describe what you see: "
    "which window is open, the menu names or buttons you can see, any error message, "
    "and what you expected compared with what you got."
)
_MISSING_ASK = (
    "Thanks for telling me; I won't assume that option is there. "
    "Tell me exactly what you do see: the window's title, the menu names along the top, "
    "or any message on screen, and we'll work from that."
)


def _detour(state: WalkState, q: Question, text: str, verdict: str, events: dict[str, Any], *, source: str | None = None, candidates: list[str] | None = None) -> TurnResult:
    """A reply that stays on the current question: hint, why, a problem
    report, a clarification. Never moves the step."""
    return TurnResult(text, state, {**events, "verdict": verdict}, _question_ui(state, q, source=source, candidates=candidates))


def _handle_intent(state: WalkState, q: Question, message: str, intent: Intent, events: dict[str, Any]) -> TurnResult | None:
    """Student intent first, grading second. Returns None when the message
    is an answer attempt (or a free question) for the normal path."""
    step = SCRIPT.step(state.step_id)
    events["intent"] = intent.value

    if intent is Intent.SWITCH_TO_PRACTICE or (state.troubleshooting and intent is Intent.PROBLEM_RESOLVED):
        # "Back to step", "it works now": show the same question again.
        resolved = state.troubleshooting
        state.troubleshooting = False
        state.clarify = 0
        lead = "Good, glad that's sorted." if resolved else "Here is where you are."
        text = _with_options(f"{lead} {_fmt(q.ask, state)}", q)
        return _detour(state, q, text, "problem_resolved" if resolved else "resume_shown", events)

    if intent is Intent.USER_REQUESTED_HINT:
        state.clarify = 0
        if "hint" in _consumed(state, q):
            text = _with_options(
                "That was the only hint I have for this one. If it still isn't clear, say \"just tell me\" "
                "and I'll show you the answer, or tell me what you see on screen.", q)
            return _detour(state, q, text, "hint_repeated", events, source="hint", candidates=["why", "different", "just_tell"])
        _consume(state, q, "hint")
        if q.hint:
            text = _with_options(f"**Hint:** {_fmt(q.hint, state)}", q)
        else:
            text = _with_options(
                f"I don't have a separate hint for this one: the answer comes straight from your screen once you have done this: "
                f"{_fmt(step.do, state)}\n\nWhen you're ready: {_fmt(q.ask, state)}", q)
        return _detour(state, q, text, "hint_requested", events, source="hint")

    if intent is Intent.USER_REQUESTED_EXPLANATION:
        state.clarify = 0
        if "why" in _consumed(state, q):
            text = _with_options(f"That's the reason I gave just above. When you're ready: {_fmt(q.ask, state)}", q)
            return _detour(state, q, text, "why_repeated", events, source="why")
        _consume(state, q, "why")
        text = _with_options(f"**Why this step:** {_fmt(step.why, state)}\n\nWhen you are ready: {_fmt(q.ask, state)}", q)
        return _detour(state, q, text, "why_requested", events, source="why")

    if intent is Intent.TROUBLESHOOTING or (state.troubleshooting and intent in (Intent.ANSWER, Intent.USER_QUESTION)):
        already = state.troubleshooting
        state.troubleshooting = True
        state.clarify = 0
        # Not consumed: unlike a hint, a new problem can come up on the
        # same question, so the chip is only hidden on its own reply.
        if already and intent is not Intent.TROUBLESHOOTING:
            # The student is describing the problem. A structured answer
            # (option, number) or a correct free-text answer goes back to
            # normal grading; any other text is a report for the grounded
            # path to diagnose -- never counted as a wrong try.
            # Free-text keys are loose patterns, so a long description
            # ("it just doesn't open at all") can contain a key word; only
            # a short, correct reply counts as an answer here.
            verdict = grader.grade(q, message)
            short_answer = (
                q.kind == "short" and verdict.correct
                and len(grader._tokens(message)) <= 5 and not conv.is_negative(message)
            )
            if verdict.attempted and (q.kind != "short" or short_answer):
                state.troubleshooting = False
                return None
            return TurnResult(None, state, {**events, "verdict": "troubleshoot_report"}, {}, resume_line=_resume_line(state))
        detailed = len(grader._tokens(message)) >= 9
        if detailed:
            # A specific report on the first message: diagnose it now.
            return TurnResult(None, state, {**events, "verdict": "troubleshoot_report"}, {}, resume_line=_resume_line(state))
        parts = [_MISSING_ASK if conv.is_missing_ui(message) else _TROUBLE_ASK]
        if step.stuck:
            parts.append(f"Things that commonly trip people up here: {_fmt(step.stuck, state)}")
        return _detour(state, q, "\n\n".join(parts), "troubleshooting", events,
                       source="different", candidates=["back_to_step", "study_theory", "skip"])

    if intent is Intent.STEP_REFUSED:
        state.clarify += 1
        if state.clarify == 1:
            text = (
                "No problem, you don't have to do this step right now. What would you like instead? "
                "I can switch to the theory behind it, give you a hint, help if something isn't working, "
                "or skip it for now."
            )
            return _detour(state, q, text, "step_refused", events,
                           candidates=["study_theory", "hint", "different", "skip"])
        text = (
            "Understood, we won't do it. Tell me in a few words what you'd rather do, "
            'or say "skip this step" to move past it, or "study theory" to switch to the concepts.'
        )
        return _detour(state, q, text, "step_refused_again", events, candidates=["study_theory", "skip"])

    return None


def _handle_answer(state: WalkState, message: str) -> TurnResult:
    step = SCRIPT.step(state.step_id)
    q = _current_question(state)
    events: dict[str, Any] = {"step_id": step.id, "question_id": q.id if q else None}
    if q is None:
        reply, ui = _advance(state, "")
        return TurnResult(reply, state, {**events, "verdict": "advance"}, ui)

    if grader.is_back(message):
        prev = _prev_position(state)
        if prev is None:
            reply, ui = _step_message(state, "You are at the first step.")
        else:
            state.step_id, state.combo_index = prev
            reply, ui = _step_message(state, "Going back.")
        return TurnResult(reply, state, {**events, "verdict": "back"}, ui)

    intent = conv.intent_for_chip_text(message) or conv.classify(message)
    if grader.is_skip(message):
        intent = Intent.STEP_SKIPPED
    log.info("[INTENT] step=%s -> %s troubleshooting=%s consumed=%s", step.id, intent.value, state.troubleshooting, _consumed(state, q))

    if intent is Intent.STEP_SKIPPED:
        _flag_help(state, q.id)
        state.skipped.append(step.id)
        reply, ui = _advance(state, 'Skipped, and noted. Say "back" any time to return to it.', completed=False)
        return TurnResult(reply, state, {**events, "verdict": "skip", "intent": intent.value, "needed_help": True}, ui)

    if grader.wants_answer(message) and intent in (Intent.ANSWER, Intent.USER_QUESTION) and not state.troubleshooting:
        _flag_help(state, q.id)
        reply, ui = _after_question(state, _reveal_text(q))
        return TurnResult(reply, state, {**events, "verdict": "reveal", "needed_help": True}, ui)

    handled = _handle_intent(state, q, message, intent, events)
    if handled is not None:
        return handled
    state.clarify = 0

    if q.kind == "short" and grader.is_side_question(message):
        # A free-text answer can only be recognised by its content, so a
        # real question here is a question, not a wrong (or accidentally
        # "correct") answer -- checked before grading, because an
        # open-ended check (e.g. "tell me once it's open") would otherwise
        # accept a genuine question as a valid free-text reply.
        return TurnResult(None, state, {**events, "verdict": "side_question"}, {}, resume_line=_resume_line(state))

    verdict = grader.grade(q, message)

    if verdict.attempted and q.kind == "report":
        return _handle_report(state, q, verdict, events)

    if verdict.attempted and verdict.correct:
        state.tries.pop(q.id, None)
        state.bare = 0
        reply, ui = _after_question(state, _correct_note(q, verdict))
        return TurnResult(reply, state, {**events, "verdict": "correct", "tries": 0}, ui)

    if verdict.attempted:
        tries = state.tries.get(q.id, 0) + 1
        state.tries[q.id] = tries
        if tries < TRIES_ALLOWED:
            hint = _fmt(q.hint, state) if q.hint else "Look again at your screen and try once more."
            return TurnResult(
                _with_options(f"Not quite. {hint}", q), state,
                {**events, "verdict": "wrong_hint", "tries": tries}, _question_ui(state, q),
            )
        _flag_help(state, q.id)
        reply, ui = _after_question(state, "Let me show you rather than keep you guessing. " + _reveal_text(q))
        return TurnResult(reply, state, {**events, "verdict": "wrong_reveal", "tries": tries, "needed_help": True}, ui)

    if grader.is_bare_confirmation(message):
        state.bare += 1
        if state.bare >= 3:
            text = (
                "I keep asking because I cannot see your screen: I need one fact from it to know the step worked. "
                'Say "give me a hint" if you are unsure, or "just tell me" and I will show the answer.'
            )
        else:
            text = _with_options(f"{_pick(_PROBE_OPENERS, state, state.bare)} {_fmt(q.ask, state)}", q)
        return TurnResult(text, state, {**events, "verdict": "probe", "bare": state.bare}, _question_ui(state, q))

    if grader.is_side_question(message):
        return TurnResult(None, state, {**events, "verdict": "side_question"}, {}, resume_line=_resume_line(state))

    if q.kind == "mcq":
        text = _with_options("Pick one of the options (A, B or C), or tap it.", q)
    elif q.kind in ("number", "report"):
        text = f"I need a number for this one. {_fmt(q.ask, state)}"
    else:
        text = f"Say a little more, in your own words. {_fmt(q.ask, state)}"
    return TurnResult(text, state, {**events, "verdict": "unparsed"}, _question_ui(state, q))


# --------------------------------------------------------------- entry points


def start(state: WalkState) -> TurnResult:
    """Open the walkthrough with the first chapter's curiosity question."""
    if state.mode == "concept":
        from backend.socratic_engine.walkthrough import concept_session

        return concept_session.start(state)
    state.status = "active"
    state.phase = "hook"
    first = SCRIPT.chapters[0].id
    if first not in state.hooked:
        state.hooked.append(first)
    text, ui = _hook_message(state)
    return TurnResult(text, state, {"step_id": state.step_id, "verdict": "start"}, ui)


def show_current(state: WalkState, lead: str = "") -> TurnResult:
    if state.mode == "theory":  # only ever the one pending follow-up; never a software step
        if state.concept:
            text, ui = _concept_message(state, lead)
            return TurnResult(text, state, {"verdict": "resume"}, ui)
        return TurnResult(lead or "What would you like to understand?", state, {"verdict": "resume"}, {})
    if state.mode == "concept":
        from backend.socratic_engine.walkthrough import concept_session

        return concept_session.show_current(state, lead)
    if state.phase == "hook":
        text, ui = _hook_message(state, opener=lead)
    elif state.phase == "quiz" and state.quiz:
        text, ui = _quiz_message(state, lead)
    elif state.phase == "concept" and state.concept:
        text, ui = _concept_message(state, lead)
    elif state.phase == "assess" and state.assess:
        text, ui = _assess_message(state, lead)
    else:
        state.phase = "step"
        text, ui = _step_message(state, lead)
    return TurnResult(text, state, {"step_id": state.step_id, "verdict": "resume"}, ui)


def step_context(state: WalkState) -> str:
    """One line describing where the student is, for grounding a side
    question. Contains only authored text and the step title."""
    if state.mode == "concept":
        from backend.socratic_engine.walkthrough import concept_session

        return concept_session.step_context(state)
    if state.phase == "quiz":
        return "The student is answering a short checkpoint quiz."
    if state.phase == "assess":
        return "The student has finished the experiment and is answering short final reflection questions."
    if state.phase == "concept" and state.concept:
        return (
            f"The student is at {_progress(state)['label']} and was just asked a short conceptual "
            "question about the experiment."
        )
    step = SCRIPT.step(state.step_id)
    line = f"The student is in a guided walkthrough at {_progress(state)['label']}: {step.title}."
    if state.troubleshooting:
        # Authored instruction text only, so the grounded answer diagnoses
        # against what the manual actually asks for at this step.
        line += (
            f" They are reporting a problem with this step, whose instruction is: {_fmt(step.do, state)}"
            " Help with this step only, one actionable check at a time."
        )
    return line


def take_turn(state: WalkState, message: str) -> TurnResult:
    if state.status == "done":
        return TurnResult(None, state, {"verdict": "done_passthrough"})
    if grader.is_resume_phrase(message) and not grader.is_bare_confirmation(message):
        result = show_current(state, "Here is where you are.")
        result.events["verdict"] = "resume_shown"
        return result
    cs = _cs(state)
    cs.tick()
    _save_cs(state, cs)
    if state.mode == "concept" and state.phase not in ("concept", "assess"):
        # Never fall into the software step machine in phone-only mode.
        from backend.socratic_engine.walkthrough import concept_session

        return concept_session.show_current(state, "Here is where you are.")
    if state.phase == "hook":
        result = _turn_hook(state, message)
    elif state.phase == "quiz":
        result = _turn_quiz(state, message)
    elif state.phase == "concept" and state.concept:
        result = _turn_concept(state, message)
    elif state.phase == "assess" and state.assess:
        result = _turn_assess(state, message)
    else:
        result = _handle_answer(state, message)
    if "intervention" in result.ui:
        result.events.setdefault("intervention", result.ui["intervention"])
    return result


def _turn_hook(state: WalkState, message: str) -> TurnResult:
    chapter = _chapter(state)
    events = {"step_id": state.step_id, "chapter": chapter.id}
    if grader.is_side_question(message) and not grader.wants_answer(message):
        return TurnResult(None, state, {**events, "verdict": "side_question"}, {}, resume_line=_resume_line(state))
    if grader.wants_answer(message) or grader.is_skip(message) or conv.classify(message) in (Intent.STEP_REFUSED, Intent.STEP_SKIPPED):
        state.skipped.append(f"hook:{chapter.id}")
        lead, events["verdict"] = "No problem, let's get going.", "hook_skipped"
    else:
        state.predictions[chapter.id] = message.strip()[:300]
        lead, events["verdict"] = _fmt(chapter.hook_ack, state), "hook_answered"
    state.phase = "step"
    text, ui = _enter_step(state, lead)
    return TurnResult(text, state, events, ui)


def _turn_quiz(state: WalkState, message: str) -> TurnResult:
    quiz = state.quiz or {"items": [], "answers": {}}
    events = {"step_id": state.step_id, "phase": "quiz"}
    if grader.is_skip_quiz(message) or grader.is_skip(message) or conv.classify(message) in (Intent.STEP_REFUSED, Intent.STEP_SKIPPED):
        state.skipped.append(f"quiz:{_chapter(state).id}")
        state.quiz = None
        state.steps_since_quiz = 0
        text, ui = _move_to_next(state, "Skipping the checkpoint.")
        return TurnResult(text, state, {**events, "verdict": "quiz_skipped"}, ui)
    open_numbers = [n for n in range(1, len(quiz["items"]) + 1) if str(n) not in quiz["answers"]]
    parsed = _parse_quiz_answers(message, open_numbers)
    if not parsed:
        if grader.is_side_question(message):
            return TurnResult(None, state, {**events, "verdict": "side_question"}, {}, resume_line=_resume_line(state))
        text, ui = _quiz_message(state, "I did not catch an answer.")
        return TurnResult(text, state, {**events, "verdict": "quiz_unparsed"}, ui)
    for n, key in parsed.items():
        item = _find_item(quiz["items"][n - 1]["id"])
        if key in {c.key for c in item.choices}:
            quiz["answers"][str(n)] = key
    state.quiz = quiz
    if len(quiz["answers"]) < len(quiz["items"]):
        text, ui = _quiz_message(state, "Got it. One more.")
        return TurnResult(text, state, {**events, "verdict": "quiz_partial"}, ui)
    feedback = _finish_quiz(state)
    correct = [h["correct"] for h in state.quiz_history[-len(quiz["items"]):]]
    text, ui = _move_to_next(state, feedback)
    return TurnResult(text, state, {**events, "verdict": "quiz_done", "quiz_correct": correct}, ui)
