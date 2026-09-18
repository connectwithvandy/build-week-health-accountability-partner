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


def _state_db(path: Path, *, chat: str = "9111@s.whatsapp.net", delivered: int = 3) -> Path:
    """A miniature state.db with the shape the drill reassembles.

    Two delivery obligations on one session is not padding: it is the shape
    that made the first real drill report 40,796 messages for a user in a
    database holding 6,341, because the join multiplied messages by
    obligations.
    """
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY, session_key TEXT, started_at REAL);
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, role TEXT, content TEXT, timestamp REAL
        );
        CREATE TABLE delivery_obligations (
            obligation_id TEXT PRIMARY KEY, session_key TEXT, chat_id TEXT,
            content TEXT, state TEXT, created_at REAL
        );
        """
    )
    db.execute("INSERT INTO sessions VALUES ('s1', 'k1', 1.0)")
    for n in range(4):
        db.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?,?,?,?)",
            ("s1", "user", f"message {n}", float(n)),
        )
    for n in range(delivered):
        db.execute(
            "INSERT INTO delivery_obligations VALUES (?,?,?,?,?,?)",
            (f"o{n}", "k1", chat, f"delivered text {n}", "delivered", float(n)),
        )
    db.commit()
    db.close()
    return path


class TestRepresentativeFlow:
    """T05 wants a restored environment to complete a representative user
    flow. Without starting a gateway, which would fight the live one for the
    WhatsApp credentials, the honest version is to rebuild it from the data."""

    def test_a_real_user_is_rebuilt(self, backup, tmp_path):
        db = _state_db(tmp_path / "state.db")
        ok, detail = backup.representative_user_flow(db)
        assert ok, detail
        assert "4 message(s)" in detail
        assert "3 delivered" in detail

    def test_messages_are_not_multiplied_by_obligations(self, backup, tmp_path):
        """The bug the first live drill actually had. Four messages and ten
        obligations on one session is four messages, not forty."""
        db = _state_db(tmp_path / "state.db", delivered=10)
        ok, detail = backup.representative_user_flow(db)
        assert ok, detail
        assert "4 message(s)" in detail

    def test_an_empty_ledger_is_a_failed_drill(self, backup, tmp_path):
        """Intact, restorable and carrying nobody's history. integrity_check
        passes on this file, which is exactly why the flow check exists."""
        db = _state_db(tmp_path / "state.db", delivered=0)
        ok, detail = backup.representative_user_flow(db)
        assert not ok
        assert "no delivered message" in detail

    def test_a_missing_database_does_not_crash_the_drill(self, backup, tmp_path):
        ok, detail = backup.representative_user_flow(tmp_path / "gone.db")
        assert not ok


class TestRestoreRefusals:
    """Restore is the only function here that writes. Every refusal is checked
    before anything is copied, so a refusal can never leave a half-restored
    home behind."""

    def _backup_dir(self, backup, tmp_path, verified=True):
        source = tmp_path / "a-backup"
        source.mkdir()
        _state_db(source / "state.db")
        (source / "receipt.json").write_text(json.dumps({"verified": verified}))
        return source

    def test_it_will_not_restore_under_a_running_gateway(self, backup, tmp_path, monkeypatch):
        monkeypatch.setattr(backup, "gateway_is_running", lambda home: True)
        source = self._backup_dir(backup, tmp_path)
        into = tmp_path / "home"
        ok, notes = backup.restore(source, into, force=False)
        assert not ok
        assert "gateway is running" in notes[0]
        assert not into.exists(), "a refusal must not create the target"

    def test_it_will_not_silently_overwrite_a_home(self, backup, tmp_path, monkeypatch):
        monkeypatch.setattr(backup, "gateway_is_running", lambda home: False)
        source = self._backup_dir(backup, tmp_path)
        into = tmp_path / "home"
        into.mkdir()
        _state_db(into / "state.db")
        before = (into / "state.db").read_bytes()
        ok, notes = backup.restore(source, into, force=False)
        assert not ok
        assert "already holds a state.db" in notes[0]
        assert (into / "state.db").read_bytes() == before

    def test_force_overwrites_deliberately(self, backup, tmp_path, monkeypatch):
        monkeypatch.setattr(backup, "gateway_is_running", lambda home: False)
        source = self._backup_dir(backup, tmp_path)
        into = tmp_path / "home"
        into.mkdir()
        (into / "state.db").write_bytes(b"old")
        ok, _ = backup.restore(source, into, force=True)
        assert ok
        assert (into / "state.db").read_bytes() != b"old"

    def test_an_unverified_backup_is_refused(self, backup, tmp_path, monkeypatch):
        monkeypatch.setattr(backup, "gateway_is_running", lambda home: False)
        source = self._backup_dir(backup, tmp_path, verified=False)
        ok, notes = backup.restore(source, tmp_path / "home", force=False)
        assert not ok
        assert "INCOMPLETE" in notes[0]

    def test_a_backup_with_no_receipt_is_not_trusted(self, backup, tmp_path, monkeypatch):
        monkeypatch.setattr(backup, "gateway_is_running", lambda home: False)
        source = tmp_path / "loose-folder"
        source.mkdir()
        _state_db(source / "state.db")
        ok, notes = backup.restore(source, tmp_path / "home", force=False)
        assert not ok
        assert "no receipt" in notes[0]

    def test_an_unreadable_pgrep_means_yes_it_is_running(self, backup, monkeypatch):
        """Biased towards refusing. A false stop costs a flag; a false clear
        costs the database."""
        def explode(*a, **k):
            raise OSError("no pgrep here")
        monkeypatch.setattr(backup.subprocess, "run", explode)
        assert backup.gateway_is_running(Path("/anywhere")) is True


class TestRetention:
    def test_nothing_is_pruned_below_the_limit(self, backup, tmp_path):
        backup.DESTINATION.mkdir(parents=True)
        for n in range(3):
            (backup.DESTINATION / f"2026-09-0{n}").mkdir()
        assert backup.prune(keep=14) == []

    def test_the_oldest_go_first(self, backup):
        backup.DESTINATION.mkdir(parents=True)
        for n in range(1, 6):
            folder = backup.DESTINATION / f"2026-09-0{n}"
            folder.mkdir()
            folder.joinpath("receipt.json").write_text(json.dumps({"verified": True}))
        dropped = backup.prune(keep=3)
        assert dropped == ["2026-09-01", "2026-09-02"]
        assert (backup.DESTINATION / "2026-09-05").exists()

    def test_the_last_verified_backup_is_never_pruned(self, backup):
        """The failure this guards against: everything starts failing, the
        good copy ages out, and retention deletes it to keep bad ones."""
        backup.DESTINATION.mkdir(parents=True)
        good = backup.DESTINATION / "2026-09-01"
        good.mkdir()
        good.joinpath("receipt.json").write_text(json.dumps({"verified": True}))
        for n in range(2, 8):
            bad = backup.DESTINATION / f"2026-09-0{n}"
            bad.mkdir()
            bad.joinpath("receipt.json").write_text(json.dumps({"verified": False}))
        backup.prune(keep=2)
        assert good.exists(), "the only verified backup was deleted by retention"


class TestTheScheduledJob:
    """The plist is a file launchd parses, not a file Python parses, and on
    18 Sep 2026 those two disagreed: a stray `-->` left bare text outside any
    tag, plistlib read it happily and reported the correct interpreter, and
    launchd rejected the file and carried on running the previous definition.
    Nothing would have said so until a 04:00 backup was needed."""

    def test_the_plist_passes_apples_own_validator(self, backup):
        import subprocess
        result = subprocess.run(
            ["plutil", "-lint", str(backup.PLIST_SRC)], capture_output=True
        )
        assert result.returncode == 0, (result.stdout + result.stderr).decode()

    def test_it_runs_under_an_interpreter_allowed_to_read_the_script(self, backup):
        """macOS refuses a launchd agent access to ~/Documents unless that
        binary has been granted it. /usr/bin/python3 has not, and the first
        scheduled run died on 'Operation not permitted' before reading its own
        script. ai.ted.gatewatch has run hundreds of times using the venv's."""
        import plistlib
        spec = plistlib.loads(backup.PLIST_SRC.read_bytes())
        interpreter = spec["ProgramArguments"][0]
        assert "/usr/bin/python3" != interpreter
        assert interpreter.endswith("/venv/bin/python3"), interpreter

    def test_it_never_restores_on_a_timer(self, backup):
        """Restoring is a decision a person makes. A scheduled job that could
        restore is a scheduled job that can overwrite a live home at 4am."""
        import plistlib
        spec = plistlib.loads(backup.PLIST_SRC.read_bytes())
        assert "--restore" not in spec["ProgramArguments"]
        assert "--drill" not in spec["ProgramArguments"]

    def test_it_does_not_run_at_load(self, backup):
        import plistlib
        spec = plistlib.loads(backup.PLIST_SRC.read_bytes())
        assert spec.get("RunAtLoad") is False
        assert spec["StartCalendarInterval"] == {"Hour": 4, "Minute": 0}


