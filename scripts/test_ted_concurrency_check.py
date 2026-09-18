"""T02, checked against real overlaps rather than staged ones.

A check that can only pass is not a check. Each test here builds the leak it
is meant to catch and asserts it is caught.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import time
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent / "ted-concurrency-check.py"


@pytest.fixture
def tool(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("ted_concurrency_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _db(tool, sessions, messages, delivered):
    db = sqlite3.connect(tool.STATE_DB)
    db.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY, session_key TEXT,
                               chat_id TEXT, display_name TEXT);
        CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               session_id TEXT, role TEXT, content TEXT, timestamp REAL);
        CREATE TABLE delivery_obligations (obligation_id TEXT PRIMARY KEY,
                               session_key TEXT, chat_id TEXT, content TEXT,
                               state TEXT, created_at REAL);
        """
    )
    db.executemany("INSERT INTO sessions VALUES (?,?,?,?)", sessions)
    db.executemany(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?,?,?,?)",
        messages,
    )
    db.executemany("INSERT INTO delivery_obligations VALUES (?,?,?,?,?,?)", delivered)
    db.commit()
    db.close()


NOW = time.time() - 3600


class TestFindingOverlaps:
    def test_two_people_in_the_same_minute_is_an_episode(self, tool):
        _db(
            tool,
            [("s1", "k1", "aaa@lid", "Venky"), ("s2", "k2", "bbb@lid", "Vishal")],
            [("s1", "user", "160", NOW), ("s2", "user", "Cool", NOW + 9)],
            [],
        )
        db = tool.connect()
        try:
            found = tool.episodes(db, days=30, window=90)
        finally:
            db.close()
        assert len(found) == 1
        assert found[0]["names"] == {"Venky", "Vishal"}

    def test_one_person_twice_is_not_an_overlap(self, tool):
        _db(
            tool,
            [("s1", "k1", "aaa@lid", "Venky")],
            [("s1", "user", "160", NOW), ("s1", "user", "75", NOW + 5)],
            [],
        )
        db = tool.connect()
        try:
            assert tool.episodes(db, days=30, window=90) == []
        finally:
            db.close()

    def test_far_apart_is_not_an_overlap(self, tool):
        _db(
            tool,
            [("s1", "k1", "aaa@lid", "Venky"), ("s2", "k2", "bbb@lid", "Vishal")],
            [("s1", "user", "160", NOW), ("s2", "user", "Cool", NOW + 600)],
            [],
        )
        db = tool.connect()
        try:
            assert tool.episodes(db, days=30, window=90) == []
        finally:
            db.close()


class TestItCatchesRealLeaks:
    def test_a_misrouted_message_is_caught(self, tool):
        """The failure that matters most: a reply delivered to the wrong
        person. Nobody reports this politely."""
        _db(
            tool,
            [("s1", "k1", "aaa@lid", "Venky"), ("s2", "k2", "bbb@lid", "Vishal")],
            [("s1", "user", "160", NOW)],
            [("o1", "k1", "bbb@lid", "160, got it", "delivered", NOW + 1)],
        )
        db = tool.connect()
        try:
            sent = tool.delivered_in(db, NOW, NOW, 90)
            problems = tool.check_routing(db, sent)
        finally:
            db.close()
        assert problems, "a message on Venky's session went to Vishal and passed"
        assert "bbb@lid" in problems[0]

    def test_a_shared_session_is_caught(self, tool):
        _db(
            tool,
            [("s1", "shared", "aaa@lid", "Venky"), ("s2", "shared", "bbb@lid", "Vishal")],
            [],
            [],
        )
        db = tool.connect()
        try:
            problems = tool.check_one_chat_per_session(db, {"aaa@lid", "bbb@lid"})
        finally:
            db.close()
        assert problems
        assert "shared by 2" in problems[0]

    def test_somebody_elses_name_in_my_thread_is_caught(self, tool):
        _db(tool, [], [], [])
        sent = [{
            "chat_id": "aaa@lid",
            "session_key": "k1",
            "content": "nice one Vishal, logged it",
            "created_at": NOW,
        }]
        problems = tool.check_no_other_names(
            sent, {"aaa@lid": "Venky", "bbb@lid": "Vishal"}
        )
        assert problems
        assert "Vishal" in problems[0]

    def test_my_own_name_is_not_a_leak(self, tool):
        _db(tool, [], [], [])
        sent = [{
            "chat_id": "aaa@lid", "session_key": "k1",
            "content": "nice one Venky, logged it", "created_at": NOW,
        }]
        assert tool.check_no_other_names(
            sent, {"aaa@lid": "Venky", "bbb@lid": "Vishal"}
        ) == []

    def test_two_people_with_the_same_name_do_not_trip_it(self, tool):
        """Two Arpits exist on this box. Hearing your own name is not a leak
        just because somebody else has it too."""
        _db(tool, [], [], [])
        sent = [{
            "chat_id": "aaa@lid", "session_key": "k1",
            "content": "got it arpit", "created_at": NOW,
        }]
        assert tool.check_no_other_names(
            sent, {"aaa@lid": "arpit", "bbb@lid": "Arpit"}
        ) == []

    def test_a_short_or_generic_name_never_fires(self, tool):
        """"Ted" is in every message and a two-letter name matches inside
        ordinary words. Either would make this check cry wolf until it was
        switched off."""
        _db(tool, [], [], [])
        sent = [{
            "chat_id": "aaa@lid", "session_key": "k1",
            "content": "ted here, jo tum bhejte ho", "created_at": NOW,
        }]
        assert tool.check_no_other_names(
            sent, {"aaa@lid": "Venky", "bbb@lid": "Ted"}
        ) == []
        assert tool.check_no_other_names(
            sent, {"aaa@lid": "Venky", "bbb@lid": "Jo"}
        ) == []
