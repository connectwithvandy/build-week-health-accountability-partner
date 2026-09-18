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
