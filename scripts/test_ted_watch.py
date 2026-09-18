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
    # Never the live gateway's database. `check_model` asks it whether the
    # primary model has answered since the last failure, and without this a
    # test asserting "an empty balance is caught" passes or fails according to
    # whether this laptop's Ted happens to be healthy right now. A path that
    # does not exist is also the right default: it leaves the alarm raised,
    # which is the direction every unknown here fails in.
    monkeypatch.setattr(module, "STATE_DB", tmp_path / "no-state.db")
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


class TestCheckRunaway:
    """The conversation cap must never be the thing nobody hears about.

    7 Sep 2026: one thread ran 330 turns and 44.2M input tokens, 35% of
    everything the account has spent, with Ted answering what reads like his
    own voice. The cap that now stops that also stops answering somebody, and
    it cannot say so over WhatsApp, because not answering WhatsApp is how it
    works.
    """

    def _state(self, watch, tmp_path, monkeypatch, chats):
        import json

        path = tmp_path / "runaway.json"
        path.write_text(json.dumps({"chats": chats}), encoding="utf-8")
        monkeypatch.setattr(watch, "RUNAWAY_STATE", path)
        return path

    def test_no_record_is_not_a_failure(self, watch, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "RUNAWAY_STATE", tmp_path / "nope.json")
        ok, detail = watch.check_runaway()
        assert ok is True
        assert "no conversation has hit the cap" in detail

    def test_a_corrupt_record_is_not_a_failure(self, watch, tmp_path, monkeypatch):
        path = tmp_path / "runaway.json"
        path.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(watch, "RUNAWAY_STATE", path)
        ok, _ = watch.check_runaway()
        assert ok is True

    def test_a_live_cap_is_reported(self, watch, tmp_path, monkeypatch):
        import time

        self._state(watch, tmp_path, monkeypatch, {
            "whatsapp:sha256:abc": {
                "firstAt": time.time() - 600,
                "lastAt": time.time() - 60,
                "turnsInWindow": 231,
                "dropped": 171,
            },
        })
        ok, detail = watch.check_runaway()
        assert ok is False
        assert "171 messages dropped" in detail
        assert "231 turns" in detail

    def test_an_old_cap_has_stopped_mattering(self, watch, tmp_path, monkeypatch):
        """It recovers on its own after an hour. A day later it is history."""
        import time

        self._state(watch, tmp_path, monkeypatch, {
            "whatsapp:sha256:abc": {
                "firstAt": time.time() - 3 * 24 * 3600,
                "lastAt": time.time() - 3 * 24 * 3600,
                "turnsInWindow": 61,
                "dropped": 1,
            },
        })
        ok, detail = watch.check_runaway()
        assert ok is True
        assert "no conversation has hit the cap" in detail

    def test_two_threads_are_counted_as_two(self, watch, tmp_path, monkeypatch):
        import time

        now = time.time()
        self._state(watch, tmp_path, monkeypatch, {
            "whatsapp:sha256:a": {"lastAt": now, "turnsInWindow": 61, "dropped": 2},
            "whatsapp:sha256:b": {"lastAt": now, "turnsInWindow": 90, "dropped": 5},
        })
        ok, detail = watch.check_runaway()
        assert ok is False
        assert "2 threads" in detail
        assert "7 messages dropped" in detail
        assert "90 turns" in detail

    def test_the_watcher_reports_it_as_its_own_component(self, watch):
        """A flapping gate must not swallow the alert for an ignored person."""
        import inspect

        source = inspect.getsource(watch.main)
        assert '("runaway", runaway_ok' in source


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


# --- the model coming back ---------------------------------------------------
#
# check_model reads a 24-hour window, so without a recovery test an outage that
# ended at lunchtime keeps raising the same alarm until the following lunchtime.
# On 17 Sep the balance had been topped up, the primary had answered every call
# for seventeen hours, and the watchdog still said FAILING. An alarm that cries
# wolf for a day after the fact is one nobody reads on the day it matters.
#
# Every test here also pins the direction of failure: anything unknowable leaves
# the alarm raised. A false alarm costs a look; a missed outage cost ten days.

import sqlite3
from datetime import datetime, timedelta


