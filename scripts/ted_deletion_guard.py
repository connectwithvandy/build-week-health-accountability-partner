"""A record marked forgotten is not a user to repair.

T09, item 2 in `docs/T09_DELETION_AUDIT.md`.

WHAT HAPPENED. Udayan asked Ted to forget him on 3 September 2026 at 22:59.
`_forget_user` emptied his record and wrote back a tombstone, and its own
comment says what that tombstone is allowed to be:

    a hashed key and a time, no profile and nothing they told Ted. Keeping
    strictly less than the deletion removed is the trade that makes the
    deletion hold.

The live record is `{"forgotten_at": 1788456543.297, "name": "UD"}`. The
snapshots date it: the two from before the deletion have no record for him at
all, and every snapshot from 4 Sep 12:27 onward has the name. Something wrote
a name back into an erased record within about thirteen hours, and the
transcript rules out the innocent explanation — his last exchange is Ted
saying "haha no idea yet, that's got wiped along with everything else", and he
never wrote again.

WHY A SHARED MODULE AND NOT FIVE COPIES OF AN `IF`. Which writer did it is
still not known, and finding the one is the wrong fix. `ted-reconcile-setup`,
`ted-repair-goal-drift`, `ted-repair-language-preference`,
`ted-repair-profile-drift` and `ted-repair-swallowed-weights` all read the
same file and all iterate every user in it. To a script walking users, a
tombstone is just a thin record with fields missing — which is precisely what
a repair script is built to fill in. The class is that the deletion path and
the repair paths do not know about each other. Naming the guard once is what
makes the next repair script inherit it instead of re-learning this.

WHY IT IS NOT SILENT, AND WHY IT DOES NOT PRINT. Skipping somebody invisibly
is how this would quietly become the opposite bug. So each script says how
many records it stepped over — and never who, because naming them puts back
the identifier the deletion removed.

The printing is the caller's, not this module's, and that is not a style
choice. The first version printed from inside the load helper, which put a
human line above `ted-reconcile-setup.py --json` and broke the sweep's
onboarding check within a minute: "CANNOT BE READ: did not print JSON". The
sweep reads stdout and stderr together on purpose, so there was no stream to
hide it on. A module that a machine-readable script calls must not decide to
write to stdout.

Importable as `ted_deletion_guard` because these scripts run as
`python3 scripts/<name>.py`, which puts `scripts/` first on the path.
"""

from __future__ import annotations

from typing import Any

# The one field that marks an erasure. `_forget_user` writes it, the audit
# reads it, and nothing else may be required for a record to count as erased:
# a guard that also insisted on, say, an empty name would have let this exact
# record through, because this record has a name.
TOMBSTONE = "forgotten_at"


def is_forgotten(record: Any) -> bool:
    """Whether this record belongs to somebody who asked to be erased."""
    return isinstance(record, dict) and record.get(TOMBSTONE) is not None


def living(users: dict[str, Any]) -> dict[str, Any]:
    """The records a repair script may read and write.

    Returns a new dict. A script that filtered in place would drop the
    tombstones on its next write, which deletes the record of the deletion —
    the opposite mistake, and a worse one, because nothing would then know
    the person had ever asked.
    """
    if not isinstance(users, dict):
        return {}
    return {key: value for key, value in users.items() if not is_forgotten(value)}


def forgotten_keys(users: dict[str, Any]) -> list[str]:
    """The keys being stepped over, for counting rather than printing."""
    if not isinstance(users, dict):
        return []
    return [key for key, value in users.items() if is_forgotten(value)]


def note(users: dict[str, Any]) -> str:
    """One line for the script to print, or empty when there is nothing to say.

    The count and never the key. A repair script's output is read at a
    terminal and pasted into notes, and the whole point of the erasure is that
    the identifier stops appearing in places like that.
    """
    skipped = len(forgotten_keys(users))
    if not skipped:
        return ""
    people = "person" if skipped == 1 else "people"
    return f"  skipping {skipped} {people} who asked to be forgotten"
