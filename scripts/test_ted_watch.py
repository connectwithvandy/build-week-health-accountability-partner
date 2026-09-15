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
    # Real backoff belongs in production, not in a test run. Attempts are left
    # alone so the retry itself is still exercised.
    monkeypatch.setattr(module, "EMAIL_RETRY_SECONDS", 0)
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


class TestCheckModel:
    """The failure that hid for ten days.

    The Anthropic balance ran dry on 5 Sep 2026. Every call since failed and
    fell back to OpenRouter, so users kept getting answers and every existing
    check stayed green. The fallback working is what made it invisible, so this
    reads the failure and not the outcome.
    """

    def _log(self, watch, tmp_path, monkeypatch, lines):
        log = tmp_path / "agent.log"
        log.write_text("\n".join(lines) + "\n")
        monkeypatch.setattr(watch, "AGENT_LOG", log)
        return log

    def _stamp(self, watch, hours_ago):
        from datetime import timedelta

        return (watch.datetime.now() - timedelta(hours=hours_ago)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    def test_missing_log_is_not_a_failure(self, watch, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "AGENT_LOG", tmp_path / "nope.log")
        ok, detail = watch.check_model()
        assert ok is True
        assert "no agent log" in detail

    def test_quiet_log_reads_healthy(self, watch, tmp_path, monkeypatch):
        self._log(watch, tmp_path, monkeypatch, [
            f"{self._stamp(watch, 1)},001 INFO agent: API call #1 model=claude-sonnet-5",
        ])
        ok, _ = watch.check_model()
        assert ok is True

    def test_empty_balance_is_caught(self, watch, tmp_path, monkeypatch):
        self._log(watch, tmp_path, monkeypatch, [
            f"{self._stamp(watch, 2)},001 INFO agent: Error code: 400 - "
            "{'message': 'Your credit balance is too low to access the Anthropic API.'}",
        ])
        ok, detail = watch.check_model()
        assert ok is False
        assert "credit balance is empty" in detail

    def test_a_dropped_connection_is_left_alone(self, watch, tmp_path, monkeypatch):
        """The fallback exists for these. Waking someone for one is noise."""
        self._log(watch, tmp_path, monkeypatch, [
            f"{self._stamp(watch, 1)},001 WARNING agent: API call failed "
            "error_type=APIConnectionError provider=anthropic",
        ])
        ok, _ = watch.check_model()
        assert ok is True

    def test_an_old_failure_that_stopped_does_not_keep_alerting(
        self, watch, tmp_path, monkeypatch
    ):
        self._log(watch, tmp_path, monkeypatch, [
            f"{self._stamp(watch, watch.MODEL_WINDOW_HOURS + 6)},001 INFO agent: "
            "Your credit balance is too low to access the Anthropic API.",
        ])
        ok, _ = watch.check_model()
        assert ok is True

    def test_a_rejected_key_is_caught_too(self, watch, tmp_path, monkeypatch):
        self._log(watch, tmp_path, monkeypatch, [
            f"{self._stamp(watch, 1)},001 ERROR agent: authentication_error",
        ])
        ok, detail = watch.check_model()
        assert ok is False
        assert "rejected" in detail


class TestCheckDropped:
    """Patch 12 drops a reply that missed its moment. Nothing noticed.

    GT sent "All" on 11 Sep 2026 and the reply died with the link. Ankiita
    asked at 00:29 on 15 Sep why replies were slow, the agent hung, and the
    apology could not send either. Both kept getting scheduled nudges while
    neither got an answer.
    """

    def _ledger(self, watch, tmp_path, monkeypatch, rows):
        import sqlite3

        db = tmp_path / "state.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE delivery_obligations ("
            "obligation_id TEXT PRIMARY KEY, chat_id TEXT, state TEXT, created_at REAL)"
        )
        conn.executemany(
            "INSERT INTO delivery_obligations VALUES (?,?,?,?)",
            [(str(i), c, s, w) for i, (c, s, w) in enumerate(rows)],
        )
        conn.commit()
        conn.close()
        monkeypatch.setattr(watch, "STATE_DB", db)
        return db

    def test_no_ledger_is_not_a_failure(self, watch, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "STATE_DB", tmp_path / "nope.db")
        ok, detail = watch.check_dropped()
        assert ok is True
        assert "no delivery ledger" in detail

    def test_everything_delivered_reads_clear(self, watch, tmp_path, monkeypatch):
        import time

        self._ledger(watch, tmp_path, monkeypatch, [
            ("ankiita", "delivered", time.time() - 3600),
        ])
        ok, detail = watch.check_dropped()
        assert ok is True
        assert "nobody is waiting" in detail

    def test_a_dropped_reply_is_reported(self, watch, tmp_path, monkeypatch):
        import time

        self._ledger(watch, tmp_path, monkeypatch, [
            ("gt", "abandoned", time.time() - 4 * 24 * 3600),
        ])
        ok, detail = watch.check_dropped()
        assert ok is False
        assert "1 person" in detail
        assert "4 days" in detail

    def test_answering_them_later_closes_it(self, watch, tmp_path, monkeypatch):
        """Shreya was dropped on 14 Sep at 14:22 and answered that evening."""
        import time

        now = time.time()
        self._ledger(watch, tmp_path, monkeypatch, [
            ("shreya", "abandoned", now - 8 * 3600),
            ("shreya", "delivered", now - 2 * 3600),
        ])
        ok, detail = watch.check_dropped()
        assert ok is True
        assert "nobody is waiting" in detail

    def test_an_earlier_delivery_does_not_close_it(self, watch, tmp_path, monkeypatch):
        """Only a message sent *after* the drop counts. Ankiita's last good
        reply was 14 Sep 09:56, hours before the 15 Sep 01:02 drop."""
        import time

        now = time.time()
        self._ledger(watch, tmp_path, monkeypatch, [
            ("ankiita", "delivered", now - 30 * 3600),
            ("ankiita", "abandoned", now - 11 * 3600),
        ])
        ok, detail = watch.check_dropped()
        assert ok is False
        assert "11h" in detail

    def test_two_people_waiting_reads_as_people(self, watch, tmp_path, monkeypatch):
        import time

        now = time.time()
        self._ledger(watch, tmp_path, monkeypatch, [
            ("gt", "abandoned", now - 4 * 24 * 3600),
            ("ankiita", "abandoned", now - 11 * 3600),
        ])
        ok, detail = watch.check_dropped()
        assert ok is False
        assert "2 people" in detail


    def test_being_answered_by_a_cron_job_closes_it(self, watch, tmp_path, monkeypatch):
        """A cron job hands its text to the live adapter and writes no ledger
        row, so GT stayed on this list for five minutes after being answered."""
        import time
        from datetime import datetime

        now = time.time()
        self._ledger(watch, tmp_path, monkeypatch, [
            ("124575694233831@lid", "abandoned", now - 4 * 24 * 3600),
        ])
        stamp = datetime.fromtimestamp(now - 3600).strftime("%Y-%m-%d %H:%M:%S")
        log = tmp_path / "agent.log"
        log.write_text(
            f"{stamp},001 INFO cron.scheduler: Job 'x': delivered to "
            "whatsapp:124575694233831@lid via live adapter\n"
        )
        monkeypatch.setattr(watch, "AGENT_LOG", log)
        ok, detail = watch.check_dropped()
        assert ok is True
        assert "nobody is waiting" in detail

    def test_a_cron_delivery_from_before_the_drop_does_not_close_it(
        self, watch, tmp_path, monkeypatch
    ):
        """Only a message after the drop counts. GT was getting nudges the
        whole four days he was waiting, which is the thing that made it read
        as being ignored rather than failed."""
        import time
        from datetime import datetime

        now = time.time()
        self._ledger(watch, tmp_path, monkeypatch, [
            ("124575694233831@lid", "abandoned", now - 4 * 24 * 3600),
        ])
        stamp = datetime.fromtimestamp(now - 6 * 24 * 3600).strftime("%Y-%m-%d %H:%M:%S")
        log = tmp_path / "agent.log"
        log.write_text(
            f"{stamp},001 INFO cron.scheduler: Job 'x': delivered to "
            "whatsapp:124575694233831@lid via live adapter\n"
        )
        monkeypatch.setattr(watch, "AGENT_LOG", log)
        ok, detail = watch.check_dropped()
        assert ok is False
        assert "1 person" in detail

    def test_a_silent_cron_run_does_not_count_as_reaching_them(
        self, watch, tmp_path, monkeypatch
    ):
        """A run the reminder gate silences returns SILENT and delivers
        nothing, which is why this reads the delivery and not the job status."""
        import time
        from datetime import datetime

        now = time.time()
        self._ledger(watch, tmp_path, monkeypatch, [
            ("124575694233831@lid", "abandoned", now - 4 * 24 * 3600),
        ])
        stamp = datetime.fromtimestamp(now - 3600).strftime("%Y-%m-%d %H:%M:%S")
        log = tmp_path / "agent.log"
        log.write_text(
            f"{stamp},001 INFO cron.scheduler: Job 'x': agent returned "
            "[SILENT] — skipping delivery\n"
        )
        monkeypatch.setattr(watch, "AGENT_LOG", log)
        ok, _ = watch.check_dropped()
        assert ok is False

    def test_an_ancient_drop_falls_out_of_the_window(self, watch, tmp_path, monkeypatch):
        import time

        self._ledger(watch, tmp_path, monkeypatch, [
            ("someone", "abandoned", time.time() - 30 * 24 * 3600),
        ])
        ok, _ = watch.check_dropped()
        assert ok is True


