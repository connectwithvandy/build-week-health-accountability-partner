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


# --- the Cloud API is a second WhatsApp, and the guard was blind to it ---
#
# On 19 Sep 2026 whatsapp_cloud was live, absent from platform_toolsets, and so
# running on hermes-whatsapp: terminal, files, patch and the browser. The guard
# read only the whatsapp key and said everything was fine. These tests exist so
# that a third WhatsApp cannot repeat it.

CLOUD_LIVE = (
    "WHATSAPP_CLOUD_PHONE_NUMBER_ID=1324962557368120\n"
    "WHATSAPP_CLOUD_ACCESS_TOKEN=EAAtoken\n"
)


def _env(guard, tmp_path, monkeypatch, text: str):
    env = tmp_path / "dotenv"
    env.write_text(text)
    monkeypatch.setattr(guard, "HERMES_ENV", env)
    for name in ("WHATSAPP_CLOUD_PHONE_NUMBER_ID", "WHATSAPP_CLOUD_ACCESS_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def test_cloud_is_out_of_scope_until_it_is_configured(guard, tmp_path, monkeypatch):
    _env(guard, tmp_path, monkeypatch, "")
    assert guard.whatsapp_platforms() == ["whatsapp"]


def test_cloud_is_in_scope_once_phone_and_token_are_set(guard, tmp_path, monkeypatch):
    _env(guard, tmp_path, monkeypatch, CLOUD_LIVE)
    assert guard.whatsapp_platforms() == ["whatsapp", "whatsapp_cloud"]


def test_cloud_needs_a_token_too_not_just_a_phone_id(guard, tmp_path, monkeypatch):
    _env(guard, tmp_path, monkeypatch, "WHATSAPP_CLOUD_PHONE_NUMBER_ID=123\n")
    assert guard.whatsapp_platforms() == ["whatsapp"]


def test_live_cloud_without_a_scope_is_unsafe(guard, tmp_path, monkeypatch):
    _config(guard, tmp_path, monkeypatch, SAFE_WHATSAPP)
    _env(guard, tmp_path, monkeypatch, CLOUD_LIVE)
    assert guard.unsafe_whatsapp_toolsets_by_platform() == {
        "whatsapp_cloud": ["<unscoped>"]
    }


def test_scoping_the_cloud_clears_it(guard, tmp_path, monkeypatch):
    _config(
        guard,
        tmp_path,
        monkeypatch,
        SAFE_WHATSAPP + "  whatsapp_cloud:\n    - cronjob\n    - ted\n    - vision\n",
    )
    _env(guard, tmp_path, monkeypatch, CLOUD_LIVE)
    assert guard.unsafe_whatsapp_toolsets_by_platform() == {}


def test_an_unsafe_tool_on_the_cloud_is_named(guard, tmp_path, monkeypatch):
    _config(
        guard,
        tmp_path,
        monkeypatch,
        SAFE_WHATSAPP + "  whatsapp_cloud:\n    - ted\n    - terminal\n",
    )
    _env(guard, tmp_path, monkeypatch, CLOUD_LIVE)
    assert guard.unsafe_whatsapp_toolsets_by_platform() == {
        "whatsapp_cloud": ["terminal"]
    }


def test_a_dormant_cloud_does_not_fail_the_guard(guard, tmp_path, monkeypatch):
    """No token means gateway/config.py never adds the platform, so no finding."""
    _config(guard, tmp_path, monkeypatch, SAFE_WHATSAPP)
    _env(guard, tmp_path, monkeypatch, "")
    assert guard.unsafe_whatsapp_toolsets_by_platform() == {}


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


# --- the second door ---------------------------------------------------------
#
# platform_toolsets.whatsapp was locked to three toolsets on 17 Sep and the
# guard has checked it since. It reads one of the two lists Hermes consults.
# Plugin toolsets go through `known_plugin_toolsets`, where a platform with no
# entry has seen nothing, and anything it has not seen arrives enabled.


DOOR_OPEN = """platform_toolsets:
  whatsapp:
    - cronjob
    - ted
    - vision
known_plugin_toolsets:
  cli:
    - spotify
"""

DOOR_CLOSED = DOOR_OPEN + """  whatsapp:
    - spotify
    - ted
"""


def test_whatsapp_with_no_plugin_entry_is_open(guard, tmp_path, monkeypatch):
    _config(guard, tmp_path, monkeypatch, DOOR_OPEN)
    assert guard.whatsapp_plugins_unrecorded() is True


def test_whatsapp_that_has_seen_its_plugins_is_closed(guard, tmp_path, monkeypatch):
    _config(guard, tmp_path, monkeypatch, DOOR_CLOSED)
    assert guard.whatsapp_plugins_unrecorded() is False


def test_an_empty_whatsapp_entry_still_counts_as_seen(guard, tmp_path, monkeypatch):
    # Hermes writes an empty list when a platform has plugins offered and none
    # chosen. Empty is a decision; absent is not.
    _config(guard, tmp_path, monkeypatch, DOOR_OPEN + "  whatsapp:\n")
    assert guard.whatsapp_plugins_unrecorded() is False
    assert guard._known_plugin_toolsets("whatsapp") == []


def test_a_config_without_the_parent_key_is_open(guard, tmp_path, monkeypatch):
    _config(guard, tmp_path, monkeypatch, "platform_toolsets:\n  whatsapp:\n    - ted\n")
    assert guard.whatsapp_plugins_unrecorded() is True


def test_an_unreadable_config_is_treated_as_open(guard, tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "HERMES", tmp_path / "gone")
    assert guard.whatsapp_plugins_unrecorded() is True


def test_a_cli_entry_does_not_close_whatsapp(guard, tmp_path, monkeypatch):
    # The bug exactly: the file looks configured, and the configured platform
    # is the one nobody talks to.
    _config(guard, tmp_path, monkeypatch, DOOR_OPEN)
    assert guard._known_plugin_toolsets("cli") == ["spotify"]
    assert guard._known_plugin_toolsets("whatsapp") is None


# --- a plugin that nobody put here -------------------------------------------


def _plugin(root: Path, name: str) -> None:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "plugin.yaml").write_text(f"name: {name}\n")


