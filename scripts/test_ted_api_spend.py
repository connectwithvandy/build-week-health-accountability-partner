"""Tests for scripts/ted-api-spend.py.

The point of the script is that it disagrees with Hermes about the bill, so the
arithmetic is the thing under test. A test that only checked it ran would miss
the one bug that matters: repricing cache writes at the wrong multiple, which
is exactly the bug it exists to correct.

    .venv/bin/pytest scripts/test_ted_api_spend.py
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent / "ted-api-spend.py"


def _load(monkeypatch, hermes_home: Path):
    """Import the script fresh with HERMES_HOME pointed at a sandbox.

    Module-level path constants are resolved at import, the same trap conftest
    describes for the gate, so the env var has to be set before the import and
    the module cannot be cached between tests with different homes.
    """
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    spec = importlib.util.spec_from_file_location("ted_api_spend_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _usage_db(path: Path, rows: list[tuple]) -> None:
    """A state.db with just the columns the script reads."""
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE session_model_usage (
               session_id TEXT, model TEXT, billing_provider TEXT,
               api_call_count INTEGER, input_tokens INTEGER, output_tokens INTEGER,
               cache_read_tokens INTEGER, cache_write_tokens INTEGER,
               last_seen REAL)"""
    )
    connection.executemany(
        "INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?,?,?)", rows
    )
    connection.commit()
    connection.close()


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path


class TestConfiguredCacheTTL:
    def test_reads_one_hour(self, monkeypatch, home):
        (home / "config.yaml").write_text(
            "model:\n  provider: anthropic\nprompt_caching:\n  cache_ttl: 1h\n"
        )
        assert _load(monkeypatch, home).configured_cache_ttl() == "1h"

    def test_reads_five_minutes(self, monkeypatch, home):
        (home / "config.yaml").write_text("prompt_caching:\n  cache_ttl: 5m\n")
        assert _load(monkeypatch, home).configured_cache_ttl() == "5m"

    def test_tolerates_quotes_and_a_trailing_comment(self, monkeypatch, home):
        # The shipped default is written as: cache_ttl: "5m"  # use "1h" for ...
        # so the quoted form is the one most likely to be on a real box.
        (home / "config.yaml").write_text('prompt_caching:\n  cache_ttl: "1h"\n')
        assert _load(monkeypatch, home).configured_cache_ttl() == "1h"

    def test_missing_config_falls_back_to_five_minutes(self, monkeypatch, home):
        # Matches agent_init.py, which also defaults to 5m. A misread must
        # never invent a bigger multiplier than the gateway is really using.
        assert _load(monkeypatch, home).configured_cache_ttl() == "5m"

    def test_unknown_value_falls_back(self, monkeypatch, home):
        (home / "config.yaml").write_text("prompt_caching:\n  cache_ttl: 12h\n")
        assert _load(monkeypatch, home).configured_cache_ttl() == "5m"

    def test_a_cache_ttl_outside_the_block_is_not_read(self, monkeypatch, home):
        # openrouter.response_cache_ttl is a different setting entirely and
        # lives under its own key. Reading it here would price the bill off a
        # response cache that has nothing to do with prompt caching.
        (home / "config.yaml").write_text(
            "openrouter:\n  cache_ttl: 1h\nmodel:\n  provider: anthropic\n"
        )
        assert _load(monkeypatch, home).configured_cache_ttl() == "5m"


class TestPricing:
    def test_one_hour_write_is_twice_input(self, monkeypatch, home):
        module = _load(monkeypatch, home)
        row = {
            "model": "claude-sonnet-5",
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 1_000_000,
        }
        assert module.price_row(row, "1h") == pytest.approx(4.00)
        assert module.price_row(row, "5m") == pytest.approx(2.50)

    def test_the_gap_hermes_misses(self, monkeypatch, home):
        """The 60% understatement, on the real 17 Sep shape.

        A cron firing that missed cache twice: 88,796 written, nothing read.
        Hermes records $0.223 for it because usage_pricing.py has one write
        price per model. At the 1h TTL that was live, it is $0.355.
        """
        module = _load(monkeypatch, home)
        row = {
            "model": "claude-sonnet-5",
            "input_tokens": 4,
            "output_tokens": 76,
            "cache_read_tokens": 0,
            "cache_write_tokens": 88_796,
        }
        assert module.price_row(row, "5m") == pytest.approx(0.2230, abs=0.001)
        assert module.price_row(row, "1h") == pytest.approx(0.3560, abs=0.001)

    def test_cache_read_is_a_tenth_of_input(self, monkeypatch, home):
        module = _load(monkeypatch, home)
        row = {
            "model": "claude-sonnet-5",
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 1_000_000,
            "cache_write_tokens": 0,
        }
        assert module.price_row(row, "1h") == pytest.approx(0.20)

    def test_unknown_model_is_unpriced_not_free(self, monkeypatch, home):
        # Returning 0.0 here would quietly shrink the total every time a
        # fallback to OpenRouter happened, which is the exact moment somebody
        # is most likely to be reading this report.
        module = _load(monkeypatch, home)
        row = {
            "model": "openai/gpt-5.3-codex",
            "input_tokens": 1_000_000,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }
        assert module.price_row(row, "1h") is None


