#!/usr/bin/env python3
"""One person's messages, answered in the order they were sent.

Roadmap task T08. Rapid messages from one person must not race each other,
while different people must not block one another.

THE MECHANISM ALREADY EXISTS, UPSTREAM AND IN CONFIG. Hermes holds three
layers: a per-routing-key busy guard in the adapter, `_running_agents` in the
runner, and `gateway/turn_lease.py`, which serializes the load-history → run →
flush region per resolved session id. On top of those, `~/.hermes/config.yaml`
sets `busy_input_mode: queue`, chosen after a tester sent five messages in
eighty seconds on 3 Sep and `interrupt` aborted the turn already in flight. A
follow-up now cascades after the running turn through a FIFO that keeps each
message its own turn in arrival order.

So T08 does not need a queue written. What it needs is evidence, which is what
this is: the same shape as `ted-concurrency-check.py`, which closed T02 by
checking real traffic rather than asserting.

WHAT IT ASSERTS

  arrival order   per person, user messages are persisted in the order they
                  arrived. Row id is processing order and `timestamp` is
                  arrival; if a later-arriving message is processed first, the
                  queue failed. That is the exact failure `turn_lease.py`
                  describes — rows persisting in completion order instead.

  nothing dropped every user message has a reply after it. Checked per PERSON
                  and not per session: a session rolls over mid-conversation,
                  and grouping by session called 13 messages unanswered when 5
                  were. Anything still unanswered is cross-checked against
                  `delivery_obligations`, so a reply Ted wrote and could not
                  deliver is reported as a failed delivery rather than as a
                  message he ignored.

  overlaps seen   how many messages arrived while Ted was mid-turn. Printed
                  whether or not anything is wrong, because a run that found no
                  fault and a run that found no traffic must not look alike.
                  This file's own history is the reason: a check that read one
                  source and reported 100%% clean was wrong for a week.

WHAT IS DELIBERATELY NOT A FAULT

An assistant row followed by a user row with an earlier timestamp is queueing
working, not breaking: the person typed while Ted was composing, so their
message arrives later in the transcript carrying its real arrival time. 119 of
those in the 30 days to 18 Sep 2026, and every one is the feature.

Two rows from a SINGLE inbound message — a document's injected text and its
caption land milliseconds apart — are not two messages and cannot be out of
order with each other. They are exempt and counted separately.

It reads the database read-only and writes nothing anywhere.

    python3 scripts/ted-ordering-check.py            # last 30 days
    python3 scripts/ted-ordering-check.py --days 7
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE_DB = HERMES / "state.db"

DEFAULT_DAYS = 30

# Rows this close together came from one inbound message being split, not from
# a person sending twice. Measured: Ankiita's PDF and its caption are 11ms
# apart. A person cannot send two WhatsApp messages inside a second, and if
# they could, the 0.35s debounce would merge them into one turn anyway.
SAME_MESSAGE_SECONDS = 1.0

# Clock skew. Timestamps come from the sending device by way of the bridge, so
# a millisecond of disagreement is not evidence of anything.
ORDER_TOLERANCE_SECONDS = 0.001


def connect() -> sqlite3.Connection:
    if not STATE_DB.is_file():
        raise SystemExit(f"No state database at {STATE_DB}")
    db = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def conversation(db: sqlite3.Connection, days: int) -> dict[str, list[sqlite3.Row]]:
    """Every WhatsApp turn in the window, grouped by person.

    Keyed on `chat_id` rather than `session_id` on purpose: the person is the
    unit T08 is about, and one person's conversation spans many sessions.
    """
    cutoff = datetime.now().timestamp() - days * 86400
    rows = db.execute(
        """
        SELECT m.id, m.role, m.timestamp, m.platform_message_id,
               s.chat_id, s.display_name, m.content
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE m.timestamp > ?
          AND s.source = 'whatsapp'
          AND m.role IN ('user', 'assistant')
        ORDER BY m.id
        """,
        (cutoff,),
    ).fetchall()

    by_person: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        by_person.setdefault(row["chat_id"], []).append(row)
    return by_person


def out_of_order(by_person: dict[str, list[sqlite3.Row]]) -> list[dict]:
    """User messages processed before a message that arrived earlier."""
    faults: list[dict] = []
    for chat, rows in by_person.items():
        previous = None
        for row in rows:
            if row["role"] != "user":
                continue
            if previous is not None:
                drift = previous["timestamp"] - row["timestamp"]
                if drift > ORDER_TOLERANCE_SECONDS and drift > SAME_MESSAGE_SECONDS:
                    faults.append({"chat": chat, "first": previous, "second": row})
            previous = row
    return faults


def split_messages(by_person: dict[str, list[sqlite3.Row]]) -> int:
    """Rows close enough together to be one inbound message, not two."""
    count = 0
    for rows in by_person.values():
        previous = None
        for row in rows:
            if row["role"] != "user":
                continue
            if previous is not None:
                drift = previous["timestamp"] - row["timestamp"]
                if ORDER_TOLERANCE_SECONDS < drift <= SAME_MESSAGE_SECONDS:
                    count += 1
            previous = row
    return count


def mid_turn_arrivals(by_person: dict[str, list[sqlite3.Row]]) -> int:
    """Messages that landed while Ted was still composing the previous reply.

    The condition T08 exists for. Not a fault: it is the queue doing its job,
    and a count of zero means this check saw no concurrency to judge.
    """
    count = 0
    for rows in by_person.values():
        previous = None
        for row in rows:
            if (
                previous is not None
                and previous["role"] == "assistant"
                and row["role"] == "user"
                and row["timestamp"] < previous["timestamp"]
            ):
                count += 1
            previous = row
    return count


def unanswered(by_person: dict[str, list[sqlite3.Row]]) -> list[sqlite3.Row]:
    """User messages with no reply after them, anywhere, for that person."""
    silent: list[sqlite3.Row] = []
    for rows in by_person.values():
        for index, row in enumerate(rows):
            if row["role"] != "user":
                continue
            if not any(later["role"] == "assistant" for later in rows[index + 1 :]):
                silent.append(row)
    return silent


def undelivered_chats(db: sqlite3.Connection) -> dict[str, str]:
    """Chats where Ted wrote a reply the bridge could not deliver.

    `abandoned` is the ledger's terminal state. A person in here was not
    ignored by the queue; they were disconnected from, which is a different
    fault with a different fix and must not be counted as this one.
    """
    return {
        row["chat_id"]: (row["last_error"] or "").strip()
        for row in db.execute(
            "SELECT chat_id, last_error FROM delivery_obligations WHERE state='abandoned'"
        )
    }


def when(row: sqlite3.Row) -> str:
    return datetime.fromtimestamp(row["timestamp"]).strftime("%d %b %H:%M:%S")


def snippet(row: sqlite3.Row, width: int = 58) -> str:
    text = (row["content"] or "").replace("\n", " ").strip()
    return text[:width] + ("…" if len(text) > width else "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    args = parser.parse_args()

    db = connect()
    by_person = conversation(db, args.days)

    people = len(by_person)
    inbound = sum(1 for rows in by_person.values() for r in rows if r["role"] == "user")
    overlaps = mid_turn_arrivals(by_person)
    split = split_messages(by_person)
    faults = out_of_order(by_person)
    silent = unanswered(by_person)
    undelivered = undelivered_chats(db)

    print(f"{args.days} days, {people} people, {inbound} messages from them.")
    print(f"  {overlaps} arrived while Ted was mid-turn — the case T08 is about.")
    print(f"  {split} were one message split into two rows, not two messages.")

    if inbound == 0:
        print("\nNo inbound traffic in the window. Nothing was checked.")
        return 3
    if overlaps == 0:
        print(
            "\nNo message arrived mid-turn in this window, so ordering under "
            "load was not\nexercised. This is not a pass."
        )

    if faults:
        print(f"\nFAIL: {len(faults)} message(s) answered out of arrival order:")
        for fault in faults:
            print(
                f"  {fault['first']['display_name']}: processed "
                f"{when(fault['first'])} '{snippet(fault['first'], 30)}' "
                f"before {when(fault['second'])} '{snippet(fault['second'], 30)}'"
            )
    else:
        print("  ok  every message was answered in the order it arrived.")

    ignored = [row for row in silent if row["chat_id"] not in undelivered]
    disconnected = [row for row in silent if row["chat_id"] in undelivered]

    if disconnected:
        print(
            f"\n  {len(disconnected)} message(s) got a reply that could not be "
            "delivered — a disconnect,\n      not the queue:"
        )
        for row in disconnected:
            print(f"      {when(row)} {row['display_name']}: {undelivered[row['chat_id']]}")

    if ignored:
        # Not an ordering fault, and saying so matters: every one found so far
        # was the model call failing, not the queue. Reported at the same
        # weight anyway, because from where the person sits it is the same
        # thing — they wrote to Ted and nothing came back.
        print(
            f"\nFAIL: {len(ignored)} message(s) got no reply at all, and no "
            "delivery was even attempted.\n      The queue is not the suspect; "
            "look for the turn in agent.log. Known cases are\n      explained "
            "in docs/T08_ORDERING.md."
        )
        for row in ignored:
            print(f"  {when(row)} {str(row['display_name'])[:18]:18s} | {snippet(row)}")
    else:
        print("  ok  nothing a person sent was left without a reply.")

    if faults or ignored:
        return 1
    if overlaps == 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
