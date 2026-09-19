"""A repair script must not refill a record somebody asked to have erased.

Udayan's live tombstone is `{"forgotten_at": 1788456543.297, "name": "UD"}`.
A name came back into an erased record within thirteen hours of the deletion,
and he never wrote again, so nothing he did put it there.

The shape of that record is why the first test here exists: it *has* a name,
so any guard written as "a tombstone is an empty record" would have waved it
through. The only thing that marks an erasure is `forgotten_at`.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "ted_deletion_guard_under_test", _SCRIPTS / "ted_deletion_guard.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load()

# The real record, as it sits in the live file.
UDAYAN = {"forgotten_at": 1788456543.297, "name": "UD"}
LIVING = {"name": "Vandy", "setup": "done", "weight_kg": 62.0}


def test_the_live_tombstone_is_recognised_although_it_has_a_name() -> None:
    assert guard.is_forgotten(UDAYAN)


def test_a_normal_record_is_not_a_tombstone() -> None:
    assert not guard.is_forgotten(LIVING)


@pytest.mark.parametrize("value", [None, "", 0, [], "forgotten", {"name": "x"}])
def test_nothing_else_counts_as_erased(value) -> None:
    assert not guard.is_forgotten(value)


def test_living_drops_only_the_erased() -> None:
    users = {"a": LIVING, "b": UDAYAN, "c": dict(LIVING)}
    kept = guard.living(users)
    assert set(kept) == {"a", "c"}


def test_living_does_not_mutate_what_it_was_given() -> None:
    """The tombstone has to survive in the file.

    A script that filtered in place would drop it on its next write, which
    erases the record *of* the erasure — the opposite mistake, and worse,
    because then nothing knows the person ever asked.
    """
    users = {"a": LIVING, "b": UDAYAN}
    guard.living(users)
    assert "b" in users
    assert users["b"] == UDAYAN


def test_the_note_counts_and_never_names() -> None:
    users = {"whatsapp:sha256:" + "f" * 64: UDAYAN, "a": LIVING}
    line = guard.note(users)
    assert "1 person" in line
    # The identifier must not come back in output somebody pastes into notes.
    assert "sha256" not in line
    assert "UD" not in line


def test_the_note_is_empty_when_there_is_nothing_to_say() -> None:
    assert guard.note({"a": LIVING}) == ""


def test_the_note_reads_naturally_for_more_than_one() -> None:
    assert "2 people" in guard.note({"a": UDAYAN, "b": dict(UDAYAN)})


# --- the class test -------------------------------------------------------
#
# The point of a shared module is that the next repair script inherits the
# rule. That only holds if something notices when one does not, so this walks
# the scripts rather than trusting the five that were wired up by hand.

# Read-only readers. None of them writes a user record back, so none can
# resurrect one: the audit must see tombstones to report on them, the backup
# copies the file whole, and the hygiene tool only removes keys that cannot
# belong to a person at all.
_READ_ONLY = {
    "ted-deletion-audit.py",
    "ted-backup.py",
    "ted-state-hygiene.py",
}


def _touches_gate_users(source: str) -> bool:
    return "ted-safety-gates-onboarding" in source


def test_every_writer_of_the_gate_state_uses_the_guard() -> None:
    missing = []
    for path in sorted(_SCRIPTS.glob("ted-*.py")):
        if path.name in _READ_ONLY or path.name.startswith("test_"):
            continue
        source = path.read_text(encoding="utf-8")
        if not _touches_gate_users(source):
            continue
        if not re.search(r"\bted_deletion_guard\b", source):
            missing.append(path.name)
    assert not missing, (
        "these read the gate's user records and do not know what a tombstone "
        f"is: {missing}. Import ted_deletion_guard and filter with living(), "
        "or add the script to _READ_ONLY if it never writes a record back."
    )


def test_the_guard_is_not_printing_to_stdout() -> None:
    """It broke the sweep's onboarding check once by doing exactly that.

    `ted-reconcile-setup.py --json` is read by `ted-sweep.py`, which merges
    stdout and stderr, so there is no stream a stray human line can hide on.
    """
    source = (_SCRIPTS / "ted_deletion_guard.py").read_text(encoding="utf-8")
    code = re.sub(r'""".*?"""', "", source, flags=re.S)
    assert "print(" not in code
