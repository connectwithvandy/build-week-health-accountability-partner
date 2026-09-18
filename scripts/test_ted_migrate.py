"""The ledger that says which repairs this data has already had.

Eight repair scripts existed and nothing recorded that any of them had run.
That was survivable while data only moved forward. Restore ended that: a backup
from before a repair silently undoes it, and the ledger is the only way to know
what a restored home still needs.

The failure mode under test is a runner that reports a clean system it cannot
actually see. `unknown` must never be rounded to `clean`.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent / "ted-migrate.py"


@pytest.fixture
def migrate(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    spec = importlib.util.spec_from_file_location("ted_migrate_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: @dataclass resolves its own module through
    # sys.modules, and without this it finds None and dies inside dataclasses.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _fake_script(path: Path, prints: str, exit_code: int = 0) -> Path:
    path.write_text(
        "import sys\n"
        f"print({prints!r})\n"
        f"sys.exit({exit_code})\n"
    )
    return path


class TestTheLedgerTravelsWithTheData:
    def test_it_lives_where_the_backup_will_find_it(self, migrate):
        """A ledger anywhere else is useless: it has to arrive with the data it
        describes, and ted-backup.py copies ~/.hermes/state."""
        assert migrate.LEDGER.parent.name == "state"
        assert migrate.LEDGER.parent.parent == migrate.HERMES

    def test_recording_then_reading_back(self, migrate):
        one = migrate.MIGRATIONS[0]
        migrate.record(one, why="ran on the VM")
        held = migrate.load_ledger()["applied"][one.id]
        assert held["script"] == one.script
        assert held["why"] == "ran on the VM"
        assert held["at_readable"]

    def test_a_missing_ledger_is_empty_not_an_error(self, migrate):
        assert migrate.load_ledger() == {"applied": {}}

    def test_a_corrupt_ledger_does_not_crash_the_runner(self, migrate):
        migrate.LEDGER.parent.mkdir(parents=True)
        migrate.LEDGER.write_text("{ truncated")
        assert migrate.load_ledger() == {"applied": {}}

    def test_recording_one_does_not_forget_the_others(self, migrate):
        migrate.record(migrate.MIGRATIONS[0], why="first")
        migrate.record(migrate.MIGRATIONS[1], why="second")
        applied = migrate.load_ledger()["applied"]
        assert len(applied) == 2


class TestVerdicts:
    def _migration(self, migrate, script: Path, clean_when):
        return migrate.Migration(
            "999", script.name, "a test repair", "gate",
            clean_when=clean_when, interpreter=sys.executable,
        )

    def test_the_clean_marker_reads_clean(self, migrate, tmp_path, monkeypatch):
        script = _fake_script(tmp_path / "x.py", "Nothing to do.")
        monkeypatch.setattr(migrate, "SCRIPTS", tmp_path)
        verdict, _ = migrate.dry_run(self._migration(migrate, script, "Nothing to do."))
        assert verdict == "clean"

    def test_no_marker_in_the_output_is_pending(self, migrate, tmp_path, monkeypatch):
        script = _fake_script(tmp_path / "x.py", "3 users need fixing")
        monkeypatch.setattr(migrate, "SCRIPTS", tmp_path)
        verdict, detail = migrate.dry_run(self._migration(migrate, script, "Nothing to do."))
        assert verdict == "pending"
        assert "3 users need fixing" in detail

    def test_a_script_with_no_marker_is_unknown_never_clean(self, migrate, tmp_path, monkeypatch):
        """Three of the eight print counts rather than a verdict. Reporting
        those as clean would be the runner inventing confidence."""
        script = _fake_script(tmp_path / "x.py", "already correct, nothing to do   5")
        monkeypatch.setattr(migrate, "SCRIPTS", tmp_path)
        verdict, detail = migrate.dry_run(self._migration(migrate, script, None))
        assert verdict == "unknown"
        assert "read the dry run yourself" in detail

    def test_a_failing_script_is_unknown_not_clean(self, migrate, tmp_path, monkeypatch):
        script = _fake_script(tmp_path / "x.py", "Nothing to do.", exit_code=1)
        monkeypatch.setattr(migrate, "SCRIPTS", tmp_path)
        verdict, detail = migrate.dry_run(self._migration(migrate, script, "Nothing to do."))
        assert verdict == "unknown", "a script that failed proved nothing"
        assert "exited 1" in detail

    def test_a_missing_script_is_unknown(self, migrate, tmp_path, monkeypatch):
        monkeypatch.setattr(migrate, "SCRIPTS", tmp_path)
        gone = migrate.Migration(
            "999", "not-here.py", "x", "gate",
            clean_when="Nothing to do.", interpreter=sys.executable,
        )
        verdict, detail = migrate.dry_run(gone)
        assert verdict == "unknown"
        assert "gone" in detail

    def test_a_missing_interpreter_is_unknown(self, migrate, tmp_path, monkeypatch):
        script = _fake_script(tmp_path / "x.py", "Nothing to do.")
        monkeypatch.setattr(migrate, "SCRIPTS", tmp_path)
        needs_venv = migrate.Migration(
            "999", script.name, "x", "cron",
            clean_when="Nothing to do.", interpreter="/no/such/python3",
        )
        verdict, detail = migrate.dry_run(needs_venv)
        assert verdict == "unknown"
        assert "not here" in detail


class TestTheRegistry:
    def test_every_migration_names_a_script_that_exists(self, migrate):
        """The registry going stale is how this becomes decoration."""
        for one in migrate.MIGRATIONS:
            assert (Path(__file__).resolve().parent / one.script).exists(), one.script

    def test_ids_are_unique(self, migrate):
        ids = [one.id for one in migrate.MIGRATIONS]
        assert len(ids) == len(set(ids))

    def test_a_migration_without_a_marker_explains_itself(self, migrate):
        """If it cannot be auto-checked, the note has to say why, or the
        `unknown` beside it is just noise."""
        for one in migrate.MIGRATIONS:
            if one.clean_when is None:
                assert one.note, f"{one.id} has no marker and no explanation"

    def test_the_cron_repair_uses_the_interpreter_that_has_croniter(self, migrate):
        """Without croniter, update_job stores next_run_at: null and the
        reminder silently never fires again."""
        ghost = migrate.find("008")
        assert ghost.script == "ted-repair-ghost-jobs.py"
        assert ghost.interpreter.endswith("/venv/bin/python3")

    def test_find_by_id_and_by_script_name(self, migrate):
        assert migrate.find("003").script == "ted-repair-language-preference.py"
        assert migrate.find("ted-repair-language-preference.py").id == "003"
        assert migrate.find("nope") is None