class TestEmailRetry:
    """A blip used to lose the alert outright.

    At 11:52 on 15 Sep 2026 the watcher caught the WhatsApp link going down,
    tried to mail it, and got "Connection unexpectedly closed: The read
    operation timed out". The same credentials worked by hand an hour later,
    so a real outage went unreported because of one bad moment on the wire.
    """

    def _configured(self, watch):
        _write_env(
            watch,
            TED_ALERT_EMAIL_TO="her@example.com",
            TED_ALERT_SMTP_USER="ted@example.com",
            TED_ALERT_SMTP_PASSWORD="app-password",
        )

    def test_a_blip_is_retried_and_can_still_get_through(self, watch, monkeypatch):
        self._configured(watch)
        calls = {"n": 0}

        class Server:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def login(self, *a):
                pass

            def send_message(self, *a):
                pass

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError("read operation timed out")
            return Server()

        monkeypatch.setattr(watch.smtplib, "SMTP_SSL", flaky)
        assert watch.send_email("t", "b", urgent=True, dry_run=False) == "sent"
        assert calls["n"] == 3

    def test_a_wrong_password_is_never_retried(self, watch, monkeypatch):
        """It will be refused again. Three goes only delays the report."""
        self._configured(watch)
        calls = {"n": 0}

        def refuse(*args, **kwargs):
            calls["n"] += 1
            raise watch.smtplib.SMTPAuthenticationError(535, b"nope")

        monkeypatch.setattr(watch.smtplib, "SMTP_SSL", refuse)
        result = watch.send_email("t", "b", urgent=True, dry_run=False)
        assert "refused the login" in result
        assert calls["n"] == 1

    def test_notify_says_whether_anything_actually_reached_her(
        self, watch, monkeypatch
    ):
        """The desk notification does not count. On 8 Sep 2026 it popped up to
        an empty room for seventeen hours."""
        monkeypatch.setattr(watch.subprocess, "run", lambda *a, **k: None)

        monkeypatch.setattr(
            watch, "remote_alerts", lambda *a, **k: [("email", "failed (down)")]
        )
        assert watch.notify("t", "b", dry_run=False) is False

        monkeypatch.setattr(
            watch, "remote_alerts", lambda *a, **k: [("email", "sent")]
        )
        assert watch.notify("t", "b", dry_run=False) is True