def _usage_db(path, rows):
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE session_model_usage "
        "(session_id TEXT, model TEXT, billing_provider TEXT, last_seen REAL)"
    )
    connection.executemany(
        "INSERT INTO session_model_usage VALUES (?,?,?,?)", rows
    )
    connection.commit()
    connection.close()


FAILED_AT = datetime(2026, 9, 16, 22, 0, 0)


class TestPrimaryModelRecovery:
    def test_a_success_after_the_failure_is_a_recovery(self, watch, tmp_path, monkeypatch):
        db = tmp_path / "state.db"
        later = FAILED_AT + timedelta(hours=18)
        _usage_db(db, [("s1", "claude-sonnet-5", "anthropic", later.timestamp())])
        monkeypatch.setattr(watch, "STATE_DB", db)
        monkeypatch.setattr(watch, "configured_primary", lambda: ("anthropic", "claude-sonnet-5"))
        assert watch.primary_model_recovered_since(FAILED_AT) == later

    def test_a_success_before_the_failure_is_not(self, watch, tmp_path, monkeypatch):
        db = tmp_path / "state.db"
        earlier = FAILED_AT - timedelta(hours=3)
        _usage_db(db, [("s1", "claude-sonnet-5", "anthropic", earlier.timestamp())])
        monkeypatch.setattr(watch, "STATE_DB", db)
        monkeypatch.setattr(watch, "configured_primary", lambda: ("anthropic", "claude-sonnet-5"))
        assert watch.primary_model_recovered_since(FAILED_AT) is None

    def test_the_fallback_answering_is_not_a_recovery(self, watch, tmp_path, monkeypatch):
        """The fallback working is exactly what makes the outage invisible.
        Only the configured primary counts."""
        db = tmp_path / "state.db"
        later = FAILED_AT + timedelta(hours=18)
        _usage_db(db, [("s1", "openai/gpt-5.3-codex", "openrouter", later.timestamp())])
        monkeypatch.setattr(watch, "STATE_DB", db)
        monkeypatch.setattr(watch, "configured_primary", lambda: ("anthropic", "claude-sonnet-5"))
        assert watch.primary_model_recovered_since(FAILED_AT) is None

    def test_the_same_model_on_another_provider_is_not_a_recovery(self, watch, tmp_path, monkeypatch):
        """claude-sonnet-5 through OpenRouter is still not the primary billing
        route, and the dead end being repaired is an Anthropic balance."""
        db = tmp_path / "state.db"
        later = FAILED_AT + timedelta(hours=18)
        _usage_db(db, [("s1", "claude-sonnet-5", "openrouter", later.timestamp())])
        monkeypatch.setattr(watch, "STATE_DB", db)
        monkeypatch.setattr(watch, "configured_primary", lambda: ("anthropic", "claude-sonnet-5"))
        assert watch.primary_model_recovered_since(FAILED_AT) is None

    def test_no_database_leaves_the_alarm_raised(self, watch, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "STATE_DB", tmp_path / "gone.db")
        monkeypatch.setattr(watch, "configured_primary", lambda: ("anthropic", "claude-sonnet-5"))
        assert watch.primary_model_recovered_since(FAILED_AT) is None

    def test_an_unreadable_config_leaves_the_alarm_raised(self, watch, tmp_path, monkeypatch):
        db = tmp_path / "state.db"
        _usage_db(db, [("s1", "claude-sonnet-5", "anthropic",
                        (FAILED_AT + timedelta(hours=18)).timestamp())])
        monkeypatch.setattr(watch, "STATE_DB", db)
        monkeypatch.setattr(watch, "configured_primary", lambda: None)
        assert watch.primary_model_recovered_since(FAILED_AT) is None

    def test_a_table_that_is_not_there_leaves_the_alarm_raised(self, watch, tmp_path, monkeypatch):
        db = tmp_path / "state.db"
        sqlite3.connect(db).close()
        monkeypatch.setattr(watch, "STATE_DB", db)
        monkeypatch.setattr(watch, "configured_primary", lambda: ("anthropic", "claude-sonnet-5"))
        assert watch.primary_model_recovered_since(FAILED_AT) is None

    def test_no_failure_to_recover_from(self, watch):
        assert watch.primary_model_recovered_since(None) is None


