import json

import pytest

from batterylife.config import RESULTS_DIR
from batterylife.lifecycle.grading import assess, grade, lifecycle_stage
from batterylife.lifecycle.sustainability import value


@pytest.mark.parametrize("soh,r,cycles,expected", [
    (0.85, 1.1, 500, "A"),
    (0.85, 1.5, 500, "B"),      # too much resistance growth for EV re-use
    (0.75, 1.2, 250, "B"),
    (0.75, 1.2, 100, "C"),      # not enough cycles left for daily storage
    (0.65, 1.8, None, "C"),
    (0.55, 1.1, None, "D"),
    (0.70, 2.5, None, "D"),     # resistance beyond any re-use limit
])
def test_grade_rules(soh, r, cycles, expected):
    assert grade(soh, r, cycles)[0] == expected


def test_low_confidence_when_interval_crosses_boundary():
    a = assess(0.81, 0.77, 1.1, 400, 350)
    assert a.grade == "A" and a.grade_at_lower_bound == "B" and a.confidence == "low"
    assert "laboratory" in a.recommendation


def test_high_confidence_and_service_years():
    a = assess(0.75, 0.73, 1.2, 600, 500)
    assert a.grade == "B" and a.confidence == "high"
    assert a.service_years == pytest.approx(2.0)


def test_lifecycle_stage():
    assert lifecycle_stage(0.9) == "First life"
    assert lifecycle_stage(0.7) == "Second-life window"
    assert lifecycle_stage(0.5) == "End of life"


def test_value_routes():
    reuse, rec = value("B", 0.75, "nasa"), value("D", 0.5, "nasa")
    assert reuse["route"] == "re-use" and reuse["co2_avoided_kg_pack"] > 0
    assert rec["route"] == "recycle" and rec["co2_avoided_kg_pack"] == 0
    assert reuse["value_usd_pack"] > rec["value_usd_pack"]


@pytest.mark.skipif(not (RESULTS_DIR / "second_life_summary.json").exists(), reason="run the pipeline first")
def test_saved_grading_quality():
    s = json.loads((RESULTS_DIR / "second_life_summary.json").read_text())
    assert s["all"]["agreement"] > 0.75
    assert s["all"]["agreement_when_high_confidence"] >= s["all"]["agreement"]
