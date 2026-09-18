"""What a migration to the official API would cost, counted not guessed.

The number that matters is how much of Ted falls outside the 24-hour window,
because that part stops being his own words and becomes a pre-approved
template. Getting the classification wrong in either direction misprices the
whole decision.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import time
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent / "ted-window-check.py"
HOUR = 3600


@pytest.fixture
def tool(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("ted_window_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _db(tool, inbound, delivered):
    db = sqlite3.connect(tool.STATE_DB)
    db.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY, chat_id TEXT);
        CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               session_id TEXT, role TEXT, timestamp REAL);
        CREATE TABLE delivery_obligations (obligation_id TEXT PRIMARY KEY,
                               chat_id TEXT, state TEXT, created_at REAL);
        """
    )
    db.execute("INSERT INTO sessions VALUES ('s1','aaa@lid')")
    db.executemany(
        "INSERT INTO messages (session_id, role, timestamp) VALUES ('s1','user',?)",
        [(t,) for t in inbound],
    )
    db.executemany(
        "INSERT INTO delivery_obligations VALUES (?,?,?,?)",
        [(f"o{n}", "aaa@lid", "delivered", t) for n, t in enumerate(delivered)],
    )
    db.commit()
    db.close()
    return sqlite3.connect(f"file:{tool.STATE_DB}?mode=ro", uri=True)


class TestClassification:
    def test_a_reply_minutes_later_is_free(self, tool):
        now = time.time() - HOUR
        db = _db(tool, [now], [now + 60])
        try:
            counts = tool.classify(db, days=7)
        finally:
            db.close()
        assert counts == {
            "delivered": 1, "free": 1, "needs_template": 0, "unknown": 0, "days": 7
        }

    def test_a_nudge_two_days_later_needs_a_template(self, tool):
        """The 9pm reminder to somebody who has not written since Tuesday.
        This is the whole migration question in one row."""
        now = time.time() - HOUR
        db = _db(tool, [now - 48 * HOUR], [now])
        try:
            counts = tool.classify(db, days=7)
        finally:
            db.close()
        assert counts["needs_template"] == 1
        assert counts["free"] == 0

    def test_the_boundary_is_inclusive(self, tool):
        """Exactly 24 hours is still inside. A message priced wrong at the
        boundary is priced wrong for every daily reminder there is."""
        now = time.time() - 48 * HOUR
        db = _db(tool, [now], [now + 24 * HOUR])
        try:
            assert tool.classify(db, days=30)["free"] == 1
        finally:
            db.close()

    def test_one_second_past_the_boundary_is_outside(self, tool):
        now = time.time() - 48 * HOUR
        db = _db(tool, [now], [now + 24 * HOUR + 1])
        try:
            assert tool.classify(db, days=30)["needs_template"] == 1
        finally:
            db.close()

    def test_the_window_reopens_on_every_message(self, tool):
        """It is the *latest* inbound that counts, not the first. Reading the
        first would price a long conversation as if it had gone cold."""
        now = time.time() - HOUR
        db = _db(tool, [now - 40 * HOUR, now - 60], [now])
        try:
            assert tool.classify(db, days=7)["free"] == 1
        finally:
            db.close()

    def test_a_message_with_no_inbound_at_all_is_unknown(self, tool):
        """Counted as neither rather than as free. Guessing in the cheap
        direction is how a migration comes in over budget."""
        now = time.time() - HOUR
        db = _db(tool, [], [now])
        try:
            counts = tool.classify(db, days=7)
        finally:
            db.close()
        assert counts["unknown"] == 1
        assert counts["free"] == 0 and counts["needs_template"] == 0

    def test_only_delivered_messages_are_priced(self, tool):
        """An abandoned reply cost nobody anything."""
        now = time.time() - HOUR
        db = _db(tool, [now - 48 * HOUR], [now])
        db.close()
        writable = sqlite3.connect(tool.STATE_DB)
        writable.execute(
            "INSERT INTO delivery_obligations VALUES ('x','aaa@lid','abandoned',?)",
            (now,),
        )
        writable.commit()
        writable.close()
        db = sqlite3.connect(f"file:{tool.STATE_DB}?mode=ro", uri=True)
        try:
            assert tool.classify(db, days=7)["delivered"] == 1
        finally:
            db.close()
