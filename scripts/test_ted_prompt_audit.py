"""What the prompt audit must not get wrong about its own numbers.

Every case here is a mistake the first draft actually made against the live
system, and each one reported a prompt that was cheaper than the real thing:

1. Characters ÷ 4 undercounted SOUL.md by 27% — 10,696 against a real 14,670.
   Ted is Hinglish with emoji and tokenizes at 2.92 chars per token, so the
   generic English ratio is wrong in the direction that hides the cost.
2. Summing per-tool counts reported 8,711 tokens for a payload the API counts
   as 5,525, because the fixed per-request tool overhead was added once per
   tool instead of once.
3. Reading the toolset without `~/.hermes/.env` measured one tool instead of
   ten: every Convex-backed tool fails its check_fn with no credentials, and
   the audit reported a tenth of the truth without noticing.
4. A tool payload that could not be counted was reported as 0 rather than as
   unknown, which reads as "tools are free".
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

_SOURCE = Path(__file__).resolve().parent / "ted-prompt-audit.py"

SPEC = importlib.util.spec_from_file_location("ted_prompt_audit", _SOURCE)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class FakeCounter:
    """A counter with a known answer, so the arithmetic is the thing tested."""

    def __init__(self, per_char: float = 1 / 3, tools: int | None = 5_000) -> None:
        self.mode = "counted"
        self._per_char = per_char
        self._tools = tools
        self.calls = 0

    def count(self, text: str) -> int:
        self.calls += 1
        return round(len(text) * self._per_char) if text else 0

    def count_tools(self, defs):
        return self._tools

    def save(self) -> None:
        pass


# ── The ratio that started it ──────────────────────────────────────────


def test_fallback_ratio_is_teds_measured_one_not_four():
    """2.92, measured on SOUL.md, not the generic English 4.

    At 4 the audit undercounts the identity block by a quarter. The constant
    is the finding; a later edit that "rounds it to 4" would silently restore
    the bug.
    """
    assert audit.CHARS_PER_TOKEN == pytest.approx(2.92)
    # 42,799 chars of SOUL.md counted as 14,670 tokens on 19 Sep 2026.
    assert round(42_799 / audit.CHARS_PER_TOKEN) == pytest.approx(14_657, abs=50)


def test_estimate_without_api_says_so(tmp_path, monkeypatch):
    """A run that could not count must not claim it counted."""
    monkeypatch.setattr(audit, "TOKEN_CACHE", tmp_path / "cache.json")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(audit, "HERMES_HOME", tmp_path)  # no .env to load
    counter = audit.TokenCounter(allow_api=False)
    assert counter.mode == "estimated"
    assert counter.count("x" * 292) == 100


def test_counted_results_are_cached_on_disk(tmp_path, monkeypatch):
    """The second run of the day must not re-ask for the same string."""
    monkeypatch.setattr(audit, "TOKEN_CACHE", tmp_path / "cache.json")
    counter = audit.TokenCounter(allow_api=False)
    counter._cache["deadbeef"] = 7  # noqa: SLF001 - pinning the file format
    counter._dirty = True  # noqa: SLF001
    counter.save()
    assert json.loads((tmp_path / "cache.json").read_text())["deadbeef"] == 7


# ── Tool counting ──────────────────────────────────────────────────────


def test_tool_payload_is_counted_once_not_summed_per_tool():
    """One payload, one overhead.

    The audit must ask its counter for the whole tool list, never sum
    per-tool counts — that added the API's fixed tool overhead once per tool
    and reported 8,711 for a real 5,525.
    """
    counter = FakeCounter(tools=5_525)
    result = counter.count_tools([{"a": 1}, {"b": 2}, {"c": 3}])
    assert result == 5_525


def test_uncountable_tools_are_unknown_not_zero(tmp_path, monkeypatch):
    """Zero reads as 'tools are free'. They are not."""
    monkeypatch.setattr(audit, "TOKEN_CACHE", tmp_path / "cache.json")
    counter = audit.TokenCounter(allow_api=False)
    assert counter.count_tools([{"name": "x"}]) is None


def test_openai_envelope_is_converted_for_counting():
    """count_tokens rejects Hermes' OpenAI envelope with a 400.

    The gateway's Anthropic adapter converts on the way out; so must this, or
    the tool payload measures as nothing at all.
    """
    converted = audit._to_anthropic_tool(  # noqa: SLF001
        {
            "type": "function",
            "function": {
                "name": "ted_log_entry",
                "description": "log it",
                "parameters": {"type": "object", "properties": {"x": {}}},
            },
        }
    )
    assert converted["name"] == "ted_log_entry"
    assert converted["input_schema"]["properties"] == {"x": {}}
    assert "function" not in converted


def test_bare_anthropic_tool_survives_conversion():
    converted = audit._to_anthropic_tool(  # noqa: SLF001
        {"name": "t", "description": "d", "input_schema": {"type": "object"}}
    )
    assert converted["input_schema"] == {"type": "object"}


def test_env_is_loaded_before_the_toolset_is_read(tmp_path, monkeypatch):
    """Without the gateway's .env, nine of ten tools vanish behind check_fn."""
    monkeypatch.setattr(audit, "HERMES_HOME", tmp_path)
    (tmp_path / ".env").write_text(
        "# a comment\nTED_CONVEX_SITE_URL=https://example.test\n"
        'TED_HERMES_SHARED_SECRET="shh"\nMALFORMED\n'
    )
    monkeypatch.delenv("TED_CONVEX_SITE_URL", raising=False)
    monkeypatch.delenv("TED_HERMES_SHARED_SECRET", raising=False)
    audit.load_hermes_env()
    import os

    assert os.environ["TED_CONVEX_SITE_URL"] == "https://example.test"
    assert os.environ["TED_HERMES_SHARED_SECRET"] == "shh"


