"""Keep the whole test run out of ~/.hermes.

`ted_safety_gates` resolves its state and log paths at import, so the redirect
has to be in place before the test module imports it. conftest is imported
first, which is the only reliable hook for that.

This is not tidiness. Three unit-test fixture keys — "real-memory",
"staged-memory" and "wrong-tool" — were found sitting in the live consent
state file. A fixture key that ever collided with a real user key would mark
that user as already-disclosed and silently skip a disclosure they are owed.
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

# The real gateway reads these from ~/.hermes/.env. A test run must never
# inherit a live Convex URL or secret and write to production.
os.environ.pop("TED_CONVEX_SITE_URL", None)
os.environ.pop("TED_HERMES_SHARED_SECRET", None)

TEST_SANDBOX = _SANDBOX


def pytest_sessionfinish(session: object, exitstatus: object) -> None:
    shutil.rmtree(_SANDBOX, ignore_errors=True)