class TestDrillFreshness:
    """A restore proof goes stale, and nobody remembers to drill by hand. The
    daily job re-drills rather than relying on anyone noticing."""

    def test_never_drilled_counts_as_stale(self, backup):
        backup.DESTINATION.mkdir(parents=True, exist_ok=True)
        backup.LAST_DRILL = backup.DESTINATION / "last-drill.json"
        assert backup.drill_is_stale() is True

    def test_a_recent_pass_is_not_stale(self, backup):
        import time
        backup.DESTINATION.mkdir(parents=True, exist_ok=True)
        backup.LAST_DRILL = backup.DESTINATION / "last-drill.json"
        backup.LAST_DRILL.write_text(
            json.dumps({"passed": True, "drilled_at": time.time()})
        )
        assert backup.drill_is_stale() is False

    def test_an_old_pass_is_stale(self, backup):
        import time
        backup.DESTINATION.mkdir(parents=True, exist_ok=True)
        backup.LAST_DRILL = backup.DESTINATION / "last-drill.json"
        backup.LAST_DRILL.write_text(
            json.dumps({"passed": True, "drilled_at": time.time() - 8 * 86400})
        )
        assert backup.drill_is_stale() is True

    def test_a_failed_drill_is_always_stale(self, backup):
        """A failure is not a proof with a date on it. Re-drill until it passes."""
        import time
        backup.DESTINATION.mkdir(parents=True, exist_ok=True)
        backup.LAST_DRILL = backup.DESTINATION / "last-drill.json"
        backup.LAST_DRILL.write_text(
            json.dumps({"passed": False, "drilled_at": time.time()})
        )
        assert backup.drill_is_stale() is True