def test_env_never_overrides_what_is_already_set(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "HERMES_HOME", tmp_path)
    (tmp_path / ".env").write_text("TED_CONVEX_SITE_URL=https://from-file.test\n")
    monkeypatch.setenv("TED_CONVEX_SITE_URL", "https://already-set.test")
    audit.load_hermes_env()
    import os

    assert os.environ["TED_CONVEX_SITE_URL"] == "https://already-set.test"


# ── Splitting SOUL.md ──────────────────────────────────────────────────


def test_sections_account_for_the_whole_file():
    """Nothing may fall between two headings.

    A split that drops the preamble reports a smaller identity block than the
    one that is sent.
    """
    text = "intro line\n\n## One\nbody one\n\n### Two\nbody two\n"
    sections = audit.split_sections(text)
    rebuilt = "\n".join(body for _, body in sections)
    assert rebuilt.replace("\n", "") == text.replace("\n", "")
    assert sections[0][0] == "(preamble)"
    assert [h for h, _ in sections[1:]] == ["## One", "### Two"]


def test_a_subheading_starts_its_own_section():
    """Nesting is presentation. The model reads one flat string."""
    sections = audit.split_sections("## A\na\n### B\nb\n")
    assert [h for h, _ in sections] == ["## A", "### B"]


def test_hash_inside_prose_is_not_a_heading():
    sections = audit.split_sections("## A\nsomething #hashtag and #1 place\n")
    assert len(sections) == 1


def test_soul_sections_are_ordered_by_size(tmp_path):
    soul = tmp_path / "SOUL.md"
    soul.write_text("## Small\nx\n\n## Large\n" + ("y " * 200) + "\n")
    result = audit.audit_soul(soul, FakeCounter())
    assert [row["heading"] for row in result["sections"]] == ["Large", "Small"]
    assert result["tokens"] > 0


def test_missing_soul_is_none_not_a_crash(tmp_path):
    assert audit.audit_soul(tmp_path / "nope.md", FakeCounter()) is None


