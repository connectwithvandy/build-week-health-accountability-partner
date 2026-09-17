"""The config this edits is the live one, and it has been corrupted once before.

`config.yaml.corrupt.20260831-183933.bak` is why every test here is about the
edit staying surgical. The script adds two lines to a 270-line file that holds
the model, the API credentials, the cache TTL and the fallback model. An edit
that reflows or drops any of that is worse than the waste it fixes.

So: the insert goes in the right place, it leaves every other byte alone, it
refuses rather than guesses when the shape is unfamiliar, and it never
overwrites a scoping somebody else chose.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SOURCE = Path(__file__).resolve().parent / "ted-scope-cron-tools.py"


def _load():
    spec = importlib.util.spec_from_file_location("ted_scope_cron_tools", _SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load()


# The shape of the real file on 17 Sep 2026: cron absent, whatsapp present,
# and unrelated keys on both sides of the block.
CONFIG = """model:
  provider: anthropic
  model: claude-sonnet-5
prompt_caching:
  cache_ttl: 1h
platform_toolsets:
  cli:
    - browser
    - terminal
  whatsapp:
    - cronjob
    - file
    - ted
    - vision
  telegram:
    - hermes-telegram
fallback_model:
  provider: openrouter
  model: openai/gpt-5.3-codex
"""


class TestReadingWhatIsThere:
    def test_finds_an_existing_platform(self, mod):
        assert mod.platform_block(CONFIG, "whatsapp") == ["cronjob", "file", "ted", "vision"]

    def test_cron_is_absent(self, mod):
        assert mod.platform_block(CONFIG, PLATFORM := "cron") is None

    def test_absent_is_not_confused_with_empty(self, mod):
        """A key listing nothing is a deliberate act; a missing key is the bug."""
        empty = CONFIG.replace("  telegram:\n    - hermes-telegram\n", "  telegram:\n")
        assert mod.platform_block(empty, "telegram") == []

    def test_a_key_outside_the_block_is_not_picked_up(self, mod):
        """`cron:` is also a top-level key in the real config. It is not this one."""
        text = "cron:\n  enabled: true\n" + CONFIG
        assert mod.platform_block(text, "cron") is None


class TestTheEdit:
    def test_adds_the_platform(self, mod):
        out = mod.insert_platform(CONFIG, "cron", ["ted"])
        assert mod.platform_block(out, "cron") == ["ted"]

    def test_changes_nothing_else(self, mod):
        """Exactly two lines appear and no existing line moves, changes or goes.

        Compared as a real diff rather than by membership: `    - ted` already
        occurs under whatsapp, so a set-difference check passes while the file
        is being mangled somewhere else entirely.
        """
        import difflib

        out = mod.insert_platform(CONFIG, "cron", ["ted"])
        delta = [
            line
            for line in difflib.ndiff(CONFIG.splitlines(), out.splitlines())
            if line[0] in "+-"
        ]
        assert delta == ["+   cron:", "+     - ted"]
        # every other platform survives untouched
        for platform in ("cli", "whatsapp", "telegram"):
            assert mod.platform_block(out, platform) == mod.platform_block(CONFIG, platform)

    def test_leaves_the_credentials_and_the_cache_ttl_alone(self, mod):
        out = mod.insert_platform(CONFIG, "cron", ["ted"])
        for line in ("  cache_ttl: 1h", "  model: claude-sonnet-5", "  model: openai/gpt-5.3-codex"):
            assert line in out.splitlines()

    def test_is_idempotent_at_the_reading_level(self, mod):
        """Applied twice would double the block, so the script must see the
        first one and stop. That decision is `platform_block` returning a list."""
        once = mod.insert_platform(CONFIG, "cron", ["ted"])
        assert mod.platform_block(once, "cron") is not None

    def test_refuses_a_file_with_no_block_rather_than_inventing_one(self, mod):
        with pytest.raises(SystemExit):
            mod.insert_platform("model:\n  provider: anthropic\n", "cron", ["ted"])


class TestWhatItChoosesToSend:
    def test_cron_gets_only_the_ted_toolset(self, mod):
        """Not whatsapp's four. A firing sends one line: it reads no photo,
        opens no file, and must not be able to create more scheduled jobs."""
        assert mod.TOOLSETS == ["ted"]

    def test_it_targets_cron(self, mod):
        assert mod.PLATFORM == "cron"


class TestTakingItBackOut:
    """Reversible means one command, and a revert that cannot eat anything else."""

    def test_round_trip_is_byte_identical(self, mod):
        out = mod.insert_platform(CONFIG, "cron", ["ted"])
        assert mod.remove_platform(out, "cron", ["ted"]) == CONFIG

    def test_revert_leaves_other_platforms_alone(self, mod):
        out = mod.insert_platform(CONFIG, "cron", ["ted"])
        back = mod.remove_platform(out, "cron", ["ted"])
        for platform in ("cli", "whatsapp", "telegram"):
            assert mod.platform_block(back, platform) == mod.platform_block(CONFIG, platform)

    def test_refuses_to_remove_a_block_somebody_edited(self, mod):
        """If the list is no longer what we wrote, somebody chose that. Undoing
        our change is not permission to throw theirs away."""
        edited = mod.insert_platform(CONFIG, "cron", ["ted", "vision"])
        with pytest.raises(SystemExit):
            mod.remove_platform(edited, "cron", ["ted"])

    def test_refuses_when_there_is_no_block_at_all(self, mod):
        with pytest.raises(SystemExit):
            mod.remove_platform("model:\n  provider: anthropic\n", "cron", ["ted"])

    def test_a_longer_list_is_never_half_removed(self, mod):
        """The bug this test was written for: matching the first two lines of a
        three-item list removed them and left `- vision` dangling directly under
        `platform_toolsets:`, which is a corrupt config, not a failed revert."""
        edited = mod.insert_platform(CONFIG, "cron", ["ted", "vision"])
        with pytest.raises(SystemExit):
            mod.remove_platform(edited, "cron", ["ted"])
        # and the file is untouched, because it raised before writing anything
        assert mod.platform_block(edited, "cron") == ["ted", "vision"]

    def test_revert_still_works_when_cron_is_the_only_platform(self, mod):
        only = "platform_toolsets:\n  cron:\n    - ted\n"
        assert mod.remove_platform(only, "cron", ["ted"]) == "platform_toolsets:\n"


class TestTheBackup:
    """The backup is the whole reversibility story if anything else goes wrong."""

    def test_two_writes_in_the_same_second_keep_both_backups(self, mod, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "CONFIG", tmp_path / "config.yaml")
        mod.CONFIG.write_text(CONFIG)
        first = mod._backup_path()
        first.write_text("first")
        second = mod._backup_path()
        assert second != first
        assert first.read_text() == "first"

    def test_write_actually_copies_the_old_contents(self, mod, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "CONFIG", tmp_path / "config.yaml")
        mod.CONFIG.write_text(CONFIG)
        backup = mod._write("replaced\n", "note")
        assert backup.read_text() == CONFIG
        assert mod.CONFIG.read_text() == "replaced\n"