class TestCheckModelUsesTheRecovery:
    """The end-to-end behaviour, not just the helper."""

    def _log(self, watch, tmp_path, monkeypatch, when: datetime):
        log = tmp_path / "agent.log"
        log.write_text(
            f"{when:%Y-%m-%d %H:%M:%S} ERROR credit balance is too low to access\n"
        )
        monkeypatch.setattr(watch, "AGENT_LOG", log)

    def test_a_live_outage_still_raises(self, watch, tmp_path, monkeypatch):
        self._log(watch, tmp_path, monkeypatch, datetime.now() - timedelta(minutes=5))
        monkeypatch.setattr(watch, "primary_model_recovered_since", lambda when: None)
        ok, detail = watch.check_model()
        assert ok is False
        assert "credit balance is empty" in detail

    def test_a_healed_outage_does_not(self, watch, tmp_path, monkeypatch):
        """Seventeen hours of the primary answering, inside a 24-hour window."""
        self._log(watch, tmp_path, monkeypatch, datetime.now() - timedelta(hours=19))
        recovered = datetime.now() - timedelta(hours=1)
        monkeypatch.setattr(watch, "primary_model_recovered_since", lambda when: recovered)
        ok, detail = watch.check_model()
        assert ok is True
        assert "recovered" in detail

    def test_the_healed_message_still_says_it_failed(self, watch, tmp_path, monkeypatch):
        """Recovered is not the same as nothing happened. The count stays, or
        a run of daily outages reads as a clean week."""
        self._log(watch, tmp_path, monkeypatch, datetime.now() - timedelta(hours=19))
        monkeypatch.setattr(
            watch, "primary_model_recovered_since",
            lambda when: datetime.now() - timedelta(hours=1),
        )
        _ok, detail = watch.check_model()
        assert "failed calls earlier" in detail

    def test_an_error_outside_the_window_is_not_a_failure_at_all(self, watch, tmp_path, monkeypatch):
        self._log(watch, tmp_path, monkeypatch, datetime.now() - timedelta(hours=30))
        ok, detail = watch.check_model()
        assert ok is True
        assert detail == "primary model answering"


