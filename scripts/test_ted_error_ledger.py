"""The error rate has to survive the log that held it.

T12's one stated gap, and `ai.ted.logs` turned it from "the log might have
rotated" into "the evidence is deleted at 30 days on a timer".

A failed API call that was retried successfully leaves no trace anywhere
else — that is what a successful retry means — so the log line is the only
record that Ted nearly failed.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ledger = _load("ted_error_ledger_under_test", "ted_error_ledger.py")

LINE = "{day} 00:23:58,783 WARNING [x] agent.conversation_loop: API call failed (attempt 1/3) error_type=BadRequestError"
OTHER = "{day} 00:24:00,000 INFO [x] agent.conversation_loop: fine"


def _logs(tmp_path: Path, **files) -> Path:
    for name, lines in files.items():
        (tmp_path / name.replace("_", ".")).write_text("\n".join(lines), encoding="utf-8")
    return tmp_path


def test_it_counts_a_failure_per_day(tmp_path):
    _logs(tmp_path, agent_log=[
        LINE.format(day="2026-09-18"),
        LINE.format(day="2026-09-18"),
        OTHER.format(day="2026-09-18"),
        LINE.format(day="2026-09-19"),
    ])
    assert ledger.scan(tmp_path) == {"2026-09-18": 2, "2026-09-19": 1}


def test_a_day_in_both_logs_takes_the_larger_count(tmp_path):
    """Not the sum: the rotated copy and the live one overlap."""
    _logs(
        tmp_path,
        agent_log_1=[LINE.format(day="2026-09-18")] * 5,
        agent_log=[LINE.format(day="2026-09-18")] * 2,
    )
    assert ledger.scan(tmp_path) == {"2026-09-18": 5}


def test_missing_logs_are_not_an_error(tmp_path):
    assert ledger.scan(tmp_path) == {}


def test_update_writes_and_is_idempotent(tmp_path):
    logs = _logs(tmp_path, agent_log=[LINE.format(day="2026-09-18")] * 3)
    path = tmp_path / "state" / "ledger.json"

    first = ledger.update(logs, path)
    assert first["days"] == {"2026-09-18": 3}
    assert first["new_days"] == ["2026-09-18"]

    second = ledger.update(logs, path)
    assert second["days"] == {"2026-09-18": 3}
    assert second["new_days"] == []
    assert second["raised_days"] == []


def test_the_count_never_goes_down_when_the_log_rotates_away(tmp_path):
    """The whole point. A shrinking log must not revise history downward."""
    logs = _logs(tmp_path, agent_log=[LINE.format(day="2026-09-18")] * 9)
    path = tmp_path / "ledger.json"
    ledger.update(logs, path)

    # The log rotates and the day is gone from it entirely.
    (logs / "agent.log").write_text("", encoding="utf-8")
    after = ledger.update(logs, path)

    assert after["days"] == {"2026-09-18": 9}
    assert ledger.read(path) == {"2026-09-18": 9}


def test_a_later_run_on_the_same_day_raises_the_count(tmp_path):
    logs = _logs(tmp_path, agent_log=[LINE.format(day="2026-09-19")])
    path = tmp_path / "ledger.json"
    ledger.update(logs, path)
    (logs / "agent.log").write_text(
        "\n".join([LINE.format(day="2026-09-19")] * 4), encoding="utf-8"
    )
    after = ledger.update(logs, path)
    assert after["days"] == {"2026-09-19": 4}
    assert after["raised_days"] == ["2026-09-19"]


def test_it_keeps_a_date_and_a_count_and_nothing_else(tmp_path):
    """A failure line can carry a prompt fragment. T35 is why this matters."""
    logs = _logs(tmp_path, agent_log=[
        "2026-09-18 00:23:58,783 WARNING [sess] agent.conversation_loop: "
        "API call failed (attempt 1/3) error_type=BadRequestError body='i weigh 82kg'"
    ])
    path = tmp_path / "ledger.json"
    ledger.update(logs, path)
    written = path.read_text(encoding="utf-8")
    assert "82kg" not in written
    assert "BadRequestError" not in written
    assert "sess" not in written
    assert json.loads(written) == {"days": {"2026-09-18": 1}}


def test_an_unreadable_ledger_falls_back_rather_than_reporting_zero(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("{not json", encoding="utf-8")
    assert ledger.read(path) == {}


def test_a_ledger_of_the_wrong_shape_is_ignored(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"days": ["2026-09-18"]}), encoding="utf-8")
    assert ledger.read(path) == {}


# --- the wiring, which is where this went wrong once ----------------------


def test_the_rollup_runs_above_every_early_return():
    """It sat below the `--scrub` early return for one commit.

    The default invocation is the one launchd makes, and it takes that early
    return — so the job would have exited 0 every morning having kept
    nothing. The failure would have been invisible until the first day
    somebody needed a rotated error count.
    """
    source = (_SCRIPTS / "ted-log-retention.py").read_text(encoding="utf-8")
    body = source.split("def main(", 1)[1]
    rollup = body.index("ted_error_ledger.update(")
    first_return = body.index("return 0")
    assert rollup < first_return


def test_the_baseline_reads_the_ledger_not_only_the_log():
    source = (_SCRIPTS / "ted-baseline.py").read_text(encoding="utf-8")
    assert "ted_error_ledger.read(ERROR_LEDGER)" in source
    assert "ted_error_ledger.scan(LOGS)" in source


def test_the_two_scripts_agree_on_what_a_failure_line_is():
    """One pattern, imported. Two copies would drift and nobody would see it."""
    baseline = (_SCRIPTS / "ted-baseline.py").read_text(encoding="utf-8")
    assert "import ted_error_ledger" in baseline
    assert ledger.FAILURE.pattern.endswith("API call failed")
