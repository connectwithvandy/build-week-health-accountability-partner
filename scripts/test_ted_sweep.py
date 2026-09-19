"""The sweep, and the two ways a watcher like this dies.

It dies loud, by crying wolf until nobody reads it. It dies quiet, by losing
the ability to read a check and reporting that as nothing wrong. The second is
worse, and most of what is tested here is the second.

Every fixture is verbatim output from the real scripts on 19 Sep 2026, cut
down. A test written against imagined output proves the test.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent / "ted-sweep.py"


@pytest.fixture
def sweep(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("ted_sweep_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ORDERING_WITH_FINDINGS = """
30 days, 58 people, 1460 messages from them.
  119 arrived while Ted was mid-turn — the case T08 is about.
  ok  every message was answered in the order it arrived.

  1 message(s) got a reply that could not be delivered — a disconnect,
      not the queue:
      11 Sep 11:18:17 GT: {"error":"Connection Closed"}

FAIL: 4 message(s) got no reply at all, and no delivery was even attempted.
"""

ORDERING_CLEAN = """
30 days, 58 people, 1460 messages from them.
  ok  every message was answered in the order it arrived.
"""

DELETION_WITH_FINDINGS = """
1 person/people marked forgotten.

Udayan
  LIVE  state.db messages: 25 row(s)

FAIL: 4 live finding(s). A person asked to be forgotten and something
kept them.
"""

DELETION_CLEAN = "1 person/people marked forgotten.\n\n  Nothing left.\n"

CONCURRENCY_CLEAN = """
  4 of 32 episode(s) had messages to inspect, and
  all of them are clean: every message reached the person it was for.
"""

WINDOW = """
272 message(s) delivered in the last 7 days

  inside the 24h window, free        228   83.8%
  outside it, needs a template        44   16.2%