def test_a_pinned_plugin_is_not_reported(guard, tmp_path, monkeypatch):
    _plugin(tmp_path / "plugins", "ted-safety-gates")
    monkeypatch.setattr(guard, "PLUGIN_DIRS", (tmp_path / "plugins",))
    assert guard.unpinned_plugins() == []


def test_a_new_plugin_is_reported(guard, tmp_path, monkeypatch):
    _plugin(tmp_path / "plugins", "ted-safety-gates")
    _plugin(tmp_path / "plugins", "shiny-new-thing")
    monkeypatch.setattr(guard, "PLUGIN_DIRS", (tmp_path / "plugins",))
    assert guard.unpinned_plugins() == ["shiny-new-thing"]


def test_both_plugin_directories_are_read(guard, tmp_path, monkeypatch):
    _plugin(tmp_path / "bundled", "arrived-with-the-upgrade")
    _plugin(tmp_path / "installed", "installed-by-hand")
    monkeypatch.setattr(
        guard, "PLUGIN_DIRS", (tmp_path / "bundled", tmp_path / "installed")
    )
    assert guard.unpinned_plugins() == [
        "arrived-with-the-upgrade",
        "installed-by-hand",
    ]


def test_a_folder_without_a_manifest_is_not_a_plugin(guard, tmp_path, monkeypatch):
    (tmp_path / "plugins" / "__pycache__").mkdir(parents=True)
    (tmp_path / "plugins" / "notes").mkdir()
    monkeypatch.setattr(guard, "PLUGIN_DIRS", (tmp_path / "plugins",))
    assert guard.unpinned_plugins() == []


def test_a_missing_plugin_directory_is_not_a_finding(guard, tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "PLUGIN_DIRS", (tmp_path / "gone",))
    assert guard.unpinned_plugins() == []


def test_the_pinned_list_matches_this_machine():
    # Not a fixture: if this fails, a plugin really did appear and the guard's
    # inventory is the thing that is out of date.
    guard = _load_guard()
    assert guard.unpinned_plugins() == []


def test_recording_plugins_is_not_the_same_as_closing_the_door(guard, tmp_path, monkeypatch):
    """The limit of the entry, pinned so the report cannot overclaim again.

    A config that records every plugin installed today and one that records
    none are identical for a plugin that arrives tomorrow: both leave it
    enabled, because `known_plugin_toolsets` is a record of what was seen, not
    an allowlist. The first draft of this check said "the door is closed" and
    was wrong; `unpinned_plugins` is what actually watches that case.
    """
    _config(guard, tmp_path, monkeypatch, DOOR_CLOSED)
    recorded = guard._known_plugin_toolsets("whatsapp")

    assert guard.whatsapp_plugins_unrecorded() is False
    assert "arrived-tomorrow" not in recorded


