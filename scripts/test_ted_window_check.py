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
        assert counts["delivered"] == 1
        assert counts["free"] == 1
        assert counts["needs_template"] == 0
        assert counts["reply"]["free"] == 1
        assert sum(counts["reminder"].values()) == 0

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


class TestRemindersAreCountedToo:
    """The bug this file shipped with.

    The first version read `delivery_obligations` alone and reported that 100%
    of Ted's traffic fell inside the free window. A scheduled reminder never
    touches that ledger: the cron scheduler hands it to the adapter and writes
    one line to agent.log. Ted had been sending 7 to 21 a day, every day, and
    the check could not see one of them — which is exactly the traffic that
    needs templates. It read 0% outside the window; the real figure is 21%.
    """

    LINE = (
        "2026-09-18 00:00:18,461 INFO cron.scheduler: Job '6e77ad1b48ab': "
        "delivered to whatsapp:115650651500637@lid via live adapter\n"
    )

    def _log(self, tool, when: float, chat: str = "aaa@lid"):
        import datetime as dt
        stamp = dt.datetime.fromtimestamp(when).strftime("%Y-%m-%d %H:%M:%S")
        logs = Path(tool.LOG_DIR)
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "agent.log").write_text(
            f"{stamp},461 INFO cron.scheduler: Job 'x': "
            f"delivered to whatsapp:{chat} via live adapter\n"
        )

    def test_the_real_log_line_parses(self, tool):
        Path(tool.LOG_DIR).mkdir(parents=True, exist_ok=True)
        (Path(tool.LOG_DIR) / "agent.log").write_text(self.LINE)
        sent = tool.cron_deliveries(since=0)
        assert len(sent) == 1
        assert sent[0][1] == "115650651500637@lid"

    def test_a_reminder_outside_the_window_needs_a_template(self, tool):
        now = time.time() - HOUR
        db = _db(tool, [now - 48 * HOUR], [])
        self._log(tool, now)
        try:
            counts = tool.classify(db, days=7)
        finally:
            db.close()
        assert counts["reminder"]["template"] == 1
        assert counts["needs_template"] == 1

    def test_a_reminder_inside_the_window_is_free(self, tool):
        now = time.time() - HOUR
        db = _db(tool, [now - 60], [])
        self._log(tool, now)
        try:
            counts = tool.classify(db, days=7)
        finally:
            db.close()
        assert counts["reminder"]["free"] == 1
        assert counts["needs_template"] == 0

    def test_replies_and_reminders_are_counted_separately(self, tool):
        """Kept apart on purpose: a zero in the reminder column is the signal
        that this is reading the wrong thing, not that the news is good."""
        now = time.time() - HOUR
        db = _db(tool, [now - 48 * HOUR], [now])
        self._log(tool, now)
        try:
            counts = tool.classify(db, days=7)
        finally:
            db.close()
        assert sum(counts["reply"].values()) == 1
        assert sum(counts["reminder"].values()) == 1
        assert counts["delivered"] == 2

    def test_a_missing_log_is_not_a_crash(self, tool):
        assert tool.cron_deliveries(since=0) == []

    def test_lines_that_are_not_deliveries_are_ignored(self, tool):
        Path(tool.LOG_DIR).mkdir(parents=True, exist_ok=True)
        (Path(tool.LOG_DIR) / "agent.log").write_text(
            "2026-09-18 00:00:08,787 INFO cron.scheduler: Running job 'x'\n"
            "2026-09-18 00:00:18,012 INFO cron.scheduler: Job 'x' completed successfully\n"
        )
        assert tool.cron_deliveries(since=0) == []
