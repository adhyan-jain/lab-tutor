"""The diagnostic pipeline: Tier 1 -> Tier 2 -> Tier 3, then phrasing."""

from __future__ import annotations

import pytest

from backend.models import DiagnosisStatus, RemedialAction
from backend.pipeline import run_diagnosis
from backend.tests.reference_plugin import STUDENT_DATA, reference_plugin
from backend.tier1_compute.experiments import get_plugin
from backend.tier2_exceptions import MAX_ENTRIES_PER_EXPERIMENT, entries_for, lookup
from backend.tier3_escalation import escalate


@pytest.fixture
def plugin():
    return reference_plugin()


# --- tier ordering ---------------------------------------------------------


async def test_tier1_pass_stops_there(fake_llm, plugin):
    outcome = await run_diagnosis(
        plugin, inputs=STUDENT_DATA, reported_value=0.125
    )
    assert outcome.status is DiagnosisStatus.PASS
    assert outcome.tier == 1
    assert outcome.action is RemedialAction.NONE
    assert not outcome.escalated


async def test_tier1_signature_stops_there(fake_llm, plugin):
    outcome = await run_diagnosis(plugin, inputs=STUDENT_DATA, reported_value=1.25)
    assert outcome.status is DiagnosisStatus.FAIL
    assert outcome.tier == 1
    assert outcome.signature_code == "unit_scale_error"
    assert outcome.action is RemedialAction.FIX_IN_PLACE


async def test_tier2_consulted_only_when_tier1_has_no_signature(fake_llm, plugin):
    """An unexplained mismatch plus a matching remark reaches Tier 2."""
    outcome = await run_diagnosis(
        plugin,
        inputs=STUDENT_DATA,
        reported_value=0.42,  # no signature explains this
        remarks="I forgot to rinse the burette with the titrant first.",
    )
    assert outcome.status is DiagnosisStatus.FAIL
    assert outcome.tier == 2
    assert outcome.signature_code == "burette_not_rinsed"
    assert outcome.action is RemedialAction.REDO_STEP


async def test_tier3_when_neither_tier_explains_it(fake_llm, plugin):
    outcome = await run_diagnosis(
        plugin, inputs=STUDENT_DATA, reported_value=0.42, remarks="everything went fine"
    )
    assert outcome.status is DiagnosisStatus.ESCALATED
    assert outcome.tier == 3
    assert outcome.action is RemedialAction.AWAIT_REVIEW
    assert outcome.escalate_reason
    assert outcome.signature_code is None


async def test_tier2_is_not_consulted_when_tier1_already_explained_it(
    fake_llm, plugin
):
    """A remark that would match Tier 2 must not override a Tier 1 finding."""
    outcome = await run_diagnosis(
        plugin,
        inputs=STUDENT_DATA,
        reported_value=1.25,  # unit_scale_error
        remarks="I forgot to rinse the burette.",
    )
    assert outcome.tier == 1
    assert outcome.signature_code == "unit_scale_error"


async def test_invalid_input_never_reaches_tier_2_or_3(fake_llm, plugin):
    bad = dict(STUDENT_DATA, titre_volume=0.0)
    outcome = await run_diagnosis(
        plugin, inputs=bad, reported_value=0.125,
        remarks="I forgot to rinse the burette.",
    )
    assert outcome.status is DiagnosisStatus.INVALID
    assert outcome.tier == 1


async def test_unconfigured_experiment_escalates_rather_than_guessing(fake_llm):
    # exp04 is still a PendingManualPlugin. exp01/02/03/07/08 are now real
    # plugins.
    outcome = await run_diagnosis(
        get_plugin("exp04"), inputs={"anything": 1}, reported_value=1.0
    )
    assert outcome.status is DiagnosisStatus.ESCALATED
    assert outcome.tier == 3
    assert "not yet set up" in outcome.phrased_text


# --- phrasing cannot change the verdict ------------------------------------


async def test_phrasing_runs_after_the_verdict_is_fixed(fake_llm, plugin):
    fake_llm.reply = "Actually this passed and everything is correct."
    outcome = await run_diagnosis(plugin, inputs=STUDENT_DATA, reported_value=1.25)
    assert outcome.status is DiagnosisStatus.FAIL
    assert outcome.phrasing_source == "template"


