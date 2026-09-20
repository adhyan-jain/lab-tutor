"""Unified AI Chat routes: modern ChatGPT-style multi-thread chat interface.

Integrates grounded retrieval Q&A, genuine step-by-step Socratic guidance,
and deterministic Tier 1-3 diagnostic checking behind a single chat
surface -- the student never picks a "mode"; `send_message` decides
deterministically which of the three the message is, the same way a
human demonstrator would tell "give me a hint" apart from "here's my
final result" apart from "what does this term mean".

Socratic guidance reuses the EXACT engine and DB rows
`backend/api/socratic_routes.py` uses (`SocraticSession`/
`SocraticAttempt`, `backend.socratic_engine.handle_attempt`/
`compute_reveal`/`tutor_reply`) -- one session per (student, classroom,
experiment, actor_type), looked up/created lazily on first use in any
thread for that experiment, exactly like `POST /api/socratic/session`
does. The old `/api/socratic/*` routes keep working unchanged for
anything that still calls them directly; this file is a second caller
of the same deterministic engine, not a parallel implementation of it.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend import audit, ratelimit
from backend import classrooms as classroom_service
from backend.answer_gate import PrematureRevealError
from backend.auth import Principal, current_user
from backend.auth.dependencies import attribute_login_session_to_classroom
from backend.data_access import FacultyScope, StudentScope
from backend.db import get_session
from backend.extraction import extract_submission
from backend.models import (
    ActorType,
    ChatMessage,
    ChatMessageKind,
    ChatThread,
    Diagnosis,
    Escalation,
    RemedialAction,
    SocraticAttempt,
    SocraticSession,
    Submission,
)
from backend.config import get_settings
from backend.pipeline import run_diagnosis
from backend.socratic_engine.walkthrough import controller as walkthrough_controller
from backend.socratic_engine.walkthrough import service as walkthrough_service
from backend.retrieval.pipeline import QUALITATIVE_EXPERIMENTS, answer_question
from backend.llm import telemetry as llm_telemetry
from backend.router import RouterMode, route_message
from backend.scope import ontology
from backend.socratic_engine import (
    compute_reveal,
    handle_attempt,
    steps_for,
    triage,
    tutor_reply,
)
from backend.tier1_compute.experiments import (
    ManualNotTranscribedError,
    UnknownExperimentError,
    get_plugin,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


def _llm_meta(
    latency_ms: float | None, prompt_tokens: int | None, completion_tokens: int | None
) -> dict:
    """Research metadata for one tutor turn's model call. Empty when no
    backend was actually called (triage, template, extractive answers) --
    never invents a number for a backend that didn't report one."""
    if latency_ms is None and prompt_tokens is None and completion_tokens is None:
        return {}
    from backend.config import get_settings

    settings = get_settings()
    model = {"vertex": settings.vertex_model, "ollama": settings.ollama_model}.get(
        settings.llm_backend, settings.llm_model
    )
    return {
        "llm_backend": settings.llm_backend,
        "llm_model": model,
        "llm_latency_ms": round(latency_ms, 1) if latency_ms is not None else None,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }


def derive_title(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not cleaned:
        return "New chat"
    if len(cleaned) <= 40:
        return cleaned
    return cleaned[:40].rstrip() + "…"


#: A student treats this as one continuous conversation, the same way a
#: ChatGPT-style thread works -- so a follow-up ("what does V_inf mean in
#: that formula?") needs the model to have seen the earlier turn. Bounded
#: in both message count and per-message length so a long-running thread
#: cannot silently balloon a prompt.
MAX_HISTORY_MESSAGES = 12
MAX_HISTORY_CHARS_PER_MESSAGE = 500
#: Tutor turns are long numbered procedures; clipping them at the student
#: limit would cut a walkthrough off before "go back to step 2" can be
#: answered from it.
MAX_HISTORY_CHARS_PER_TUTOR_MESSAGE = 1800


async def _recent_history_text(db: AsyncSession, thread_id: str) -> str:
    """Up to the last `MAX_HISTORY_MESSAGES` turns of this thread, oldest
    first, as plain STUDENT:/TUTOR: lines. Called before the current
    turn's message is inserted, so it never includes it. This is context
    for phrasing only -- it never changes what Tier 1 computes or what a
    Socratic reply is permitted to reveal (see backend/answer_gate)."""
    rows = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.thread_id == thread_id)
                .order_by(ChatMessage.created_at.desc())
                .limit(MAX_HISTORY_MESSAGES)
            )
        ).all()
    )
    rows.reverse()
    lines = [
        f"{'STUDENT' if m.author == 'student' else 'TUTOR'}: "
        f"{m.content[: MAX_HISTORY_CHARS_PER_MESSAGE if m.author == 'student' else MAX_HISTORY_CHARS_PER_TUTOR_MESSAGE]}"
        for m in rows
    ]
    return "\n".join(lines)


