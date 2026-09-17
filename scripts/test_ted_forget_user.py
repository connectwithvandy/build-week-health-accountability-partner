"""The containment rule in ted-forget-user.py, which is the part that unlinks.

Everything else in that script reads or refuses. This is the one place it
removes a file, and the filename comes out of message text the gateway wrote,
so it is input rather than a constant. A path that escapes the cache would be
deleting something nobody asked it to.
"""

import importlib.util
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parent / "ted-forget-user.py"
spec = importlib.util.spec_from_file_location("ted_forget_user", MODULE)
forget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(forget)


def deletable(path: str) -> bool:
    """The exact test the script applies before unlinking."""
    p = Path(path)
    return any(p.is_relative_to(root) for root in forget.DELETABLE_ROOTS)


@pytest.mark.parametrize(
    "path",
    [
        "~/.hermes/cache/images/img_2ae20ec5d829.jpg",
        "~/.hermes/cache/audio/voice_abc123.ogg",
    ],
)
def test_cached_media_is_deletable(path):
    assert deletable(str(Path(path).expanduser()))


@pytest.mark.parametrize(
    "path",
    [
        "~/.hermes/state.db",
        "~/.hermes/SOUL.md",
        "~/.hermes/logs/agent.log",
        "~/.ssh/id_rsa",
        "/etc/passwd",
        "~/Documents/build-week-health accountability partner/hermes/SOUL.md",
        # The traversal shape: a path that starts inside the cache and climbs
        # out of it. `is_relative_to` compares the literal parts, so this has
        # to be checked rather than assumed.
        "~/.hermes/cache/images/../../SOUL.md",
    ],
)
def test_everything_else_is_not(path):
    assert not deletable(str(Path(path).expanduser().resolve()))


def test_the_media_pattern_only_matches_media():
    """A path in message text is only a candidate if it looks like an upload."""
    found = forget.MEDIA_PATH.findall(
        "logged it /Users/x/.hermes/cache/images/a.jpg and "
        "/Users/x/.hermes/state.db and /Users/x/.hermes/cache/audio/b.ogg"
    )
    assert found == [
        "/Users/x/.hermes/cache/images/a.jpg",
        "/Users/x/.hermes/cache/audio/b.ogg",
    ]


def test_the_roots_are_the_two_cache_directories():
    """If a third root is ever added it should be a deliberate edit, not a
    surprise found while reading a deletion that went too far."""
    assert [p.name for p in forget.DELETABLE_ROOTS] == ["images", "audio"]
    assert all(p.parent.name == "cache" for p in forget.DELETABLE_ROOTS)


# The gate state report. It only reads, but the way it fails matters: a key
# derived differently from the gate's own finds nothing, and nothing looks
# exactly like clean. These pin the derivation to the gate's real function.

import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hermes.ted_safety_gates import _user_state_key  # noqa: E402


@pytest.mark.parametrize(
    "sender_id",
    # Invented identifiers. The derivation is a hash of "whatsapp:" + the id,
    # so it holds for any string, and a real one would be a live user's handle
    # sitting in a public repository about their health.
    ["111111111111111@lid", "222222222222222@lid", "919999000111"],
)
def test_the_derived_key_is_the_gate_s_own_key(sender_id):
    """If _user_state_key ever changes, this fails instead of the report."""
    assert forget.gate_key(sender_id) == _user_state_key("whatsapp", sender_id, "")


def write_state(directory: Path, name: str, payload: dict) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_the_report_finds_a_user_in_both_live_and_snapshot(tmp_path, monkeypatch):
    key = forget.gate_key("919999000111")
    other = forget.gate_key("911111000222")
    monkeypatch.setattr(forget, "GATE_STATE_DIR", tmp_path)
    write_state(tmp_path, "ted-safety-gates-onboarding.json",
                {key: {"age": 30, "name": "A"}, other: {"age": 41}})
    write_state(tmp_path, "ted-safety-gates-onboarding.json.bak.pre-age-repair",
                {key: {"age": 29}, other: {"age": 41}})

    records = forget.gate_records_for({key})

    assert len(records) == 2
    assert {p.name.endswith(".json") for p, _k, _f in records} == {True, False}
    assert all(found_key == key for _p, found_key, _f in records)


def test_the_report_never_reports_another_user(tmp_path, monkeypatch):
    key = forget.gate_key("919999000111")
    other = forget.gate_key("911111000222")
    monkeypatch.setattr(forget, "GATE_STATE_DIR", tmp_path)
    write_state(tmp_path, "ted-safety-gates-onboarding.json", {other: {"age": 41}})

    assert forget.gate_records_for({key}) == []


def test_the_disclosure_list_shape_is_understood(tmp_path, monkeypatch):
    """That file is a list of keys, not a map of records."""
    key = forget.gate_key("919999000111")
    monkeypatch.setattr(forget, "GATE_STATE_DIR", tmp_path)
    write_state(tmp_path, "ted-safety-gates-disclosures.json", {"user_keys": [key]})

    records = forget.gate_records_for({key})

    assert [f for _p, _k, f in records] == [["disclosure-sent"]]


