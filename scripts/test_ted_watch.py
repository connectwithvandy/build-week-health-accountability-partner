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
import sys
import json
from datetime import datetime, timedelta, timezone
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


class TestCheckSilent:
    """The turn that ended having written nothing, and nobody knew.

    4 Sep 2026: Palak and Vishwas Mishra each said "Okay Ted, let's do this"
    and were met with silence, because OpenRouter answered 402 on the primary
    model and on the fallback. Neither ever wrote again. `check_dropped` could
    not have seen it — there was no reply to drop — and it took fifteen days
    and a check written for T08 to find them.
    """

    def _history(self, watch, tmp_path, monkeypatch, messages, obligations=()):
        """A gateway database with the two tables this reads.

        `messages`/`sessions` are what T08's check reads, and
        `delivery_obligations` is the line between "wrote nothing" and "wrote
        something that never arrived".
        """
        import sqlite3

        db = tmp_path / "state.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, chat_id TEXT, "
            "display_name TEXT, source TEXT)"
        )
        conn.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, "
            "role TEXT, timestamp REAL, platform_message_id TEXT, content TEXT)"
        )
        conn.execute(
            "CREATE TABLE delivery_obligations ("
            "obligation_id TEXT PRIMARY KEY, chat_id TEXT, state TEXT, "
            "created_at REAL, last_error TEXT)"
        )
        for chat in {chat for chat, _, _ in messages}:
            conn.execute(
                "INSERT INTO sessions VALUES (?,?,?,?)",
                (chat, chat, chat, "whatsapp"),
            )
        for index, (chat, role, when) in enumerate(messages, start=1):
            conn.execute(
                "INSERT INTO messages VALUES (?,?,?,?,?,?)",
                (index, chat, role, when, f"msg{index}", "hello"),
            )
        for index, (chat, state, when) in enumerate(obligations):
            conn.execute(
                "INSERT INTO delivery_obligations VALUES (?,?,?,?,?)",
                (f"ob{index}", chat, state, when, ""),
            )
        conn.commit()
        conn.close()
        monkeypatch.setattr(watch, "STATE_DB", db)
        return db

    def test_no_history_is_not_a_failure(self, watch, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "STATE_DB", tmp_path / "nope.db")
        ok, detail = watch.check_silent()
        assert ok is True
        assert "no message history" in detail

    def test_an_answered_message_reads_clear(self, watch, tmp_path, monkeypatch):
        import time

        now = time.time()
        self._history(watch, tmp_path, monkeypatch, [
            ("palak", "user", now - 7200),
            ("palak", "assistant", now - 7100),
        ])
        ok, detail = watch.check_silent()
        assert ok is True
        assert "wrote something" in detail

    def test_a_turn_that_composed_nothing_is_reported(self, watch, tmp_path, monkeypatch):
        import time

        now = time.time()
        self._history(watch, tmp_path, monkeypatch, [
            ("palak", "user", now - 7200),
        ])
        ok, detail = watch.check_silent()
        assert ok is False
        assert "1 person wrote and Ted composed nothing back" in detail
        assert "2h" in detail

    def test_a_written_reply_that_never_sent_belongs_to_the_other_check(
        self, watch, tmp_path, monkeypatch
    ):
        """GT, 11 Sep 2026. Ted wrote to him and the link died carrying it.

        That is `check_dropped`'s, and counting it here too would wake Vandy
        twice about one person and tell her the wrong thing once.
        """
        import time

        now = time.time()
        self._history(
            watch, tmp_path, monkeypatch,
            [("gt", "user", now - 7200)],
            [("gt", "abandoned", now - 7100)],
        )
        ok, detail = watch.check_silent()
        assert ok is True
        assert "wrote something" in detail

    def test_a_turn_still_in_flight_is_left_alone(self, watch, tmp_path, monkeypatch):
        """Ankiita's slowest honest reply took thirty minutes. Not a fault."""
        import time

        now = time.time()
        self._history(watch, tmp_path, monkeypatch, [
            ("ankiita", "user", now - 120),
        ])
        ok, _ = watch.check_silent()
        assert ok is True

    def test_two_people_reads_as_people(self, watch, tmp_path, monkeypatch):
        import time

        now = time.time()
        self._history(watch, tmp_path, monkeypatch, [
            ("palak", "user", now - 7200),
            ("vishwas", "user", now - 7000),
        ])
        ok, detail = watch.check_silent()
        assert ok is False
        assert "2 people wrote" in detail

    def test_one_person_writing_twice_is_one_person(self, watch, tmp_path, monkeypatch):
        """Palak sent two messages a minute apart. She is one person waiting."""
        import time

        now = time.time()
        self._history(watch, tmp_path, monkeypatch, [
            ("palak", "user", now - 7200),
            ("palak", "user", now - 7140),
        ])
        ok, detail = watch.check_silent()
        assert ok is False
        assert "1 person wrote" in detail

    def test_a_later_reply_closes_it(self, watch, tmp_path, monkeypatch):
        import time

        now = time.time()
        self._history(watch, tmp_path, monkeypatch, [
            ("palak", "user", now - 7200),
            ("palak", "user", now - 7140),
            ("palak", "assistant", now - 3600),
        ])
        ok, _ = watch.check_silent()
        assert ok is True

    def test_an_ancient_silence_falls_out_of_the_window(self, watch, tmp_path, monkeypatch):
        """The real 4 Sep rows are older than this window and stay quiet.

        Deliberate: the alarm is for noticing today, and the four from
        September are written down in docs/T08_ORDERING.md instead.
        """
        import time

        now = time.time()
        self._history(watch, tmp_path, monkeypatch, [
            ("palak", "user", now - 30 * 24 * 3600),
        ])
        ok, _ = watch.check_silent()
        assert ok is True

    def test_days_are_reported_once_it_is_long_enough(self, watch, tmp_path, monkeypatch):
        import time

        now = time.time()
        self._history(watch, tmp_path, monkeypatch, [
            ("vinit", "user", now - 4 * 24 * 3600),
        ])
        ok, detail = watch.check_silent()
        assert ok is False
        assert "4 days" in detail

    def test_a_missing_ordering_check_does_not_crash_the_watcher(
        self, watch, tmp_path, monkeypatch
    ):
        import time

        now = time.time()
        self._history(watch, tmp_path, monkeypatch, [("palak", "user", now - 7200)])
        monkeypatch.setattr(watch, "ordering_check", lambda: None)
        ok, detail = watch.check_silent()
        assert ok is True
        assert "ted-ordering-check.py" in detail


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