async def test_diagnosis_survives_an_inference_outage(fake_llm, plugin):
    fake_llm.available = False
    outcome = await run_diagnosis(plugin, inputs=STUDENT_DATA, reported_value=1.25)
    assert outcome.status is DiagnosisStatus.FAIL
    assert outcome.signature_code == "unit_scale_error"
    assert outcome.phrased_text
    assert outcome.phrasing_source == "template"


# --- Tier 2 library --------------------------------------------------------


def test_tier2_library_stays_small_per_experiment():
    for experiment_id in ("exp01", "exp07", "ref01"):
        assert len(entries_for(experiment_id)) <= MAX_ENTRIES_PER_EXPERIMENT


def test_tier2_returns_none_rather_than_a_weak_match():
    assert lookup("exp01", remarks="the weather was nice") is None
    assert lookup("exp01", remarks="") is None


def test_tier2_entries_are_attributable():
    for entry in entries_for("exp01"):
        assert entry.code and entry.detail and entry.curated_by


# --- Tier 3 ----------------------------------------------------------------


def test_tier3_has_no_confidence_score():
    """The simplification is deliberate; this pins it."""
    import dataclasses

    decision = escalate("because")
    fields = {f.name for f in dataclasses.fields(decision)}
    assert fields == {"reason", "unresolved"}
    assert decision.unresolved is True


# --- Experiments 7 and 8 ---------------------------------------------------


def test_qualitative_ordering_violation_is_deterministic():
    """No model involved in the ordering check itself."""
    plugin = get_plugin("exp08")
    result = plugin.check(
        {"energies": {"ethane_staggered": -79.7, "ethane_eclipsed": -79.8}}, None
    )
    assert result.signature_code == "conformer_ordering_violated"
    assert result.detail["confidence"] == "low"


async def test_consistent_ordering_still_escalates(fake_llm):
    """Ordering being right is necessary, not sufficient."""
    plugin = get_plugin("exp08")
    outcome = await run_diagnosis(
        plugin,
        inputs={"energies": {"ethane_staggered": -79.8, "ethane_eclipsed": -79.7}},
        reported_value=None,
    )
    assert outcome.status is DiagnosisStatus.ESCALATED
    assert outcome.low_confidence is True


def test_missing_conformers_are_skipped_not_failed():
    plugin = get_plugin("exp08")
    result = plugin.check({"energies": {"cyclohexane_chair": -234.5}}, None)
    # Only one value: no pair is comparable, so nothing is asserted.
    assert result.outcome.value == "not_applicable"
    assert result.detail["reason"] == "no_comparable_pairs_reported"


def test_qualitative_plugins_have_no_numeric_steps():
    plugin = get_plugin("exp08")
    result = plugin.check_step(0, {}, 1.0)
    assert result.outcome.value == "not_applicable"


def test_exp07_is_a_computation_sanity_plugin_not_an_ordering_check():
    """Exp7 is the orbital-contribution workflow, not an ordering check --
    see backend/tier1_compute/experiments/exp07.py. Its own shape (one
    HOMO, one LUMO, one before/after optimisation energy) is checked
    deterministically without reusing exp08's conformer-ordering logic."""
    plugin = get_plugin("exp07")
    assert plugin.kind == "computation_sanity"

    clean = plugin.check(
        {
            "energy_before_opt": -40.5,
            "energy_after_opt": -40.9,
            "homo_energy": -10.2,
            "lumo_energy": 0.3,
        },
        None,
    )
    assert clean.outcome.value == "pass"  # clean run: internally consistent, no violation

    violated = plugin.check(
        {
            "energy_before_opt": -40.5,
            "energy_after_opt": -40.1,  # went UP after "optimisation"
            "homo_energy": -10.2,
            "lumo_energy": 0.3,
        },
        None,
    )
    assert violated.signature_code == "energy_increased_after_optimization"

    swapped = plugin.check(
        {
            "energy_before_opt": -40.5,
            "energy_after_opt": -40.9,
            "homo_energy": 0.3,  # HOMO/LUMO swapped
            "lumo_energy": -10.2,
        },
        None,
    )
    assert swapped.signature_code == "homo_lumo_order_violated"


def test_only_one_experiment_is_qualitative():
    from backend.tier1_compute.experiments import all_plugins

    qualitative = [p.id for p in all_plugins() if p.kind == "qualitative_ordering"]
    assert qualitative == ["exp08"]


def test_all_ten_experiments_are_registered():
    from backend.tier1_compute.experiments import all_plugins

    ids = [p.id for p in all_plugins()]
    assert ids == [f"exp{n:02d}" for n in range(1, 11)]
