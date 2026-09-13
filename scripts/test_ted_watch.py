"""Config reading for the watchdog's alert channels.

Everything here is about the same failure: a channel that looks set up and
is not. The 8 Sep 2026 outage ran seventeen hours because the only alarm was
a notification on an empty desk, and the fix for that is worth nothing if the
replacement quietly reads no credentials and reports success.

Every test pins HERMES_ENV at a temp file. A test that fell through to the
real ~/.hermes/.env would read live credentials and, worse, would pass on
this laptop and fail everywhere else.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SOURCE = Path(__file__).resolve().parent / "ted-watch.py"


@pytest.fixture
def watch(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ted_watch_under_test", _SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HERMES_ENV", tmp_path / ".env")
    for name in (*module.EMAIL_KEYS, *module.PUSHOVER_KEYS):
        monkeypatch.delenv(name, raising=False)
    for name in (
        "TED_ALERT_EMAIL_FROM",
        "TED_ALERT_SMTP_HOST",
        "TED_ALERT_SMTP_PORT",
    ):
        monkeypatch.delenv(name, raising=False)
    return module


def _write_env(watch, **values: str) -> None:
    watch.HERMES_ENV.write_text("\n".join(f"{k}={v}" for k, v in values.items()))


class TestSetting:
    def test_reads_the_environment(self, watch, monkeypatch):
        monkeypatch.setenv("TED_ALERT_EMAIL_TO", "her@example.com")
        assert watch.setting("TED_ALERT_EMAIL_TO") == "her@example.com"

    def test_reads_the_env_file_when_the_environment_is_empty(self, watch):
        """launchd inherits almost nothing, so the file is the path that
        matters at 3am."""
        _write_env(watch, TED_ALERT_EMAIL_TO="her@example.com")
        assert watch.setting("TED_ALERT_EMAIL_TO") == "her@example.com"

    def test_the_environment_wins_over_the_file(self, watch, monkeypatch):
        _write_env(watch, TED_ALERT_EMAIL_TO="stale@example.com")
        monkeypatch.setenv("TED_ALERT_EMAIL_TO", "fresh@example.com")
        assert watch.setting("TED_ALERT_EMAIL_TO") == "fresh@example.com"

    def test_quotes_and_whitespace_come_off(self, watch):
        """A pasted secret usually arrives wearing one or the other."""
        watch.HERMES_ENV.write_text('TED_ALERT_SMTP_PASSWORD = "abcd efgh ijkl"  \n')
        assert watch.setting("TED_ALERT_SMTP_PASSWORD") == "abcd efgh ijkl"

    def test_an_empty_value_is_the_same_as_absent(self, watch):
        _write_env(watch, TED_ALERT_EMAIL_TO="")
        assert watch.setting("TED_ALERT_EMAIL_TO") == ""

    def test_a_missing_env_file_is_not_an_error(self, watch):
        assert watch.setting("TED_ALERT_EMAIL_TO") == ""


class TestEmailConfig:
    def _full(self) -> dict[str, str]:
        return {
            "TED_ALERT_EMAIL_TO": "her@example.com",
            "TED_ALERT_SMTP_USER": "ted@example.com",
            "TED_ALERT_SMTP_PASSWORD": "app-password",
        }

    def test_complete_config_is_read(self, watch):
        _write_env(watch, **self._full())
        config = watch.email_config()
        assert config["to"] == "her@example.com"
        assert config["password"] == "app-password"

    def test_sender_defaults_to_the_smtp_user(self, watch):
        _write_env(watch, **self._full())
        assert watch.email_config()["sender"] == "ted@example.com"

    def test_host_and_port_default_to_gmail_over_ssl(self, watch):
        _write_env(watch, **self._full())
        config = watch.email_config()
        assert config["host"] == watch.EMAIL_DEFAULT_HOST
        assert config["port"] == watch.EMAIL_DEFAULT_PORT

    def test_host_and_port_can_be_overridden(self, watch):
        _write_env(
            watch,
            **self._full(),
            TED_ALERT_SMTP_HOST="smtp.fastmail.com",
            TED_ALERT_SMTP_PORT="587",
        )
        config = watch.email_config()
        assert config["host"] == "smtp.fastmail.com"
        assert config["port"] == 587

    def test_a_nonsense_port_falls_back_rather_than_crashing(self, watch):
        _write_env(watch, **self._full(), TED_ALERT_SMTP_PORT="not-a-number")
        assert watch.email_config()["port"] == watch.EMAIL_DEFAULT_PORT

    def test_any_missing_key_means_not_configured(self, watch):
        """Half a config is the dangerous state: it reads as set up."""
        for missing in ("TED_ALERT_EMAIL_TO", "TED_ALERT_SMTP_USER", "TED_ALERT_SMTP_PASSWORD"):
            values = self._full()
            del values[missing]
            _write_env(watch, **values)
            assert watch.email_config() is None, f"missing {missing} should disable email"

    def test_nothing_configured_is_none_not_an_exception(self, watch):
        assert watch.email_config() is None


class TestPushoverCredentials:
    def test_both_keys_present(self, watch):
        _write_env(watch, PUSHOVER_USER_KEY="u", PUSHOVER_API_TOKEN="t")
        assert watch.pushover_credentials() == ("u", "t")

    def test_one_key_alone_is_not_enough(self, watch):
        _write_env(watch, PUSHOVER_USER_KEY="u")
        assert watch.pushover_credentials() is None


class TestRemoteAlerts:
    def test_unconfigured_channels_report_and_never_raise(self, watch):
        results = dict(watch.remote_alerts("t", "b", urgent=True, dry_run=False))
        assert results == {"email": "not configured", "pushover": "not configured"}

    def test_dry_run_names_the_destination_without_sending(self, watch):
        _write_env(
            watch,
            TED_ALERT_EMAIL_TO="her@example.com",
            TED_ALERT_SMTP_USER="ted@example.com",
            TED_ALERT_SMTP_PASSWORD="app-password",
        )
        results = dict(watch.remote_alerts("t", "b", urgent=True, dry_run=True))
        assert results["email"] == "would email her@example.com"

    def test_a_broken_channel_cannot_take_the_others_down(self, watch, monkeypatch):
        """The desk alert and every other channel must still go out. This is
        the rule the whole file rests on: add a road, never remove one."""
        _write_env(
            watch,
            TED_ALERT_EMAIL_TO="her@example.com",
            TED_ALERT_SMTP_USER="ted@example.com",
            TED_ALERT_SMTP_PASSWORD="app-password",
        )

        def explode(*args, **kwargs):
            raise OSError("network is down")

        monkeypatch.setattr(watch.smtplib, "SMTP_SSL", explode)
        results = dict(watch.remote_alerts("t", "b", urgent=True, dry_run=False))
        assert results["email"].startswith("failed (")
        assert results["pushover"] == "not configured"