class TestCheckPower:
    """The host check. Every case here is a way the laptop ends the service
    without the service noticing, which is the whole reason it was added: on
    17 Sep 2026 five components reported healthy on a machine held awake by one
    unsupervised command, running on battery, with fifty-six chats on it.
    """

    ASSERTION_HELD = (
        "Assertion status system-wide:\n"
        "   PreventUserIdleSystemSleep     1\n"
        "Listed by owning process:\n"
        "   pid 2185(caffeinate): [0x000000ba00018282] 59:07:10 "
        'PreventUserIdleSystemSleep named: "caffeinate command-line tool"  \n'
        "\tDetails: caffeinate asserting forever\n"
        "\tLocalized=THE CAFFEINATE TOOL IS PREVENTING SLEEP.\n"
    )

    ASSERTION_TIMED = (
        "Assertion status system-wide:\n"
        "   PreventUserIdleSystemSleep     1\n"
        "Listed by owning process:\n"
        "   pid 81253(caffeinate): [0x00033fea000193bc] 00:00:45 "
        'PreventUserIdleSystemSleep named: "caffeinate command-line tool"  \n'
        "\tTimeout will fire in 255 secs Action=TimeoutActionRelease\n"
    )

    ASSERTION_NONE = (
        "Assertion status system-wide:\n"
        "   PreventUserIdleSystemSleep     0\n"
        "Listed by owning process:\n"
    )

    ON_AC = "Now drawing from 'AC Power'\n -InternalBattery-0\t100%; charged; 0:00 remaining present: true\n"

    def _pin(self, watch, monkeypatch, assertions, batt):
        def fake(*args):
            return assertions if "assertions" in args else batt
        monkeypatch.setattr(watch, "_pmset", fake)

    def test_held_and_plugged_in_is_fine(self, watch, monkeypatch):
        self._pin(watch, monkeypatch, self.ASSERTION_HELD, self.ON_AC)
        ok, detail = watch.check_power()
        assert ok
        assert "awake" in detail

    def test_no_hold_at_all_is_an_alert(self, watch, monkeypatch):
        self._pin(watch, monkeypatch, self.ASSERTION_NONE, self.ON_AC)
        ok, detail = watch.check_power()
        assert not ok
        assert "idle-sleep" in detail

    def test_a_five_minute_hold_does_not_count_as_a_hold(self, watch, monkeypatch):
        """The case that would have read as healthy four minutes before sleep.

        A timed caffeinate shows the same assertion name as the permanent one.
        Only the 'asserting forever' line tells them apart, and counting the
        timed one would report a laptop as safe right up until it slept.
        """
        self._pin(watch, monkeypatch, self.ASSERTION_TIMED, self.ON_AC)
        ok, detail = watch.check_power()
        assert not ok
        assert "idle-sleep" in detail

    def test_low_battery_is_an_alert(self, watch, monkeypatch):
        batt = (
            "Now drawing from 'Battery Power'\n"
            " -InternalBattery-0 (id=34865251)\t18%; discharging; 1:12 remaining present: true\n"
        )
        self._pin(watch, monkeypatch, self.ASSERTION_HELD, batt)
        ok, detail = watch.check_power()
        assert not ok
        assert "18%" in detail
        assert "1:12" in detail

    def test_comfortable_battery_is_said_but_not_alerted(self, watch, monkeypatch):
        """She unplugs this laptop every day. An alert every time is noise, and
        a watcher people learn to ignore is worse than one that says less."""
        batt = (
            "Now drawing from 'Battery Power'\n"
            " -InternalBattery-0 (id=34865251)\t71%; discharging; 12:44 remaining present: true\n"
        )
        self._pin(watch, monkeypatch, self.ASSERTION_HELD, batt)
        ok, detail = watch.check_power()
        assert ok
        assert "71%" in detail

    def test_both_wrong_at_once_reports_both(self, watch, monkeypatch):
        batt = (
            "Now drawing from 'Battery Power'\n"
            " -InternalBattery-0 (id=34865251)\t9%; discharging; 0:21 remaining present: true\n"
        )
        self._pin(watch, monkeypatch, self.ASSERTION_NONE, batt)
        ok, detail = watch.check_power()
        assert not ok
        assert "idle-sleep" in detail
        assert "9%" in detail

    def test_no_pmset_retires_the_check(self, watch, monkeypatch):
        """T04 moves Ted to a host with no lid and no battery. A check about
        both should go quiet there by itself rather than alert forever."""
        monkeypatch.setattr(watch, "_pmset", lambda *args: "")
        ok, detail = watch.check_power()
        assert ok
        assert "no laptop power" in detail

    def test_pmset_missing_binary_is_not_an_exception(self, watch, monkeypatch):
        def explode(*args, **kwargs):
            raise FileNotFoundError("pmset")
        monkeypatch.setattr(watch.subprocess, "run", explode)
        ok, _ = watch.check_power()
        assert ok

    def test_the_awake_plist_parses_and_supervises(self, watch):
        """A plist that does not parse installs as silently as one that does,
        and KeepAlive is the whole point: caffeinate is the assertion, so a
        caffeinate that exits and stays exited is a laptop that sleeps."""
        import plistlib
        loaded = plistlib.loads(watch.AWAKE_PLIST_SRC.read_bytes())
        assert loaded["Label"] == watch.AWAKE_LABEL
        assert loaded["KeepAlive"] is True
        assert loaded["RunAtLoad"] is True
        assert loaded["ProgramArguments"][0].endswith("caffeinate")