class TestCronSplit:
    def test_cron_sessions_are_recognised(self, monkeypatch, home):
        module = _load(monkeypatch, home)
        assert module.is_cron("cron_85afaa52e9af_20260917_130005")
        assert not module.is_cron("20260917_173621_28e3b888")
        assert not module.is_cron("whatsapp_919999999999")

    def test_summary_splits_the_two_workloads(self, monkeypatch, home):
        module = _load(monkeypatch, home)
        rows = [
            {
                "session_id": "cron_abc_20260917_130005",
                "model": "claude-sonnet-5",
                "api_call_count": 2,
                "input_tokens": 4,
                "output_tokens": 76,
                "cache_read_tokens": 0,
                "cache_write_tokens": 88_796,
            },
            {
                "session_id": "20260917_173621_28e3b888",
                "model": "claude-sonnet-5",
                "api_call_count": 1,
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_tokens": 40_000,
                "cache_write_tokens": 0,
            },
        ]
        buckets = module.summarise(rows, "1h")
        assert buckets["cron"]["sessions"] == 1
        assert buckets["chat"]["sessions"] == 1
        assert buckets["all"]["calls"] == 3
        # Nothing was served from cache on the cron side; nearly all of it was
        # on the chat side. This is the contrast the report exists to show.
        assert buckets["cron"]["cache_hit_rate"] == pytest.approx(0.0)
        assert buckets["chat"]["cache_hit_rate"] == pytest.approx(40_000 / 40_100)
        assert buckets["all"]["usd"] == pytest.approx(
            buckets["cron"]["usd"] + buckets["chat"]["usd"]
        )

    def test_repeated_session_id_counts_once(self, monkeypatch, home):
        """A session split across two models is one firing, not two.

        `session_model_usage` is keyed by (session, model, provider, ...), so a
        firing that fell back to OpenRouter mid-turn has two rows. Counting
        those as two firings would halve the per-firing cost and make a
        fallback look like an improvement.
        """
        module = _load(monkeypatch, home)
        rows = [
            {
                "session_id": "cron_abc_20260917_130005",
                "model": "claude-sonnet-5",
                "api_call_count": 1,
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_tokens": 0,
                "cache_write_tokens": 100,
            },
            {
                "session_id": "cron_abc_20260917_130005",
                "model": "claude-opus-5",
                "api_call_count": 1,
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_tokens": 0,
                "cache_write_tokens": 100,
            },
        ]
        buckets = module.summarise(rows, "1h")
        assert buckets["cron"]["sessions"] == 1
        assert buckets["cron"]["calls"] == 2
        assert buckets["cron"]["calls_per_session"] == pytest.approx(2.0)

    def test_empty_window_does_not_divide_by_zero(self, monkeypatch, home):
        module = _load(monkeypatch, home)
        buckets = module.summarise([], "1h")
        assert buckets["cron"]["sessions"] == 0
        assert buckets["cron"]["calls_per_session"] == 0.0
        assert buckets["cron"]["cache_hit_rate"] == 0.0
        assert buckets["cron"]["prompt_tokens_per_call"] == 0.0


