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
import json
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

SAFE_WHATSAPP = """platform_toolsets:
  whatsapp:
    - cronjob
    - ted
    - vision
  telegram:
    - hermes-telegram
"""

UNSAFE_WHATSAPP = """platform_toolsets:
  whatsapp:
    - cronjob
    - file
    - ted
    - vision
"""


def test_safe_whatsapp_toolsets_pass(guard, tmp_path, monkeypatch):
    _config(guard, tmp_path, monkeypatch, SAFE_WHATSAPP)
    assert guard.unsafe_whatsapp_toolsets() == []


def test_file_tool_is_never_available_in_whatsapp(guard, tmp_path, monkeypatch):
    _config(guard, tmp_path, monkeypatch, UNSAFE_WHATSAPP)
    assert guard.unsafe_whatsapp_toolsets() == ["file"]


def test_unknown_whatsapp_toolset_fails_closed(guard, tmp_path, monkeypatch):
    _config(
        guard,
        tmp_path,
        monkeypatch,
        SAFE_WHATSAPP.replace("    - vision\n", "    - future-power-tool\n"),
    )
    assert guard.unsafe_whatsapp_toolsets() == ["future-power-tool"]


def test_missing_whatsapp_scope_fails_closed(guard, tmp_path, monkeypatch):
    _config(guard, tmp_path, monkeypatch, "platform_toolsets:\n  cron:\n    - ted\n")
    assert guard.unsafe_whatsapp_toolsets() == ["<unscoped>"]


def test_unreadable_config_fails_closed(guard, tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "HERMES", tmp_path / "gone")
    assert guard.unsafe_whatsapp_toolsets() == ["<unreadable>"]


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


# --- unpinned cron jobs ------------------------------------------------------
#
# An unpinned job is skipped when the global model changes, and since Hermes
# patch 08 that skip never reaches the user's chat. The reminder just stops.
# The gate pins each new one as it is created but swallows its own errors on
# purpose, so this is the only thing that would notice it had stopped working.


def _jobs(guard, tmp_path, monkeypatch, jobs):
    monkeypatch.setattr(guard, "HERMES", tmp_path)
    (tmp_path / "cron").mkdir(exist_ok=True)
    (tmp_path / "cron" / "jobs.json").write_text(json.dumps({"jobs": jobs}))


PINNED = {"name": "ted:a:meals", "enabled": True,
          "provider": "anthropic", "model": "claude-sonnet-5"}


def test_a_pinned_job_is_fine(guard, tmp_path, monkeypatch):
    _jobs(guard, tmp_path, monkeypatch, [PINNED])
    assert guard.unpinned_enabled_jobs() == []


def test_an_unpinned_enabled_job_is_reported(guard, tmp_path, monkeypatch):
    _jobs(guard, tmp_path, monkeypatch,
          [{"name": "ted:a:meals", "enabled": True, "provider": None, "model": None}])
    assert guard.unpinned_enabled_jobs() == ["ted:a:meals"]


def test_half_pinned_counts_as_unpinned(guard, tmp_path, monkeypatch):
    """The drift guard checks each axis separately, so a job with a provider
    and no model is skipped just the same."""
    _jobs(guard, tmp_path, monkeypatch,
          [{"name": "ted:a:meals", "enabled": True, "provider": "anthropic", "model": ""}])
    assert guard.unpinned_enabled_jobs() == ["ted:a:meals"]


def test_a_disabled_job_is_not_reported(guard, tmp_path, monkeypatch):
    """It sends nothing either way. It gets pinned when it is resumed."""
    _jobs(guard, tmp_path, monkeypatch,
          [{"name": "ted:a:meals", "enabled": False, "provider": None, "model": None}])
    assert guard.unpinned_enabled_jobs() == []


def test_a_no_agent_job_is_not_reported(guard, tmp_path, monkeypatch):
    """It makes no model call, so there is no model to pin."""
    _jobs(guard, tmp_path, monkeypatch,
          [{"name": "backup", "enabled": True, "no_agent": True,
            "provider": None, "model": None}])
    assert guard.unpinned_enabled_jobs() == []


def test_a_missing_jobs_file_is_not_a_crash(guard, tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "HERMES", tmp_path / "gone")
    assert guard.unpinned_enabled_jobs() == []


def test_a_bare_list_shape_is_read_too(guard, tmp_path, monkeypatch):
    """jobs.json has been written as a bare list and as {"jobs": [...]}."""
    monkeypatch.setattr(guard, "HERMES", tmp_path)
    (tmp_path / "cron").mkdir(exist_ok=True)
    (tmp_path / "cron" / "jobs.json").write_text(json.dumps(
        [{"name": "ted:a:meals", "enabled": True, "provider": None, "model": None}]))
    assert guard.unpinned_enabled_jobs() == ["ted:a:meals"]


