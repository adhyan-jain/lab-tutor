"""Unified Chat routes tests: /api/chat/threads and /api/chat/messages.
"""

from __future__ import annotations

import pytest

from backend.auth import session as session_cookie

pytestmark = pytest.mark.asyncio


def auth(token: str) -> dict[str, str]:
    return {"Cookie": f"{session_cookie.COOKIE_NAME}={token}"}


def _fake_answer_result(*, experiment_id: str | None, text: str = "a grounded answer"):
    """A minimal, valid AnswerResult for spying on answer_question() calls
    without depending on the real retrieval/LLM pipeline."""
    from backend.retrieval.pipeline import AnswerResult
    from backend.scope.classifier import ScopeDecision
    from backend.scope.normalize import NormalizedQuery
    from backend.scope.statuses import AnswerStatus, ScopeLevel

    decision = ScopeDecision(
        level=ScopeLevel.DIRECT,
        query=NormalizedQuery(raw=text, text=text),
        experiment_id=experiment_id,
    )
    return AnswerResult(
        status=AnswerStatus.IN_SCOPE_SUPPORTED, decision=decision, text=text, citations=()
    )


async def _classroom_with_active_session(
    client, prof_token: str, experiment_id: str = "exp01"
) -> tuple[str, str, str]:
    created = await client.post(
        "/api/classrooms", json={"name": "Chat Classroom"}, headers=auth(prof_token)
    )
    classroom_id = created.json()["id"]
    student_code = created.json()["student_join_code"]
    started = await client.post(
        f"/api/classrooms/{classroom_id}/sessions/start",
        json={"experiment_id": experiment_id},
        headers=auth(prof_token),
    )
    assert started.status_code == 201
    return classroom_id, student_code, started.json()["session_id"]


