"""The backup, and every way it could lie about having worked.

An unverified backup is a belief. Each test here is a shape that would restore
badly while the script reported success, which is the only failure mode that
actually matters: you find out at restore time, and restore time is the worst
possible time to find out.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent / "ted-backup.py"


@pytest.fixture
def backup(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ted_backup_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DESTINATION", tmp_path / "backups")
    return module


def _session(path: Path, creds: dict | str = "default") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if creds == "default":
        creds = {
            "noiseKey": {"private": "x"},
            "signedIdentityKey": {"private": "y"},
            "registrationId": 12345,
            "me": {"id": "1@s.whatsapp.net", "name": "Ted"},
        }
    path.joinpath("creds.json").write_text(
        creds if isinstance(creds, str) else json.dumps(creds), encoding="utf-8"
    )
    return path


class TestSessionVerification:
    def test_a_complete_session_verifies(self, backup, tmp_path):
        ok, detail = backup.verify_session(_session(tmp_path / "s"))
        assert ok
        assert "device identity present" in detail

    def test_a_session_with_no_creds_is_not_a_session(self, backup, tmp_path):
        (tmp_path / "empty").mkdir()
        ok, detail = backup.verify_session(tmp_path / "empty")
        assert not ok
        assert "not a usable session" in detail

    def test_truncated_creds_are_caught(self, backup, tmp_path):
        """The one that matters. A half-copied creds.json exists on disk and
        passes any check that only asks whether the file is there."""
        ok, detail = backup.verify_session(_session(tmp_path / "s", '{"noiseKey":'))
        assert not ok
        assert "does not parse" in detail

    def test_valid_json_missing_the_device_identity_is_caught(self, backup, tmp_path):
        """Parses cleanly, restores cleanly, and is not a linked device."""
        ok, detail = backup.verify_session(_session(tmp_path / "s", {"me": {"id": "1"}}))
        assert not ok
        assert "noiseKey" in detail


class TestDatabaseSnapshot:
    def _db(self, path: Path, rows: int = 3) -> Path:
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE messages (id INTEGER)")
        connection.execute("CREATE TABLE delivery_obligations (id INTEGER)")
        connection.execute("CREATE TABLE sessions (id INTEGER)")
        for i in range(rows):
            connection.execute("INSERT INTO delivery_obligations VALUES (?)", (i,))
        connection.commit()
        connection.close()
        return path

    def test_snapshot_then_verify(self, backup, tmp_path):
        source = self._db(tmp_path / "live.db")
        ok, _ = backup.snapshot_database(source, tmp_path / "copy.db")
        assert ok
        ok, detail = backup.verify_database(tmp_path / "copy.db")
        assert ok
        assert "delivery_obligations 3" in detail

    def test_the_source_is_never_modified(self, backup, tmp_path):
        """A backup tool that can write to the thing it backs up is a backup
        tool that can lose it."""
        source = self._db(tmp_path / "live.db")
        before = source.read_bytes()
        backup.snapshot_database(source, tmp_path / "copy.db")
        assert source.read_bytes() == before

    def test_a_missing_database_fails_loudly(self, backup, tmp_path):
        ok, detail = backup.snapshot_database(tmp_path / "nope.db", tmp_path / "c.db")
        assert not ok
        assert "does not exist" in detail

    def test_an_intact_but_empty_database_is_reported(self, backup, tmp_path):
        """Zero obligations passes integrity_check and tells you nothing about
        what anyone was sent, so the counts are read back and printed."""
        source = self._db(tmp_path / "live.db", rows=0)
        backup.snapshot_database(source, tmp_path / "copy.db")
        ok, detail = backup.verify_database(tmp_path / "copy.db")
        assert ok
        assert "delivery_obligations 0" in detail

    def test_a_corrupt_copy_is_caught(self, backup, tmp_path):
        corrupt = tmp_path / "corrupt.db"
        corrupt.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)
        ok, detail = backup.verify_database(corrupt)
        assert not ok


class TestCron:
    def test_jobs_are_counted(self, backup, tmp_path):
        (tmp_path / "cron").mkdir()
        (tmp_path / "cron" / "jobs.json").write_text(json.dumps([{"id": 1}, {"id": 2}]))
        ok, detail = backup.verify_cron(tmp_path / "cron")
        assert ok
        assert "2 job(s)" in detail

    def test_unparseable_jobs_are_caught(self, backup, tmp_path):
        (tmp_path / "cron").mkdir()
        (tmp_path / "cron" / "jobs.json").write_text("{not json")
        ok, detail = backup.verify_cron(tmp_path / "cron")
        assert not ok
        assert "does not parse" in detail


class TestReceipt:
    def test_a_failed_backup_exits_nonzero_and_says_so(self, backup, monkeypatch, tmp_path):
        """Silence on failure is the whole problem. A backup that failed must
        not be something you discover while trying to restore from it."""
        monkeypatch.setattr(backup, "STATE_DB", tmp_path / "missing.db")
        monkeypatch.setattr(backup, "SESSION", tmp_path / "missing-session")
        monkeypatch.setattr(backup, "CRON", tmp_path / "missing-cron")
        monkeypatch.setattr(backup, "CONFIG", tmp_path / "missing.yaml")
        assert backup.take_backup() == 1
        folder = next((backup.DESTINATION).iterdir())
        receipt = json.loads((folder / "receipt.json").read_text())
        assert receipt["verified"] is False
        assert "state.db" in receipt["failures"]

    def test_listing_says_so_when_nothing_was_ever_taken(self, backup):
        assert backup.list_backups() == 1
