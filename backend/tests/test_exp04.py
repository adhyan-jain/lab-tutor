"""Experiment 4 -- potentiometric iron-in-steel: synthetic self-consistency checks.

The manual prints no worked numeric example for Exp 4 (both titration tables
are blank), so there is no Category 1 golden case. These tests build an
S-curve with the endpoint at a chosen volume, then check the plugin recovers
that endpoint and applies the manual's formulas:

    N(steel) = 0.05 * V / 20,   Fe (g/100 mL) = N * 55.85 * 100 / 1000
"""

from __future__ import annotations

import math

import pytest

from backend.tier1_compute.experiments import get_plugin
from backend.tier1_compute.experiments.exp04 import (
    ENDPOINT_CHECKER,
    FINAL_CHECKER,
    iron_g_per_100ml,
)
from backend.tier1_compute.shared.types import Outcome

_TRUE_ENDPOINT = 11.4
# Coarse early additions, fine ones through the jump -- normal practice.
_VOLUMES = [0, 2, 4, 6, 8, 10, 10.6, 11.0, 11.2, 11.4, 11.6, 11.8, 12.2, 13, 14]
_EMF = [350 + 250 * math.tanh((v - _TRUE_ENDPOINT) / 0.25) for v in _VOLUMES]
_DATA = {"kmno4_volume_ml": _VOLUMES, "emf_mv": _EMF}

# Hand calculation from the manual's formulas for V = 11.4 mL:
#   N = 0.05 * 11.4 / 20 = 0.0285 ;  Fe = 0.0285 * 55.85 * 100 / 1000 = 0.1591725
_FE_AT_TRUE_ENDPOINT = 0.1591725


def test_iron_formula_matches_the_hand_calculation():
    assert iron_g_per_100ml(11.4) == pytest.approx(_FE_AT_TRUE_ENDPOINT, rel=1e-9)


def test_endpoint_is_recovered_from_raw_emf_and_volume():
    assert ENDPOINT_CHECKER.find_endpoint(_DATA) == pytest.approx(_TRUE_ENDPOINT, abs=0.15)


def test_correct_iron_content_passes():
    result = FINAL_CHECKER.check(_DATA, reported=_FE_AT_TRUE_ENDPOINT)
    assert result.outcome is Outcome.PASS


def test_wrong_iron_content_fails():
    result = FINAL_CHECKER.check(_DATA, reported=_FE_AT_TRUE_ENDPOINT * 10)  # mL/L slip
    assert not result.passed


def test_wrong_endpoint_volume_fails_the_endpoint_step():
    result = ENDPOINT_CHECKER.check(_DATA, reported=10.0)
    assert not result.passed


def test_plugin_is_wired_and_has_a_final_step():
    plugin = get_plugin("exp04")
    assert plugin.is_ready
    result = plugin.check_step(2, _DATA, _FE_AT_TRUE_ENDPOINT)
    assert result.passed


def test_flat_response_is_not_called_an_endpoint():
    flat = {"kmno4_volume_ml": _VOLUMES, "emf_mv": [350.0 + 0.01 * v for v in _VOLUMES]}
    result = FINAL_CHECKER.check(flat, reported=_FE_AT_TRUE_ENDPOINT)
    assert not result.passed


def test_too_few_readings_is_invalid_input():
    short = {"kmno4_volume_ml": [0, 5, 10], "emf_mv": [300, 320, 600]}
    assert FINAL_CHECKER.validate(short)
