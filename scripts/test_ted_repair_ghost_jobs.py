"""A reminder that is switched on and never arrives, with nothing reporting it.

`enabled: true`, `state: "scheduled"`, `next_run_at: null`. The scheduler fires
by next run, so there is nothing to fire. Everything else looks healthy, the
user has been told their reminder is set, and it simply never comes.

Four real reminders were put into this state on 17 Sep 2026 by a tool run under
an interpreter without `croniter`, while it printed "Updated 15 of 15".

What these tests defend is the *reading*: a repair that mistakes a paused job
for a ghost would wake reminders somebody deliberately silenced, which is worse
than the fault it is fixing.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_SOURCE = REPO / "scripts" / "ted-repair-ghost-jobs.py"


def _load():
    spec = importlib.util.spec_from_file_location("ted_repair_ghost_jobs", _SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load()


NEXT = "2026-09-18T13:08:00+05:30"


class TestWhatCountsAsAGhost:
    def test_enabled_scheduled_and_no_next_run(self, mod):
        """The exact shape the four live reminders were left in."""
        assert mod.is_ghost(
            {"enabled": True, "state": "scheduled", "next_run_at": None}
        ) is True

    def test_a_healthy_job_is_not_a_ghost(self, mod):
        assert mod.is_ghost(
            {"enabled": True, "state": "scheduled", "next_run_at": NEXT}
        ) is False

    def test_a_paused_job_is_never_a_ghost(self, mod):
        """A paused job keeps a stale next run on purpose; resuming recomputes
        it. Treating one as a ghost would wake reminders somebody silenced."""
        assert mod.is_ghost(
            {"enabled": False, "state": "paused", "next_run_at": None}
        ) is False

    def test_a_paused_job_that_still_says_enabled_is_not_a_ghost(self, mod):
        """Both flags are read, because the two disagree in real data: the 35
        jobs paused on 17 Sep carry state=paused with enabled already false,
        but the pause path sets them in two steps."""
        assert mod.is_ghost(
            {"enabled": True, "state": "paused", "next_run_at": None}
        ) is False

    def test_a_switched_off_job_is_not_a_ghost(self, mod):
        assert mod.is_ghost(
            {"enabled": False, "state": "scheduled", "next_run_at": None}
        ) is False

    def test_an_empty_next_run_counts_as_missing(self, mod):
        """JSON round trips have produced "" as well as null here."""
        assert mod.is_ghost(
            {"enabled": True, "state": "scheduled", "next_run_at": ""}
        ) is True

    def test_a_missing_key_counts_as_missing(self, mod):
        assert mod.is_ghost({"enabled": True, "state": "scheduled"}) is True


class TestItRefusesToMakeMoreGhosts:
    def test_the_docstring_names_the_interpreter_that_works(self, mod):
        """The whole fault was running the wrong python. The error has to say
        which one, or the next person repeats it."""
        source = _SOURCE.read_text()
        assert "hermes-agent/venv/bin/python3" in source

    def test_it_checks_croniter_before_importing_hermes(self, mod):
        """Ordering matters: without croniter this tool would rewrite each
        ghost as a ghost."""
        source = _SOURCE.read_text()
        assert source.index("import croniter") < source.index("from cron.jobs import")


class TestTheSpreadScriptCannotCauseThisAgain:
    """The fix for the cause, not the symptom, lives in the other script."""

    def test_it_refuses_an_interpreter_without_croniter(self):
        import sys
        from unittest.mock import patch

        spec = importlib.util.spec_from_file_location(
            "ted_spread_reminder_times", REPO / "scripts" / "ted-spread-reminder-times.py"
        )
        spread = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(spread)

        real_import = __import__

        def no_croniter(name, *args, **kwargs):
            if name == "croniter":
                raise ImportError("No module named 'croniter'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", no_croniter):
            with pytest.raises(SystemExit) as exit_info:
                spread.require_a_usable_interpreter()
        assert "croniter" in str(exit_info.value)
        assert "hermes-agent/venv/bin/python3" in str(exit_info.value)

    def test_the_check_runs_before_anything_is_read(self):
        """A dry run under a bad interpreter is harmless, but finding out at
        --apply means finding out after somebody decided to trust the plan."""
        source = (REPO / "scripts" / "ted-spread-reminder-times.py").read_text()
        body = source[source.index("def main("):]
        assert body.index("require_a_usable_interpreter()") < body.index("load_gate()")