class TestReadRows:
    def test_window_bounds_are_honoured(self, monkeypatch, home):
        _usage_db(
            home / "state.db",
            [
                ("cron_a_1", "claude-sonnet-5", "anthropic", 1, 1, 1, 0, 0, 1000.0),
                ("cron_b_2", "claude-sonnet-5", "anthropic", 1, 1, 1, 0, 0, 2000.0),
                ("cron_c_3", "claude-sonnet-5", "anthropic", 1, 1, 1, 0, 0, 3000.0),
            ],
        )
        module = _load(monkeypatch, home)
        assert len(module.read_rows(0, None)) == 3
        assert len(module.read_rows(2000.0, None)) == 2
        # The split moment belongs to `after`, never to both.
        assert len(module.read_rows(0, 2000.0)) == 1

    def test_missing_database_says_so(self, monkeypatch, home):
        module = _load(monkeypatch, home)
        with pytest.raises(SystemExit) as caught:
            module.read_rows(0, None)
        assert "No usage database" in str(caught.value)

    def test_the_database_is_opened_read_only(self, monkeypatch, home):
        """The gateway is serving out of this file while the report runs."""
        db = home / "state.db"
        _usage_db(db, [("cron_a_1", "claude-sonnet-5", "anthropic", 1, 1, 1, 0, 0, 1000.0)])
        module = _load(monkeypatch, home)
        module.read_rows(0, None)  # must not fail, and must not have written
        connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM session_model_usage")
        connection.close()

    def test_a_changed_schema_is_reported_not_crashed(self, monkeypatch, home):
        db = home / "state.db"
        connection = sqlite3.connect(db)
        connection.execute("CREATE TABLE session_model_usage (session_id TEXT)")
        connection.commit()
        connection.close()
        module = _load(monkeypatch, home)
        with pytest.raises(SystemExit) as caught:
            module.read_rows(0, None)
        assert "schema" in str(caught.value)


class TestParseWhen:
    def test_accepts_a_date_and_a_moment(self, monkeypatch, home):
        module = _load(monkeypatch, home)
        day = module.parse_when("2026-09-17")
        moment = module.parse_when("2026-09-17T17:42")
        assert moment > day

    def test_rejects_nonsense_with_an_example(self, monkeypatch, home):
        module = _load(monkeypatch, home)
        with pytest.raises(SystemExit) as caught:
            module.parse_when("last tuesday")
        assert "2026-09-17" in str(caught.value)


class TestTTLCaution:
    """config.yaml has no history, so a long window is priced at today's TTL.

    Silently doing that across the 16 Sept change is the one way this report
    can be more wrong than the Hermes estimate it exists to correct.
    """

    def test_warns_when_the_window_predates_the_config(self, monkeypatch, home):
        config = home / "config.yaml"
        config.write_text("prompt_caching:\n  cache_ttl: 1h\n")
        module = _load(monkeypatch, home)
        since = config.stat().st_mtime - 86_400
        message = module.ttl_caution(since)
        assert message is not None
        assert "overstated" in message

    def test_silent_when_the_window_starts_after_the_config(self, monkeypatch, home):
        config = home / "config.yaml"
        config.write_text("prompt_caching:\n  cache_ttl: 1h\n")
        module = _load(monkeypatch, home)
        assert module.ttl_caution(config.stat().st_mtime + 1) is None

    def test_no_config_means_no_claim_either_way(self, monkeypatch, home):
        module = _load(monkeypatch, home)
        assert module.ttl_caution(0) is None


def _executions_db(path: Path, stamps: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE executions (id TEXT, job_id TEXT, status TEXT, claimed_at TEXT)"
    )
    connection.executemany(
        "INSERT INTO executions VALUES (?,?,?,?)",
        [(f"e{i}", f"j{i}", "completed", s) for i, s in enumerate(stamps)],
    )
    connection.commit()
    connection.close()


class TestFiringCount:
    """A free firing leaves no usage row, so usage cannot be the denominator.

    This is the bug the first version of this report shipped with: it read
    "0 cron firings" on the evening patch 13 went live, when one had in fact
    fired and been skipped for nothing. Counting from the executions table is
    what tells those two apart.
    """

    def test_counts_firings_that_never_called_the_model(self, monkeypatch, home):
        _executions_db(
            home / "cron" / "executions.db",
            [
                "2026-09-17T18:08:31.454072+05:30",
                "2026-09-17T18:30:00.100000+05:30",
            ],
        )
        module = _load(monkeypatch, home)
        since = module.parse_when("2026-09-17T00:00")
        assert module.count_firings(since, None) == 2

    def test_window_bounds_apply(self, monkeypatch, home):
        _executions_db(
            home / "cron" / "executions.db",
            [
                "2026-09-17T13:00:05.000000+05:30",
                "2026-09-17T18:08:31.000000+05:30",
            ],
        )
        module = _load(monkeypatch, home)
        split = module.parse_when("2026-09-17T17:42")
        assert module.count_firings(module.parse_when("2026-09-17T00:00"), split) == 1
        assert module.count_firings(split, None) == 1

    def test_absent_database_is_unknown_not_zero(self, monkeypatch, home):
        # None means "cannot say"; 0 would be a claim that nothing fired, and
        # the report prints a different sentence for each.
        module = _load(monkeypatch, home)
        assert module.count_firings(0, None) is None

    def test_a_malformed_stamp_does_not_sink_the_report(self, monkeypatch, home):
        _executions_db(
            home / "cron" / "executions.db",
            ["not a timestamp", "2026-09-17T18:08:31.000000+05:30"],
        )
        module = _load(monkeypatch, home)
        assert module.count_firings(module.parse_when("2026-09-17T00:00"), None) == 1

    def test_skipped_is_firings_minus_billed(self, monkeypatch, home):
        """The number that proves patch 13, on the real 17 Sep evening shape."""
        _executions_db(
            home / "cron" / "executions.db", ["2026-09-17T18:08:31.000000+05:30"]
        )
        module = _load(monkeypatch, home)
        # One firing happened and left no usage row at all.
        buckets = module.summarise([], "1h")
        firings = module.count_firings(module.parse_when("2026-09-17T00:00"), None)
        assert firings == 1
        assert buckets["cron"]["sessions"] == 0
        assert max(0, firings - buckets["cron"]["sessions"]) == 1


