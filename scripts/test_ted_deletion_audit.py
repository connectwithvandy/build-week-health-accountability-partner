"""The post-delete search T09's definition of done asks for.

The case that matters is the one it found on its first run: Udayan asked to be
forgotten on 3 Sep 2026 and the gate's tombstone still carries a name. Every
test here is either that shape or a way of getting it wrong quietly.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

_SOURCE = Path(__file__).resolve().parent / "ted-deletion-audit.py"


def _load():
    """Register before executing: @dataclass resolves its own module through
    sys.modules, and a module that is not there yet raises on the decorator."""
    spec = importlib.util.spec_from_file_location("ted_deletion_audit", _SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit = _load()

KEY = audit.gate_key("100000000000000@lid")


# --- the tombstone -----------------------------------------------------------


def test_a_clean_tombstone_is_not_a_finding():
    # What _forget_user promises to leave: a hashed key and a time.
    assert audit.check_tombstone(KEY, {"forgotten_at": 1788456543.2}) == []


def test_the_index_is_allowed_too():
    record = {"forgotten_at": 1788456543.2, "forgotten_at_index": 22}
    assert audit.check_tombstone(KEY, record) == []


def test_a_name_that_came_back_is_a_finding():
    # The live case, 3 Sep 2026.
    findings = audit.check_tombstone(KEY, {"forgotten_at": 1.0, "name": "UD"})
    assert len(findings) == 1
    assert "name='UD'" in findings[0].detail
    assert findings[0].live is True


def test_every_extra_key_is_named_not_just_the_first():
    # A repair script that writes a profile back writes more than one field,
    # and a report that says "and others" sends somebody back to the file.
    record = {"forgotten_at": 1.0, "name": "UD", "age": 31, "weight": 70.5}
    detail = audit.check_tombstone(KEY, record)[0].detail
    assert "name='UD'" in detail and "age=31" in detail and "weight=70.5" in detail


# --- keys --------------------------------------------------------------------


def test_the_derivation_is_the_one_the_gate_uses():
    """Pinned against a synthetic id, on purpose.

    An earlier version pinned this against a real user's WhatsApp id and the
    key derived from it — specifically the one person who asked to be
    forgotten, in a public repository. Publishing an identifier for somebody
    who exercised erasure is the one place this project must not be casual, so
    the id here is invented.

    What is still pinned is what matters: `sha256("whatsapp:" + id)`, the
    formula copied from the gate. If the gate's derivation ever changes, this
    fails here rather than the audit quietly finding nobody.
    """
    assert KEY == (
        "whatsapp:sha256:20b6781f0ee2b521d247fcb8ebea57ff79bbecbb1622294f"
        "bdd65b6c1345d48d"
    )


def test_different_people_get_different_keys():
    assert audit.gate_key("111@lid") != audit.gate_key("222@lid")


# --- scheduled work ----------------------------------------------------------


def _hermes(tmp_path, monkeypatch, jobs):
    (tmp_path / "cron").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cron" / "jobs.json").write_text(json.dumps({"jobs": jobs}))
    monkeypatch.setattr(audit, "HERMES", tmp_path)


def test_a_reminder_for_a_deleted_person_is_found(tmp_path, monkeypatch):
    # T09: "cancel future reminders and queued work". A job that still fires is
    # the most visible possible failure — the person hears from Ted after
    # asking to be erased.
    _hermes(tmp_path, monkeypatch, [
        {"name": "ted:b75ccdaa2420:daily_review", "enabled": True},
        {"name": "someone else's job", "enabled": True},
    ])
    person = audit.Person(label="x", gate_keys={"whatsapp:sha256:b75ccdaa2420ffff"})
    findings = audit.check_scheduled(person)
    assert len(findings) == 1
    assert "ENABLED" in findings[0].detail


def test_a_disabled_job_is_still_reported_and_labelled(tmp_path, monkeypatch):
    # Disabled is not cancelled. It survives a restart and an edit away from
    # firing again, so it is reported — with its state, so the reader can weigh
    # it rather than being alarmed.
    _hermes(tmp_path, monkeypatch, [{"name": "ted:aaaaaaaaaaaa:meals", "enabled": False}])
    person = audit.Person(label="x", gate_keys={"whatsapp:sha256:aaaaaaaaaaaabbbb"})
    findings = audit.check_scheduled(person)
    assert len(findings) == 1
    assert "disabled" in findings[0].detail


def test_a_job_matched_by_chat_id_is_found(tmp_path, monkeypatch):
    _hermes(tmp_path, monkeypatch, [
        {"name": "Vitamin D reminder", "origin": {"chat_id": "999@lid"}, "enabled": True}
    ])
    person = audit.Person(label="x", identifiers={"999@lid"})
    assert len(audit.check_scheduled(person)) == 1


def test_an_unreadable_jobs_file_is_not_reported_as_clean(tmp_path, monkeypatch):
    # The failure this whole file exists to prevent: a check that cannot read
    # a store must never answer "nothing there".
    (tmp_path / "cron").mkdir(parents=True)
    (tmp_path / "cron" / "jobs.json").write_text("{not json")
    monkeypatch.setattr(audit, "HERMES", tmp_path)
    findings = audit.check_scheduled(audit.Person(label="x", identifiers={"999@lid"}))
    assert len(findings) == 1
    assert "cannot prove" in findings[0].detail


def test_a_person_with_no_identifiers_matches_nothing(tmp_path, monkeypatch):
    # An empty needle must not match every job in the file.
    _hermes(tmp_path, monkeypatch, [{"name": "ted:aaaa:meals", "enabled": True}])
    assert audit.check_scheduled(audit.Person(label="x")) == []


# --- the database ------------------------------------------------------------


def _db(tmp_path, monkeypatch, setup: str = ""):
    """A state database with optional rows, handed back read-only.

    The audit opens `mode=ro` deliberately — it must not be able to change what
    it is auditing — so fixture rows go in through a separate writable
    connection first.
    """
    path = tmp_path / "state.db"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE sessions (id TEXT, source TEXT, chat_id TEXT, user_id TEXT,
                               display_name TEXT);
        CREATE TABLE messages (id INTEGER, session_id TEXT, role TEXT);
        CREATE TABLE delivery_obligations (chat_id TEXT, state TEXT);
        CREATE TABLE gateway_routing (entry_json TEXT);
        """
        + setup
    )
    db.commit()
    db.close()
    monkeypatch.setattr(audit, "STATE_DB", path)
    return audit.connect()