# --- a green report over a stale process is the failure mode that fooled us ---
#
# On 19 Sep 2026 whatsapp_cloud was scoped in config.yaml and still unscoped in
# the running gateway, and every line of the report said ok. The staleness
# check covered the gate source only. It now covers every startup input.


def _aged(path, seconds_after: float, registered: float):
    """Give one file an mtime relative to the registration stamp."""
    import os

    os.utime(path, (registered + seconds_after, registered + seconds_after))


def test_config_edited_after_the_gateway_read_it_is_stale(guard, tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "HERMES", tmp_path)
    monkeypatch.setattr(guard, "HERMES_ENV", tmp_path / ".env")
    monkeypatch.setattr(guard, "gate_source", lambda: None)
    config = tmp_path / "config.yaml"
    config.write_text("platform_toolsets:\n")
    (tmp_path / ".env").write_text("")

    registered = 1_000_000.0
    _aged(config, 60, registered)
    _aged(tmp_path / ".env", -60, registered)

    stale = guard.stale_startup_inputs(registered)
    assert [path.name for path, _ in stale] == ["config.yaml"]


def test_env_edited_after_the_gateway_read_it_is_stale(guard, tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "HERMES", tmp_path)
    monkeypatch.setattr(guard, "HERMES_ENV", tmp_path / ".env")
    monkeypatch.setattr(guard, "gate_source", lambda: None)
    config = tmp_path / "config.yaml"
    config.write_text("platform_toolsets:\n")
    (tmp_path / ".env").write_text("")

    registered = 1_000_000.0
    _aged(config, -60, registered)
    _aged(tmp_path / ".env", 60, registered)

    stale = guard.stale_startup_inputs(registered)
    assert [path.name for path, _ in stale] == [".env"]


def test_untouched_inputs_are_not_stale(guard, tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "HERMES", tmp_path)
    monkeypatch.setattr(guard, "HERMES_ENV", tmp_path / ".env")
    monkeypatch.setattr(guard, "gate_source", lambda: None)
    config = tmp_path / "config.yaml"
    config.write_text("platform_toolsets:\n")
    (tmp_path / ".env").write_text("")

    registered = 1_000_000.0
    _aged(config, -60, registered)
    _aged(tmp_path / ".env", -60, registered)

    assert guard.stale_startup_inputs(registered) == []


def test_a_restart_moments_after_an_edit_is_not_stale(guard, tmp_path, monkeypatch):
    """Five seconds of slack: the restart lands just after the edit."""
    monkeypatch.setattr(guard, "HERMES", tmp_path)
    monkeypatch.setattr(guard, "HERMES_ENV", tmp_path / ".env")
    monkeypatch.setattr(guard, "gate_source", lambda: None)
    config = tmp_path / "config.yaml"
    config.write_text("platform_toolsets:\n")
    (tmp_path / ".env").write_text("")

    registered = 1_000_000.0
    _aged(config, 3, registered)
    _aged(tmp_path / ".env", -60, registered)

    assert guard.stale_startup_inputs(registered) == []


def test_a_missing_input_is_skipped_not_crashed_on(guard, tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "HERMES", tmp_path)
    monkeypatch.setattr(guard, "HERMES_ENV", tmp_path / "gone.env")
    monkeypatch.setattr(guard, "gate_source", lambda: None)
    assert guard.stale_startup_inputs(1_000_000.0) == []


def test_the_worst_offender_is_reported_first(guard, tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "HERMES", tmp_path)
    monkeypatch.setattr(guard, "HERMES_ENV", tmp_path / ".env")
    monkeypatch.setattr(guard, "gate_source", lambda: None)
    config = tmp_path / "config.yaml"
    config.write_text("platform_toolsets:\n")
    (tmp_path / ".env").write_text("")

    registered = 1_000_000.0
    _aged(config, 30, registered)
    _aged(tmp_path / ".env", 90, registered)

    assert [path.name for path, _ in guard.stale_startup_inputs(registered)] == [
        ".env",
        "config.yaml",
    ]