class TestModelNormalization:
    """The provider swap that would have zeroed the bill.

    `price_row` looks its rate up by exact string. The day the model moves to
    Bedrock every id gains a region prefix and a vendor segment, every row
    goes unpriced, and the report prints $0.00 under a one-line footnote while
    real money leaves. These pin the shapes Hermes actually lists for Bedrock.
    """

    def test_plain_anthropic_name_is_untouched(self, monkeypatch, home):
        spend = _load(monkeypatch, home)
        assert spend.normalize_model("claude-sonnet-5") == "claude-sonnet-5"

    def test_bedrock_inference_profile(self, monkeypatch, home):
        spend = _load(monkeypatch, home)
        assert spend.normalize_model("us.anthropic.claude-sonnet-5") == "claude-sonnet-5"

    def test_bedrock_with_version_suffix(self, monkeypatch, home):
        spend = _load(monkeypatch, home)
        assert spend.normalize_model("us.anthropic.claude-opus-4-6-v1") == "claude-opus-4-6"

    def test_bedrock_with_dated_build_and_version(self, monkeypatch, home):
        spend = _load(monkeypatch, home)
        assert (
            spend.normalize_model("us.anthropic.claude-haiku-4-5-20251001-v1:0")
            == "claude-haiku-4-5"
        )

    def test_every_bedrock_id_hermes_lists_for_claude(self, monkeypatch, home):
        """Taken verbatim from hermes_cli/models.py so a Hermes-side rename
        shows up here as a failure rather than as a silent $0.00."""
        spend = _load(monkeypatch, home)
        for listed, expected in (
            ("us.anthropic.claude-sonnet-5", "claude-sonnet-5"),
            ("us.anthropic.claude-sonnet-4-6", "claude-sonnet-4-6"),
            ("us.anthropic.claude-opus-4-6-v1", "claude-opus-4-6"),
            ("us.anthropic.claude-haiku-4-5-20251001-v1:0", "claude-haiku-4-5"),
            ("us.anthropic.claude-sonnet-4-5-20250929-v1:0", "claude-sonnet-4-5"),
        ):
            assert spend.normalize_model(listed) == expected

    def test_the_model_ted_runs_prices_through_bedrock(self, monkeypatch, home):
        """The one that matters: same model, same money, either spelling."""
        spend = _load(monkeypatch, home)
        row = {
            "model": "us.anthropic.claude-sonnet-5",
            "input_tokens": 1_000_000,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "api_call_count": 1,
        }
        direct = dict(row, model="claude-sonnet-5")
        assert spend.price_row(row, "1h") == spend.price_row(direct, "1h")
        assert spend.price_row(row, "1h") == 2.00

    def test_an_unknown_model_stays_unpriced(self, monkeypatch, home):
        """Normalisation must never round a stranger into a known rate.
        Unpriced is the safe direction: it is counted and reported, not hidden."""
        spend = _load(monkeypatch, home)
        row = {
            "model": "openai/gpt-5.3-codex",
            "input_tokens": 1_000_000,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "api_call_count": 1,
        }
        assert spend.price_row(row, "1h") is None

    def test_regional_profile_is_flagged_not_repriced(self, monkeypatch, home):
        """A regional endpoint may cost more than these Anthropic rates. The
        file's rule is to say so, never to quietly invent a number."""
        spend = _load(monkeypatch, home)
        assert spend.is_bedrock_regional("us.anthropic.claude-sonnet-5")
        assert not spend.is_bedrock_regional("claude-sonnet-5")
        assert not spend.is_bedrock_regional("openai/gpt-5.3-codex")
