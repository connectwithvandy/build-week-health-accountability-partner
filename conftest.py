"""Keep the whole test run out of ~/.hermes.

`ted_safety_gates` resolves its state and log paths at import, so the redirect
has to be in place before the test module imports it. conftest is imported
first, which is the only reliable hook for that.

This is not tidiness. Three unit-test fixture keys — "real-memory",
"staged-memory" and "wrong-tool" — were found sitting in the live consent
state file. A fixture key that ever collided with a real user key would mark
that user as already-disclosed and silently skip a disclosure they are owed.

Run the suite with pytest:

    .venv/bin/pytest hermes/test_ted_safety_gates.py

`python3 -m unittest` does not load conftest, so the redirect above never
happens and the run writes straight into ~/.hermes/state. That is not a
hypothetical either: it put all eight fixture keys back into the live files on
3 Sep, including the three named above, five weeks after they were cleaned out.
The run-isolation test catches it, but only after the damage is done.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_SANDBOX = Path(tempfile.mkdtemp(prefix="ted-gates-tests-"))
(_SANDBOX / "state").mkdir()
(_SANDBOX / "logs").mkdir()

os.environ["TED_GATES_STATE_DIR"] = str(_SANDBOX / "state")
os.environ["TED_GATES_AGENT_LOG"] = str(_SANDBOX / "logs" / "agent.log")

# Reminders are real Hermes cron jobs, created by shelling out to the CLI. A
# test run must not schedule, reschedule or cancel anything on this machine —
# a stray job is the fixture-key mistake again, with a WhatsApp message on the
# end of it. Tests that care about scheduling patch _run_cron_cli directly.
os.environ["TED_GATES_DISABLE_CRON"] = "1"

# The real gateway reads these from ~/.hermes/.env. A test run must never
# inherit a live Convex URL or secret and write to production.
os.environ.pop("TED_CONVEX_SITE_URL", None)
os.environ.pop("TED_HERMES_SHARED_SECRET", None)

TEST_SANDBOX = _SANDBOX


def pytest_sessionfinish(session: object, exitstatus: object) -> None:
    shutil.rmtree(_SANDBOX, ignore_errors=True)
