"""A cleanup that deletes real people is worse than the mess it removes.

The first draft of `ted-state-hygiene.py` called anything that was not a
`whatsapp:sha256:…` key a test fixture. The live disclosures file holds 113
keys and 52 of them are raw session ids, which is what `_user_state_key`
returns when the platform hands over no sender id. That draft would have
deleted 52 real disclosure records, and Ted would have re-sent the data
notice to half his users.

So the shape of a real key is the first thing tested here, and the only one
that would be a disaster to get wrong.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SOURCE = Path(__file__).resolve().parent / "ted-state-hygiene.py"


def _load():
    spec = importlib.util.spec_from_file_location("ted_state_hygiene", _SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hygiene = _load()


@pytest.mark.parametrize(
    "key",
    [
        "whatsapp:sha256:" + "a" * 64,
        "telegram:sha256:" + "0123456789abcdef" * 4,
        # The fallback shape. 52 of these are in the live file right now.
        "20260901_214702_20e16f0e",
        "20260904_010119_f4d2d58b",
    ],
)
def test_a_real_key_is_never_called_a_fixture(key: str) -> None:
    assert hygiene.is_a_person(key)


@pytest.mark.parametrize(
    "key",
    [
        "proof-mealtime",
        "probe-user",
        "probe:0",
        "probe-9pm, mumbai",
        "fixture-key-that-must-not-escape",
        "real-memory",
        # Near misses: the hash is the wrong length, and the session id has
        # the wrong number of digits. Neither is a shape the gateway makes.
        "whatsapp:sha256:" + "a" * 63,
        "2026091_214702_20e16f0e",
    ],
)
def test_a_fixture_key_is_found(key: str) -> None:
    assert not hygiene.is_a_person(key)


def _state(tmp_path: Path, onboarding: dict, disclosures: list[str]) -> Path:
    (tmp_path / "ted-safety-gates-onboarding.json").write_text(
        json.dumps({"users": onboarding}), encoding="utf-8"
    )
    (tmp_path / "ted-safety-gates-disclosures.json").write_text(
        json.dumps({"user_keys": disclosures}), encoding="utf-8"
    )
    return tmp_path


REAL = "whatsapp:sha256:" + "b" * 64
SESSION = "20260903_160233_b094058c"


def test_it_finds_both_files(tmp_path: Path) -> None:
    directory = _state(
        tmp_path, {REAL: {"name": "a real person"}, "probe-user": {}}, [SESSION, "real-memory"]
    )
    found = hygiene.scan(directory)
    assert found["ted-safety-gates-onboarding.json"] == ["probe-user"]
    assert found["ted-safety-gates-disclosures.json"] == ["real-memory"]


def test_removing_keeps_every_real_key(tmp_path: Path) -> None:
    directory = _state(
        tmp_path, {REAL: {"name": "a real person"}, "probe-user": {}}, [SESSION, "real-memory"]
    )
    hygiene.remove(directory)

    onboarding = json.loads(
        (directory / "ted-safety-gates-onboarding.json").read_text(encoding="utf-8")
    )
    disclosures = json.loads(
        (directory / "ted-safety-gates-disclosures.json").read_text(encoding="utf-8")
    )
    assert list(onboarding["users"]) == [REAL]
    assert onboarding["users"][REAL] == {"name": "a real person"}
    assert disclosures["user_keys"] == [SESSION]


def test_removing_backs_the_file_up_first(tmp_path: Path) -> None:
    """The convention the nine repair scripts already use."""
    directory = _state(tmp_path, {REAL: {}, "probe-user": {}}, [SESSION])
    hygiene.remove(directory)
    backups = list(directory.glob("ted-safety-gates-onboarding.json.bak.pre-hygiene-*"))
    assert len(backups) == 1
    assert "probe-user" in backups[0].read_text(encoding="utf-8")
    # The file with nothing to remove is left completely alone.
    assert not list(directory.glob("ted-safety-gates-disclosures.json.bak.*"))


def test_a_clean_state_reports_nothing(tmp_path: Path) -> None:
    directory = _state(tmp_path, {REAL: {}}, [SESSION])
    assert hygiene.scan(directory) == {}
    assert hygiene.remove(directory) == {}


def test_a_missing_file_is_not_a_finding(tmp_path: Path) -> None:
    assert hygiene.scan(tmp_path) == {}


def test_an_unreadable_file_raises_rather_than_reading_clean(tmp_path: Path) -> None:
    """A check that returns zero findings on a failure is the worst kind.

    `ted-memory-audit.py` reported a clean audit from a crash on 19 Sep, and
    the rule the sweep settled on is that unreadable is a finding, never a
    zero.
    """
    (tmp_path / "ted-safety-gates-onboarding.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        hygiene.scan(tmp_path)