def test_unreadable_state_files_are_skipped_not_fatal(tmp_path, monkeypatch):
    key = forget.gate_key("919999000111")
    monkeypatch.setattr(forget, "GATE_STATE_DIR", tmp_path)
    (tmp_path / "ted-safety-gates-onboarding.json.bak.truncated").write_text("{not json")
    write_state(tmp_path, "ted-safety-gates-onboarding.json", {key: {"age": 30}})

    assert len(forget.gate_records_for({key})) == 1


# The scrub. This one writes, so the tests are about what it must NOT do:
# touch a live file, lose another user, or leave a half-written snapshot.


def test_the_scrub_removes_the_user_from_a_snapshot(tmp_path, monkeypatch):
    key = forget.gate_key("919999000111")
    monkeypatch.setattr(forget, "GATE_STATE_DIR", tmp_path)
    snap = write_state(tmp_path, "ted-safety-gates-onboarding.json.bak.pre-age-repair",
                       {key: {"age": 29, "weight_kg": 71}})

    files, records, failures = forget.scrub_gate_snapshots({key})

    assert (files, records, failures) == (1, 1, [])
    assert json.loads(snap.read_text()) == {}


def test_the_scrub_never_touches_a_live_file(tmp_path, monkeypatch):
    """The gateway owns those and rewrites them wholesale from memory."""
    key = forget.gate_key("919999000111")
    monkeypatch.setattr(forget, "GATE_STATE_DIR", tmp_path)
    live = write_state(tmp_path, "ted-safety-gates-onboarding.json", {key: {"age": 30}})
    before = live.read_bytes()

    files, records, _ = forget.scrub_gate_snapshots({key})

    assert (files, records) == (0, 0)
    assert live.read_bytes() == before


def test_every_other_user_survives_the_scrub(tmp_path, monkeypatch):
    key = forget.gate_key("919999000111")
    others = {forget.gate_key(f"9111110002{n:02d}"): {"age": 40 + n, "name": f"U{n}"}
              for n in range(12)}
    monkeypatch.setattr(forget, "GATE_STATE_DIR", tmp_path)
    snap = write_state(tmp_path, "ted-safety-gates-onboarding.json.bak.pre-goal-repair",
                       {key: {"age": 29}, **others})

    forget.scrub_gate_snapshots({key})

    assert json.loads(snap.read_text()) == others


def test_the_scrub_handles_the_disclosure_list_shape(tmp_path, monkeypatch):
    key = forget.gate_key("919999000111")
    other = forget.gate_key("911111000222")
    monkeypatch.setattr(forget, "GATE_STATE_DIR", tmp_path)
    snap = write_state(tmp_path, "ted-safety-gates-disclosures.json.bak.pre-fixture-purge",
                       {"user_keys": [key, other]})

    files, records, _ = forget.scrub_gate_snapshots({key})

    assert (files, records) == (1, 1)
    assert json.loads(snap.read_text()) == {"user_keys": [other]}


def test_an_unreadable_snapshot_is_left_alone_not_rewritten(tmp_path, monkeypatch):
    key = forget.gate_key("919999000111")
    monkeypatch.setattr(forget, "GATE_STATE_DIR", tmp_path)
    broken = tmp_path / "ted-safety-gates-onboarding.json.bak.truncated"
    broken.write_text("{not json")

    files, records, failures = forget.scrub_gate_snapshots({key})

    assert (files, records, failures) == (0, 0, [])
    assert broken.read_text() == "{not json"


def test_the_scrub_is_idempotent(tmp_path, monkeypatch):
    key = forget.gate_key("919999000111")
    monkeypatch.setattr(forget, "GATE_STATE_DIR", tmp_path)
    write_state(tmp_path, "ted-safety-gates-onboarding.json.bak.pre-pause", {key: {"age": 29}})

    first = forget.scrub_gate_snapshots({key})
    second = forget.scrub_gate_snapshots({key})

    assert first == (1, 1, [])
    assert second == (0, 0, [])


def test_no_temp_file_is_left_behind(tmp_path, monkeypatch):
    key = forget.gate_key("919999000111")
    monkeypatch.setattr(forget, "GATE_STATE_DIR", tmp_path)
    write_state(tmp_path, "ted-safety-gates-onboarding.json.bak.pre-weight", {key: {"age": 29}})

    forget.scrub_gate_snapshots({key})

    assert list(tmp_path.glob("*.scrub.tmp")) == []


