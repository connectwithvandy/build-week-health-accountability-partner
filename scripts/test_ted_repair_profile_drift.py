"""Which calorie number Ted counts a day against, when the two stores differ.

The gate keeps its own `tracking_kcal` and Convex keeps the agreed target.
Where they disagree, `_daily_overview` uses the gate's, so that is the number
the user is actually judged by — and on 17 Sep 2026 it was the wrong one for
five people. venky was trying to gain at 2,100 and was counted against his
1,910 maintenance, which removes the surplus his goal needs. Hari was told
1,870 and was being scored against 2,200.

The repair is narrow on purpose, and most of these tests defend the narrowness
rather than the fix: `ted-target-direction.py` is explicit that a number
somebody was told to their face is not this script's to overwrite. The one
case that IS safe is when the gate's figure is merely its own maintenance
estimate, because that is the tell that no target was ever agreed there.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SOURCE = Path(__file__).resolve().parent / "ted-repair-profile-drift.py"


def _load():
    spec = importlib.util.spec_from_file_location("ted_repair_profile_drift", _SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load()


class TestTheGateHasNothing:
    def test_an_empty_gate_takes_the_agreed_target(self, mod):
        """Without this the meal card loses its "left" figure and its bar."""
        change = mod.tracked_kcal_change({}, 1500)
        assert change == (1500, "tracking_kcal missing -> 1500")

    def test_empty_strings_count_as_nothing(self, mod):
        record = {"tracking_kcal": "", "maintenance_kcal": ""}
        assert mod.tracked_kcal_change(record, 1500)[0] == 1500


class TestTheGateFellBackToMaintenance:
    def test_venky_gets_the_target_he_was_told(self, mod):
        record = {"tracking_kcal": 1910, "maintenance_kcal": 1910}
        value, note = mod.tracked_kcal_change(record, 2100)
        assert value == 2100
        assert "was only maintenance" in note

    def test_hari_stops_being_scored_above_his_plan(self, mod):
        record = {"tracking_kcal": 2200, "maintenance_kcal": 2200}
        assert mod.tracked_kcal_change(record, 1870)[0] == 1870

    def test_a_one_calorie_difference_still_counts(self, mod):
        """Roshan's was 2,440 against 2,450. Small, and still the wrong number."""
        record = {"tracking_kcal": 2440, "maintenance_kcal": 2440}
        assert mod.tracked_kcal_change(record, 2450)[0] == 2450


class TestWhatItMustNeverTouch:
    def test_a_gate_target_that_is_not_maintenance_is_left_alone(self, mod):
        """A real second opinion. That needs a conversation, not a write.

        Gourav is the live case this protects: his 1,550 is below his resting
        burn, it is deliberate, and it is not this script's to move.
        """
        record = {"tracking_kcal": 1550, "maintenance_kcal": 2292}
        assert mod.tracked_kcal_change(record, 1740) is None

    def test_agreement_is_not_a_change(self, mod):
        record = {"tracking_kcal": 2100, "maintenance_kcal": 2100}
        assert mod.tracked_kcal_change(record, 2100) is None

    def test_no_convex_target_means_no_write(self, mod):
        """Nothing was ever agreed, so there is nothing to copy."""
        for convex in (None, "", 0, -1, "1800"):
            assert mod.tracked_kcal_change({"tracking_kcal": 1910,
                                            "maintenance_kcal": 1910}, convex) is None

    def test_a_gate_with_only_a_maintenance_figure_is_left_alone(self, mod):
        """No tracked figure to correct, and maintenance is not a target."""
        record = {"maintenance_kcal": 2010}
        assert mod.tracked_kcal_change(record, 2100) is None

    def test_a_gate_with_only_a_tracked_figure_is_left_alone(self, mod):
        """Nothing proves it was a fallback rather than an agreed number."""
        record = {"tracking_kcal": 2010}
        assert mod.tracked_kcal_change(record, 2100) is None


class TestFloatsDoNotCauseSpuriousWrites:
    def test_a_float_equal_to_its_int_is_still_agreement(self, mod):
        record = {"tracking_kcal": 2100.0, "maintenance_kcal": 2100.0}
        assert mod.tracked_kcal_change(record, 2100.4) is None
