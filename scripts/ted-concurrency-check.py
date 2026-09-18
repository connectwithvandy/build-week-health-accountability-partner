#!/usr/bin/env python3
"""Two real people talking to Ted at once, and whether anything crossed.

Roadmap task T02. The automated suites prove isolation against fixtures; the
one thing they cannot manufacture is two real humans typing in the same
minute. That was the last open half of T02, and on 18 Sep 2026 it turned out
not to need staging at all: it had already happened. Vishal S sent "Cool" nine
seconds into Venky's onboarding on 16 Sep, and each got their own reply.

One observation is an anecdote. This makes it a check, so every future overlap
is evidence too and a regression shows up the day it happens rather than in a
complaint.

WHAT COUNTS AS AN OVERLAP. Two messages from different chats inside the same
window, default 90 seconds. Not "the same second": the failure this guards
against is one turn's state leaking into another's, and a turn takes tens of
seconds from inbound to delivered. A strict definition would call the real
16 Sep episode a near miss and check nothing.

WHAT IT ASSERTS, all read back from what was actually delivered rather than
what the model wrote:

  routed      every delivered message reached the chat its session belongs to.
              Misrouting is the failure that matters most and the one nobody
              would discover politely.
  one chat    no session carries messages for two different chats.
  no names    a message delivered to one person never contains the name of
              somebody else who was mid-conversation at that moment.

It reads the database read-only and writes nothing anywhere.

    python3 scripts/ted-concurrency-check.py            # last 30 days
    python3 scripts/ted-concurrency-check.py --days 90
    python3 scripts/ted-concurrency-check.py --window 30
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE_DB = HERMES / "state.db"

DEFAULT_WINDOW_SECONDS = 90
DEFAULT_DAYS = 30

# A name has to be distinctive before its appearance in someone else's thread
# means anything. "Ted" is in every message; a two-letter name would match
# inside ordinary words. Three characters is the floor, and the match is
# whole-word so "Sarah" does not fire on "Sarah's" being absent or on
# "arah" inside another word.
_MIN_NAME_LENGTH = 3
_NOT_A_LEAK = {"ted", "bot", "you", "the", "and"}


def connect() -> sqlite3.Connection:
    if not STATE_DB.exists():
        raise SystemExit(f"No database at {STATE_DB}.")
    connection = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def episodes(db: sqlite3.Connection, days: int, window: int) -> list[dict]:
    """Every stretch where two different chats were active together.

    Grouped into episodes rather than listed pair by pair: one busy minute
    produces dozens of pairs and reads as dozens of incidents.
    """
    rows = db.execute(
        "SELECT s.chat_id, s.display_name, m.timestamp "
        "FROM messages m JOIN sessions s ON s.id = m.session_id "
        "WHERE m.role = 'user' AND s.chat_id IS NOT NULL AND s.chat_id != '' "
        "AND m.timestamp >= strftime('%s','now') - ? "
        "ORDER BY m.timestamp",
        (days * 86400,),
    ).fetchall()

    found: list[dict] = []
    for index, row in enumerate(rows):
        for other in rows[index + 1 :]:
            if other["timestamp"] - row["timestamp"] > window:
                break
            if other["chat_id"] == row["chat_id"]:
                continue
            here = {row["chat_id"], other["chat_id"]}
            # Extend the episode already running rather than opening a new one.
            if found and found[-1]["chats"] & here and (
                row["timestamp"] - found[-1]["ended"] <= window
            ):
                found[-1]["chats"] |= here
                found[-1]["names"] |= {row["display_name"], other["display_name"]}
                found[-1]["ended"] = max(found[-1]["ended"], other["timestamp"])
                continue
            found.append({
                "chats": set(here),
                "names": {row["display_name"], other["display_name"]},
                "started": row["timestamp"],
                "ended": other["timestamp"],
            })
    return found


def delivered_in(db: sqlite3.Connection, start: float, end: float, pad: int) -> list[sqlite3.Row]:
    """What actually went out around an episode.

    `delivery_obligations`, never `messages`: the ledger is the only record of
    what a person received, and the whole point here is what reached whom.
    """
    return db.execute(
        "SELECT d.chat_id, d.session_key, d.content, d.created_at "
        "FROM delivery_obligations d "
        "WHERE d.state = 'delivered' AND d.created_at BETWEEN ? AND ?",
        (start - pad, end + pad),
    ).fetchall()


def check_routing(db: sqlite3.Connection, sent: list[sqlite3.Row]) -> list[str]:
    """Every delivered message reached the chat its session belongs to."""
    problems = []
    for row in sent:
        owners = db.execute(
            "SELECT DISTINCT chat_id FROM sessions WHERE session_key = ? "
            "AND chat_id IS NOT NULL AND chat_id != ''",
            (row["session_key"],),
        ).fetchall()
        known = {owner["chat_id"] for owner in owners}
        if known and row["chat_id"] not in known:
            problems.append(
                f"a message on session {row['session_key']} went to "
                f"{row['chat_id']}, which is not one of {sorted(known)}"
            )
    return problems


def check_one_chat_per_session(db: sqlite3.Connection, chats: set[str]) -> list[str]:
    """No session carries two people."""
    problems = []
    rows = db.execute(
        "SELECT session_key, COUNT(DISTINCT chat_id) n FROM sessions "
        "WHERE chat_id IS NOT NULL AND chat_id != '' GROUP BY session_key HAVING n > 1"
    ).fetchall()
    for row in rows:
        problems.append(
            f"session {row['session_key']} is shared by {row['n']} different chats"
        )
    return problems


def check_no_other_names(sent: list[sqlite3.Row], names: dict[str, str]) -> list[str]:
    """Nobody is told somebody else's name.

    The cheapest possible proxy for a leak, and the one a real person would
    notice first: being called by a stranger's name, or hearing about them.
    """
    problems = []
    for row in sent:
        mine = (names.get(row["chat_id"]) or "").strip()
        for chat, name in names.items():
            if chat == row["chat_id"]:
                continue
            name = (name or "").strip()
            if len(name) < _MIN_NAME_LENGTH or name.lower() in _NOT_A_LEAK:
                continue
            # Somebody else sharing my own name is not a leak.
            if name.lower() == mine.lower():
                continue
            if re.search(rf"\b{re.escape(name)}\b", row["content"] or "", re.I):
                problems.append(
                    f"a message to {mine or row['chat_id']} contains "
                    f"{name!r}, who was mid-conversation at the same time"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="T02, checked against real overlaps.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW_SECONDS)
    args = parser.parse_args()

    db = connect()
    try:
        found = episodes(db, args.days, args.window)
        if not found:
            print(
                f"No two people talked to Ted within {args.window}s of each other "
                f"in the last {args.days} days.\n"
                "Nothing failed. Nothing was proven either: T02's live half stays open."
            )
            return 0

        names = {
            row["chat_id"]: row["display_name"]
            for row in db.execute(
                "SELECT DISTINCT chat_id, display_name FROM sessions "
                "WHERE chat_id IS NOT NULL AND chat_id != ''"
            ).fetchall()
        }

        print(f"{len(found)} concurrent episode(s) in the last {args.days} days\n")
        problems: list[str] = []
        checked = 0
        for episode in found:
            sent = delivered_in(db, episode["started"], episode["ended"], args.window)
            here = check_routing(db, sent)
            here += check_one_chat_per_session(db, episode["chats"])
            here += check_no_other_names(
                sent, {chat: names.get(chat, "") for chat in episode["chats"]}
            )
            when = db.execute(
                "SELECT datetime(?,'unixepoch','localtime') t", (episode["started"],)
            ).fetchone()["t"]
            who = ", ".join(sorted(n for n in episode["names"] if n))
            if not sent:
                # An overlap with nothing delivered inside it is not evidence.
                # Counting it as clean would inflate the number that matters.
                mark = "nothing delivered in the window, nothing proven"
            else:
                checked += 1
                mark = "clean" if not here else f"{len(here)} PROBLEM(S)"
            print(f"  {when}  {who}")
            print(f"      {len(sent)} message(s) delivered in the window — {mark}")
            for problem in here:
                print(f"      ! {problem}")
            problems += here

        print()
        if problems:
            print(f"  {len(problems)} problem(s). T02 is not holding.")
            return 1
        if not checked:
            print(
                f"  {len(found)} overlap(s) found and none of them delivered a\n"
                "  message, so nothing was actually inspected. T02's live half\n"
                "  stays open."
            )
            return 0
        print(
            f"  {checked} of {len(found)} episode(s) had messages to inspect, and\n"
            "  all of them are clean: every message reached the person it was\n"
            "  for, no session was shared, and nobody was told anybody else's\n"
            "  name. T02's live half, on real traffic."
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