class TestCheckJobs:
    """The one condition on T11's alert list that nothing watched.

    T11 names "failed scheduled jobs". The other five — disconnect, model
    failures, queue backlog, missing safety assets, health-check — have had a
    component since 17 Sep. A reminder that stops firing is invisible in a
    chat: it looks exactly like a quiet day.
    """

    @staticmethod
    def _jobs(watch, tmp_path, monkeypatch, *jobs):
        path = tmp_path / "jobs.json"
        path.write_text(json.dumps({"jobs": list(jobs)}))
        monkeypatch.setattr(watch, "JOBS_FILE", path)

    @staticmethod
    def _job(**overrides):
        job = {
            "name": "ted:aaaa:daily_review",
            "enabled": True,
            "state": "scheduled",
            "paused_at": None,
            "last_status": "ok",
            "next_run_at": (
                datetime.now(timezone.utc) + timedelta(hours=3)
            ).isoformat(),
        }
        job.update(overrides)
        return job

    def test_healthy_jobs_raise_nothing(self, watch, tmp_path, monkeypatch):
        self._jobs(watch, tmp_path, monkeypatch, self._job(), self._job())
        ok, detail = watch.check_jobs()
        assert ok is True
        assert "2 scheduled reminders" in detail

    def test_a_failed_run_is_caught(self, watch, tmp_path, monkeypatch):
        # The 4 Sep shape: the provider returned 402 and the turn composed
        # nothing. Nothing outside the log said so for fifteen days.
        self._jobs(watch, tmp_path, monkeypatch,
                   self._job(last_status="error", name="ted:bbbb:omega3"))
        ok, detail = watch.check_jobs()
        assert ok is False
        assert "ted:bbbb:omega3" in detail

    def test_a_delivery_error_is_caught_even_when_the_run_says_ok(
        self, watch, tmp_path, monkeypatch
    ):
        # The job ran and wrote a line; the send failed. last_status is still
        # "ok", because it describes the run and not the delivery.
        self._jobs(watch, tmp_path, monkeypatch,
                   self._job(last_delivery_error="Not connected to WhatsApp"))
        ok, _ = watch.check_jobs()
        assert ok is False

    def test_a_scheduler_that_stopped_ticking_is_caught(
        self, watch, tmp_path, monkeypatch
    ):
        # The invisible half. Every job still says last_status ok, because ok
        # describes its LAST run, so a dead scheduler leaves the whole list
        # looking healthy forever.
        overdue = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        self._jobs(watch, tmp_path, monkeypatch, self._job(next_run_at=overdue))
        ok, detail = watch.check_jobs()
        assert ok is False
        assert "overdue" in detail

    def test_a_few_minutes_late_is_not_an_alarm(self, watch, tmp_path, monkeypatch):
        # The scheduler ticks every 60s and a run takes time. Waking somebody
        # for five minutes of lateness is how an alarm gets ignored.
        late = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self._jobs(watch, tmp_path, monkeypatch, self._job(next_run_at=late))
        assert watch.check_jobs()[0] is True

    def test_disabled_jobs_are_not_faults(self, watch, tmp_path, monkeypatch):
        # 40 of 60 are disabled and correctly so: twelve people sit in
        # awaitingBreakReply and the gate refuses their sends anyway.
        stale = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
        self._jobs(watch, tmp_path, monkeypatch,
                   self._job(enabled=False, next_run_at=stale, last_status="error"))
        ok, detail = watch.check_jobs()
        assert ok is True
        assert detail == "no reminder is scheduled"

    def test_a_paused_job_is_somebodys_decision(self, watch, tmp_path, monkeypatch):
        stale = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        self._jobs(watch, tmp_path, monkeypatch,
                   self._job(paused_at="2026-09-13T14:45:37", next_run_at=stale))
        assert watch.check_jobs()[0] is True

    def test_an_unreadable_schedule_is_an_outage_not_a_gap(
        self, watch, tmp_path, monkeypatch
    ):
        # Every reminder Ted sends is defined in this file. Failing to read it
        # is the alarm, not a reason to stay quiet.
        path = tmp_path / "jobs.json"
        path.write_text("{ truncated")
        monkeypatch.setattr(watch, "JOBS_FILE", path)
        ok, detail = watch.check_jobs()
        assert ok is False
        assert "cannot read" in detail

    def test_a_missing_schedule_is_an_outage_too(self, watch, tmp_path, monkeypatch):
        monkeypatch.setattr(watch, "JOBS_FILE", tmp_path / "gone.json")
        assert watch.check_jobs()[0] is False

    def test_an_unparseable_date_does_not_crash_the_watcher(
        self, watch, tmp_path, monkeypatch
    ):
        # A watcher that raises is a watcher that is not watching.
        self._jobs(watch, tmp_path, monkeypatch, self._job(next_run_at="whenever"))
        assert watch.check_jobs()[0] is True

    def test_the_prompt_is_never_read(self, watch, tmp_path, monkeypatch):
        # T11: enough to debug, without message content. The prompt holds what
        # to take and how much.
        secret = "remind Vandy to take Chelated Iron 29mg on an empty stomach"
        self._jobs(watch, tmp_path, monkeypatch,
                   self._job(last_status="error", prompt=secret))
        _, detail = watch.check_jobs()
        assert "Iron" not in detail and "29mg" not in detail


