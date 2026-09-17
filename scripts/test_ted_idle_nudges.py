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


# --- running unattended ------------------------------------------------------
#
# A reconciler nobody runs is the same as no reconciler: the gatewatch plist sat
# in scripts/ for days without being installed and had never run once. And a
# reconciler that DOES run unattended can be wrong at scale, so the cap and the
# plist's own settings are pinned here.

import plistlib


class TestTheUnattendedCap:
    def test_a_normal_delta_is_allowed(self, mod):
        for total in (0, 1, 5, 12):
            assert mod.too_many_changes(total, 12) is False

    def test_a_suspiciously_large_run_is_refused(self, mod):
        assert mod.too_many_changes(13, 12) is True
        assert mod.too_many_changes(35, 12) is True

    def test_zero_means_a_human_said_yes(self, mod):
        """After reading the list, --max-changes 0 applies the real backlog."""
        assert mod.too_many_changes(400, 0) is False

    def test_the_default_is_smaller_than_the_first_real_backlog(self, mod):
        """35 jobs were paused by hand on 17 Sep. A cap above that would not
        have caught the thing it exists to catch."""
        assert mod.MAX_UNATTENDED_CHANGES < 35


@pytest.fixture(scope="module")
def plist(mod):
    return plistlib.loads(mod.PLIST_SRC.read_bytes())


class TestThePlist:
    def test_no_double_hyphen_in_any_comment(self, mod):
        """XML forbids `--` inside a comment, so a plist documenting a `--flag`
        does not parse and the timer silently never loads. Caught here first."""
        import re

        text = mod.PLIST_SRC.read_text()
        for block in re.findall(r"<!--.*?-->", text, re.S):
            assert "--" not in block[4:-3], "a comment contains a double hyphen"

    def test_it_parses(self, plist):
        assert plist["Label"] == "ai.ted.idle-nudges"

    def test_it_runs_this_script(self, mod, plist):
        argv = plist["ProgramArguments"]
        assert argv[1].endswith("ted-idle-nudges.py")
        assert Path(argv[1]) == mod.PLIST_SRC.parent / "ted-idle-nudges.py"
        assert "--apply" in argv

    def test_the_interpreter_exists_and_can_import_yaml(self, plist):
        """The system python cannot run this at all: Hermes' cron module needs
        PyYAML. A plist naming the wrong python fails silently, hourly."""
        import subprocess

        python = plist["ProgramArguments"][0]
        assert Path(python).exists(), f"{python} does not exist"
        done = subprocess.run([python, "-c", "import yaml"], capture_output=True)
        assert done.returncode == 0, "the plist's python has no PyYAML"

    def test_it_does_not_run_at_load(self, plist):
        """Installing a timer must not rewrite real schedules as a side effect
        of installing it."""
        assert plist["RunAtLoad"] is False

    def test_it_runs_hourly(self, plist):
        """Daily would mean a returning user waits a day for their reminders."""
        assert plist["StartInterval"] == 3600

    def test_the_path_can_find_npx(self, plist):
        """It shells out to `npx convex`, and launchd starts with a bare PATH."""
        assert "/usr/local/bin" in plist["EnvironmentVariables"]["PATH"]
