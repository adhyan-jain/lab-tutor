"""The conversational router's failure posture: `route_message` must
return `None` -- never a partially-trusted decision -- for every way an
LLM call can go wrong, since every caller's safety depends on `None`
meaning "run the deterministic dispatch instead."
"""

from __future__ import annotations

import pytest

from backend.config import reload_settings
from backend.router.router import route_message
from backend.router.schema import RouterMode

pytestmark = pytest.mark.asyncio

KNOWN = {"exp02": "Ester hydrolysis kinetics", "exp07": "Orbital contributions"}


async def test_valid_decision_parses(fake_llm):
    fake_llm.reply = (
        '{"mode": "qa", "experiment_id": "exp02", "confidence": 0.85, '
        '"needs_retrieval": true, "retrieval_query": "why is V_inf needed", '
        '"rationale": "follow-up"}'
    )
    decision = await route_message(
        message="why?",
        history="STUDENT: what is v_inf\nTUTOR: it is the titre volume at completion.",
        active_experiment="exp02",
        known_experiments=KNOWN,
    )
    assert decision is not None
    assert decision.mode is RouterMode.QA
    assert decision.experiment_id == "exp02"
    assert decision.retrieval_query == "why is V_inf needed"


async def test_strips_markdown_fences(fake_llm):
    fake_llm.reply = (
        '```json\n{"mode": "qa", "experiment_id": null, "confidence": 0.7, '
        '"needs_retrieval": true}\n```'
    )
    decision = await route_message(
        message="what is a burette", history="", active_experiment=None, known_experiments=KNOWN
    )
    assert decision is not None
    assert decision.mode is RouterMode.QA


async def test_none_on_malformed_json(fake_llm):
    fake_llm.reply = "That is a great question, let me think about it."
    decision = await route_message(
        message="why?", history="", active_experiment="exp02", known_experiments=KNOWN
    )
    assert decision is None


async def test_none_on_missing_required_field(fake_llm):
    # No "confidence" -- required by the schema.
    fake_llm.reply = '{"mode": "qa", "experiment_id": "exp02"}'
    decision = await route_message(
        message="why?", history="", active_experiment="exp02", known_experiments=KNOWN
    )
    assert decision is None


async def test_none_on_invalid_mode_string(fake_llm):
    fake_llm.reply = '{"mode": "definitely_not_a_mode", "confidence": 0.9}'
    decision = await route_message(
        message="why?", history="", active_experiment="exp02", known_experiments=KNOWN
    )
    assert decision is None


async def test_unknown_experiment_id_is_discarded_not_rejected(fake_llm):
    """An invented experiment id is stripped, but a decision that is
    otherwise valid and confident is still usable -- the caller's own
    `active_experiment` fallback covers the gap."""
    fake_llm.reply = '{"mode": "qa", "experiment_id": "exp99", "confidence": 0.9}'
    decision = await route_message(
        message="why?", history="", active_experiment="exp02", known_experiments=KNOWN
    )
    assert decision is not None
    assert decision.experiment_id is None


async def test_none_below_confidence_threshold(fake_llm):
    fake_llm.reply = '{"mode": "qa", "experiment_id": "exp02", "confidence": 0.1}'
    decision = await route_message(
        message="why?", history="", active_experiment="exp02", known_experiments=KNOWN
    )
    assert decision is None


async def test_none_when_llm_unavailable(fake_llm):
    fake_llm.available = False
    decision = await route_message(
        message="why?", history="", active_experiment="exp02", known_experiments=KNOWN
    )
    assert decision is None


async def test_none_when_disabled(monkeypatch, fake_llm):
    monkeypatch.setenv("LABTUTOR_ROUTER_ENABLED", "false")
    reload_settings()
    try:
        decision = await route_message(
            message="why?", history="", active_experiment="exp02", known_experiments=KNOWN
        )
        assert decision is None
        assert fake_llm.calls == [], "a disabled router must not call the backend at all"
    finally:
        monkeypatch.delenv("LABTUTOR_ROUTER_ENABLED", raising=False)
        reload_settings()


async def test_clarification_forces_no_retrieval(fake_llm):
    fake_llm.reply = (
        '{"mode": "clarification", "confidence": 0.9, "needs_retrieval": true}'
    )
    decision = await route_message(
        message="why?", history="", active_experiment=None, known_experiments=KNOWN
    )
    assert decision is not None
    assert decision.needs_retrieval is False