class TestStaleFailureProbe:
    """The alarm that went on stating something untrue.

    On 18 Sep 2026 the balance was topped up at 21:00 and the model check kept
    emailing "the Anthropic credit balance is empty" every fifteen minutes,
    because recovery is proven by a successful primary call and no user had
    messaged yet. An alarm that asserts a falsehood is how an alarm stops being
    read, which is the failure this whole file exists to prevent.
    """

    def _log(self, watch, tmp_path, monkeypatch, when: datetime):
        log = tmp_path / "agent.log"
        log.write_text(
            f"{when:%Y-%m-%d %H:%M:%S} ERROR credit balance is too low to access\n"
        )
        monkeypatch.setattr(watch, "AGENT_LOG", log)

    def test_a_fresh_failure_is_not_stale(self, watch):
        assert watch.failure_is_stale(datetime.now() - timedelta(minutes=2)) is False

    def test_an_old_failure_is_stale(self, watch):
        assert watch.failure_is_stale(datetime.now() - timedelta(hours=2)) is True

    def test_no_failure_is_not_stale(self, watch):
        assert watch.failure_is_stale(None) is False

    def test_a_live_outage_is_read_from_the_log_not_probed(self, watch, tmp_path, monkeypatch):
        """While failures keep arriving the log is authoritative, and probing
        would spend money to learn what it already says."""
        self._log(watch, tmp_path, monkeypatch, datetime.now() - timedelta(minutes=2))
        monkeypatch.setattr(watch, "primary_model_recovered_since", lambda when: None)
        probed = []
        monkeypatch.setattr(watch, "probe_primary", lambda *a, **k: probed.append(1) or (True, "probed"))
        ok, detail = watch.check_model()
        assert ok is False
        assert probed == [], "probed during a live outage"

    def test_a_stale_failure_is_settled_by_probing(self, watch, tmp_path, monkeypatch):
        self._log(watch, tmp_path, monkeypatch, datetime.now() - timedelta(hours=2))
        monkeypatch.setattr(watch, "primary_model_recovered_since", lambda when: None)
        monkeypatch.setattr(watch, "probe_primary", lambda *a, **k: (True, "probed"))
        ok, detail = watch.check_model()
        assert ok is True
        assert "proved by probe" in detail
        assert "40 failed" not in detail  # the real count comes from the log
        assert "failed calls earlier in the window" in detail

    def test_a_probe_that_fails_keeps_the_alarm(self, watch, tmp_path, monkeypatch):
        self._log(watch, tmp_path, monkeypatch, datetime.now() - timedelta(hours=2))
        monkeypatch.setattr(watch, "primary_model_recovered_since", lambda when: None)
        monkeypatch.setattr(
            watch, "probe_primary",
            lambda *a, **k: (False, "the Anthropic credit balance is empty"),
        )
        ok, detail = watch.check_model()
        assert ok is False
        assert "confirmed by probe just now" in detail

    def test_a_network_failure_is_not_read_as_a_billing_failure(self, watch, monkeypatch):
        """A probe that cannot reach the provider proves nothing about money."""
        monkeypatch.setattr(watch, "configured_primary", lambda: ("anthropic", "claude-sonnet-5"))
        monkeypatch.setattr(watch, "setting", lambda name: "key")

        def unreachable(*a, **k):
            raise watch.urllib.error.URLError("down")

        monkeypatch.setattr(watch.urllib.request, "urlopen", unreachable)
        ok, detail = watch.probe_primary()
        assert ok is None, "a probe that could not run is not a model failure"
        assert "could not reach the provider" in detail

    def test_it_will_not_probe_a_provider_it_cannot_speak_to(self, watch, monkeypatch):
        monkeypatch.setattr(watch, "configured_primary", lambda: ("openrouter", "x"))
        ok, detail = watch.probe_primary()
        assert ok is None
        assert "cannot probe openrouter" in detail

    def test_it_will_not_probe_without_a_key(self, watch, monkeypatch):
        monkeypatch.setattr(watch, "configured_primary", lambda: ("anthropic", "claude-sonnet-5"))
        monkeypatch.setattr(watch, "setting", lambda name: "")
        ok, detail = watch.probe_primary()
        assert ok is None
        assert "no ANTHROPIC_API_KEY" in detail

    def test_a_probe_that_could_not_run_leaves_the_logs_reason_standing(
        self, watch, tmp_path, monkeypatch
    ):
        """The regression two older tests caught. 'no ANTHROPIC_API_KEY to
        probe with' must never replace 'the API key was rejected': one is a
        fact about the model, the other is a fact about the watcher."""
        log = tmp_path / "agent.log"
        log.write_text(
            f"{datetime.now() - timedelta(hours=2):%Y-%m-%d %H:%M:%S} "
            "ERROR authentication_error\n"
        )
        monkeypatch.setattr(watch, "AGENT_LOG", log)
        monkeypatch.setattr(watch, "primary_model_recovered_since", lambda when: None)
        monkeypatch.setattr(watch, "probe_primary", lambda *a, **k: (None, "no key"))
        ok, detail = watch.check_model()
        assert ok is False
        assert "rejected" in detail
        assert "no key" not in detail
