"""What counts as Ted breaking one of his own rules.

Every pattern here is a line in SOUL.md, so the risk is not a crash, it is a
regex that quietly answers the wrong question and makes a week look clean.
The false positives are pinned as hard as the true ones: "friend-first" is a
hyphenated word and not a dash in the middle of a sentence, and a reply that
mentions a number near an emoji is only a fault when the two are adjacent.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import time
from pathlib import Path

import pytest

_SOURCE = Path(__file__).resolve().parent / "ted-voice-check.py"


@pytest.fixture
def check():
    spec = importlib.util.spec_from_file_location("ted_voice_under_test", _SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rule(check, name):
    return next(pattern for label, _why, pattern in check.RULES if label == name)


class TestTheDashRule:
    @pytest.mark.parametrize("text", [
        "nice one — that's the third day running",
        "nice one – that's the third day running",
        "nice one - that's the third day running",
    ])
    def test_a_dash_in_the_middle_is_caught(self, check, text):
        assert rule(check, "mid-sentence dash").search(text)

    @pytest.mark.parametrize("text", [
        "friend-first, always",
        "that's a well-balanced plate",
        "arre yaar, 1-2 rotis is fine",
    ])
    def test_a_hyphenated_word_is_not_a_dash(self, check, text):
        assert not rule(check, "mid-sentence dash").search(text)


class TestTheReceiptRule:
    @pytest.mark.parametrize("text", ["logged!", "Noted, 2 rotis", "got it", "saved"])
    def test_a_receipt_opening_is_caught(self, check, text):
        assert rule(check, "receipt opening").search(text)

    def test_the_same_word_later_is_not_an_opening(self, check):
        assert not rule(check, "receipt opening").search("that's all logged now")


class TestTheEmojiRule:
    @pytest.mark.parametrize("text", ["🔥 1850 today", "1850 🔥", "protein 92g 💪"])
    def test_an_emoji_beside_a_number_is_caught(self, check, text):
        assert rule(check, "emoji beside a number").search(text)

    def test_an_emoji_away_from_the_number_is_fine(self, check):
        # SOUL.md wants the emoji in what he says, not beside what he counts.
        assert not rule(check, "emoji beside a number").search(
            "ooo rajma chawal 😍 proper home food"
        )

    def test_a_line_break_between_them_is_not_beside(self, check):
        """The meal card ends on a figure and the next block opens on an
        emoji. Two lines apart is a layout, not a metric wearing an emoji,
        and counting it hid every real hit under 43 false ones."""
        assert not rule(check, "emoji beside a number").search(
            "Fiber: 6g\n\n📊 Daily Overview:"
        )


class TestTheCardIsNotProse:
    """The gate appends a fixed block. Ted did not write it, so it is not
    measured as his voice."""

    def test_the_meal_card_is_cut(self, check):
        reply = (
            "ooo pav bhaji 😍 that butter is doing work\n\n"
            "🍽️ Meal 1 Summary:\nCalories: 750 kcal\nProtein: 12g"
        )
        assert check.spoken_part(reply) == (
            "ooo pav bhaji 😍 that butter is doing work"
        )

    def test_the_daily_overview_and_its_bar_are_cut(self, check):
        reply = "solid day\n\n📊 Daily Overview:\nCalories: 1870\n🟢🟢⚪⚪⚪⚪ 31%"
        assert check.spoken_part(reply) == "solid day"
        assert not rule(check, "emoji beside a number").search(
            check.spoken_part(reply)
        )

    def test_a_reply_with_no_card_is_untouched(self, check):
        assert check.spoken_part("just words") == "just words"

    def test_a_reply_that_is_only_a_card_still_counts_as_a_reply(self, check):
        stats = check.measure(["📊 Daily Overview:\nCalories: 1870"])
        assert stats["replies"] == 1
        assert stats["emoji beside a number"] == 0


class TestTheQuestionRule:
    def test_two_questions_are_caught(self, check):
        assert rule(check, "two or more questions").search("how much? and when?")

    def test_one_question_is_the_rule_not_the_fault(self, check):
        assert not rule(check, "two or more questions").search("how much did you have?")


class TestMeasure:
    def test_an_empty_sample_measures_nothing(self, check):
        # Not a tidy zero. A week with no traffic and a week with no faults
        # must never print the same thing.
        assert check.measure([]) == {"replies": 0}

    def test_counts_are_out_of_the_sample(self, check):
        stats = check.measure(["logged!", "ooo nice", "noted"])
        assert stats["replies"] == 3
        assert stats["receipt opening"] == 2
        assert stats["mid-sentence dash"] == 0


class TestWhatIsRead:
    def _db(self, tmp_path, rows):
        db = tmp_path / "state.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, chat_id TEXT, "
            "display_name TEXT, source TEXT)"
        )
        conn.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, "
            "role TEXT, timestamp REAL, content TEXT)"
        )
        for index, (session, role, text) in enumerate(rows, start=1):
            conn.execute(
                "INSERT OR IGNORE INTO sessions VALUES (?,?,?,?)",
                (session, session, session, "whatsapp"),
            )
            conn.execute(
                "INSERT INTO messages VALUES (?,?,?,?,?)",
                (index, session, role, time.time() - 60, text),
            )
        conn.commit()
        conn.close()
        return db

    def _read(self, check, db):
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return check.replies(conn, time.time() - 3600, time.time())
        finally:
            conn.close()

    def test_only_teds_own_words_are_read(self, check, tmp_path):
        """The user's text is never counted, and never leaves the database."""
        db = self._db(tmp_path, [
            ("gt", "user", "i had 2 rotis and dal"),
            ("gt", "assistant", "ooo dal rice, solid"),
        ])
        assert self._read(check, db) == [("gt", "ooo dal rice, solid")]

    def test_reminders_are_left_out(self, check, tmp_path):
        """A reminder is allowed to be one line with no reaction. Counting it
        beside a conversation moves every number without anything changing."""
        db = self._db(tmp_path, [
            ("cron_abc_20260919", "assistant", "time for water"),
            ("gt", "assistant", "ooo dal rice, solid"),
        ])
        assert self._read(check, db) == [("gt", "ooo dal rice, solid")]


