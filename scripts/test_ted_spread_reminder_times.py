"""This script edits when real reminders reach real people.

Everything here defends one line: it may only move a job that is sitting on a
REMINDER_MENU default for its owner. A daily review, a supplement the user
named, a free-form job, or a default somebody has already moved must all come
back untouched, because Ted said those times out loud and moving one would be
announcing one number and storing another.

The timezone tests are the ones that matter most. A job for a London user is
stored in this laptop's clock, so a naive "is the minute :00?" check would read
their 13:00 as 17:30 and skip it, or worse, match a different user's real time.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_SOURCE = REPO / "scripts" / "ted-spread-reminder-times.py"


def _load():
    spec = importlib.util.spec_from_file_location("ted_spread_reminder_times", _SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load()


@pytest.fixture(scope="module")
def gates():
    os.environ.setdefault("TED_GATES_DISABLE_CRON", "1")
    sys.path.insert(0, str(REPO / "hermes"))
    import ted_safety_gates

    return ted_safety_gates


KEY = "whatsapp:sha256:" + "a" * 52  # last 12 chars are the job-name suffix
SUFFIX = KEY[-12:]


@pytest.fixture
def keys():
    return {SUFFIX: KEY}


def _job(name: str, expr: str) -> dict:
    return {"id": "abc", "name": name, "schedule": {"kind": "cron", "expr": expr}}


def _menu_expr(gates, slot: str) -> str:
    return gates._cron_expression(slot, gates._user_time_zone(KEY))


class TestWhatItAgreesToMove:
    def test_moves_a_job_sitting_on_the_menu_default(self, mod, gates, keys):
        slots = mod.menu_slots(gates)
        job = _job(f"ted:{SUFFIX}:meals", _menu_expr(gates, slots["meals"]))
        plan = mod.planned_change(gates, job, slots, keys)
        assert plan is not None
        old, new, who, rid = plan
        assert rid == "meals" and who == KEY and new != old

    def test_the_new_time_is_the_one_the_gate_would_pick(self, mod, gates, keys):
        """So a later re-save by picks_gate edits nothing. If these two ever
        disagree the job is rewritten on every re-save, forever."""
        slots = mod.menu_slots(gates)
        job = _job(f"ted:{SUFFIX}:water_1", _menu_expr(gates, slots["water_1"]))
        _old, new, _who, _rid = mod.planned_change(gates, job, slots, keys)
        moved = gates._spread_default_time(slots["water_1"], KEY)
        assert new == gates._cron_expression(moved, gates._user_time_zone(KEY))

    def test_the_hour_is_unchanged(self, mod, gates, keys):
        slots = mod.menu_slots(gates)
        for rid in slots:
            job = _job(f"ted:{SUFFIX}:{rid}", _menu_expr(gates, slots[rid]))
            plan = mod.planned_change(gates, job, slots, keys)
            if plan is None:
                continue  # this user's offset is 0 for that slot
            old, new, _who, _rid = plan
            assert old.split()[1] == new.split()[1], f"{rid} changed hour"


class TestWhatItRefusesToTouch:
    def test_a_daily_review_is_never_moved(self, mod, gates, keys):
        """Ted repeats this one back: "9pm it is ✅"."""
        slots = mod.menu_slots(gates)
        job = _job(f"ted:{SUFFIX}:daily_review", "0 21 * * *")
        assert mod.planned_change(gates, job, slots, keys) is None

    def test_a_free_form_job_is_never_moved(self, mod, gates, keys):
        slots = mod.menu_slots(gates)
        for name in ("Vitamin D reminder", "hanuman chalisa 40-day reminder"):
            assert mod.planned_change(gates, _job(name, "0 13 * * *"), slots, keys) is None

    def test_a_default_somebody_already_moved_is_left_alone(self, mod, gates, keys):
        """The live case: ted:83e97a6589a3:supplements sits at 15:00, not the
        menu's 09:00, because its owner moved it."""
        slots = mod.menu_slots(gates)
        job = _job(f"ted:{SUFFIX}:supplements", "0 15 * * *")
        assert mod.planned_change(gates, job, slots, keys) is None

    def test_an_unknown_user_is_skipped_not_guessed(self, mod, gates):
        """Without the full key the minute would differ from the gate's, so the
        job would be rewritten again on the user's next re-save."""
        slots = mod.menu_slots(gates)
        job = _job("ted:ffffffffffff:meals", _menu_expr(gates, slots["meals"]))
        assert mod.planned_change(gates, job, slots, {}) is None

    def test_a_zero_offset_user_is_reported_as_no_change(self, mod, gates):
        """One user in fifteen draws offset 0. That is nothing to do, not a
        job to rewrite to the value it already holds."""
        slots = mod.menu_slots(gates)
        zero = next(
            (k for k in (f"whatsapp:sha256:{i:052d}" for i in range(400))
             if gates._spread_default_time("13:00", k) == "13:00"),
            None,
        )
        assert zero is not None, "no zero-offset key found to test with"
        job = _job(f"ted:{zero[-12:]}:meals", _menu_expr(gates, slots["meals"]))
        assert mod.planned_change(gates, job, slots, {zero[-12:]: zero}) is None