def test_the_gate_source_is_still_watched(guard, tmp_path, monkeypatch):
    """The original check must survive being generalised."""
    monkeypatch.setattr(guard, "HERMES", tmp_path)
    monkeypatch.setattr(guard, "HERMES_ENV", tmp_path / ".env")
    source = tmp_path / "gates.py"
    source.write_text("")
    monkeypatch.setattr(guard, "gate_source", lambda: source)
    (tmp_path / "config.yaml").write_text("platform_toolsets:\n")
    (tmp_path / ".env").write_text("")

    registered = 1_000_000.0
    _aged(source, 60, registered)
    _aged(tmp_path / "config.yaml", -60, registered)
    _aged(tmp_path / ".env", -60, registered)

    assert [path.name for path, _ in guard.stale_startup_inputs(registered)] == [
        "gates.py"
    ]


class TestACheckoutIsNotAnEdit:
    """19 Sep 2026, twice in one afternoon.

    Editing the gate source correctly reported the running gateway as stale,
    and emailed about it. Then `git checkout main` rewrote every file in the
    tree and reported it again, for files whose bytes had not changed at all.
    The first was true and useful. The second was a false page, and a guard
    that cries wolf ends the same way as one that cannot see a stale process:
    unread at the moment it matters.

    The timestamp opens the question now, and the contents answer it.
    """

    @staticmethod
    def _bed(guard, tmp_path, monkeypatch, body: str = "platform_toolsets:\n"):
        monkeypatch.setattr(guard, "HERMES", tmp_path)
        monkeypatch.setattr(guard, "HERMES_ENV", tmp_path / ".env")
        monkeypatch.setattr(guard, "gate_source", lambda: None)
        config = tmp_path / "config.yaml"
        config.write_text(body)
        (tmp_path / ".env").write_text("")
        return config

    def test_a_file_touched_but_unchanged_is_not_stale(
        self, guard, tmp_path, monkeypatch
    ):
        config = self._bed(guard, tmp_path, monkeypatch)
        registered = 1_000_000.0
        _aged(config, -60, registered)
        _aged(tmp_path / ".env", -60, registered)
        # Seen once while untouched, which is what makes the fingerprint
        # trustworthy.
        assert guard.stale_startup_inputs(registered) == []
        # Now a checkout: same bytes, new timestamp.
        _aged(config, 60, registered)
        assert guard.stale_startup_inputs(registered) == []

    def test_a_real_edit_is_still_caught(self, guard, tmp_path, monkeypatch):
        config = self._bed(guard, tmp_path, monkeypatch)
        registered = 1_000_000.0
        _aged(config, -60, registered)
        _aged(tmp_path / ".env", -60, registered)
        assert guard.stale_startup_inputs(registered) == []
        config.write_text("platform_toolsets:\n  whatsapp: [ted]\n")
        _aged(config, 60, registered)
        assert [p.name for p, _ in guard.stale_startup_inputs(registered)] == [
            "config.yaml"
        ]

    def test_a_file_never_seen_clean_falls_back_to_the_timestamp(
        self, guard, tmp_path, monkeypatch
    ):
        """The hole this could have had. If somebody edits a file and the guard
        first runs afterwards, the hash it sees is the edited one, and trusting
        it would bless the change instead of reporting it. So a fingerprint is
        only recorded while the file is still untouched since boot, and without
        one the timestamp stands."""
        config = self._bed(guard, tmp_path, monkeypatch)
        registered = 1_000_000.0
        _aged(config, 60, registered)
        _aged(tmp_path / ".env", -60, registered)
        assert [p.name for p, _ in guard.stale_startup_inputs(registered)] == [
            "config.yaml"
        ]

    def test_a_restart_starts_the_fingerprints_over(
        self, guard, tmp_path, monkeypatch
    ):
        """Fingerprints belong to one run of the gateway. Carrying them across
        a restart would compare today's disk with what a dead process read."""
        config = self._bed(guard, tmp_path, monkeypatch)
        first = 1_000_000.0
        _aged(config, -60, first)
        _aged(tmp_path / ".env", -60, first)
        assert guard.stale_startup_inputs(first) == []
        stored = json.loads(guard.fingerprints_path().read_text())
        assert stored["registered"] == first
        second = 2_000_000.0
        _aged(config, 60, second)
        assert [p.name for p, _ in guard.stale_startup_inputs(second)] == [
            "config.yaml"
        ]

    def test_it_never_writes_outside_the_hermes_home_it_was_given(
        self, guard, tmp_path, monkeypatch
    ):
        config = self._bed(guard, tmp_path, monkeypatch)
        registered = 1_000_000.0
        _aged(config, -60, registered)
        _aged(tmp_path / ".env", -60, registered)
        guard.stale_startup_inputs(registered)
        assert guard.fingerprints_path().is_relative_to(tmp_path)
        assert guard.fingerprints_path().exists()