"""


class TestItReadsTheRealOutput:
    def test_unanswered_people_are_counted(self, sweep):
        assert sweep.ordering(ORDERING_WITH_FINDINGS) == {
            "unanswered": 4,
            "written but not delivered": 1,
        }

    def test_a_clean_ordering_run_is_zero_not_unreadable(self, sweep):
        assert sweep.ordering(ORDERING_CLEAN)["unanswered"] == 0

    def test_a_deletion_still_outstanding_is_counted(self, sweep):
        assert sweep.deletion(DELETION_WITH_FINDINGS) == {
            "stores still holding a forgotten user": 4
        }

    def test_a_deletion_honoured_reads_zero(self, sweep):
        assert sweep.deletion(DELETION_CLEAN) == {
            "stores still holding a forgotten user": 0
        }

    def test_onboarding_is_counted_from_the_plans(self, sweep):
        payload = json.dumps({"plans": [
            {"missing": ["age", "checkInTime"], "disagrees": False},
            {"missing": ["checkInTime"], "disagrees": False},
            {"missing": [], "disagrees": True},
        ]})
        assert sweep.onboarding(payload) == {
            "users stuck in onboarding": 2,
            "of those, missing a check-in time": 2,
            "records that disagree with themselves": 1,
        }

    def test_nobody_crossing_reads_zero(self, sweep):
        assert sweep.concurrency(CONCURRENCY_CLEAN) == {
            "episodes where users crossed": 0
        }

    def test_the_template_share_is_read(self, sweep):
        assert sweep.window(WINDOW) == {"% of sends needing a template": 16}

    def test_the_bill_is_rounded_to_the_nearest_ten(self, sweep):
        payload = json.dumps({"windows": {"window": {"all": {"usd": 46.25}}}})
        assert sweep.spend(payload) == {
            "$ in the last 7 days, to the nearest 10": 50
        }


class TestAWatcherThatCannotReadSaysSo:
    """The failure that matters. A reworded check must never read as clean."""

    def test_a_reworded_ordering_check_is_not_silently_clean(self, sweep):
        with pytest.raises(sweep.ShapeChanged):
            sweep.ordering("everything looks great today!")

    def test_a_reworded_deletion_check_is_not_silently_clean(self, sweep):
        with pytest.raises(sweep.ShapeChanged):
            sweep.deletion("nothing to report")

    def test_a_reworded_concurrency_check_is_not_silently_clean(self, sweep):
        with pytest.raises(sweep.ShapeChanged):
            sweep.concurrency("32 episodes examined")

    def test_a_check_that_crashed_instead_of_printing_json(self, sweep):
        with pytest.raises(sweep.ShapeChanged):
            sweep.onboarding("Traceback (most recent call last):\n  ConnectionError")

    def test_a_json_check_that_lost_its_key(self, sweep):
        with pytest.raises(sweep.ShapeChanged):
            sweep.memory(json.dumps({"facts": 86}))

    def test_one_broken_check_does_not_take_the_other_six(self, sweep, monkeypatch):
        def only_ordering_works(argv):
            if argv[0] == "ted-ordering-check.py":
                return ORDERING_CLEAN
            raise RuntimeError("boom")

        monkeypatch.setattr(sweep, "run", only_ordering_works)
        out = sweep.sweep()
        assert out["unanswered people"]["facts"]["unanswered"] == 0
        assert "unreadable" in out["deletion requests"]
        assert len(out) == len(sweep.CHECKS)


class TestItSpeaksOnlyWhenSomethingMoved:
    @staticmethod
    def _facts(**kw):
        return {"facts": dict(kw)}

    def test_nothing_moved_says_nothing(self, sweep):
        state = {"unanswered people": self._facts(unanswered=0)}
        assert sweep.differences(state, state) == []

    def test_a_person_going_unanswered_wakes_somebody(self, sweep):
        moved = sweep.differences(
            {"unanswered people": self._facts(unanswered=0)},
            {"unanswered people": self._facts(unanswered=1)},
        )
        assert moved == [("unanswered people", "unanswered: 0 → 1", True)]

    def test_a_finding_being_fixed_is_worth_saying_too(self, sweep):
        moved = sweep.differences(
            {"deletion requests": self._facts(**{"stores": 4})},
            {"deletion requests": self._facts(**{"stores": 0})},
        )
        assert moved[0][1] == "stores: 4 → 0"
        assert moved[0][2] is True

    def test_the_bill_moving_is_printed_and_does_not_wake_anybody(self, sweep):
        moved = sweep.differences(
            {"spend": self._facts(**{"$": 50})},
            {"spend": self._facts(**{"$": 90})},
        )
        assert moved[0][2] is False

    def test_a_check_becoming_unreadable_always_wakes_somebody(self, sweep):
        """Even for a check whose findings never alert. This is not a finding,
        it is the sweep telling you it has stopped being a sweep."""
        moved = sweep.differences(
            {"template share": self._facts(**{"%": 16})},
            {"template share": {"unreadable": "could not find template share"}},
        )
        assert moved[0][2] is True

    def test_a_recovery_is_one_line_with_the_numbers_in_it(self, sweep):
        moved = sweep.differences(
            {"memory keys": {"unreadable": "no key_collisions"}},
            {"memory keys": self._facts(**{"keys": 1})},
        )
        assert len(moved) == 1
        assert "can be read again" in moved[0][1]
        assert "keys 1" in moved[0][1]

    def test_the_first_run_is_a_baseline_not_a_wall_of_news(self, sweep):
        """With nothing stored, every fact is new. Sending that as an alert on
        the day it is installed is how a watcher gets filtered on day two."""
        assert sweep.differences({}, {"unanswered people": self._facts(unanswered=4)}) == []


class TestInstallingItIsProvedNotAnnounced:
    """The mistake this class is named after was made on 19 Sep 2026.

    The job was installed, kickstarted, and reported exit code 0. It was also
    blind in one place the whole time, because launchd had no PATH and the
    memory audit could not find `npx`. Exit code 0 was true and worthless.
    """

    def test_a_clean_run_has_nothing_unreadable(self, sweep):
        state = {"checks": {
            "unanswered people": {"facts": {"unanswered": 0}},
            "memory keys": {"facts": {"keys stored under two spellings": 1}},
        }}
        assert sweep.unreadable_checks(state) == []

    def test_a_blind_check_is_named_however_well_the_job_exited(self, sweep):
        state = {"checks": {
            "unanswered people": {"facts": {"unanswered": 0}},
            "memory keys": {"unreadable": "did not print JSON"},
            "spend": {"unreadable": "no total in the spend report"},
        }}
        assert sweep.unreadable_checks(state) == ["memory keys", "spend"]

    def test_no_state_at_all_is_not_read_as_healthy(self, sweep):
        """An install that produced no state file has not been proved either,
        and the caller checks the exit code first for exactly that."""
        assert sweep.unreadable_checks({}) == []

    def test_the_plist_is_valid_to_the_parser_launchd_actually_uses(self, sweep):
        """plutil, not plistlib. They disagree, and a stray `-->` once left a
        plist that plistlib read happily and launchd rejected outright, going
        on running the previous definition without a word."""
        import subprocess

        done = subprocess.run(
            ["plutil", "-lint", str(sweep.PLIST_SRC)], capture_output=True
        )
        assert done.returncode == 0, done.stdout.decode()

    def test_the_plist_carries_a_path_that_can_find_npx(self, sweep):
        """The specific fix. Without it the memory audit is perfect by hand
        and silently useless on the schedule."""
        import plistlib

        loaded = plistlib.loads(sweep.PLIST_SRC.read_bytes())
        path = loaded["EnvironmentVariables"]["PATH"]
        assert any(
            (Path(part) / "npx").exists() for part in path.split(":")
        ), f"no npx on {path}"

    def test_the_plist_runs_the_interpreter_launchd_is_allowed_to_use(self, sweep):
        """macOS refuses a launchd agent access to ~/Documents unless the
        binary has been granted it, and Command Line Tools python has not."""
        import plistlib

        loaded = plistlib.loads(sweep.PLIST_SRC.read_bytes())
        assert "venv/bin/python3" in loaded["ProgramArguments"][0]