class CreateThreadRequest(BaseModel):
    classroom_id: str
    experiment_id: str
    title: str | None = None


class RenameThreadRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class SendChatMessageRequest(BaseModel):
    classroom_id: str
    experiment_id: str
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None


async def _actor_type_for(db: AsyncSession, principal: Principal, classroom_id: str) -> ActorType:
    if principal.is_admin:
        return ActorType.ADMIN_TEST
    if principal.is_faculty:
        return ActorType.FACULTY_TEST
    if await classroom_service.can_act_as_faculty(db, principal, classroom_id):
        return ActorType.FACULTY_TEST
    return ActorType.STUDENT


async def _resolve_session_and_experiment(
    db: AsyncSession, principal: Principal, actor_type: ActorType, classroom_id: str, experiment_id: str
) -> tuple[str | None, str]:
    if actor_type is ActorType.STUDENT:
        scope = StudentScope(db, principal.id)
        if not await scope.is_enrolled(classroom_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Classroom not found"
            )
        active = await classroom_service.get_active_session(db, classroom_id)
        if active is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No active class session for this classroom yet.",
            )
        if active.experiment_id != experiment_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Active class session experiment is {active.experiment_id}, not {experiment_id}.",
            )
        return active.id, active.experiment_id

    fscope = FacultyScope(db, principal.id)
    if not (principal.is_admin or await fscope.is_member(classroom_id)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Classroom not found"
        )
    active = await classroom_service.get_active_session(db, classroom_id)
    class_session_id = active.id if (active and active.experiment_id == experiment_id) else None
    return class_session_id, experiment_id


def _extract_numbers_dict(text: str) -> dict[str, Any]:
    """Parse key=value pairs or plain list of numbers from text for diagnostic processing."""
    result: dict[str, Any] = {}

    # Look for key=value or key: value pairs
    pairs = re.findall(r"([a-zA-Z0-9_]+)\s*[:=]\s*([-\d\.,\s\[\]]+)", text)
    for key, val_str in pairs:
        k = key.strip().lower()
        val_str = val_str.strip(" ,[]")
        if not val_str:
            continue
        if "," in val_str or " " in val_str:
            nums = [p for p in re.split(r"[\s,]+", val_str) if p]
            try:
                result[k] = [float(n) for n in nums]
            except ValueError:
                pass
        else:
            try:
                result[k] = float(val_str)
            except ValueError:
                pass

    return result