def test_an_empty_key_set_scrubs_nothing(tmp_path, monkeypatch):
    """A failed derivation must be a no-op, never a wildcard."""
    monkeypatch.setattr(forget, "GATE_STATE_DIR", tmp_path)
    snap = write_state(tmp_path, "ted-safety-gates-onboarding.json.bak.pre-age",
                       {forget.gate_key("919999000111"): {"age": 29}})
    before = snap.read_bytes()

    assert forget.scrub_gate_snapshots(set()) == (0, 0, [])
    assert snap.read_bytes() == before


# Voice notes, matched by arrival time because nothing else links them to a
# person. The tests that matter are the ones where it must REFUSE to guess.

import os
import sqlite3
import time


def audio_world(tmp_path, monkeypatch, messages, files):
    """A fake gateway store and audio cache. messages: [(ts, person)]."""
    db = tmp_path / "state.db"
    con = sqlite3.connect(db)
    con.execute("create table sessions (id text, source text, user_id text, chat_id text)")
    con.execute("create table messages (session_id text, role text, timestamp real)")
    people = {p for _ts, p in messages}
    for person in people:
        con.execute("insert into sessions values (?,?,?,?)",
                    (f"sess-{person}", "whatsapp", person, person))
    for ts, person in messages:
        con.execute("insert into messages values (?,?,?)", (f"sess-{person}", "user", ts))
    con.commit(); con.close()

    audio = tmp_path / "cache" / "audio"
    audio.mkdir(parents=True)
    for name, when in files:
        path = audio / name
        path.write_bytes(b"ogg")
        os.utime(path, (when, when))

    monkeypatch.setattr(forget, "HERMES", tmp_path)
    monkeypatch.setattr(forget, "STATE_DB", db)
    monkeypatch.setattr(forget, "connect_ro",
                        lambda: sqlite3.connect(f"file:{db}?mode=ro", uri=True))


NOW = time.time()


def test_a_voice_note_beside_one_persons_message_is_theirs(tmp_path, monkeypatch):
    audio_world(tmp_path, monkeypatch, [(NOW, "asha")], [("aud_1.ogg", NOW + 5)])

    owned, ambiguous = forget.unreferenced_audio_for(["sess-asha"])

    assert [p.name for p in owned] == ["aud_1.ogg"]
    assert ambiguous == []


def test_two_people_talking_at_once_leaves_the_file_alone(tmp_path, monkeypatch):
    """The whole point. An ambiguous file is reported, never deleted."""
    audio_world(tmp_path, monkeypatch,
                [(NOW, "asha"), (NOW + 2, "bilal")], [("aud_1.ogg", NOW + 1)])

    owned, ambiguous = forget.unreferenced_audio_for(["sess-asha"])

    assert owned == []
    assert [p.name for p in ambiguous] == ["aud_1.ogg"]


def test_another_persons_voice_note_is_never_claimed(tmp_path, monkeypatch):
    audio_world(tmp_path, monkeypatch,
                [(NOW, "asha"), (NOW + 5000, "bilal")], [("aud_1.ogg", NOW + 5001)])

    owned, ambiguous = forget.unreferenced_audio_for(["sess-asha"])

    assert (owned, ambiguous) == ([], [])


def test_a_voice_note_nobody_was_talking_near_is_left(tmp_path, monkeypatch):
    audio_world(tmp_path, monkeypatch, [(NOW, "asha")], [("aud_1.ogg", NOW + 9999)])

    assert forget.unreferenced_audio_for(["sess-asha"]) == ([], [])


def test_the_window_edge_is_respected(tmp_path, monkeypatch):
    inside = NOW + forget.VOICE_WINDOW_SECONDS - 1
    outside = NOW + forget.VOICE_WINDOW_SECONDS + 1
    audio_world(tmp_path, monkeypatch, [(NOW, "asha")],
                [("in.ogg", inside), ("out.ogg", outside)])

    owned, _ = forget.unreferenced_audio_for(["sess-asha"])

    assert [p.name for p in owned] == ["in.ogg"]


def test_no_sessions_claims_nothing(tmp_path, monkeypatch):
    """A failed lookup must never turn into a wildcard delete."""
    audio_world(tmp_path, monkeypatch, [(NOW, "asha")], [("aud_1.ogg", NOW)])

    assert forget.unreferenced_audio_for([]) == ([], [])


def test_a_missing_audio_directory_is_not_a_crash(tmp_path, monkeypatch):
    audio_world(tmp_path, monkeypatch, [(NOW, "asha")], [])
    (tmp_path / "cache" / "audio").rmdir()

    assert forget.unreferenced_audio_for(["sess-asha"]) == ([], [])


def test_voice_notes_stay_inside_the_deletable_roots(tmp_path, monkeypatch):
    """They are unlinked by the same loop as photos, so the same rule holds."""
    audio_world(tmp_path, monkeypatch, [(NOW, "asha")], [("aud_1.ogg", NOW)])
    owned, _ = forget.unreferenced_audio_for(["sess-asha"])

    assert owned and all(p.is_relative_to(tmp_path / "cache" / "audio") for p in owned)
