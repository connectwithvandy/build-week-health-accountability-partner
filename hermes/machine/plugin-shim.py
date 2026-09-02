"""Load the versioned Ted safety gate used by the local Hermes gateway."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


# The repo folder is the live source of the gates. Candidates are tried in
# order so a rename of the project folder cannot silently disable safety.
_CANDIDATES = (
    Path.home() / "Documents" / "build-week-health accountability partner",
    Path.home() / "Documents" / "build-week-fitness-coach",
)
SOURCE = next(
    (
        candidate / "hermes" / "ted_safety_gates" / "__init__.py"
        for candidate in _CANDIDATES
        if (candidate / "hermes" / "ted_safety_gates" / "__init__.py").is_file()
    ),
    _CANDIDATES[0] / "hermes" / "ted_safety_gates" / "__init__.py",
)
if not SOURCE.is_file():
    raise RuntimeError(
        "Ted safety gates source not found. Tried: "
        + ", ".join(str(c) for c in _CANDIDATES)
        + ". Ted must not run without its gates."
    )
SPEC = importlib.util.spec_from_file_location("ted_safety_gates_live", SOURCE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load Ted safety gates from {SOURCE}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

register = MODULE.register
