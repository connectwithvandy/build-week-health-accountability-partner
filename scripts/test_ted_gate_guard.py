"""The gate guard must not mistake log rotation for absent gates.

On 11 Sep 2026 agent.log rotated at 00:23 and took the only
ted_safety_gates_registered line into agent.log.1. The gateway had not
restarted since 9 Sep, so nothing wrote a replacement, and the guard reported
"no ted_safety_gates_registered line" for two and a half days. The watchdog
turned that into 158 alarms saying Ted was serving ungated. The gates were
running the whole time.

The alarm this script raises is the most serious one in the project, so the
case that made it lie gets a test.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

import pytest

_SOURCE = Path(__file__).resolve().parent / "ted-gate-guard.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("ted_gate_guard_under_test", _SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def guard(tmp_path, monkeypatch):
    module = _load_guard()
    monkeypatch.setattr(module, "AGENT_LOG", tmp_path / "agent.log")
    return module


def _line(when: str) -> str:
    return (
        f"{when},070 INFO ted.safety_gates: ted_safety_gates_registered "
        "source=/repo/hermes/ted_safety_gates/__init__.py memory=on\n"
    )


def _epoch(when: str) -> float:
    return datetime.strptime(when, "%Y-%m-%d %H:%M:%S").timestamp()


def test_reads_the_live_log(guard):
    guard.AGENT_LOG.write_text(_line("2026-09-13 12:54:58"))
    assert guard.last_registration() == _epoch("2026-09-13 12:54:58")


def test_takes_the_last_line_when_the_log_has_several(guard):
    guard.AGENT_LOG.write_text(
        _line("2026-09-09 12:28:12") + "unrelated\n" + _line("2026-09-09 15:50:03")
    )
    assert guard.last_registration() == _epoch("2026-09-09 15:50:03")


def test_finds_the_line_after_rotation_carried_it_away(guard):
    """The 11 Sep case. Live log exists, has no registration, gates are fine."""
    guard.AGENT_LOG.parent.joinpath("agent.log.1").write_text(
        _line("2026-09-09 12:28:12")
    )
    guard.AGENT_LOG.write_text("2026-09-11 00:23:23,876 INFO [something else]\n")
    assert guard.last_registration() == _epoch("2026-09-09 12:28:12")


def test_live_log_wins_over_a_rotated_copy(guard):
    guard.AGENT_LOG.parent.joinpath("agent.log.1").write_text(
        _line("2026-09-09 12:28:12")
    )
    guard.AGENT_LOG.write_text(_line("2026-09-13 12:54:58"))
    assert guard.last_registration() == _epoch("2026-09-13 12:54:58")


def test_walks_back_through_several_rotations_in_order(guard):
    guard.AGENT_LOG.parent.joinpath("agent.log.2").write_text(
        _line("2026-09-05 08:00:00")
    )
    guard.AGENT_LOG.parent.joinpath("agent.log.1").write_text(
        _line("2026-09-09 12:28:12")
    )
    guard.AGENT_LOG.write_text("nothing here\n")
    assert guard.last_registration() == _epoch("2026-09-09 12:28:12")


def test_still_reports_absent_when_no_log_has_the_line(guard):
    """The real failure must survive. Rotation is the excuse, not a blanket one."""
    guard.AGENT_LOG.parent.joinpath("agent.log.1").write_text("old noise\n")
    guard.AGENT_LOG.write_text("new noise\n")
    assert guard.last_registration() is None


def test_no_logs_at_all_is_absent_not_a_crash(guard):
    assert guard.last_registration() is None


def test_oddly_named_sibling_never_outranks_a_real_rotation(guard):
    guard.AGENT_LOG.parent.joinpath("agent.log.bak").write_text(
        _line("2026-01-01 00:00:00")
    )
    guard.AGENT_LOG.parent.joinpath("agent.log.1").write_text(
        _line("2026-09-09 12:28:12")
    )
    guard.AGENT_LOG.write_text("nothing\n")
    assert guard.last_registration() == _epoch("2026-09-09 12:28:12")


# --- cron tool scoping -------------------------------------------------------
#
# config.yaml is not version controlled, so the fix it checks for is always one
# reinstall away from being gone. These pin the reading, because a check that
# quietly answers "fine" for a file it cannot parse is worse than no check.


def _config(guard, tmp_path, monkeypatch, text: str):
    monkeypatch.setattr(guard, "HERMES", tmp_path)
    (tmp_path / "config.yaml").write_text(text)


SCOPED = """platform_toolsets:
  cron:
    - ted
  whatsapp:
    - ted
"""

UNSCOPED = """platform_toolsets:
  whatsapp:
    - ted
  telegram:
    - hermes-telegram
"""


def test_scoped_cron_passes(guard, tmp_path, monkeypatch):
    _config(guard, tmp_path, monkeypatch, SCOPED)
    assert guard.cron_tools_unscoped() is False


def test_missing_cron_key_is_caught(guard, tmp_path, monkeypatch):
    _config(guard, tmp_path, monkeypatch, UNSCOPED)
    assert guard.cron_tools_unscoped() is True


def test_top_level_cron_key_does_not_count(guard, tmp_path, monkeypatch):
    """The real config has a top-level `cron:` block for the scheduler itself.
    Reading that as the scoping would report a fix that was never applied."""
    _config(guard, tmp_path, monkeypatch, "cron:\n  enabled: true\n" + UNSCOPED)
    assert guard.cron_tools_unscoped() is True


def test_a_later_platform_after_cron_still_reads_as_scoped(guard, tmp_path, monkeypatch):
    _config(guard, tmp_path, monkeypatch, SCOPED + "image_gen:\n  use_gateway: true\n")
    assert guard.cron_tools_unscoped() is False


def test_no_config_file_is_not_a_crash(guard, tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "HERMES", tmp_path / "gone")
    assert guard.cron_tools_unscoped() is False