class TestTheFallbackCanStillPay:
    """`check_credit`. The one check here that reads a number before it breaks.

    Every other check in the watcher reads a failure that has already reached
    somebody. This one exists because of 4 Sep 2026, when OpenRouter answered
    402 on the primary model and on the fallback within the same minute, three
    people got silence, and two of them never wrote again. By the time a log
    says 402 the damage is done, so this is the alarm that has to be early.
    """

    @staticmethod
    def _balance(watch, monkeypatch, granted, used):
        """The provider's own answer, without touching the network."""
        import io

        class _Response(io.StringIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake(request, timeout=None):
            payload = {"data": {"total_credits": granted, "total_usage": used}}
            return _Response(json.dumps(payload))

        monkeypatch.setattr(watch, "setting", lambda name: "a-key")
        monkeypatch.setattr(watch.urllib.request, "urlopen", fake)

    def test_a_healthy_balance_with_a_measured_burn_is_quiet(
        self, watch, monkeypatch
    ):
        self._balance(watch, monkeypatch, granted=30.0, used=5.0)
        # Six hours ago the counter read 4.00, so $1 has gone in six hours:
        # $4 a day against $25 left, which is comfortable.
        state = {
            "credit_anchor_usage": 4.0,
            "credit_anchor_at": watch.time.time() - 6 * 3600,
        }
        ok, detail = watch.check_credit(state)
        assert ok is True
        assert "$25.00" in detail

    def test_days_of_cover_not_dollars_is_what_alarms(self, watch, monkeypatch):
        # $8 is over the dollar floor and is still two days of cover. A check
        # that only looked at the balance would say this was fine.
        self._balance(watch, monkeypatch, granted=30.0, used=22.0)
        state = {
            "credit_anchor_usage": 21.0,
            "credit_anchor_at": watch.time.time() - 6 * 3600,
        }
        ok, detail = watch.check_credit(state)
        assert ok is False
        assert "$8.00" in detail
        assert "day" in detail

    def test_an_empty_balance_alarms_before_any_burn_is_known(
        self, watch, monkeypatch
    ):
        self._balance(watch, monkeypatch, granted=30.0, used=29.0)
        state = {}
        ok, detail = watch.check_credit(state)
        assert ok is False
        assert "$1.00" in detail

    def test_a_first_run_anchors_the_burn_instead_of_guessing_it(
        self, watch, monkeypatch
    ):
        self._balance(watch, monkeypatch, granted=30.0, used=6.0)
        state = {}
        ok, detail = watch.check_credit(state)
        assert ok is True
        assert "not measured yet" in detail
        assert state["credit_anchor_usage"] == 6.0

    def test_a_window_under_two_hours_is_noise_not_a_burn_rate(
        self, watch, monkeypatch
    ):
        # One dollar in ten minutes is $144 a day if you believe it. Nobody
        # should be woken for an extrapolation that wide.
        self._balance(watch, monkeypatch, granted=30.0, used=7.0)
        state = {
            "credit_anchor_usage": 6.0,
            "credit_anchor_at": watch.time.time() - 600,
        }
        ok, detail = watch.check_credit(state)
        assert ok is True
        assert "not measured yet" in detail

    def test_a_top_up_reads_as_a_reset_not_as_infinite_runway(
        self, watch, monkeypatch
    ):
        # A top-up moves the counter backwards. Believed as a burn rate it is
        # negative, which divides into a runway of forever.
        self._balance(watch, monkeypatch, granted=60.0, used=2.0)
        state = {
            "credit_anchor_usage": 25.0,
            "credit_anchor_at": watch.time.time() - 6 * 3600,
        }
        ok, detail = watch.check_credit(state)
        assert ok is True
        assert state["credit_anchor_usage"] == 2.0

    def test_an_unreachable_provider_is_not_an_unpaid_bill(
        self, watch, monkeypatch
    ):
        monkeypatch.setattr(watch, "setting", lambda name: "a-key")

        def unreachable(request, timeout=None):
            raise watch.urllib.error.URLError("no route to host")

        monkeypatch.setattr(watch.urllib.request, "urlopen", unreachable)
        ok, detail = watch.check_credit({})
        assert ok is True
        assert "could not read" in detail

    def test_no_key_is_reported_rather_than_read_as_empty(
        self, watch, monkeypatch
    ):
        monkeypatch.setattr(watch, "setting", lambda name: "")
        ok, detail = watch.check_credit({})
        assert ok is True
        assert "no OpenRouter key" in detail


class TestOneSimulatedFailureOneAlert:
    """T11's definition of done, exercised rather than asserted.

        A simulated WhatsApp/model/service failure produces one actionable
        alert outside WhatsApp within the agreed threshold.

    `--test-alert` proves the channel carries a message. It does not prove that
    a failure *becomes* one, which is the sentence above. This drives `main()`
    with a broken service and no network anywhere, and looks at what would have
    been sent.
    """

    @staticmethod
    def _rig(watch, tmp_path, monkeypatch, **health):
        """A watcher with every check healthy except the ones named."""
        sent = []
        monkeypatch.setattr(watch, "STATE", tmp_path / "watch-state.json")
        monkeypatch.setattr(watch, "run_guard", lambda: (True, "gates on"))
        monkeypatch.setattr(watch, "check_link", lambda: (True, "connected", False))
        monkeypatch.setattr(watch, "check_model", lambda: (True, "answering"))
        monkeypatch.setattr(watch, "check_dropped", lambda: (True, "nobody waiting"))
        monkeypatch.setattr(watch, "check_silent", lambda: (True, "wrote something"))
        monkeypatch.setattr(watch, "check_runaway", lambda: (True, "none"))
        monkeypatch.setattr(watch, "check_power", lambda: (True, "plugged in"))
        monkeypatch.setattr(watch, "check_jobs", lambda: (True, "on time"))
        # Takes the state dict, unlike every other check, so the stub has to
        # accept it or main() dies on an argument rather than on a fault.
        monkeypatch.setattr(watch, "check_credit", lambda state: (True, "funded"))
        for name, value in health.items():
            monkeypatch.setattr(watch, name, lambda *args, value=value: value)

        def record(title, body, dry_run, urgent=True):
            sent.append((title, body))
            return True

        monkeypatch.setattr(watch, "notify", record)
        monkeypatch.setattr(sys, "argv", ["ted-watch.py"])
        return sent

    def test_a_dead_whatsapp_link_produces_exactly_one_alert(
        self, watch, tmp_path, monkeypatch
    ):
        sent = self._rig(
            watch, tmp_path, monkeypatch,
            check_link=(False, "logged out", True),
        )
        assert watch.main() == 0
        assert len(sent) == 1
        title, body = sent[0]
        assert "WhatsApp" in title
        # Actionable: it has to say what to do, not only that something broke.
        assert "hermes whatsapp" in body

    def test_a_turn_that_wrote_nothing_produces_one_alert(
        self, watch, tmp_path, monkeypatch
    ):
        sent = self._rig(
            watch, tmp_path, monkeypatch,
            check_silent=(False, "2 people wrote and Ted composed nothing back, "
                                 "longest waiting 3h"),
        )
        assert watch.main() == 0
        assert len(sent) == 1
        title, body = sent[0]
        assert "wrote nothing back" in title
        assert "npm run ordering" in body

    def test_a_logged_out_link_does_not_answer_for_the_model(
        self, watch, tmp_path, monkeypatch
    ):
        """Two failures at once, each described as itself.

        The logged-out branch sat ahead of every per-component branch, so a
        dead model during a WhatsApp logout was announced as the logout, with
        the QR instructions attached. Two things broken and one of them
        invisible is how the 8 Sep outage ran for seventeen hours.
        """
        sent = self._rig(
            watch, tmp_path, monkeypatch,
            check_link=(False, "logged out", True),
            check_model=(False, "the Anthropic credit balance is empty"),
        )
        assert watch.main() == 0
        assert len(sent) == 2
        bodies = {title: body for title, body in sent}
        model = next(body for title, body in sent if "model" in title)
        assert "credit balance is empty" in model
        assert "hermes whatsapp" not in model
        assert any("logged out of WhatsApp" in title for title in bodies)

    def test_a_fallback_about_to_run_dry_produces_one_alert(
        self, watch, tmp_path, monkeypatch
    ):
        sent = self._rig(
            watch, tmp_path, monkeypatch,
            check_credit=(False, "$1.20 left, about 0.4 day(s) at $3.00 a day"),
        )
        assert watch.main() == 0
        assert len(sent) == 1
        title, body = sent[0]
        assert "credit" in title.lower()
        assert "$1.20" in body
        # Actionable, and it has to say why a funded fallback matters at all:
        # nothing is broken at the moment the alert fires.
        assert "Top up OpenRouter" in body

    def test_a_reminder_that_stopped_firing_produces_one_alert(
        self, watch, tmp_path, monkeypatch
    ):
        sent = self._rig(
            watch, tmp_path, monkeypatch,
            check_jobs=(False, "3 reminder(s) overdue, the oldest by 5 hours"),
        )
        assert watch.main() == 0
        assert len(sent) == 1
        title, body = sent[0]
        assert "reminders" in title
        assert "overdue" in body
        assert "npm run ordering" in body

    def test_the_same_failure_twice_does_not_alert_twice(
        self, watch, tmp_path, monkeypatch
    ):
        # The dedupe T11 asks for. A check that alarms every fifteen minutes
        # is a check somebody mutes.
        sent = self._rig(
            watch, tmp_path, monkeypatch,
            check_jobs=(False, "3 reminder(s) overdue, the oldest by 5 hours"),
        )
        assert watch.main() == 0
        assert watch.main() == 0
        assert len(sent) == 1

    def test_two_unrelated_failures_are_two_alerts(
        self, watch, tmp_path, monkeypatch
    ):
        # Per-component clocks: a flapping gate must not swallow the alert for
        # a link that died.
        sent = self._rig(
            watch, tmp_path, monkeypatch,
            check_jobs=(False, "3 reminder(s) overdue, the oldest by 5 hours"),
            check_power=(False, "battery at 4%"),
        )
        assert watch.main() == 0
        assert len(sent) == 2

    def test_recovery_is_announced_once(self, watch, tmp_path, monkeypatch):
        sent = self._rig(
            watch, tmp_path, monkeypatch,
            check_jobs=(False, "3 reminder(s) overdue, the oldest by 5 hours"),
        )
        assert watch.main() == 0
        monkeypatch.setattr(watch, "check_jobs", lambda: (True, "on time"))
        assert watch.main() == 0
        assert len(sent) == 2
        assert "back" in sent[1][0]
        assert watch.main() == 0
        assert len(sent) == 2

    def test_a_healthy_first_run_says_nothing_at_all(
        self, watch, tmp_path, monkeypatch
    ):
        # A watcher that says hello when installed trains you to ignore it.
        sent = self._rig(watch, tmp_path, monkeypatch)
        assert watch.main() == 0
        assert sent == []

    def test_no_alert_body_carries_what_somebody_said(
        self, watch, tmp_path, monkeypatch
    ):
        # T11: enough context to debug without exposing message content.
        sent = self._rig(
            watch, tmp_path, monkeypatch,
            check_jobs=(False, "1 reminder(s) failed on their last run: ted:bbbb:omega3"),
            check_link=(False, "logged out", True),
        )
        assert watch.main() == 0
        for _, body in sent:
            assert "katori" not in body and "kcal" not in body
