"""Pausing somebody's reminders is only safe while the gate refuses them anyway.

Every test here defends that one claim. The script's whole licence to touch a
real user's schedule is that `gateReminderDelivery` already returns
`allowed: false` for them, so nothing they receive changes. The moment it
paused a job whose sends would have gone out, it would be deleting reminders
people asked for, silently, to save money — the opposite of the trade.

The decision lives in `gate_blocks_every_send`, which mirrors the two standing
refusals in `remindersAllowed`. A quiet hour or the daily cap must NOT count:
those refuse one send and the job must keep its schedule for the next.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

_SOURCE = Path(__file__).resolve().parent / "ted-idle-nudges.py"


def _load():
    spec = importlib.util.spec_from_file_location("ted_idle_nudges", _SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load()


NOW = 1_789_600_000_000.0  # any fixed "now" in ms; the tests only need ordering


class TestWhatCountsAsBlocked:
    def test_an_unanswered_break_offer_blocks_every_send(self, mod):
        assert mod.gate_blocks_every_send({"awaitingBreakReply": True}, NOW) == "awaitingBreakReply"

    def test_a_future_pause_blocks_every_send(self, mod):
        why = mod.gate_blocks_every_send({"pausedUntil": NOW + 86_400_000}, NOW)
        assert why.startswith("pausedUntil:")

    def test_an_expired_pause_does_not(self, mod):
        """They asked to be left until a date. The date has passed."""
        assert mod.gate_blocks_every_send({"pausedUntil": NOW - 1}, NOW) == ""

    def test_an_engaged_user_is_never_blocked(self, mod):
        assert mod.gate_blocks_every_send({"awaitingBreakReply": False, "unansweredNudges": 0}, NOW) == ""

    def test_nudges_short_of_the_offer_are_not_blocked(self, mod):
        """Four unanswered nudges earns the offer, not the silence.

        `unansweredNudges` alone must never pause anything: until the offer has
        gone out AND been ignored, Ted is still allowed to nudge, and pausing
        here would cancel reminders the user is still receiving.
        """
        for count in (0, 1, 3, 4, 9):
            assert mod.gate_blocks_every_send({"unansweredNudges": count}, NOW) == ""

    def test_quiet_hours_and_the_daily_cap_are_not_this_script_s_business(self, mod):
        """Both refuse one send. The job must stay scheduled for the next one."""
        assert mod.gate_blocks_every_send({"quietHoursStart": "22:00", "sentCount": 99}, NOW) == ""

    def test_an_empty_policy_blocks_nothing(self, mod):
        assert mod.gate_blocks_every_send({}, NOW) == ""

    def test_a_missing_pause_value_is_not_read_as_a_pause(self, mod):
        for value in (None, "", "soon", 0):
            assert mod.gate_blocks_every_send({"pausedUntil": value}, NOW) == ""


class TestWhichJobBelongsToWhom:
    def test_an_explicit_whatsapp_target_is_read(self, mod):
        assert mod.chat_id_of({"deliver": "whatsapp:35957550100644@lid"}) == "35957550100644@lid"

    def test_a_job_delivering_to_its_origin_falls_back_to_that(self, mod):
        job = {"deliver": "origin", "origin": {"chat_id": "144504426369026@lid"}}
        assert mod.chat_id_of(job) == "144504426369026@lid"

    def test_a_job_with_no_recipient_resolves_to_nothing(self, mod):
        """Unresolvable means left alone, never guessed at."""
        for job in ({}, {"deliver": "origin"}, {"deliver": "origin", "origin": {}},
                    {"deliver": "telegram:123"}):
            assert mod.chat_id_of(job) == ""


class TestResumeIsNarrow:
    def test_only_this_script_s_own_pauses_are_resumable(self, mod):
        """A job somebody paused by hand must stay paused."""
        ours = f"{mod.PAUSE_TAG}: awaitingBreakReply as of 2026-09-17"
        assert ours.startswith(mod.PAUSE_TAG)
        for theirs in ("paused by vandy", "cron error", "", "manual"):
            assert not theirs.startswith(mod.PAUSE_TAG)