def test_a_fully_deleted_person_produces_no_database_finding(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    person = audit.Person(label="gone", identifiers={"404@lid"})
    assert audit.check_database(db, person) == []


def test_surviving_messages_are_counted(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch, """
        INSERT INTO sessions VALUES ('s1','whatsapp','1@lid','1@lid','Udayan');
        INSERT INTO messages VALUES (1,'s1','user');
        INSERT INTO messages VALUES (2,'s1','assistant');
        INSERT INTO delivery_obligations VALUES ('1@lid','delivered');
    """)
    person = audit.resolve(db, "Udayan")
    findings = {f.store: f.detail for f in audit.check_database(db, person)}
    assert findings["state.db messages"] == "2 row(s)"
    assert findings["state.db sessions"] == "1 row(s)"
    assert "1 row(s)" in findings["state.db delivery_obligations"]


def test_resolving_a_person_collects_the_gate_key(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch, """
        INSERT INTO sessions VALUES ('s1','whatsapp','100000000000000@lid',
                                     '100000000000000@lid','Udayan');
    """)
    person = audit.resolve(db, "Udayan")
    assert person.gate_keys == {KEY}
    assert person.label == "Udayan"


# --- retention ---------------------------------------------------------------


def test_snapshots_are_reported_as_kept_rather_than_as_leaks(tmp_path, monkeypatch):
    # A backup that forgets on demand is not a backup. These are named so the
    # retention is somebody's decision, and they must never fail the run.
    state = tmp_path / "state"
    state.mkdir(parents=True)
    (state / "onboarding.json.bak.pre-repair").write_text('{"100000000000000@lid": 1}')
    monkeypatch.setattr(audit, "GATE_STATE", state)
    monkeypatch.setattr(audit, "HERMES", tmp_path)
    monkeypatch.setattr(audit, "BACKUPS", tmp_path / "no-backups")
    person = audit.Person(label="x", identifiers={"100000000000000@lid"})
    findings = audit.check_snapshots(person)
    assert findings and all(f.live is False for f in findings)
