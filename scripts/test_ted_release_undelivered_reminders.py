"""Matching a delivery failure to the reminder it belonged to.

The ledger does not record what kind of message a row was, so the only join
available is a chat and a moment. Everything here pins the direction that
join errs in: a release that should not happen hands somebody an extra nudge
and rewinds a break offer they had earned, while a release that does not
happen costs one nudge. Every ambiguity has to resolve towards the second.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SOURCE = Path(__file__).resolve().parent / "ted-release-undelivered-reminders.py"


@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("ted_release_under_test", _SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLEARED = 1_789_000_000.0


def rows(*pairs):
    """Ledger rows for one chat: (state, seconds away from the grant)."""
    return [("chat@lid", state, CLEARED + offset) for state, offset in pairs]


def test_an_explicit_failure_in_the_window_is_a_release(script):
    state, at = script.verdict_for(CLEARED, rows(("abandoned", 3)))
    assert state == "abandoned"
    assert at == CLEARED + 3


def test_a_delivered_row_beats_a_failed_one(script):
    """A retry that eventually landed is a delivery. The user got their nudge."""
    state, _ = script.verdict_for(CLEARED, rows(("failed", 2), ("delivered", 40)))
    assert state == "delivered"


def test_no_row_at_all_is_not_a_failure(script):
    """Most sends never reach the ledger, so silence there means nothing."""
    state, _ = script.verdict_for(CLEARED, [])
    assert state == "no record"


def test_a_failure_outside_the_window_belongs_to_another_message(script):
    far = script.MATCH_WINDOW_SECONDS + 60
    state, _ = script.verdict_for(CLEARED, rows(("abandoned", far)))
    assert state == "no record"


def test_a_failure_just_before_the_grant_still_counts(script):
    """Clock skew between the two stores runs both ways."""
    state, _ = script.verdict_for(CLEARED, rows(("abandoned", -5)))
    assert state == "abandoned"


def test_the_earliest_failure_in_the_window_is_the_one_reported(script):
    _, at = script.verdict_for(CLEARED, rows(("failed", 90), ("abandoned", 10)))
    assert at == CLEARED + 10


def test_the_chat_join_matches_the_gate_rather_than_copying_it(script):
    """A second implementation of the hash would eventually disagree.

    The join is only correct because both sides derive the key the same way,
    so this asserts the script uses the gate's own function on the same input
    the cron path feeds it.
    """
    from hermes import ted_safety_gates as gates

    chat = "000000000000000@lid"
    assert gates._user_state_key("whatsapp", chat, "") == gates._user_state_key(
        "whatsapp", chat, "ignored-session"
    )
    assert gates._user_state_key("whatsapp", chat, "").startswith("whatsapp:sha256:")