class TestWhatWasDelivered:
    """`messages` is the draft. The ledger is the message.

    Nine of the twelve receipt openings a real person read in the week to
    19 Sep 2026 were fixed strings the gates write. They appear in no draft,
    so every number this file printed before this was blind to them.
    """

    def _db(self, tmp_path, rows):
        db = tmp_path / "state.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, chat_id TEXT, "
            "display_name TEXT, source TEXT)"
        )
        conn.execute(
            "CREATE TABLE delivery_obligations (obligation_id TEXT PRIMARY KEY, "
            "session_key TEXT, platform TEXT, chat_id TEXT, content TEXT, "
            "state TEXT, created_at REAL)"
        )
        conn.execute(
            "INSERT INTO sessions VALUES ('20260919_1','chat-gt','GT','whatsapp')"
        )
        for index, (session_key, chat, text, state) in enumerate(rows, start=1):
            conn.execute(
                "INSERT INTO delivery_obligations VALUES (?,?,?,?,?,?,?)",
                (str(index), session_key, "whatsapp", chat, text, state,
                 time.time() - 60),
            )
        conn.commit()
        conn.close()
        return db

    def _read(self, check, db):
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return check.delivered(conn, time.time() - 3600, time.time())
        finally:
            conn.close()

    def test_a_delivered_reply_is_read_under_the_name(self, check, tmp_path):
        db = self._db(tmp_path, [
            ("agent:main:whatsapp:dm:91", "chat-gt", "ooo dal rice", "delivered"),
        ])
        assert self._read(check, db) == [("GT", "ooo dal rice")]

    def test_a_scheduled_reminder_is_left_out(self, check, tmp_path):
        """Patch 16 put cron sends into this ledger. They are still reminders."""
        db = self._db(tmp_path, [
            ("cron:whatsapp:chat-gt", "chat-gt", "time for water", "delivered"),
            ("agent:main:whatsapp:dm:91", "chat-gt", "ooo dal rice", "delivered"),
        ])
        assert self._read(check, db) == [("GT", "ooo dal rice")]

    def test_a_reply_nobody_received_is_left_out(self, check, tmp_path):
        """An abandoned row is a delivery fault, not a voice one."""
        db = self._db(tmp_path, [
            ("agent:main:whatsapp:dm:91", "chat-gt", "logged!", "abandoned"),
        ])
        assert self._read(check, db) == []

    def test_a_database_with_no_ledger_says_nothing(self, check, tmp_path):
        """Not zero. An older state.db has no answer, and a tidy 0% would be
        the same lie an empty sample is."""
        db = tmp_path / "old.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()
        assert self._read(check, db) == []