class TestTimeZones:
    def test_a_job_is_compared_in_its_owners_zone(self, mod, gates, keys, monkeypatch):
        """A London user's 13:00 is not 13:00 on this laptop. Comparing against
        a naive "0 13 * * *" would skip them, or match somebody else's time."""
        from zoneinfo import ZoneInfo

        monkeypatch.setattr(gates, "_user_time_zone", lambda key: ZoneInfo("Europe/London"))
        slots = mod.menu_slots(gates)
        london_expr = gates._cron_expression(slots["meals"], ZoneInfo("Europe/London"))
        assert london_expr != "0 13 * * *", "fixture is not proving anything"
        plan = mod.planned_change(gates, _job(f"ted:{SUFFIX}:meals", london_expr), slots, keys)
        assert plan is not None

    def test_a_kolkata_expression_is_not_matched_for_a_london_user(
        self, mod, gates, keys, monkeypatch
    ):
        from zoneinfo import ZoneInfo

        monkeypatch.setattr(gates, "_user_time_zone", lambda key: ZoneInfo("Europe/London"))
        slots = mod.menu_slots(gates)
        assert mod.planned_change(gates, _job(f"ted:{SUFFIX}:meals", "0 13 * * *"), slots, keys) is None


class TestTheMenuItReadsFrom:
    def test_the_ids_match_what_picks_gate_writes(self, mod, gates):
        """picks_gate names water's two slots water_1 and water_2. If these
        drift apart the migration silently matches nothing."""
        assert mod.menu_slots(gates) == {
            "meals": "13:00",
            "water_1": "11:00",
            "water_2": "16:00",
            "supplements": "09:00",
            "movement": "18:00",
        }


class TestTheRoundTrip:
    """Reversible means the exact expression comes back, not roughly."""

    def test_spread_then_revert_returns_the_original_expression(self, mod, gates, keys):
        slots = mod.menu_slots(gates)
        for rid, slot in slots.items():
            original = _menu_expr(gates, slot)
            plan = mod.planned_change(gates, _job(f"ted:{SUFFIX}:{rid}", original), slots, keys)
            if plan is None:
                continue
            _old, new, _who, _rid = plan
            back = mod.revert_change(gates, _job(f"ted:{SUFFIX}:{rid}", new), slots, keys)
            assert back is not None, f"{rid} could not be reverted"
            assert back[1] == original

    def test_revert_ignores_a_job_that_is_not_on_our_time(self, mod, gates, keys):
        """Somebody moved it by hand after we ran. Putting it back on the menu
        minute would be undoing their change, not ours."""
        slots = mod.menu_slots(gates)
        assert mod.revert_change(gates, _job(f"ted:{SUFFIX}:meals", "23 13 * * *"), slots, keys) is None

    def test_revert_never_touches_a_daily_review(self, mod, gates, keys):
        slots = mod.menu_slots(gates)
        assert mod.revert_change(gates, _job(f"ted:{SUFFIX}:daily_review", "0 21 * * *"), slots, keys) is None

    def test_revert_is_not_a_second_spread(self, mod, gates, keys):
        """Running --revert twice must be a no-op, not a bounce back and forth."""
        slots = mod.menu_slots(gates)
        original = _menu_expr(gates, slots["meals"])
        plan = mod.planned_change(gates, _job(f"ted:{SUFFIX}:meals", original), slots, keys)
        assert plan is not None
        _old, new, _who, _rid = plan
        once = mod.revert_change(gates, _job(f"ted:{SUFFIX}:meals", new), slots, keys)
        twice = mod.revert_change(gates, _job(f"ted:{SUFFIX}:meals", once[1]), slots, keys)
        assert twice is None


class TestTheWriteItself:
    """The gap that let a broken call reach a real run.

    Every other test here checks which jobs get chosen. None of them checked
    that the chosen change could actually be written, so `update_job(id,
    schedule=...)` — keyword, where the real function takes a positional dict —
    failed fifteen times against live data before anything noticed.
    """

    def test_the_call_matches_the_real_update_job_signature(self, mod):
        """Bound against the function Hermes actually ships, so a vendor change
        to its shape fails here rather than at 3am against real schedules."""
        import inspect
        import sys as _sys

        _sys.path.insert(0, str(Path.home() / ".hermes" / "hermes-agent"))
        from cron.jobs import update_job

        captured = {}

        def spy(*args, **kwargs):
            inspect.signature(update_job).bind(*args, **kwargs)  # raises if wrong
            captured["args"] = args
            captured["kwargs"] = kwargs

        mod.write_schedule(spy, "abc123", "8 13 * * *")
        assert captured["kwargs"] == {}, "update_job takes positional arguments"
        assert captured["args"][0] == "abc123"

    def test_it_sends_the_schedule_and_nothing_else(self, mod):
        """`update_job` recomputes schedule_display and next_run_at itself.
        Sending our own would fight it."""
        captured = {}
        mod.write_schedule(lambda jid, updates: captured.update(jid=jid, updates=updates),
                           "abc123", "8 13 * * *")
        assert set(captured["updates"]) == {"schedule"}
        assert captured["updates"]["schedule"] == {
            "kind": "cron", "expr": "8 13 * * *", "display": "8 13 * * *",
        }

    def test_it_never_tries_to_change_the_id(self, mod):
        """`id` is an immutable field and also a path component under the cron
        output dir. update_job raises on it."""
        captured = {}
        mod.write_schedule(lambda jid, updates: captured.update(updates=updates),
                           "abc123", "8 13 * * *")
        assert "id" not in captured["updates"]

    def test_the_same_call_shape_as_the_script_that_already_worked(self, mod):
        """ted-pin-cron-jobs.py calls update_job(job["id"], {...}). This is the
        reference that existed before this script did."""
        source = (REPO / "scripts" / "ted-pin-cron-jobs.py").read_text()
        assert 'update_job(job["id"], {' in source
        mine = (REPO / "scripts" / "ted-spread-reminder-times.py").read_text()
        assert "update_job(job_id, {" in mine
