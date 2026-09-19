"""Taking users' words out of the logs without destroying the logs.

The failure that matters here is not "it missed a line". It is "it ate the
line", or "it rewrote a file the gateway was appending to". Both are tested.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent / "ted-log-retention.py"

# Verbatim from ~/.hermes/logs, with the names changed.
GATEWAY_LINE = (
    "2026-09-11 12:06:40,967 INFO gateway.run: inbound message: platform=whatsapp "
    "user=Ankiita chat=115650651500637@lid msg='Soya aur paneer ka koi combo hota he "
    "kya sabji me' reply_to_id=None reply_to_text=''\n"
)
TURN_LINE = (
    "2026-09-11 12:06:41,107 INFO [20260911_111715_e837a25d] agent.turn_context: "
    "conversation turn: session=20260911_111715_e837a25d model=claude-sonnet-5 "
    "provider=anthropic platform=whatsapp history=102 msg='Soya aur paneer'\n"
)


@pytest.fixture
def tool(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("ted_log_retention_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    return module


class TestRedaction:
    def test_the_words_go_and_the_line_stays(self, tool):
        out, removed = tool.redact_line(GATEWAY_LINE)
        assert removed == 2  # msg and reply_to_text
        assert "paneer" not in out
        spoken = "Soya aur paneer ka koi combo hota he kya sabji me"
        assert f"<{len(spoken)} chars withheld>" in out
        # Everything an operator actually needs is still there.
        assert "2026-09-11 12:06:40,967" in out
        assert "user=Ankiita" in out
        assert "chat=115650651500637@lid" in out
        assert "platform=whatsapp" in out
        assert out.endswith("\n")

    def test_the_agent_turn_line_too(self, tool):
        """Two log lines carried the same words. Closing one is not closing it."""
        out, removed = tool.redact_line(TURN_LINE)
        assert removed == 1
        assert "paneer" not in out
        assert "session=20260911_111715_e837a25d" in out
        assert "model=claude-sonnet-5" in out

    def test_an_apostrophe_does_not_end_the_message_early(self, tool):
        """Python's %r escapes the quote rather than switching to doubles, and
        a naive pattern stops at the backslash and leaves the rest in place."""
        line = "INFO msg='i\\'m having 2 rotis and paneer' reply_to_id=None\n"
        out, _ = tool.redact_line(line)
        assert "paneer" not in out
        assert "rotis" not in out
        assert "reply_to_id=None" in out

    def test_a_double_quoted_repr_is_handled(self, tool):
        """%r uses double quotes when the text contains a single one."""
        line = "INFO msg=\"don't count that one\" reply_to_id=None\n"
        out, _ = tool.redact_line(line)
        assert "count that one" not in out
        assert "reply_to_id=None" in out

    def test_lines_with_no_user_text_are_untouched(self, tool):
        line = "2026-09-18 04:00:01 INFO gateway.run: cron firing job=abc123\n"
        out, removed = tool.redact_line(line)
        assert removed == 0
        assert out == line

    def test_it_does_not_eat_an_unrelated_field(self, tool):
        """`msg=` appears inside other words. Only the field is a target."""
        line = "INFO error_msg='boom' msg='hello'\n"
        out, _ = tool.redact_line(line)
        assert "error_msg='boom'" in out
        assert "hello" not in out

    def test_redacting_twice_changes_nothing_further(self, tool):
        once, _ = tool.redact_line(GATEWAY_LINE)
        twice, removed = tool.redact_line(once)
        assert removed == 0
        assert twice == once


class TestTheReportIsTrueBeforeItIsUseful:
    """The alarm said 62 and the answer was 0.

    Two separate reasons, and both of them make a privacy check worthless in
    the same way: an alarm that is always red is one you stop reading, and the
    real line is then missed inside the noise it made.
    """

    # What patch 14 writes: the gateway formats a str with %r, so its marker
    # arrives quoted. This script writes its own bare. Both are redactions.
    PATCH_14_LINE = (
        "2026-09-11 12:06:40,967 INFO gateway.run: inbound message: platform=whatsapp "
        "user=Ankiita chat=115650651500637@lid msg='<48 chars withheld>' "
        "reply_to_id=None reply_to_text='<0 chars withheld>'\n"
    )
    # ngrok, in the same directory, in logfmt.
    NGROK_LINE = (
        't=2026-09-19T14:59:46+0530 lvl=info msg="starting web service" '
        "obj=web addr=127.0.0.1:4041\n"
    )
    # Hermes' own stderr capture, which carries no timestamp at all. A first
    # attempt at the ngrok fix skipped whole files by line shape and would
    # have stopped reading this one.
    ERROR_LOG_LINE = "WARNING gateway.run: turn failed msg='i had 2 rotis'\n"

    def test_a_line_the_gateway_already_redacted_is_not_exposure(self, tool):
        out, removed = tool.redact_line(self.PATCH_14_LINE)
        assert removed == 0
        assert out == self.PATCH_14_LINE

    def test_a_fully_redacted_log_reports_zero_not_its_own_markers(self, tool):
        log = Path(tool.LOG_DIR) / "agent.log"
        log.write_text(self.PATCH_14_LINE * 3)
        (path, exposed, withheld, _), = tool.survey()
        assert path.name == "agent.log"
        assert exposed == 0
        assert withheld == 3

    def test_another_tools_log_is_not_read_as_somebodys_food_diary(self, tool):
        out, removed = tool.redact_line(self.NGROK_LINE)
        assert removed == 0
        assert out == self.NGROK_LINE

    def test_a_scrub_leaves_another_tools_diagnostics_intact(
        self, tool, monkeypatch
    ):
        # With the gateway down, so this proves the format rule rather than
        # the live-file refusal, which would have passed either way.
        monkeypatch.setattr(tool, "gateway_is_running", lambda: False)
        log = Path(tool.LOG_DIR) / "ngrok.log"
        log.write_text(self.NGROK_LINE * 4)
        ok, _ = tool.scrub(log)
        assert ok
        assert log.read_text() == self.NGROK_LINE * 4

    def test_a_hermes_line_with_no_timestamp_is_still_read(self, tool):
        out, removed = tool.redact_line(self.ERROR_LOG_LINE)
        assert removed == 1
        assert "rotis" not in out

    def test_real_exposure_is_still_caught_after_all_of_that(self, tool):
        log = Path(tool.LOG_DIR) / "agent.log"
        log.write_text(GATEWAY_LINE + self.PATCH_14_LINE + self.NGROK_LINE)
        (_, exposed, withheld, _), = tool.survey()
        assert exposed == 1
        assert withheld == 1

    def test_the_count_and_the_scrub_use_one_definition(self, tool, monkeypatch):
        """A report that promises a redaction the scrubber then declines to
        make is the same lie in the other direction."""
        monkeypatch.setattr(tool, "gateway_is_running", lambda: False)
        log = Path(tool.LOG_DIR) / "agent.log"
        log.write_text(GATEWAY_LINE + self.NGROK_LINE + self.PATCH_14_LINE)
        (_, exposed, _, _), = tool.survey()
        ok, detail = tool.scrub(log)
        assert ok
        assert detail.startswith("2 field(s)")  # one line, msg and reply_to_text
        (_, after, _, _), = tool.survey()
        assert exposed == 1 and after == 0


class TestWhatItRefusesToTouch:
    def test_it_will_not_rewrite_a_log_the_gateway_has_open(self, tool, monkeypatch):
        """Rewriting a file another process appends to does not shorten it, it
        corrupts it: the writer keeps its offset and the next line lands past
        the end."""
        monkeypatch.setattr(tool, "gateway_is_running", lambda: True)
        live = tool.LOG_DIR / "agent.log"
        live.write_text(GATEWAY_LINE)
        ok, detail = tool.scrub(live)
        assert not ok
        assert "gateway is writing to it" in detail
        assert live.read_text() == GATEWAY_LINE, "a refusal must not modify the file"

    def test_a_rotated_log_is_safe_even_while_running(self, tool, monkeypatch):
        monkeypatch.setattr(tool, "gateway_is_running", lambda: True)
        rotated = tool.LOG_DIR / "agent.log.1"
        rotated.write_text(GATEWAY_LINE)
        ok, _ = tool.scrub(rotated)
        assert ok
        assert "paneer" not in rotated.read_text()

    def test_the_live_log_is_cleanable_once_nothing_is_running(self, tool, monkeypatch):
        monkeypatch.setattr(tool, "gateway_is_running", lambda: False)
        live = tool.LOG_DIR / "agent.log"
        live.write_text(GATEWAY_LINE)
        ok, _ = tool.scrub(live)
        assert ok
        assert "paneer" not in live.read_text()

    def test_no_pgrep_means_assume_it_is_running(self, tool, monkeypatch):
        def explode(*a, **k):
            raise OSError("no pgrep")
        monkeypatch.setattr(tool.subprocess, "run", explode)
        assert tool.gateway_is_running() is True


class TestScrubKeepsTheLog:
    def test_every_line_survives(self, tool, monkeypatch):
        """Redaction, not deletion. 'Was this person answered at all' is a
        question that has already mattered, and it needs the lines."""
        monkeypatch.setattr(tool, "gateway_is_running", lambda: False)
        log = tool.LOG_DIR / "agent.log"
        log.write_text(GATEWAY_LINE + TURN_LINE + "INFO unrelated line\n")
        tool.scrub(log)
        assert len(log.read_text().splitlines()) == 3

    def test_permissions_are_preserved(self, tool, monkeypatch):
        monkeypatch.setattr(tool, "gateway_is_running", lambda: False)
        log = tool.LOG_DIR / "agent.log"
        log.write_text(GATEWAY_LINE)
        os.chmod(log, 0o600)
        tool.scrub(log)
        assert oct(log.stat().st_mode)[-3:] == "600"

    def test_a_failed_rewrite_leaves_the_original(self, tool, monkeypatch):
        monkeypatch.setattr(tool, "gateway_is_running", lambda: False)
        log = tool.LOG_DIR / "agent.log"
        log.write_text(GATEWAY_LINE)
        monkeypatch.setattr(tool.os, "chmod", lambda *a: (_ for _ in ()).throw(OSError("nope")))
        ok, _ = tool.scrub(log)
        assert not ok
        assert log.read_text() == GATEWAY_LINE
        assert not list(tool.LOG_DIR.glob("*.scrubbing")), "temp file left behind"


class TestRetention:
    def test_only_rotated_logs_are_deleted(self, tool):
        import time
        old = time.time() - 60 * 86400
        live = tool.LOG_DIR / "agent.log"
        rotated = tool.LOG_DIR / "agent.log.1"
        for path in (live, rotated):
            path.write_text("x\n")
            os.utime(path, (old, old))
        dropped = tool.prune(days=30)
        assert dropped == ["agent.log.1"]
        assert live.exists(), "the gateway's own log was deleted from under it"

    def test_recent_rotations_are_kept(self, tool):
        rotated = tool.LOG_DIR / "agent.log.1"
        rotated.write_text("x\n")
        assert tool.prune(days=30) == []
