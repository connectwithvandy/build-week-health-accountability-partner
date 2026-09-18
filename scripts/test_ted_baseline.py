"""The baseline has to be right about the things it would be easy to fake.

Every metric here divides one number by another, and the whole value of a
baseline is that somebody trusts it later without re-deriving it. Two of these
cases are mistakes made while writing the file, against the live database:
tokens counted per reply when scheduled reminders are calls with no reply, and
days from outside the window arriving as rows of zeros.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import time
from pathlib import Path

import pytest

_SOURCE = Path(__file__).resolve().parent / "ted-baseline.py"


def _load():
    spec = importlib.util.spec_from_file_location("ted_baseline", _SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


baseline = _load()

NOW = time.time()


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE sessions (id TEXT, source TEXT, chat_id TEXT);
        CREATE TABLE messages (id INTEGER, session_id TEXT, role TEXT, timestamp REAL);
        CREATE TABLE session_model_usage (
            model TEXT, billing_provider TEXT, api_call_count INTEGER,
            input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER,
            cache_write_tokens INTEGER, estimated_cost_usd REAL, last_seen REAL);
        CREATE TABLE delivery_obligations (state TEXT, created_at REAL);
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(baseline, "STATE_DB", path)
    monkeypatch.setattr(baseline, "LOGS", tmp_path / "logs")
    return sqlite3.connect(path)


def _turn(db, session, asked_at, replied_at, chat="1@lid"):
    cur = db.execute("SELECT COALESCE(MAX(id), 0) FROM messages").fetchone()[0]
    db.execute("INSERT OR IGNORE INTO sessions VALUES (?,?,?)", (session, "whatsapp", chat))
    db.execute("INSERT INTO messages VALUES (?,?,?,?)", (cur + 1, session, "user", asked_at))
    db.execute("INSERT INTO messages VALUES (?,?,?,?)", (cur + 2, session, "assistant", replied_at))
    db.commit()


# --- latency -----------------------------------------------------------------


def test_a_reply_is_timed_from_when_the_person_asked(db):
    _turn(db, "s1", NOW - 3600, NOW - 3590)
    waits, _ = baseline.latencies(baseline.connect(), NOW - 86400)
    assert list(waits.values())[0] == [pytest.approx(10.0)]


def test_typing_while_ted_composes_does_not_produce_a_negative_wait(db):
    # The T08 shape: a message that arrives mid-turn is persisted after the
    # reply and carries its earlier arrival time. Pairing by time rather than
    # by row id would read that as Ted answering before being asked.
    _turn(db, "s1", NOW - 3600, NOW - 3590)
    db.execute("INSERT INTO messages VALUES (3,'s1','user',?)", (NOW - 3595,))
    db.execute("INSERT INTO messages VALUES (4,'s1','assistant',?)", (NOW - 3580,))
    db.commit()
    waits, _ = baseline.latencies(baseline.connect(), NOW - 86400)
    assert all(value >= 0 for values in waits.values() for value in values)


def test_a_reply_with_no_question_is_not_counted_as_fast(db):
    # A scheduled reminder is an assistant row with nobody waiting on it.
    # Counting it as a zero-second reply would flatter every latency number.
    db.execute("INSERT OR IGNORE INTO sessions VALUES ('s1','whatsapp','1@lid')")
    db.execute("INSERT INTO messages VALUES (1,'s1','assistant',?)", (NOW - 3600,))
    db.commit()
    waits, _ = baseline.latencies(baseline.connect(), NOW - 86400)
    assert waits == {}


def test_a_slow_reply_is_named_by_session_never_by_content(db):
    _turn(db, "s-slow", NOW - 3600, NOW - 3600 + 120)
    _, slow = baseline.latencies(baseline.connect(), NOW - 86400)
    assert len(slow) == 1
    assert slow[0]["session"] == "s-slow"
    assert set(slow[0]) == {"day", "session", "seconds"}


# --- tokens and cost ---------------------------------------------------------


def _usage(db, **overrides):
    row = {
        "model": "claude-sonnet-5", "billing_provider": "anthropic",
        "api_call_count": 10, "input_tokens": 100, "output_tokens": 50,
        "cache_read_tokens": 0, "cache_write_tokens": 0,
        "estimated_cost_usd": 1.0, "last_seen": NOW - 3600,
    }
    row.update(overrides)
    db.execute("INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?,?,?)", tuple(row.values()))
    db.commit()


def test_cached_tokens_are_counted_as_input(db):
    # input_tokens alone is a sixth of the truth: 441 real calls on the primary
    # model show 882 input tokens against 1.2M cache reads.
    _usage(db, input_tokens=100, cache_read_tokens=900, cache_write_tokens=1000)
    spend = baseline.usage(baseline.connect(), NOW - 86400)
    assert list(spend.values())[0]["input"] == 2000


def test_the_fallback_model_is_counted_as_fallback(db):
    _usage(db, model="openai/gpt-5.3-codex", api_call_count=7)
    _usage(db, model="claude-sonnet-5", api_call_count=3)
    day = list(baseline.usage(baseline.connect(), NOW - 86400).values())[0]
    assert day["calls"] == 10
    assert day["fallback_calls"] == 7


def test_tokens_are_reported_per_call_not_per_reply(db):
    # A scheduled reminder is a call with no reply. Dividing by replies put
    # 654,716 tokens against one quiet day and read as a bug.
    _turn(db, "s1", NOW - 3600, NOW - 3590)
    _usage(db, api_call_count=100, input_tokens=100_000)
    row = baseline.build(2)["table"][0]
    assert row["replies"] == 1
    assert row["input_tokens_per_call"] == 1000


def test_cost_per_person_divides_by_people_not_sessions(db):
    _turn(db, "s1", NOW - 3600, NOW - 3590, chat="a@lid")
    _turn(db, "s2", NOW - 3500, NOW - 3490, chat="a@lid")
    _turn(db, "s3", NOW - 3400, NOW - 3390, chat="b@lid")
    _usage(db, estimated_cost_usd=10.0)
    row = baseline.build(2)["table"][0]
    assert row["people"] == 2
    assert row["cost_per_person_usd"] == 5.0


# --- delivery ----------------------------------------------------------------


def test_delivery_rate_counts_only_terminal_states(db):
    for state in ("delivered", "delivered", "abandoned", "pending"):
        db.execute("INSERT INTO delivery_obligations VALUES (?,?)", (state, NOW - 3600))
    db.commit()
    _turn(db, "s1", NOW - 3600, NOW - 3590)
    row = baseline.build(2)["table"][0]
    # pending is not a failure and not a success — it is still in flight, and
    # counting it either way makes the rate a guess.
    assert row["delivery_rate"] == pytest.approx(2 / 3, abs=0.001)


# --- the window --------------------------------------------------------------


def test_a_day_outside_the_window_is_not_a_row_of_zeros(db, tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "agent.log").write_text(
        "2026-01-01 10:00:00,000 WARNING agent.conversation_loop: API call failed (attempt 1/3)\n"
    )
    _turn(db, "s1", NOW - 3600, NOW - 3590)
    days = [row["day"] for row in baseline.build(2)["table"]]
    assert "2026-01-01" not in days


def test_an_empty_window_says_so_rather_than_printing_a_table(db, capsys):
    baseline.render(baseline.build(2))
    assert "Nothing to baseline" in capsys.readouterr().out


def test_a_short_log_is_flagged_rather_than_read_as_no_errors(db, tmp_path):
    # The error rate is the one number with no durable source. If the log does
    # not reach the start of the window, a low rate means a short log.
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "agent.log").write_text("nothing useful here\n")
    _turn(db, "s1", NOW - 3600, NOW - 3590)
    assert baseline.build(7)["log_covers_window"] is False
