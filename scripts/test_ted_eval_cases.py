"""T16's case set: the right cases, pinned, with no user text in the repo.

The two things that would make this artefact harmful rather than useful are
leaking a message into a public repository, and two runs quietly replaying
different cases while being compared as if they had not. Both are tested
here before anything about scoring is.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent
_REPO = _SCRIPTS.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "ted_eval_cases_under_test", _SCRIPTS / "ted_eval_cases.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ec = _load()


def _db(turns):
    """turns: (session_id, system_prompt, text, ts)"""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE sessions (id TEXT, system_prompt TEXT)")
    con.execute(
        "CREATE TABLE messages (session_id TEXT, role TEXT, content TEXT, "
        "timestamp REAL)"
    )
    for sid, system, text, ts in turns:
        con.execute("INSERT INTO sessions VALUES (?,?)", (sid, system))
        con.execute(
            "INSERT INTO messages VALUES (?,?,?,?)", (sid, "user", text, ts)
        )
    con.commit()
    return con


# --- the fingerprint ------------------------------------------------------


def test_the_fingerprint_is_stable_and_carries_no_text():
    said = "3 rotis and dal for lunch"
    first = ec.fingerprint(said)
    assert first == ec.fingerprint(said)
    assert len(first) == 16
    for word in ("roti", "dal", "lunch"):
        assert word not in first


def test_different_text_is_a_different_case():
    assert ec.fingerprint("2 rotis") != ec.fingerprint("3 rotis")


# --- classification -------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("[image received]", "meal_photo"),
        ("3 rotis and dal", "meal_text"),
        ("kal maine kya khaya tha", "hinglish"),
        ("actually it was 2 rotis", "correction"),
        ("pause the reminders for a week", "pause_reschedule"),
        ("i want to lose weight now", "goal_change"),
        ("my doctor said my thyroid is off", "safety_boundary"),
        ("ted i'm genuinely confused", "frustration"),
    ],
)
def test_each_category_is_recognised(text, expected):
    assert expected in ec.classify(text)


def test_a_photo_is_not_also_filed_as_a_text_meal():
    """They are separate cases in T16, and a photo turn has no food words."""
    hits = ec.classify("[image received]")
    assert "meal_photo" in hits
    assert "meal_text" not in hits


def test_plain_english_is_not_called_hinglish():
    """"main" and "to" are Hindi words and English ones. In they would put
    most of the corpus in this category, which would make it meaningless."""
    for said in ("main course was good", "i want to log a meal", "ok"):
        assert "hinglish" not in ec.classify(said)


def test_ambiguous_is_the_absence_of_a_signal():
    assert ec.classify("hmm") == ["ambiguous"]
    # Short, but it said something.
    assert "ambiguous" not in ec.classify("2 rotis")


def test_an_empty_turn_is_not_a_case():
    assert ec.classify("") == []
    assert ec.classify("   ") == []


def test_a_long_turn_with_no_signal_is_not_ambiguous():
    """Ambiguity is short *and* unmatched; a paragraph is something else."""
    assert ec.classify("i went to the office and then came back home again") == []


# --- building -------------------------------------------------------------


SYSTEM = "you are ted"


def test_it_only_takes_turns_with_a_stored_system_prompt():
    """The bakeoff refuses a reconstructed prompt. This must not widen it."""
    con = _db([
        ("s1", SYSTEM, "3 rotis and dal", 100.0),
        ("s2", "", "2 rotis and dal", 200.0),
        ("s3", None, "4 rotis and dal", 300.0),
    ])
    found = ec.candidates(con)
    assert len(found) == 1


def test_cron_turns_are_left_to_the_other_path():
    con = _db([
        ("cron_1", SYSTEM, "3 rotis and dal", 100.0),
        ("s1", SYSTEM, "2 rotis and dal", 200.0),
    ])
    assert len(ec.candidates(con)) == 1


def test_identical_text_is_one_case_not_two():
    """The hash is the case's name, so two rows of "ok" are one case.

    Counting them separately filled a category's quota with repeats:
    `counts` read 6 for pause_reschedule while only 4 resolved.
    """
    con = _db([
        ("s1", SYSTEM, "pause", 100.0),
        ("s2", SYSTEM, "pause", 200.0),
        ("s3", SYSTEM, "stop the reminders", 300.0),
    ])
    suite = ec.build(con, 6)
    assert len(suite["cases"]) == 2


def test_the_header_count_can_never_disagree_with_the_body():
    con = _db([
        ("s1", SYSTEM, "pause", 100.0),
        ("s2", SYSTEM, "pause", 200.0),
        ("s3", SYSTEM, "stop the reminders", 300.0),
        ("s4", SYSTEM, "3 rotis and dal", 400.0),
    ])
    suite = ec.build(con, 6)
    for name, count in suite["counts"].items():
        actual = sum(1 for c in suite["cases"] if name in c["categories"])
        assert count == actual, name


def test_the_quota_is_respected():
    con = _db([
        (f"s{n}", SYSTEM, f"{n} rotis and dal", float(n)) for n in range(1, 10)
    ])
    suite = ec.build(con, 3)
    assert suite["counts"]["meal_text"] == 3


def test_a_case_can_belong_to_two_categories():
    con = _db([("s1", SYSTEM, "actually kal ka khana galat tha", 100.0)])
    suite = ec.build(con, 6)
    assert len(suite["cases"]) == 1
    assert set(suite["cases"][0]["categories"]) >= {"correction", "hinglish"}


def test_the_built_record_holds_no_text():
    con = _db([("s1", SYSTEM, "i weigh 82kg and eat 3 rotis", 100.0)])
    suite = ec.build(con, 6)
    written = json.dumps(suite)
    assert "82kg" not in written
    assert "rotis" not in written
    assert "s1" not in written
    assert set(suite["cases"][0]) == {"hash", "categories", "chars"}


# --- resolving ------------------------------------------------------------


def test_resolving_finds_the_turn_again():
    con = _db([("s1", SYSTEM, "3 rotis and dal", 100.0)])
    suite = ec.build(con, 6)
    found, missing = ec.resolve(con, suite)
    assert missing == []
    assert found[0]["prompt"] == "3 rotis and dal"
    assert found[0]["system"] == SYSTEM
    assert "meal_text" in found[0]["categories"]


def test_a_deleted_message_is_reported_not_skipped():
    """A forgotten user leaves the suite, and the run says so.

    Skipping quietly would change what "the same cases" means between two
    runs that are being compared.
    """
    con = _db([
        ("s1", SYSTEM, "3 rotis and dal", 100.0),
        ("s2", SYSTEM, "pause the reminders", 200.0),
    ])
    suite = ec.build(con, 6)
    con.execute("DELETE FROM messages WHERE session_id = 's1'")
    con.commit()
    found, missing = ec.resolve(con, suite)
    assert len(found) == 1
    assert len(missing) == 1


def test_an_unreadable_suite_file_is_empty_rather_than_wrong(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text("{not json", encoding="utf-8")
    assert ec.read(path) == {}
    assert ec.read(tmp_path / "absent.json") == {}


# --- the committed artefact ----------------------------------------------


SUITE_FILE = _REPO / "evals" / f"ted-cases-v{ec.SUITE_VERSION}.json"


def test_the_committed_suite_exists_and_is_current_version():
    suite = ec.read(SUITE_FILE)
    assert suite, f"no suite at {SUITE_FILE}"
    assert suite["version"] == ec.SUITE_VERSION


def test_the_committed_suite_carries_no_message_text():
    """The one that matters. This repository is public."""
    suite = ec.read(SUITE_FILE)
    for case in suite["cases"]:
        assert set(case) == {"hash", "categories", "chars"}
        assert all(c in "0123456789abcdef" for c in case["hash"])
        for name in case["categories"]:
            assert name in ec.CATEGORIES


def test_the_committed_suite_says_what_it_cannot_cover():
    """Nine categories where T16 names ten. The gap belongs in the artefact."""
    suite = ec.read(SUITE_FILE)
    assert "voice" in suite["unavailable"]
    assert len(ec.CATEGORIES) == 9