@router.get("/threads")
async def list_threads(
    classroom_id: str = Query(...),
    experiment_id: str = Query(...),
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    stmt = (
        select(ChatThread)
        .where(
            ChatThread.user_id == principal.id,
            ChatThread.classroom_id == classroom_id,
            ChatThread.experiment_id == experiment_id,
        )
        .order_by(ChatThread.updated_at.desc())
    )
    threads = list((await db.scalars(stmt)).all())
    return {
        "threads": [
            {
                "id": t.id,
                "title": t.title,
                "classroom_id": t.classroom_id,
                "experiment_id": t.experiment_id,
                "created_at": t.created_at.isoformat(),
                "updated_at": t.updated_at.isoformat(),
            }
            for t in threads
        ]
    }


@router.post("/threads", status_code=status.HTTP_201_CREATED)
async def create_thread(
    body: CreateThreadRequest,
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    actor_type = await _actor_type_for(db, principal, body.classroom_id)
    class_session_id, exp_id = await _resolve_session_and_experiment(
        db, principal, actor_type, body.classroom_id, body.experiment_id
    )

    thread = ChatThread(
        user_id=principal.id,
        classroom_id=body.classroom_id,
        class_session_id=class_session_id,
        experiment_id=exp_id,
        title=(body.title or "New chat").strip(),
    )
    db.add(thread)
    await db.commit()
    return {
        "id": thread.id,
        "title": thread.title,
        "classroom_id": thread.classroom_id,
        "experiment_id": thread.experiment_id,
        "created_at": thread.created_at.isoformat(),
        "updated_at": thread.updated_at.isoformat(),
    }


@router.get("/threads/{thread_id}/messages")
async def get_thread_messages(
    thread_id: str,
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    thread = (
        await db.scalars(
            select(ChatThread).where(
                ChatThread.id == thread_id, ChatThread.user_id == principal.id
            )
        )
    ).first()
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat thread not found"
        )

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.thread_id == thread_id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = list((await db.scalars(stmt)).all())
    return {
        "thread": {
            "id": thread.id,
            "title": thread.title,
            "classroom_id": thread.classroom_id,
            "experiment_id": thread.experiment_id,
        },
        "messages": [
            {
                "id": m.id,
                "author": m.author,
                "content": m.content,
                "kind": m.kind.value,
                "metadata": m.metadata_json or {},
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }


@router.patch("/threads/{thread_id}")
async def rename_thread(
    thread_id: str,
    body: RenameThreadRequest,
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    thread = (
        await db.scalars(
            select(ChatThread).where(
                ChatThread.id == thread_id, ChatThread.user_id == principal.id
            )
        )
    ).first()
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat thread not found"
        )

    thread.title = body.title.strip()
    await db.commit()
    return {"id": thread.id, "title": thread.title}


@router.delete("/threads/{thread_id}")
async def delete_thread(
    thread_id: str,
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    thread = (
        await db.scalars(
            select(ChatThread).where(
                ChatThread.id == thread_id, ChatThread.user_id == principal.id
            )
        )
    ).first()
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat thread not found"
        )

    msgs = (
        await db.scalars(
            select(ChatMessage).where(ChatMessage.thread_id == thread_id)
        )
    ).all()
    for m in msgs:
        await db.delete(m)
    await db.delete(thread)
    await db.commit()
    return {"deleted": True}


async def _get_socratic_session(
    db: AsyncSession,
    user_id: str,
    classroom_id: str,
    experiment_id: str,
    actor_type: ActorType,
) -> SocraticSession | None:
    """Lookup only, never creates -- same key `POST /api/socratic/session`
    uses (student, classroom, experiment, actor_type), so progress made
    through the chat and progress made through the standalone Socratic
    routes are the same session, never two conflicting ones.
    """
    return (
        await db.scalars(
            select(SocraticSession).where(
                SocraticSession.student_id == user_id,
                SocraticSession.classroom_id == classroom_id,
                SocraticSession.experiment_id == experiment_id,
                SocraticSession.actor_type == actor_type,
            )
        )
    ).first()


async def _start_socratic_session(
    db: AsyncSession,
    user_id: str,
    classroom_id: str,
    class_session_id: str | None,
    experiment_id: str,
    actor_type: ActorType,
) -> SocraticSession:
    session = SocraticSession(
        student_id=user_id,
        classroom_id=classroom_id,
        class_session_id=class_session_id,
        experiment_id=experiment_id,
        actor_type=actor_type,
    )
    db.add(session)
    await db.flush()
    return session


async def _handle_socratic_attempt(
    db: AsyncSession,
    principal: Principal,
    plugin,
    session: SocraticSession,
    extracted_dict: dict[str, Any],
    raw_message: str,
) -> tuple[str, ChatMessageKind, dict]:
    """One deterministic step check -- same engine call, same merge-
    across-steps behaviour, as `POST /api/socratic/session/{id}/attempt`.
    """
    numeric_keys = tuple(k for k, v in extracted_dict.items() if not isinstance(v, (list, tuple)))
    series_keys = tuple(k for k, v in extracted_dict.items() if isinstance(v, (list, tuple)))
    extracted = extract_submission(extracted_dict, numeric_fields=numeric_keys, series_fields=series_keys)
    steps = steps_for(plugin)
    total_steps = len(steps)

    if not extracted.ok:
        message = "; ".join(extracted.errors) or "That entry could not be checked."
        return message, ChatMessageKind.SOCRATIC, {
            "type": "socratic",
            "prompt": steps[session.current_step].prompt,
            "current_step": session.current_step,
            "total_steps": total_steps,
            "complete": False,
        }

    current_step_spec = steps[session.current_step]
    submitted = extracted.values.get("reported_value")
    if submitted is None:
        submitted = extracted.values.get("value")
    if submitted is None:
        # A real chat message conflates the step's own required inputs
        # and the student's answer into one flat dict ("zn_conc=1.0,
        # cu_conc=1.0, temperature_k=298, ecell=1.10") -- POST /api/
        # socratic/session/{id}/attempt keeps those as separate `data`/
        # `value` fields, but chat has no such split. Whatever numeric
        # key ISN'T one of this step's declared `requires` is the
        # student's reported answer for it.
        extra_keys = [
            k for k, v in extracted.values.items()
            if k not in current_step_spec.requires and isinstance(v, (int, float))
        ]
        if len(extra_keys) == 1:
            submitted = extracted.values[extra_keys[0]]
    if submitted is None and len(extracted.values) == 1:
        submitted = next(iter(extracted.values.values()))

    merged = dict(session.student_data or {})
    merged.update(extracted.values)

    attempts_on_step = int(
        await db.scalar(
            select(func.count())
            .select_from(SocraticAttempt)
            .where(
                SocraticAttempt.session_id == session.id,
                SocraticAttempt.step_index == session.current_step,
            )
        )
        or 0
    )

    try:
        outcome = handle_attempt(
            plugin,
            step_index=session.current_step,
            attempts_on_step=attempts_on_step,
            student_data=merged,
            submitted_value=submitted if isinstance(submitted, (int, float)) else None,
        )
    except ManualNotTranscribedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    db.add(
        SocraticAttempt(
            session_id=session.id,
            student_id=principal.id,
            step_index=session.current_step,
            submitted_value=submitted if isinstance(submitted, (int, float)) else None,
            passed=outcome.passed,
            hint_level=outcome.hint_level,
            detail=outcome.detail,
        )
    )

    session.student_data = merged
    if outcome.advanced_to is not None:
        session.current_step = outcome.advanced_to
    reply_text = outcome.message

    if outcome.all_steps_complete:
        session.all_steps_complete = True
        if outcome.passed:
            await audit.record(
                db, audit.REVEAL_GRANTED, user_id=principal.id,
                classroom_id=session.classroom_id,
                class_session_id=session.class_session_id,
                detail={"session": session.id, "experiment": session.experiment_id},
            )
            # Every step just verified -- the reveal is deterministic and
            # safe to attach to this same tutor turn, so the student does
            # not need to separately ask for it.
            try:
                reveal_text = compute_reveal(
                    plugin,
                    all_steps_complete=True,
                    student_data=merged,
                    student_final_value=submitted if isinstance(submitted, (int, float)) else None,
                )
                session.revealed = True
                reply_text = f"{reply_text}\n\n{reveal_text}"
            except PrematureRevealError:
                pass

    return reply_text, ChatMessageKind.SOCRATIC, {
        "type": "socratic",
        "prompt": steps[session.current_step].prompt,
        "current_step": session.current_step,
        "total_steps": total_steps,
        "complete": session.all_steps_complete,
        "passed": outcome.passed,
        "hint_level": outcome.hint_level,
    }


async def _handle_socratic_chat_turn(
    db: AsyncSession,
    principal: Principal,
    plugin,
    session: SocraticSession,
    raw_message: str,
    intent: triage.Intent,
    history_text: str = "",
) -> tuple[str, ChatMessageKind, dict]:
    """A question/nudge/confusion turn during an active, incomplete
    guided session -- phrased by `tutor_reply`, which is structurally
    unable to see the final answer (see backend/answer_gate). The hint
    rung is chosen by attempt count, never by the model.
    """
    from backend.rag import templates

    steps = steps_for(plugin)
    step = steps[min(session.current_step, len(steps) - 1)]
    attempts_on_step = int(
        await db.scalar(
            select(func.count())
            .select_from(SocraticAttempt)
            .where(
                SocraticAttempt.session_id == session.id,
                SocraticAttempt.step_index == session.current_step,
            )
        )
        or 0
    )
    hint = templates.hint_text(min(attempts_on_step, 3), step.hints) if attempts_on_step else ""
    hint_to_use = hint or (step.hints[0] if step.hints else templates.refusal_text())

    reply = await tutor_reply(
        student_message=raw_message,
        step_prompt=step.prompt,
        step_index=session.current_step,
        total_steps=len(steps),
        hint_text=hint_to_use,
        attempts_on_this_step=attempts_on_step,
        all_steps_complete=session.all_steps_complete,
        retrieval_query=f"{plugin.title} {step.key}",
        conversation_history=history_text,
        experiment_id=session.experiment_id,
    )


    if reply.redacted:
        await audit.record(
            db, audit.ANSWER_GATE_REDACTION, user_id=principal.id,
            classroom_id=session.classroom_id,
            detail={"session": session.id, "step": session.current_step},
        )
    if session.actor_type is ActorType.STUDENT and triage.needs_staff_attention(reply.intent):
        await audit.record(
            db, audit.STUDENT_FLAG, user_id=principal.id,
            classroom_id=session.classroom_id,
            detail={
                "intent": reply.intent.value,
                "session": session.id,
                "experiment": session.experiment_id,
                "message": raw_message[:500],
            },
        )

    # Exp7/8 can never advance through the step machine (docs/ARCHITECTURE.md
    # Sec 2.1.1), so "Step 1 of 2: ..." above every reply would be a
    # permanent, repeating banner that means nothing to the student.
    step_meta = (
        {}
        if session.experiment_id in QUALITATIVE_EXPERIMENTS
        else {
            "prompt": step.prompt,
            "current_step": session.current_step,
            "total_steps": len(steps),
            "complete": session.all_steps_complete,
        }
    )
    return reply.text, ChatMessageKind.SOCRATIC, {
        "type": "socratic",
        **step_meta,
        "answer_source": reply.source,
        "citations": [
            {"text": c.text, "page": c.page, "tier": c.tier.value} for c in reply.citations
        ],
        **_llm_meta(reply.latency_ms, reply.prompt_tokens, reply.completion_tokens),
    }


async def _handle_final_diagnostic(
    db: AsyncSession,
    principal: Principal,
    plugin,
    actor_type: ActorType,
    body: "SendChatMessageRequest",
    class_session_id: str | None,
    experiment_id: str,
) -> tuple[str, ChatMessageKind, dict]:
    """An independent, one-shot Tier 1-3 diagnostic -- same pipeline as
    POST /api/submissions -- for a student who pastes a finished record
    either before ever engaging guided mode, or after finishing it.
    """
    extracted_dict = _extract_numbers_dict(body.message)
    outcome = await run_diagnosis(
        plugin,
        inputs=extracted_dict,
        reported_value=extracted_dict.get("reported_value"),
        remarks=body.message,
        student_text=body.message,
    )

    submission = Submission(
        student_id=principal.id,
        classroom_id=body.classroom_id,
        class_session_id=class_session_id,
        experiment_id=experiment_id,
        actor_type=actor_type,
        raw_payload={"data": extracted_dict, "remarks": body.message},
        reported_value=outcome.reported_value,
    )
    db.add(submission)
    await db.flush()

    diagnosis = Diagnosis(
        submission_id=submission.id,
        student_id=principal.id,
        classroom_id=body.classroom_id,
        class_session_id=class_session_id,
        status=outcome.status,
        tier=outcome.tier,
        signature_code=outcome.signature_code,
        expected_value=outcome.expected_value,
        reported_value=outcome.reported_value,
        detail=outcome.detail,
        action=outcome.action,
        phrased_text=outcome.phrased_text,
        phrasing_source=outcome.phrasing_source,
        low_confidence=outcome.low_confidence,
    )
    db.add(diagnosis)
    await db.flush()

    # Anything that tells the caller to wait for a demonstrator must
    # actually reach one -- same rule and same shape as
    # backend/api/diagnostic_routes.py::submit.
    needs_human = outcome.escalated or outcome.action is RemedialAction.AWAIT_REVIEW
    if needs_human:
        db.add(
            Escalation(
                diagnosis_id=diagnosis.id,
                classroom_id=body.classroom_id,
                class_session_id=class_session_id,
                student_id=principal.id,
                reason=outcome.escalate_reason
                or (
                    "Diagnosed, but the remedy is human review: "
                    f"{outcome.signature_code or 'unspecified'}"
                ),
            )
        )
        await audit.record(
            db, audit.TIER3_ESCALATION, user_id=principal.id,
            classroom_id=body.classroom_id,
            class_session_id=class_session_id,
            detail={"experiment": experiment_id, "reason": outcome.escalate_reason},
        )

    await audit.record(
        db, audit.DIAGNOSIS_MADE, user_id=principal.id,
        classroom_id=body.classroom_id,
        class_session_id=class_session_id,
        detail={"status": outcome.status.value, "experiment": experiment_id},
    )

    return outcome.phrased_text, ChatMessageKind.DIAGNOSTIC, {
        "type": "diagnostic",
        "status": outcome.status.value,
        "tier": outcome.tier,
        "action": outcome.action.value,
        "explanation": outcome.phrased_text,
        "citation": outcome.citation,
        "low_confidence": outcome.low_confidence,
    }


@router.post("/messages")
async def send_message(
    body: SendChatMessageRequest,
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    request_started = time.monotonic()
    llm_stats = llm_telemetry.begin_request()
    actor_type = await _actor_type_for(db, principal, body.classroom_id)
    class_session_id, experiment_id = await _resolve_session_and_experiment(
        db, principal, actor_type, body.classroom_id, body.experiment_id
    )
    # First-write-wins: a staff sign-in (no classroom yet at login) is
    # attributed to whichever classroom they actually chat in.
    await attribute_login_session_to_classroom(db, principal.id, body.classroom_id)

    limit = ratelimit.check_qa_turn(principal.id)
    if not limit.allowed:
        await audit.record(
            db, audit.RATE_LIMITED, user_id=principal.id,
            classroom_id=body.classroom_id, detail={"scope": "chat"}, commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You are sending messages too quickly; wait a moment.",
            headers={"Retry-After": str(int(limit.retry_after_seconds) + 1)},
        )

    # Get or create thread
    thread: ChatThread | None = None
    if body.thread_id:
        thread = (
            await db.scalars(
                select(ChatThread).where(
                    ChatThread.id == body.thread_id, ChatThread.user_id == principal.id
                )
            )
        ).first()

    if thread is None:
        thread = ChatThread(
            user_id=principal.id,
            classroom_id=body.classroom_id,
            class_session_id=class_session_id,
            experiment_id=experiment_id,
            title=derive_title(body.message),
        )
        db.add(thread)
        await db.flush()
    elif thread.title == "New chat":
        thread.title = derive_title(body.message)

    # Snapshot the conversation so far, before this turn's own message is
    # inserted -- see MAX_HISTORY_MESSAGES.
    history_text = await _recent_history_text(db, thread.id)

    # Record student message
    student_msg = ChatMessage(
        thread_id=thread.id,
        kind=ChatMessageKind.QA,
        session_id=None,
        class_session_id=class_session_id,
        student_id=principal.id,
        classroom_id=body.classroom_id,
        experiment_id=experiment_id,
        actor_type=actor_type,
        author="student",
        content=body.message,
    )
    db.add(student_msg)
    await db.flush()

    # --- Intelligence Routing ---
    # 1. Safety Triage
    intent = triage.classify(body.message)

    # Guided walkthrough (Exp7): deterministic verification of each step,
    # zero model calls for most turns. Safety triage above always wins, and
    # so does a pasted key=value diagnostic record (e.g. a student who
    # skips guidance and submits a finished run directly) -- that always
    # goes to the Tier 1 final-diagnostic path below, walkthrough or not.
    wt_turn = None
    if (
        not triage.short_circuits(intent)
        and not _extract_numbers_dict(body.message)
        and get_settings().walkthrough_enabled
        and experiment_id in walkthrough_service.SUPPORTED_EXPERIMENTS
    ):
        wt_turn = await walkthrough_service.handle_turn(
            db,
            user_id=principal.id,
            classroom_id=body.classroom_id,
            class_session_id=class_session_id,
            experiment_id=experiment_id,
            actor_type=actor_type,
            message=body.message,
        )

    if triage.short_circuits(intent):
        reply_text = triage.fixed_response(intent) or ""
        msg_kind = ChatMessageKind.QA
        meta = {"type": "triage", "intent": intent.value}

        if actor_type is ActorType.STUDENT and triage.needs_staff_attention(intent):
            await audit.record(
                db, audit.STUDENT_FLAG, user_id=principal.id,
                classroom_id=body.classroom_id,
                detail={"intent": intent.value, "message": body.message[:500]},
            )
    elif wt_turn is not None and wt_turn.reply is not None:
        reply_text = wt_turn.reply
        msg_kind = ChatMessageKind.SOCRATIC
        meta = {"type": "walkthrough", "walkthrough": wt_turn.events, "ui": wt_turn.ui}
    elif wt_turn is not None:
        # A genuine side question mid-walkthrough: the normal grounded
        # answer, then a code-written line that brings the student back.
        side_history = f"{history_text}\n[{walkthrough_controller.step_context(wt_turn.state)}]".strip()
        result = await answer_question(
            body.message, active_experiment=experiment_id, conversation_history=side_history
        )
        reply_text = result.text + wt_turn.resume_line
        msg_kind = ChatMessageKind.QA
        meta = {
            "type": "qa",
            "status": result.status.value,
            "citations": [
                {"text": c.text, "page": c.page, "tier": c.tier.value} for c in result.citations
            ],
            "answer_source": result.answer_source,
            "intent": intent.value,
            "walkthrough": wt_turn.events,
            **_llm_meta(result.latency_ms, result.prompt_tokens, result.completion_tokens),
        }
    else:
        # 2. Resolve the Tier 1 plugin (if any) and any numeric data the
        # student typed, in plain text -- "ecell=1.1, temperature_k=298"
        # or "titre volumes: 1, 2, 3, 4".
        extracted_dict = _extract_numbers_dict(body.message)
        plugin = None
        try:
            plugin = get_plugin(experiment_id)
        except UnknownExperimentError:
            pass

        has_socratic_steps = False
        if plugin is not None:
            try:
                steps_for(plugin)
                has_socratic_steps = True
            except ManualNotTranscribedError:
                pass

        socratic_session: SocraticSession | None = None
        if plugin is not None and has_socratic_steps:
            socratic_session = await _get_socratic_session(
                db, principal.id, body.classroom_id, experiment_id, actor_type
            )

        socratic_active = (
            plugin is not None
            and socratic_session is not None
            and not socratic_session.all_steps_complete
        )

        if socratic_active and extracted_dict:
            # 3a. Guided mode was already engaged (the student asked for
            # guidance at some point) and is incomplete: this numeric
            # message is an attempt on the CURRENT step, verified the
            # exact same deterministic way POST
            # /api/socratic/session/{id}/attempt does. This never goes
            # through the router -- a numeric message during active
            # guidance is always Tier 1's to verify, never a routing
            # question.
            reply_text, msg_kind, meta = await _handle_socratic_attempt(
                db, principal, plugin, socratic_session, extracted_dict, body.message
            )
        else:
            # Everything else is routed by the LLM conversational router
            # (backend/router/), which decides *which subsystem* handles
            # this turn using the conversation, not just this one
            # message -- this is what lets a bare "why?" reach the same
            # grounded answer path as the question it's following up on.
            # Any failure (disabled, unavailable, malformed, low
            # confidence) returns None, and the pre-existing
            # deterministic dispatch below runs completely unchanged --
            # see backend/router/router.py's module docstring for the
            # full authority boundary.
            socratic_step_prompt = None
            if socratic_active:
                current_steps = steps_for(plugin)
                socratic_step_prompt = current_steps[
                    min(socratic_session.current_step, len(current_steps) - 1)
                ].prompt

            # Exp7/Exp8 never need the LLM router: everything a student
            # says about them is answered by the same grounded Q&A pipeline
            # (numeric pastes are still caught deterministically below), and
            # the router costs a second model call per message -- which, at
            # the project's Vertex request quota, is the difference between
            # ~12 and ~25 messages a minute for the whole class.
            router_decision = (
                None
                if experiment_id in QUALITATIVE_EXPERIMENTS
                else await route_message(
                    message=body.message,
                    history=history_text,
                    active_experiment=experiment_id,
                    known_experiments={t.id: t.title for t in ontology.routable_topics()},
                    socratic_active=socratic_active,
                    socratic_step_prompt=socratic_step_prompt,
                )
            )

            if router_decision is None:
                # --- Deterministic keyword-based dispatch, unchanged ---
                if socratic_active:
                    # 3b. Guided mode is active and incomplete, but this
                    # message has no data in it -- a question, a request
                    # for a nudge, confusion. Real Socratic conversation:
                    # phrases the CURRENT step's hint (chosen by attempt
                    # count, not by the model) or answers a genuine
                    # question grounded in the manual, and structurally
                    # cannot reveal the answer.
                    reply_text, msg_kind, meta = await _handle_socratic_chat_turn(
                        db, principal, plugin, socratic_session, body.message, intent, history_text
                    )
                elif plugin is not None and extracted_dict:
                    # 4. No guided session exists yet, or it already
                    # finished, and the student pasted numeric data:
                    # treat it as an independent final diagnostic, Tier
                    # 1-3, exactly like POST /api/submissions -- pasting
                    # a finished record straight into chat without ever
                    # asking for guidance is exactly what "provide
                    # experiment values/results naturally in chat"
                    # describes.
                    reply_text, msg_kind, meta = await _handle_final_diagnostic(
                        db, principal, plugin, actor_type, body, class_session_id, experiment_id
                    )
                elif (
                    plugin is not None
                    and has_socratic_steps
                    and socratic_session is None
                    and triage.is_guidance_request(body.message)
                ):
                    # 4b. No data, no guided session yet, but this
                    # experiment has Socratic steps configured AND the
                    # message reads as a guidance request ("guide me",
                    # "help me through this", "what's step 2") rather
                    # than a general question -- this is the first "help
                    # me through this" message, so guided mode starts
                    # now, at step one, the same lazy get-or-create POST
                    # /api/socratic/session does. A plain factual
                    # question ("what is X used for?") falls through to
                    # plain Q&A instead (branch 5) -- asking about the
                    # subject should never itself enrol the student in a
                    # guided walkthrough.
                    socratic_session = await _start_socratic_session(
                        db, principal.id, body.classroom_id, class_session_id, experiment_id, actor_type
                    )
                    reply_text, msg_kind, meta = await _handle_socratic_chat_turn(
                        db, principal, plugin, socratic_session, body.message, intent, history_text
                    )
                else:
                    # 5. Plain grounded Q&A -- theory, procedure,
                    # troubleshooting, software questions, or a
                    # follow-up once guided mode is done.
                    result = await answer_question(
                        body.message, active_experiment=experiment_id, conversation_history=history_text
                    )
                    reply_text = result.text
                    msg_kind = ChatMessageKind.QA
                    meta = {
                        "type": "qa",
                        "status": result.status.value,
                        "citations": [
                            {"text": c.text, "page": c.page, "tier": c.tier.value}
                            for c in result.citations
                        ],
                        "answer_source": result.answer_source,
                        "intent": intent.value,
                        **_llm_meta(
                            result.latency_ms, result.prompt_tokens, result.completion_tokens
                        ),
                    }
            elif (
                router_decision.mode is RouterMode.DIAGNOSTIC
                and plugin is not None
                and extracted_dict
            ):
                # Router identified a diagnostic submission; Tier 1-3
                # still computes the actual verdict, unchanged.
                reply_text, msg_kind, meta = await _handle_final_diagnostic(
                    db, principal, plugin, actor_type, body, class_session_id, experiment_id
                )
            elif (
                router_decision.mode is RouterMode.SOCRATIC
                and plugin is not None
                and has_socratic_steps
                and (socratic_session is None or not socratic_session.all_steps_complete)
            ):
                # Router identified a guidance request; the existing
                # Socratic state machine and deterministic verifier
                # remain authoritative for everything past this point.
                if socratic_session is None:
                    socratic_session = await _start_socratic_session(
                        db, principal.id, body.classroom_id, class_session_id, experiment_id, actor_type
                    )
                reply_text, msg_kind, meta = await _handle_socratic_chat_turn(
                    db, principal, plugin, socratic_session, body.message, intent, history_text
                )
            elif router_decision.mode is RouterMode.CLARIFICATION:
                # Genuinely not enough context to route conservatively --
                # ask, rather than guess an experiment. Deterministic
                # fixed text; no LLM/retrieval call for this branch.
                reply_text = (
                    "I want to make sure I answer the right thing -- could you say a "
                    "bit more, or which experiment this is about?"
                )
                msg_kind = ChatMessageKind.QA
                meta = {"type": "clarification", "router_rationale": router_decision.rationale}
            else:
                # "qa", "out_of_scope", or a diagnostic/socratic guess
                # the deterministic checks above couldn't back up (no
                # numbers to diagnose; no steps to guide through). Both
                # "qa" and "out_of_scope" are deliberately routed the
                # same way: answer_question() re-derives scope via
                # classify_scope()/resolve_status() deterministically and
                # is precision-biased against wrongly refusing a real
                # question, so the router's own out-of-scope call is
                # advisory only -- this pipeline's existing grounding
                # stays the sole authority on whether to actually answer.
                # The only thing the router changes here is the search
                # text: a context-expanded restatement (retrieval_query)
                # for a follow-up that would otherwise search on its own
                # content-free wording. `body.message` (unedited) is
                # still what's stored as the student's turn.
                result = await answer_question(
                    router_decision.retrieval_query or body.message,
                    active_experiment=router_decision.experiment_id or experiment_id,
                    conversation_history=history_text,
                )
                reply_text = result.text
                msg_kind = ChatMessageKind.QA
                meta = {
                    "type": "qa",
                    "status": result.status.value,
                    "citations": [
                        {"text": c.text, "page": c.page, "tier": c.tier.value}
                        for c in result.citations
                    ],
                    "answer_source": result.answer_source,
                    "intent": intent.value,
                    "router_mode": router_decision.mode.value,
                    **_llm_meta(result.latency_ms, result.prompt_tokens, result.completion_tokens),
                }

    # Record Assistant Message. `response_ms` is end-to-end handling time
    # (routing + retrieval + every model call), distinct from the single
    # `llm_latency_ms` of the final answer call.
    meta = {
        **(meta or {}),
        "response_ms": round((time.monotonic() - request_started) * 1000, 1),
        **llm_stats.as_meta(),
    }
    log.info(
        "chat_message llm_calls=%d attempts=%d retries=%d vertex_ok=%s fallback=%s "
        "cache_hit=%s cache_ref=%s cached_tokens=%s model=%s student=%s classroom=%s exp=%s",
        llm_stats.calls, llm_stats.attempts, llm_stats.retry_count,
        llm_stats.vertex_succeeded, llm_stats.fallback_used, llm_stats.cache_hit,
        llm_stats.cache_ref, llm_stats.cached_tokens, llm_stats.model, principal.id,
        body.classroom_id, experiment_id,
    )
    assistant_msg = ChatMessage(
        thread_id=thread.id,
        kind=msg_kind,
        session_id=None,
        class_session_id=class_session_id,
        student_id=principal.id,
        classroom_id=body.classroom_id,
        experiment_id=experiment_id,
        actor_type=actor_type,
        author="tutor",
        content=reply_text,
        metadata_json=meta,
    )
    db.add(assistant_msg)
    thread.title = thread.title  # touched
    await db.commit()

    return {
        "thread_id": thread.id,
        "thread_title": thread.title,
        "message": {
            "id": assistant_msg.id,
            "author": "tutor",
            "content": reply_text,
            "kind": msg_kind.value,
            "metadata": meta,
            "created_at": assistant_msg.created_at.isoformat(),
        },
    }