class TestChatThreads:
    async def test_thread_lifecycle(self, client, make_user):
        _, prof = await make_user("prof.chat@vit.ac.in")
        classroom_id, student_code, _ = await _classroom_with_active_session(client, prof, "exp01")
        _, student = await make_user("student.chat@vitstudent.ac.in")
        await client.post(
            "/api/classrooms/join", json={"join_code": student_code}, headers=auth(student)
        )

        # 1. Create thread
        created = await client.post(
            "/api/chat/threads",
            json={"classroom_id": classroom_id, "experiment_id": "exp01", "title": "My first chat"},
            headers=auth(student),
        )
        assert created.status_code == 201
        thread_id = created.json()["id"]
        assert created.json()["title"] == "My first chat"

        # 2. List threads
        listed = await client.get(
            f"/api/chat/threads?classroom_id={classroom_id}&experiment_id=exp01",
            headers=auth(student),
        )
        assert listed.status_code == 200
        threads = listed.json()["threads"]
        assert any(t["id"] == thread_id for t in threads)

        # 3. Rename thread
        renamed = await client.patch(
            f"/api/chat/threads/{thread_id}",
            json={"title": "Renamed Chat Title"},
            headers=auth(student),
        )
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "Renamed Chat Title"

        # 4. Delete thread
        deleted = await client.delete(
            f"/api/chat/threads/{thread_id}",
            headers=auth(student),
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True

    async def test_send_message_in_chat(self, client, make_user):
        _, prof = await make_user("prof.chat2@vit.ac.in")
        classroom_id, student_code, _ = await _classroom_with_active_session(client, prof, "exp01")
        _, student = await make_user("student.chat2@vitstudent.ac.in")
        await client.post(
            "/api/classrooms/join", json={"join_code": student_code}, headers=auth(student)
        )

        # Send message
        resp = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp01",
                "message": "What is the principle of EMF measurement?",
            },
            headers=auth(student),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "thread_id" in data
        assert "message" in data
        assert data["message"]["author"] == "tutor"
        assert "content" in data["message"]

        # Fetch messages for thread
        thread_id = data["thread_id"]
        msgs_resp = await client.get(
            f"/api/chat/threads/{thread_id}/messages",
            headers=auth(student),
        )
        assert msgs_resp.status_code == 200
        msgs = msgs_resp.json()["messages"]
        assert len(msgs) == 2  # user + tutor
        assert msgs[0]["author"] == "student"
        assert msgs[1]["author"] == "tutor"

    async def test_diagnostic_message_in_chat(self, client, make_user):
        _, prof = await make_user("prof.chat3@vit.ac.in")
        classroom_id, student_code, _ = await _classroom_with_active_session(client, prof, "exp01")
        _, student = await make_user("student.chat3@vitstudent.ac.in")
        await client.post(
            "/api/classrooms/join", json={"join_code": student_code}, headers=auth(student)
        )

        # Send diagnostic readings message with valid exp01 fields
        resp = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp01",
                "message": "Here are my readings: ecell=1.1, reported_value=-212.3",
            },
            headers=auth(student),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"]["kind"] == "diagnostic"
        assert "metadata" in data["message"]
        assert "status" in data["message"]["metadata"]

    async def test_step_calculation_guidance_in_chat(self, client, make_user):
        _, prof = await make_user("prof.chat4@vit.ac.in")
        classroom_id, student_code, _ = await _classroom_with_active_session(client, prof, "exp01")
        _, student = await make_user("student.chat4@vitstudent.ac.in")
        await client.post(
            "/api/classrooms/join", json={"join_code": student_code}, headers=auth(student)
        )

        resp = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp01",
                "message": "Can you guide me through step 1 calculation?",
            },
            headers=auth(student),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"]["kind"] in ("qa", "socratic")
        meta = data["message"]["metadata"]
        assert meta["type"] == "socratic"
        assert meta["prompt"] is not None
        assert meta["current_step"] is not None
        assert meta["total_steps"] == 2
        assert "could not find enough" not in data["message"]["content"]

    async def test_exp02_socratic_and_diagnostic_flow(self, client, make_user):
        _, prof = await make_user("prof.exp02@vit.ac.in")
        classroom_id, student_code, _ = await _classroom_with_active_session(client, prof, "exp02")
        _, student = await make_user("student.exp02@vitstudent.ac.in")
        await client.post(
            "/api/classrooms/join", json={"join_code": student_code}, headers=auth(student)
        )

        # 1. Socratic flow: calculation guidance question
        resp_qa = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp02",
                "message": "Can you guide me through step 1 calculation for rate constant k1 prime?",
            },
            headers=auth(student),
        )
        assert resp_qa.status_code == 200
        data_qa = resp_qa.json()
        assert data_qa["message"]["kind"] in ("qa", "socratic")
        meta_qa = data_qa["message"]["metadata"]
        assert meta_qa["type"] == "socratic"
        assert meta_qa["current_step"] is not None
        assert meta_qa["total_steps"] == 2
        assert meta_qa["prompt"] is not None

        # 2. Diagnostic flow: numeric readings submission
        resp_diag = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp02",
                "message": "time_min: 0, 10, 20, 30, titre_volume_ml: 10.0, 15.0, 18.0, 20.0, titre_volume_at_completion_ml: 30.0, reported_value: 0.02",
            },
            headers=auth(student),
        )
        assert resp_diag.status_code == 200
        data_diag = resp_diag.json()
        assert data_diag["message"]["kind"] in ("diagnostic", "socratic")
        assert "passed" in data_diag["message"]["metadata"] or "status" in data_diag["message"]["metadata"]

    async def test_exp03_socratic_and_diagnostic_flow(self, client, make_user):
        _, prof = await make_user("prof.exp03@vit.ac.in")
        classroom_id, student_code, _ = await _classroom_with_active_session(client, prof, "exp03")
        _, student = await make_user("student.exp03@vitstudent.ac.in")
        await client.post(
            "/api/classrooms/join", json={"join_code": student_code}, headers=auth(student)
        )

        # 1. Socratic flow
        resp_qa = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp03",
                "message": "Can you guide me through step 1 calculation for unknown concentration?",
            },
            headers=auth(student),
        )
        assert resp_qa.status_code == 200
        data_qa = resp_qa.json()
        assert data_qa["message"]["kind"] in ("qa", "socratic")
        meta_qa = data_qa["message"]["metadata"]
        assert meta_qa["type"] == "socratic"
        assert meta_qa["current_step"] is not None
        assert meta_qa["total_steps"] == 2
        assert meta_qa["prompt"] is not None

        # 2. Diagnostic flow
        resp_diag = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp03",
                "message": "standard_conc_ppm: 2, 4, 6, 8, standard_absorbance: 0.1, 0.2, 0.3, 0.4, unknown_absorbance: 0.25, reported_value: 5.0",
            },
            headers=auth(student),
        )
        assert resp_diag.status_code == 200
        data_diag = resp_diag.json()
        assert data_diag["message"]["kind"] in ("diagnostic", "socratic")
        assert "passed" in data_diag["message"]["metadata"] or "status" in data_diag["message"]["metadata"]

    async def test_exp07_socratic_and_diagnostic_flow(self, client, make_user):
        _, prof = await make_user("prof.exp07@vit.ac.in")
        classroom_id, student_code, _ = await _classroom_with_active_session(client, prof, "exp07")
        _, student = await make_user("student.exp07@vitstudent.ac.in")
        await client.post(
            "/api/classrooms/join", json={"join_code": student_code}, headers=auth(student)
        )

        # 1. Socratic flow
        resp_qa = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp07",
                "message": "Can you guide me through step 1 calculation for HOMO and LUMO energies?",
            },
            headers=auth(student),
        )
        assert resp_qa.status_code == 200
        data_qa = resp_qa.json()
        assert data_qa["message"]["kind"] in ("qa", "socratic")
        meta_qa = data_qa["message"]["metadata"]
        assert meta_qa["type"] == "socratic"
        # Exp7/8 can never advance through steps, so no "Step N of M" banner
        # metadata is sent (it would repeat above every reply).
        assert "current_step" not in meta_qa
        assert "total_steps" not in meta_qa
        assert "prompt" not in meta_qa

        # 2. Diagnostic flow
        resp_diag = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp07",
                "message": "energy_before: -40.5, energy_after: -40.52, homo_energy: -0.25, lumo_energy: 0.05",
            },
            headers=auth(student),
        )
        assert resp_diag.status_code == 200
        data_diag = resp_diag.json()
        assert data_diag["message"]["kind"] in ("diagnostic", "socratic")
        assert "passed" in data_diag["message"]["metadata"] or "status" in data_diag["message"]["metadata"]

    async def test_exp08_socratic_and_diagnostic_flow(self, client, make_user):
        _, prof = await make_user("prof.exp08@vit.ac.in")
        classroom_id, student_code, _ = await _classroom_with_active_session(client, prof, "exp08")
        _, student = await make_user("student.exp08@vitstudent.ac.in")
        await client.post(
            "/api/classrooms/join", json={"join_code": student_code}, headers=auth(student)
        )

        # 1. Socratic flow
        resp_qa = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp08",
                "message": "Can you guide me through step 3 calculation for cyclohexane conformer energies?",
            },
            headers=auth(student),
        )
        assert resp_qa.status_code == 200
        data_qa = resp_qa.json()
        assert data_qa["message"]["kind"] in ("qa", "socratic")
        meta_qa = data_qa["message"]["metadata"]
        assert meta_qa["type"] == "socratic"
        # Exp7/8 can never advance through steps, so no "Step N of M" banner
        # metadata is sent (it would repeat above every reply).
        assert "current_step" not in meta_qa
        assert "total_steps" not in meta_qa
        assert "prompt" not in meta_qa

        # 2. Diagnostic flow
        resp_diag = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp08",
                "message": "ethane_staggered: -79.8, ethane_eclipsed: -79.795, cyclohexane_chair: -235.5, cyclohexane_boat: -235.48",
            },
            headers=auth(student),
        )
        assert resp_diag.status_code == 200
        data_diag = resp_diag.json()
        assert data_diag["message"]["kind"] in ("diagnostic", "socratic")
        assert "passed" in data_diag["message"]["metadata"] or "status" in data_diag["message"]["metadata"]


