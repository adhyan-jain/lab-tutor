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
import re
from dataclasses import asdict, dataclass, field
from typing import Any

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


def new_state(student_key: str) -> WalkState:
    seed = int(hashlib.sha256(student_key.encode()).hexdigest()[:8], 16)
    return WalkState(seed=seed)


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


def _chips(q: Question | None) -> list[str]:
    chips = ["Give me a hint"] if q is not None and q.hint else []
    return chips + ["Why do this step?", "Something looks different"]


def _base_ui(state: WalkState) -> dict[str, Any]:
    return {"progress": _progress(state), "phase": state.phase}


def _question_ui(state: WalkState, q: Question, **extra: Any) -> dict[str, Any]:
    ui = {**_base_ui(state), "kind": "step", "question_id": q.id, "chips": _chips(q), **extra}
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
    return text, {**_base_ui(state), "kind": "hook", "chips": ["Just tell me"]}


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
    return text, {**_base_ui(state), "kind": "quiz", "quiz": ui_items, "chips": ["Skip quiz"]}


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


# ------------------------------------------------------------- advancing


def _advance(state: WalkState, lead: str) -> tuple[str, dict[str, Any]]:
    """Mark the current step done; show the checkpoint or the next thing."""
    step = SCRIPT.step(state.step_id)
    state.steps_done += 1
    state.steps_since_quiz += 1
    state.tries.pop(step.id, None)
    state.bare = 0
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
        return _closing_message(state, lead)
    state.step_id, state.combo_index = nxt
    state.pending = "evidence"
    state.phase = "step"
    new_chapter = _chapter(state).id
    if new_chapter != old_chapter and new_chapter not in state.hooked:
        state.phase = "hook"
        state.hooked.append(new_chapter)
        return _hook_message(state, opener=lead)
    return _step_message(state, lead)


def _closing_message(state: WalkState, lead: str) -> tuple[str, dict[str, Any]]:
    state.status = "done"
    state.phase = "done"
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

    if grader.is_skip(message):
        _flag_help(state, q.id)
        state.skipped.append(step.id)
        reply, ui = _advance(state, 'Skipped, and noted. Say "back" any time to return to it.')
        return TurnResult(reply, state, {**events, "verdict": "skip", "needed_help": True}, ui)

    if grader.wants_answer(message):
        _flag_help(state, q.id)
        reply, ui = _after_question(state, _reveal_text(q))
        return TurnResult(reply, state, {**events, "verdict": "reveal", "needed_help": True}, ui)

    lowered = message.strip().lower().rstrip("?.! ")
    if lowered in ("hint", "give me a hint", "a hint", "hint please") and q.hint:
        text = _with_options(f"**Hint:** {_fmt(q.hint, state)}", q)
        return TurnResult(text, state, {**events, "verdict": "hint_requested"}, _question_ui(state, q))

    if lowered in ("why", "why do this step", "why this step", "why are we doing this", "why do we do this"):
        text = _with_options(f"**Why this step:** {_fmt(step.why, state)}\n\nWhen you are ready: {_fmt(q.ask, state)}", q)
        return TurnResult(text, state, {**events, "verdict": "why_requested"}, _question_ui(state, q))

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

    if grader.is_problem(message) and step.stuck:
        text = _with_options(f"{_fmt(step.stuck, state)}\n\nWhen it works, tell me: {_fmt(q.ask, state)}", q)
        return TurnResult(text, state, {**events, "verdict": "stuck"}, _question_ui(state, q))

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
    state.status = "active"
    state.phase = "hook"
    first = SCRIPT.chapters[0].id
    if first not in state.hooked:
        state.hooked.append(first)
    text, ui = _hook_message(state)
    return TurnResult(text, state, {"step_id": state.step_id, "verdict": "start"}, ui)


def show_current(state: WalkState, lead: str = "") -> TurnResult:
    if state.phase == "hook":
        text, ui = _hook_message(state, opener=lead)
    elif state.phase == "quiz" and state.quiz:
        text, ui = _quiz_message(state, lead)
    else:
        state.phase = "step"
        text, ui = _step_message(state, lead)
    return TurnResult(text, state, {"step_id": state.step_id, "verdict": "resume"}, ui)


def step_context(state: WalkState) -> str:
    """One line describing where the student is, for grounding a side
    question. Contains only authored text and the step title."""
    if state.phase == "quiz":
        return "The student is answering a short checkpoint quiz."
    step = SCRIPT.step(state.step_id)
    return f"The student is in a guided walkthrough at {_progress(state)['label']}: {step.title}."


def take_turn(state: WalkState, message: str) -> TurnResult:
    if state.status == "done":
        return TurnResult(None, state, {"verdict": "done_passthrough"})
    if grader.is_resume_phrase(message) and not grader.is_bare_confirmation(message):
        result = show_current(state, "Here is where you are.")
        result.events["verdict"] = "resume_shown"
        return result
    if state.phase == "hook":
        return _turn_hook(state, message)
    if state.phase == "quiz":
        return _turn_quiz(state, message)
    return _handle_answer(state, message)


def _turn_hook(state: WalkState, message: str) -> TurnResult:
    chapter = _chapter(state)
    events = {"step_id": state.step_id, "chapter": chapter.id}
    if grader.is_side_question(message) and not grader.wants_answer(message):
        return TurnResult(None, state, {**events, "verdict": "side_question"}, {}, resume_line=_resume_line(state))
    if grader.wants_answer(message) or grader.is_skip(message):
        state.skipped.append(f"hook:{chapter.id}")
        lead, events["verdict"] = "No problem, let's get going.", "hook_skipped"
    else:
        state.predictions[chapter.id] = message.strip()[:300]
        lead, events["verdict"] = _fmt(chapter.hook_ack, state), "hook_answered"
    state.phase = "step"
    text, ui = _step_message(state, lead)
    return TurnResult(text, state, events, ui)


def _turn_quiz(state: WalkState, message: str) -> TurnResult:
    quiz = state.quiz or {"items": [], "answers": {}}
    events = {"step_id": state.step_id, "phase": "quiz"}
    if grader.is_skip_quiz(message) or grader.is_skip(message):
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
