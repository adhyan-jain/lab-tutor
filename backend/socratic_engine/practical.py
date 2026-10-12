"""Practical progress for one chat thread: what is done, what is now, what is next.

The steps are the experiment's own authored procedure (`plugin.steps()`, the
same StepSpecs the Socratic engine runs, each confirmed against the manual) --
never a generic list and never invented. There is no model call here.

Two kinds of experiment, with different rules for "done":

* "verified" -- experiments whose Socratic step machine advances (numeric
  experiments). A step is done only when the existing engine has verified the
  student's reported data and moved `SocraticSession.current_step` on. The
  tracker only reads that; nothing here can advance it.
* "self_report" -- Exp8 (and Exp7 outside phone-only mode), whose step machine
  never advances by design (docs/ARCHITECTURE.md 2.1.1): there is no data to
  check per step. The student says a step is done; the backend records it in
  this thread's ConversationState, one step at a time and only for the current
  step, so a repeated or out-of-order request never moves it. It is the
  student's report, not proof that a software operation succeeded.

Exp7 in phone-only mode has no practical steps (students have no software), so
it has no tracker. The key-ideas quiz is separate state (`walkthrough_progress`,
`ConversationState.pending`) and is never read or written here.
"""

from __future__ import annotations

from typing import Any

from backend.config import get_settings

#: Experiments whose step machine cannot advance (see module docstring).
SELF_REPORT_EXPERIMENTS = frozenset({"exp07", "exp08"})


class CompletionRejected(ValueError):
    """A completion the backend will not record. The message is shown to the
    student, so it is plain English."""


def _plugin(experiment_id: str):
    from backend.tier1_compute.experiments import get_plugin

    try:
        return get_plugin(experiment_id)
    except Exception:
        return None


def steps(experiment_id: str) -> list[dict[str, Any]]:
    """The experiment's authored steps as tracker rows, or [] if it has none."""
    plugin = _plugin(experiment_id)
    try:
        specs = plugin.steps() if plugin is not None else ()
    except Exception:
        specs = ()
    return [
        {"index": i, "title": spec.key.replace("_", " ").capitalize(), "detail": spec.prompt}
        for i, spec in enumerate(specs)
    ]


def kind(experiment_id: str) -> str | None:
    """"verified", "self_report", or None when there is no practical to track."""
    if not steps(experiment_id):
        return None
    if experiment_id == "exp07" and get_settings().phone_only:
        return None
    return "self_report" if experiment_id in SELF_REPORT_EXPERIMENTS else "verified"


def record_completion(state, experiment_id: str, step_index: int) -> None:
    """Record that the student finished `step_index` (self-report experiments
    only). Accepts exactly the current step; anything else is rejected and
    nothing changes, so a double tap or a stale page cannot skip a step."""
    if kind(experiment_id) != "self_report":
        raise CompletionRejected(
            "Steps in this experiment move on when you report your results in the chat."
        )
    total = len(steps(experiment_id))
    done = int(getattr(state, "practical_done", 0) or 0)
    if done >= total:
        raise CompletionRejected("You have already completed every step of this practical.")
    if step_index != done:
        raise CompletionRejected(
            f"That is not your current step. You are on step {done + 1}; refresh to see the latest progress."
        )
    state.practical_done = done + 1


def tracker(
    experiment_id: str,
    *,
    practical_done: int = 0,
    session_step: int | None = None,
    session_complete: bool = False,
) -> dict[str, Any]:
    """The payload the chat UI renders. `practical_done` is the self-reported
    count; `session_step`/`session_complete` come from the verified Socratic
    session (None when the student has not started it)."""
    k = kind(experiment_id)
    rows = steps(experiment_id)
    if k is None:
        return {"available": False, "experiment_id": experiment_id}
    total = len(rows)
    if k == "verified":
        done = total if session_complete else max(0, min(session_step or 0, total))
        started = session_step is not None
    else:
        done = max(0, min(int(practical_done or 0), total))
        started = done > 0
    complete = done >= total
    for row in rows:
        row["status"] = "completed" if row["index"] < done else "current" if row["index"] == done else "upcoming"
    return {
        "available": True,
        "experiment_id": experiment_id,
        "kind": k,
        "steps": rows,
        "total": total,
        "completed": done,
        "current": None if complete else done,
        "status": "complete" if complete else ("in_progress" if started else "not_started"),
    }