class TestConversationalRouter:
    """The LLM router layered in front of send_message's dispatch.

    `fake_llm` only patches `backend.router.router.get_backend`, not
    `backend.retrieval.pipeline`'s -- so a router-routed "qa" turn still
    resolves its actual answer text through the real (unconfigured, so
    immediately-LLMUnavailable) backend, same as every other test in this
    file. These tests assert on *routing* (which branch ran, what
    `answer_question` was called with), not on answer wording.
    """

    async def _classroom_and_student(self, client, make_user, tag: str, experiment_id="exp01"):
        _, prof = await make_user(f"prof.router.{tag}@vit.ac.in")
        classroom_id, student_code, _ = await _classroom_with_active_session(
            client, prof, experiment_id
        )
        _, student = await make_user(f"student.router.{tag}@vitstudent.ac.in")
        await client.post(
            "/api/classrooms/join", json={"join_code": student_code}, headers=auth(student)
        )
        return classroom_id, student

    async def test_normal_question_routes_via_router(self, client, make_user, fake_llm, monkeypatch):
        classroom_id, student = await self._classroom_and_student(client, make_user, "normal")
        fake_llm.reply = (
            '{"mode": "qa", "experiment_id": "exp01", "confidence": 0.9, '
            '"needs_retrieval": true}'
        )
        calls = []

        async def spy(message, *, active_experiment=None, conversation_history=""):
            calls.append((message, active_experiment))
            return _fake_answer_result(experiment_id=active_experiment)

        monkeypatch.setattr("backend.api.chat_routes.answer_question", spy)

        resp = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp01",
                "message": "What is the principle of EMF measurement?",
            },
            headers=auth(student),
        )
        assert resp.status_code == 200
        assert calls == [("What is the principle of EMF measurement?", "exp01")]
        assert resp.json()["message"]["metadata"]["router_mode"] == "qa"

    async def test_why_followup_reaches_qa_with_inherited_experiment_and_expanded_query(
        self, client, make_user, fake_llm, monkeypatch
    ):
        """The core repro case: a bare "why?" must not fall back to the
        deterministic "could not find enough" template just because its
        own text has nothing to search on -- the router should inherit
        the experiment and hand answer_question a context-expanded query."""
        classroom_id, student = await self._classroom_and_student(client, make_user, "why")

        def scripted_reply(user_prompt: str) -> str:
            if "why?" in user_prompt.lower():
                return (
                    '{"mode": "qa", "experiment_id": "exp01", "confidence": 0.9, '
                    '"needs_retrieval": true, '
                    '"retrieval_query": "why is the Nernst equation used for EMF measurement"}'
                )
            return '{"mode": "qa", "experiment_id": "exp01", "confidence": 0.9, "needs_retrieval": true}'

        fake_llm.reply = scripted_reply
        calls = []

        async def spy(message, *, active_experiment=None, conversation_history=""):
            calls.append((message, active_experiment, conversation_history))
            return _fake_answer_result(experiment_id=active_experiment)

        monkeypatch.setattr("backend.api.chat_routes.answer_question", spy)

        turn1 = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp01",
                "message": "What is the Nernst equation used for?",
            },
            headers=auth(student),
        )
        assert turn1.status_code == 200
        thread_id = turn1.json()["thread_id"]

        turn2 = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp01",
                "thread_id": thread_id,
                "message": "why?",
            },
            headers=auth(student),
        )
        assert turn2.status_code == 200

        # Second call: the router-supplied, context-expanded query was
        # used for retrieval/classification, not the raw "why?" -- and
        # the experiment was inherited, not lost.
        second_message, second_experiment, second_history = calls[1]
        assert second_message != "why?"
        assert "nernst" in second_message.lower() or "emf" in second_message.lower()
        assert second_experiment == "exp01"
        assert "Nernst equation" in second_history

        # The student's own turn is still stored verbatim, unexpanded.
        msgs = await client.get(f"/api/chat/threads/{thread_id}/messages", headers=auth(student))
        contents = [m["content"] for m in msgs.json()["messages"]]
        assert "why?" in contents

    async def test_what_does_that_mean_reaches_qa_not_clarification(
        self, client, make_user, fake_llm, monkeypatch
    ):
        classroom_id, student = await self._classroom_and_student(client, make_user, "whatmean")
        fake_llm.reply = (
            '{"mode": "qa", "experiment_id": "exp01", "confidence": 0.85, '
            '"needs_retrieval": true, "retrieval_query": "what does Ecell mean"}'
        )
        calls = []

        async def spy(message, *, active_experiment=None, conversation_history=""):
            calls.append(message)
            return _fake_answer_result(experiment_id=active_experiment)

        monkeypatch.setattr("backend.api.chat_routes.answer_question", spy)

        resp = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp01",
                "message": "what does that mean?",
            },
            headers=auth(student),
        )
        assert resp.status_code == 200
        assert resp.json()["message"]["metadata"]["router_mode"] == "qa"
        assert calls == ["what does Ecell mean"]

    async def test_explain_again_reaches_qa(self, client, make_user, fake_llm, monkeypatch):
        classroom_id, student = await self._classroom_and_student(client, make_user, "explainagain")
        fake_llm.reply = '{"mode": "qa", "experiment_id": "exp01", "confidence": 0.85, "needs_retrieval": true}'

        async def spy(message, *, active_experiment=None, conversation_history=""):
            return _fake_answer_result(experiment_id=active_experiment)

        monkeypatch.setattr("backend.api.chat_routes.answer_question", spy)

        resp = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp01",
                "message": "explain that again",
            },
            headers=auth(student),
        )
        assert resp.status_code == 200
        assert resp.json()["message"]["metadata"]["router_mode"] == "qa"

    async def test_contextual_diagnostic_message_routes_to_tier1(
        self, client, make_user, fake_llm
    ):
        classroom_id, student = await self._classroom_and_student(client, make_user, "diag")
        fake_llm.reply = '{"mode": "diagnostic", "experiment_id": "exp01", "confidence": 0.9}'

        resp = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp01",
                "message": "Here are my readings: ecell=1.1, reported_value=-212.3",
            },
            headers=auth(student),
        )
        assert resp.status_code == 200
        assert resp.json()["message"]["kind"] == "diagnostic"

    async def test_contextual_socratic_request_starts_session(self, client, make_user, fake_llm):
        """A phrasing with none of the deterministic guidance keywords
        ("guide me", "step N", ...) must still be able to start guided
        mode when the router recognises the intent."""
        classroom_id, student = await self._classroom_and_student(client, make_user, "socratic")
        fake_llm.reply = '{"mode": "socratic", "experiment_id": "exp01", "confidence": 0.9}'

        resp = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp01",
                "message": "Can we work through this together?",
            },
            headers=auth(student),
        )
        assert resp.status_code == 200
        meta = resp.json()["message"]["metadata"]
        assert meta["type"] == "socratic"
        assert meta["current_step"] == 0

    async def test_experiment_comparison_switches_experiment(
        self, client, make_user, fake_llm, monkeypatch
    ):
        classroom_id, student = await self._classroom_and_student(client, make_user, "compare")
        # Active session is exp01; the router decides the conversation has
        # moved to exp02.
        fake_llm.reply = '{"mode": "qa", "experiment_id": "exp02", "confidence": 0.8}'
        calls = []

        async def spy(message, *, active_experiment=None, conversation_history=""):
            calls.append(active_experiment)
            return _fake_answer_result(experiment_id=active_experiment)

        monkeypatch.setattr("backend.api.chat_routes.answer_question", spy)

        resp = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp01",
                "message": "What about the other method?",
            },
            headers=auth(student),
        )
        assert resp.status_code == 200
        assert calls == ["exp02"]

    async def test_explicit_ood_question_still_goes_through_grounding(
        self, client, make_user, fake_llm, monkeypatch
    ):
        """out_of_scope is advisory only: the deterministic scope
        classifier inside answer_question remains the sole authority on
        whether to actually refuse, so the router's call still reaches
        it rather than short-circuiting on its own say-so."""
        classroom_id, student = await self._classroom_and_student(client, make_user, "ood")
        fake_llm.reply = '{"mode": "out_of_scope", "confidence": 0.9}'
        calls = []

        async def spy(message, *, active_experiment=None, conversation_history=""):
            calls.append(message)
            return _fake_answer_result(experiment_id=active_experiment)

        monkeypatch.setattr("backend.api.chat_routes.answer_question", spy)

        resp = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp01",
                "message": "what's a good GPU for gaming?",
            },
            headers=auth(student),
        )
        assert resp.status_code == 200
        assert calls == ["what's a good GPU for gaming?"]

    async def test_safety_request_never_reaches_the_router(
        self, client, make_user, monkeypatch
    ):
        classroom_id, student = await self._classroom_and_student(client, make_user, "safety")
        called = False

        async def spy(*args, **kwargs):
            nonlocal called
            called = True
            return None

        monkeypatch.setattr("backend.api.chat_routes.route_message", spy)

        resp = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp01",
                "message": "I spilled acid on my hand",
            },
            headers=auth(student),
        )
        assert resp.status_code == 200
        assert called is False
        assert resp.json()["message"]["metadata"]["type"] == "triage"

    async def test_new_thread_no_context_routes_to_clarification(
        self, client, make_user, fake_llm
    ):
        classroom_id, student = await self._classroom_and_student(client, make_user, "clarify")
        fake_llm.reply = '{"mode": "clarification", "confidence": 0.9}'

        resp = await client.post(
            "/api/chat/messages",
            json={"classroom_id": classroom_id, "experiment_id": "exp01", "message": "why?"},
            headers=auth(student),
        )
        assert resp.status_code == 200
        meta = resp.json()["message"]["metadata"]
        assert meta["type"] == "clarification"

    async def test_router_never_called_on_stale_closed_session(
        self, client, make_user, monkeypatch
    ):
        _, prof = await make_user("prof.router.stale@vit.ac.in")
        classroom_id, student_code, session_id = await _classroom_with_active_session(
            client, prof, "exp01"
        )
        _, student = await make_user("student.router.stale@vitstudent.ac.in")
        await client.post(
            "/api/classrooms/join", json={"join_code": student_code}, headers=auth(student)
        )
        ended = await client.post(
            f"/api/classrooms/{classroom_id}/sessions/{session_id}/end", headers=auth(prof)
        )
        assert ended.status_code == 200

        called = False

        async def spy(*args, **kwargs):
            nonlocal called
            called = True
            return None

        monkeypatch.setattr("backend.api.chat_routes.route_message", spy)

        resp = await client.post(
            "/api/chat/messages",
            json={"classroom_id": classroom_id, "experiment_id": "exp01", "message": "why?"},
            headers=auth(student),
        )
        assert resp.status_code == 409
        assert called is False

    async def test_thread_history_does_not_cross_threads(self, client, make_user):
        """A second thread must never see a first thread's history -- the
        router relies on this to not leak one conversation's context into
        an unrelated one."""
        from backend.api.chat_routes import _recent_history_text
        from backend.db import get_sessionmaker

        classroom_id, student = await self._classroom_and_student(client, make_user, "isolation")

        first = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp01",
                "message": "This is thread one's secret context.",
            },
            headers=auth(student),
        )
        assert first.status_code == 200

        second = await client.post(
            "/api/chat/messages",
            json={
                "classroom_id": classroom_id,
                "experiment_id": "exp01",
                "message": "A brand new unrelated thread.",
            },
            headers=auth(student),
        )
        assert second.status_code == 200
        second_thread_id = second.json()["thread_id"]

        async with get_sessionmaker()() as db:
            history = await _recent_history_text(db, second_thread_id)
        assert "secret context" not in history

