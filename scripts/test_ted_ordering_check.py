"""What the ordering check must never confuse with a fault.

Two of the three things this file pins were mistakes made while writing it,
against the live database, and both would have been reported as bugs:

1. An assistant row followed by an earlier-stamped user row looked like 104
   ordering violations in 14 days. It is the queue working — the person typed
   while Ted was composing.
2. Grouping by session called 13 messages unanswered. Grouping by person, the
   real number was 5, because a session rolls over mid-conversation.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

_SOURCE = Path(__file__).resolve().parent / "ted-ordering-check.py"

SPEC = importlib.util.spec_from_file_location("ted_ordering_check", _SOURCE)
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)

NOW = 1_758_000_000.0


def rows(*specs) -> dict[str, list[sqlite3.Row]]:
    """Build the shape `conversation()` returns, without a database.

    Each spec is (chat, role, timestamp offset). Row ids ascend in the order
    given, which is what the real query's `ORDER BY m.id` produces: processing
    order, not arrival order.
    """
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE m (id INTEGER, role TEXT, timestamp REAL, "
        "platform_message_id TEXT, chat_id TEXT, display_name TEXT, content TEXT)"
    )
    for index, (chat, role, offset) in enumerate(specs):
        db.execute(
            "INSERT INTO m VALUES (?,?,?,?,?,?,?)",
            (index, role, NOW + offset, None, chat, chat.title(), f"{role} {index}"),
        )
    by_person: dict[str, list[sqlite3.Row]] = {}
    for row in db.execute("SELECT * FROM m ORDER BY id"):
        by_person.setdefault(row["chat_id"], []).append(row)
    return by_person


# --- what is not a fault -----------------------------------------------------


def test_typing_while_ted_composes_is_not_a_fault():
    # Ted's reply is flushed at +30 while the person's next message arrived at
    # +12. The row lands after the reply carrying its real arrival time.
    conversation = rows(
        ("alia", "user", 0),
        ("alia", "assistant", 30),
        ("alia", "user", 12),
        ("alia", "assistant", 45),
    )
    assert check.out_of_order(conversation) == []
    assert check.mid_turn_arrivals(conversation) == 1


def test_two_rows_from_one_message_are_not_two_messages():
    # A document's injected text and its caption, 11ms apart, persisted in the
    # other order. Measured on Ankiita's PDF, 1 Sep 2026.
    conversation = rows(
        ("ankiita", "user", 0.011),
        ("ankiita", "user", 0.0),
        ("ankiita", "assistant", 5),
    )
    assert check.out_of_order(conversation) == []
    assert check.split_messages(conversation) == 1


def test_a_reply_in_a_later_session_still_counts_as_answered():
    # Grouping is by person, so a session rollover between the message and the
    # reply is invisible here — which is the point.
    conversation = rows(("gt", "user", 0), ("gt", "assistant", 20))
    assert check.unanswered(conversation) == []


def test_two_people_at_once_are_not_each_others_problem():
    conversation = rows(
        ("alia", "user", 0),
        ("bhavna", "user", 1),
        ("alia", "assistant", 20),
        ("bhavna", "assistant", 22),
    )
    assert check.out_of_order(conversation) == []
    assert check.unanswered(conversation) == []


# --- what is a fault ---------------------------------------------------------


def test_a_later_message_processed_first_is_a_fault():
    # The failure turn_lease.py describes: rows persisting in completion order.
    # The second-arriving message (+60) was processed before the first (+120).
    conversation = rows(
        ("alia", "user", 120),
        ("alia", "user", 60),
        ("alia", "assistant", 130),
    )
    faults = check.out_of_order(conversation)
    assert len(faults) == 1
    assert faults[0]["first"]["timestamp"] > faults[0]["second"]["timestamp"]


def test_a_message_with_no_reply_after_it_is_found():
    conversation = rows(
        ("palak", "user", 0),
        ("palak", "assistant", 10),
        ("palak", "user", 20),
    )
    silent = check.unanswered(conversation)
    assert len(silent) == 1
    assert silent[0]["timestamp"] == NOW + 20


def test_a_person_who_never_got_a_single_reply_is_found():
    # Palak and Vishwas Mishra, 4 Sep 2026. Both sent the opener; the provider
    # was out of credit and Ted composed nothing. Neither ever wrote again.
    conversation = rows(("palak", "user", 0), ("palak", "user", 40))
    assert len(check.unanswered(conversation)) == 2


# --- the boundary ------------------------------------------------------------


@pytest.mark.parametrize(
    "drift, is_fault",
    [
        (0.0005, False),  # clock skew
        (0.5, False),  # one message split into rows
        (1.5, True),  # two messages, out of order
    ],
)
def test_where_split_rows_stop_and_reordering_starts(drift, is_fault):
    conversation = rows(("alia", "user", drift), ("alia", "user", 0), ("alia", "assistant", 10))
    assert bool(check.out_of_order(conversation)) is is_fault


def test_an_empty_window_reports_nothing_rather_than_passing():
    # A run that saw no traffic and a run that found no fault must not look
    # alike. main() returns 3 for the first; here the pieces agree there is
    # nothing to judge.
    conversation = rows()
    assert check.out_of_order(conversation) == []
    assert check.mid_turn_arrivals(conversation) == 0
    assert check.unanswered(conversation) == []