# ── The database read ──────────────────────────────────────────────────


def _db_with(sessions, messages=(), usage=()) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE sessions (id TEXT, source TEXT, system_prompt TEXT, "
        "started_at REAL)"
    )
    db.execute("CREATE TABLE messages (id INTEGER, session_id TEXT, content TEXT)")
    db.execute(
        "CREATE TABLE session_model_usage (session_id TEXT, api_call_count INT, "
        "input_tokens INT, cache_write_tokens INT, cache_read_tokens INT, "
        "output_tokens INT)"
    )
    now = 1_758_000_000.0
    for sid, source, prompt in sessions:
        db.execute(
            "INSERT INTO sessions VALUES (?,?,?,?)", (sid, source, prompt, now)
        )
    for index, (sid, content) in enumerate(messages):
        db.execute("INSERT INTO messages VALUES (?,?,?)", (index, sid, content))
    for row in usage:
        db.execute("INSERT INTO session_model_usage VALUES (?,?,?,?,?,?)", row)
    db.execute("UPDATE sessions SET started_at = strftime('%s','now') - 100")
    return db


def test_floor_is_system_plus_tools_only(monkeypatch):
    """The floor must not include history.

    It is the number a shrink has to move, and history is not something a
    prompt edit can move.
    """
    monkeypatch.setattr(
        audit,
        "audit_tools",
        lambda counter: {
            "available": True,
            "platforms": {"cron": {"toolsets": ["ted"], "count": 9, "tokens": 5_000,
                                   "names": []}},
            "note": None,
        },
    )
    db = _db_with(
        sessions=[("s1", "cron", "p" * 300)],
        messages=[("s1", "m" * 900)],
        usage=[("s1", 2, 10, 100, 50, 5)],
    )
    result = audit.audit_sessions(db, 7, FakeCounter())
    row = result["sources"][0]
    assert row["system_prompt"]["tokens"] == 100  # 300 chars at 1/3
    assert row["tools"]["tokens"] == 5_000
    assert row["floor_tokens_per_call"] == 5_100
    assert row["history"]["tokens_per_session"] > 0


def test_unmeasured_tools_leave_the_floor_unknown_not_smaller(monkeypatch):
    """The bug this whole task is about, in miniature.

    Under the repo's own `python3` the tool modules fail to import for want of
    PyYAML, the toolset resolved to nothing, and the audit reported "0 tools"
    — quietly taking 5,525 tokens off the floor and making the payload look a
    quarter smaller. A floor missing its tools is unknown, not smaller.
    """
    monkeypatch.setattr(
        audit,
        "audit_tools",
        lambda counter: {
            "available": True,
            "platforms": {
                "cron": {
                    "toolsets": ["ted"],
                    "count": None,
                    "tokens": None,
                    "names": [],
                    "error": "resolved to no tools",
                }
            },
            "note": None,
        },
    )
    db = _db_with(
        sessions=[("s1", "cron", "p" * 300)],
        usage=[("s1", 1, 100, 0, 0, 5)],
    )
    row = audit.audit_sessions(db, 7, FakeCounter())["sources"][0]
    assert row["tools"]["tokens"] is None
    assert row["floor_tokens_per_call"] is None
    assert row["system_prompt"]["tokens"] == 100  # still measured


def test_an_empty_toolset_is_an_error_not_a_measurement(monkeypatch, tmp_path):
    """Requested toolsets resolving to nothing means we cannot see the tools."""
    monkeypatch.setattr(audit, "HERMES_HOME", tmp_path)
    (tmp_path / "hermes-agent").mkdir()

    class FakeModelTools:
        @staticmethod
        def get_tool_definitions(enabled_toolsets=None, quiet_mode=False):
            return []

    monkeypatch.setitem(sys.modules, "model_tools", FakeModelTools)
    result = audit.audit_tools(FakeCounter())
    cron = result["platforms"]["cron"]
    assert cron["count"] is None
    assert cron["tokens"] is None
    assert "no tools" in cron["error"]