# Roadmap T03: fail closed when the safety asset itself is missing or broken.
#
# Hermes catches every exception a plugin raises at load time, logs one
# WARNING and carries on. For this plugin that means a rename, a syntax error
# or a missing file leaves Ted answering real people with no 18+ check and no
# forced disclosure, and nothing in the chat or the log says so. `shim_imports`
# is the stop. It had no test for any of the cases it exists to catch.

WORKING_SHIM = '''
def register(ctx):
    return None
'''


def shim_at(tmp_path, monkeypatch, body: str | None):
    """Point the guard at a shim of our choosing. None means no file at all."""
    module = _load_guard()
    path = tmp_path / "plugins" / "ted-safety-gates" / "__init__.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    if body is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(module, "SHIM", path)
    return module


def test_a_working_shim_passes(tmp_path, monkeypatch):
    module = shim_at(tmp_path, monkeypatch, WORKING_SHIM)
    assert module.shim_imports() is None


def test_a_missing_safety_file_is_caught(tmp_path, monkeypatch):
    """The rename case. Nothing is loaded, so nothing may serve."""
    module = shim_at(tmp_path, monkeypatch, None)
    problem = module.shim_imports()
    assert problem is not None
    assert "no plugin shim" in problem


def test_a_syntax_error_is_caught(tmp_path, monkeypatch):
    module = shim_at(tmp_path, monkeypatch, "def register(ctx:\n    return None\n")
    assert module.shim_imports() is not None


def test_a_shim_without_register_is_caught(tmp_path, monkeypatch):
    """It imports cleanly and is still useless. Importing is not enough."""
    module = shim_at(tmp_path, monkeypatch, "VERSION = 1\n")
    assert module.shim_imports() is not None


def test_a_register_that_is_not_callable_is_caught(tmp_path, monkeypatch):
    module = shim_at(tmp_path, monkeypatch, "register = 'not a function'\n")
    assert module.shim_imports() is not None


def test_a_shim_that_raises_on_import_is_caught(tmp_path, monkeypatch):
    """What the real shim does when the repo gate file has gone missing."""
    module = shim_at(
        tmp_path, monkeypatch,
        "raise RuntimeError('Ted safety gates source not found')\n"
        "def register(ctx):\n    return None\n",
    )
    problem = module.shim_imports()
    assert problem is not None
    assert "source not found" in problem


def test_an_empty_shim_is_caught(tmp_path, monkeypatch):
    module = shim_at(tmp_path, monkeypatch, "")
    assert module.shim_imports() is not None


def test_the_real_shim_refuses_when_its_source_is_gone(tmp_path, monkeypatch):
    """The live shim's own contract: no gates source means no gates.

    Checked against the shipped file rather than a copy, so a rewrite that
    quietly dropped the guard would fail here.
    """
    real = Path(__file__).resolve().parents[1] / "hermes" / "machine" / "plugin-shim.py"
    text = real.read_text(encoding="utf-8")
    assert "Ted must not run without its gates" in text
    assert "raise RuntimeError" in text


def test_gate_source_is_none_when_the_shim_is_missing(tmp_path, monkeypatch):
    module = shim_at(tmp_path, monkeypatch, None)
    assert module.gate_source() is None


class TestItWaitsOutARestart:
    """`hermes gateway restart` hands off to launchd and returns immediately,
    so for a second or two there is no pid file. The guard used to announce
    "gateway is not running" and exit non-zero, which on 18 Sep 2026 broke a
    `restart && guard && migrate` chain and silently skipped the migration on
    the end of it."""

    def test_it_waits_while_launchd_is_putting_it_back(self, guard, monkeypatch):
        answers = iter([None, None, 4242])
        monkeypatch.setattr(guard, "running_pid", lambda: next(answers))
        monkeypatch.setattr(guard, "launchd_job_loaded", lambda: True)
        monkeypatch.setattr(guard.time, "sleep", lambda _s: None)
        assert guard.settled_pid(grace=10) == 4242

    def test_a_gateway_stopped_on_purpose_answers_at_once(self, guard, monkeypatch):
        """No launchd definition means nobody is coming back, so waiting would
        just make every check on a stopped host take half a minute."""
        monkeypatch.setattr(guard, "running_pid", lambda: None)
        monkeypatch.setattr(guard, "launchd_job_loaded", lambda: False)
        waited = []
        monkeypatch.setattr(guard.time, "sleep", lambda s: waited.append(s))
        assert guard.settled_pid(grace=10) is None
        assert waited == []

    def test_it_gives_up_rather_than_hanging(self, guard, monkeypatch):
        monkeypatch.setattr(guard, "running_pid", lambda: None)
        monkeypatch.setattr(guard, "launchd_job_loaded", lambda: True)
        monkeypatch.setattr(guard.time, "sleep", lambda _s: None)
        assert guard.settled_pid(grace=0.01) is None

    def test_a_running_gateway_never_waits(self, guard, monkeypatch):
        monkeypatch.setattr(guard, "running_pid", lambda: 99)
        waited = []
        monkeypatch.setattr(guard.time, "sleep", lambda s: waited.append(s))
        assert guard.settled_pid() == 99
        assert waited == []