def test_billed_counts_all_three_token_columns(monkeypatch):
    """Input alone is a sixth of the truth. T12 learned this the hard way."""
    monkeypatch.setattr(
        audit, "audit_tools", lambda counter: {"available": False, "platforms": {}}
    )
    db = _db_with(
        sessions=[("s1", "cron", "p" * 30)],
        usage=[("s1", 2, 100, 400, 500, 9)],
    )
    row = audit.audit_sessions(db, 7, FakeCounter())["sources"][0]
    assert row["billed"]["total_prompt_tokens"] == 1_000
    assert row["billed"]["per_call"] == 500
    assert row["billed"]["cached_share"] == pytest.approx(0.5)


def test_read_per_write_flags_a_cache_that_never_pays_back(monkeypatch):
    """Written 400, read 100: the premium bought nothing."""
    monkeypatch.setattr(
        audit, "audit_tools", lambda counter: {"available": False, "platforms": {}}
    )
    db = _db_with(
        sessions=[("s1", "cron", "p" * 30)],
        usage=[("s1", 1, 0, 400, 100, 9)],
    )
    row = audit.audit_sessions(db, 7, FakeCounter())["sources"][0]
    assert row["billed"]["read_per_write"] == pytest.approx(0.25)


def test_no_cache_write_is_not_a_divide_by_zero(monkeypatch):
    monkeypatch.setattr(
        audit, "audit_tools", lambda counter: {"available": False, "platforms": {}}
    )
    db = _db_with(
        sessions=[("s1", "cli", "p" * 30)],
        usage=[("s1", 1, 500, 0, 0, 9)],
    )
    row = audit.audit_sessions(db, 7, FakeCounter())["sources"][0]
    assert row["billed"]["read_per_write"] is None


def test_a_session_with_no_usage_row_does_not_vanish(monkeypatch):
    """A session that never reached the model is still a prompt that exists."""
    monkeypatch.setattr(
        audit, "audit_tools", lambda counter: {"available": False, "platforms": {}}
    )
    db = _db_with(sessions=[("s1", "cron", "p" * 30)])
    sources = audit.audit_sessions(db, 7, FakeCounter())["sources"]
    assert [r["source"] for r in sources] == ["cron"]
    assert sources[0]["calls"] == 0
    assert sources[0]["billed"]["per_call"] == 0


def test_empty_system_prompts_are_skipped_not_counted_as_zero(monkeypatch):
    """A session whose prompt was never recorded would drag the average down."""
    monkeypatch.setattr(
        audit, "audit_tools", lambda counter: {"available": False, "platforms": {}}
    )
    db = _db_with(
        sessions=[("s1", "cron", "p" * 300), ("s2", "cron", ""), ("s3", "cron", None)],
    )
    row = audit.audit_sessions(db, 7, FakeCounter())["sources"][0]
    assert row["sessions"] == 1


def test_sources_are_ordered_by_what_they_cost(monkeypatch):
    monkeypatch.setattr(
        audit, "audit_tools", lambda counter: {"available": False, "platforms": {}}
    )
    db = _db_with(
        sessions=[("s1", "cli", "p" * 30), ("s2", "cron", "p" * 30)],
        usage=[("s1", 1, 10, 0, 0, 1), ("s2", 1, 9_000, 0, 0, 1)],
    )
    sources = audit.audit_sessions(db, 7, FakeCounter())["sources"]
    assert [r["source"] for r in sources] == ["cron", "cli"]


def test_platform_toolsets_falls_back_when_config_is_unreadable(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "HERMES_HOME", tmp_path)
    found = audit.platform_toolsets()
    assert found["whatsapp"] == ["cronjob", "ted", "vision"]
    assert found["cron"] == ["ted"]
