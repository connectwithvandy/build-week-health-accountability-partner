#!/usr/bin/env python3
"""The versioned eval case set — build it, and check it still resolves.

    python3 scripts/ted-eval-suite.py                 # coverage, and what is missing
    python3 scripts/ted-eval-suite.py --build 6       # rebuild, 6 cases per category
    python3 scripts/ted-eval-suite.py --json          # for the sweep

WHY THIS IS SEPARATE FROM THE RUNNER. Building the set costs nothing and
running it spends money on every model in the comparison. Keeping them apart
means the thing that has to be reviewed by a person — which cases are we
judging Ted on — can be read, argued with and committed without anybody
approving an API bill to see it.

The runner is `ted-model-bakeoff.py --suite`, which already prices a run
before it spends and scores replies against SOUL.md's countable rules.

WHAT IS IN THE FILE. A truncated sha256 per case and its categories. No
message text, no session id, no timestamp: this is a public repository and
every case is somebody's health message. See `ted_eval_cases` for why
"anonymised" cannot mean "with the name removed".

WHY A CASE CAN STOP RESOLVING, and why that is reported rather than skipped.
The text lives in `state.db`. If a person is forgotten, their messages go,
and their cases stop resolving — which is correct, and is the suite shrinking
for the right reason. A silent skip would instead quietly change what "the
same cases" means between two runs that are meant to be comparable.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ted_eval_cases  # noqa: E402

HERMES = Path.home() / ".hermes"
STATE_DB = HERMES / "state.db"
REPO = Path(__file__).resolve().parent.parent
SUITE_PATH = REPO / "evals" / f"ted-cases-v{ted_eval_cases.SUITE_VERSION}.json"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build", type=int, metavar="N",
        help="rebuild the suite with up to N cases per category",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable")
    args = parser.parse_args(argv)

    if not STATE_DB.exists():
        print(f"No store at {STATE_DB}.")
        return 1
    db = connect()

    if args.build:
        suite = ted_eval_cases.build(db, args.build)
        SUITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        SUITE_PATH.write_text(
            json.dumps(suite, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        if not args.json:
            print(f"\n  Wrote {len(suite['cases'])} case(s) to "
                  f"{SUITE_PATH.relative_to(REPO)}\n")
    else:
        suite = ted_eval_cases.read(SUITE_PATH)
        if not suite:
            print(f"\n  No suite at {SUITE_PATH.relative_to(REPO)}. "
                  "Build one with --build 6\n")
            return 1

    found, missing = ted_eval_cases.resolve(db, suite)

    if args.json:
        print(json.dumps({
            "version": suite.get("version"),
            "cases": len(suite.get("cases", [])),
            "resolved": len(found),
            "missing": len(missing),
            "counts": suite.get("counts", {}),
        }, indent=2))
        return 0

    print(f"\n  suite v{suite.get('version')} — "
          f"{len(suite.get('cases', []))} case(s), {len(found)} still resolve\n")
    for name in ted_eval_cases.CATEGORIES:
        live = sum(1 for case in found if name in case["categories"])
        print(f"    {name:<18} {live}")
    for name, why in (suite.get("unavailable") or {}).items():
        print(f"    {name:<18} -  {why}")

    if missing:
        print(f"\n  {len(missing)} case(s) no longer resolve. The message is gone "
              "from the\n  store — a forgotten user, or a rebuilt store. Rebuild "
              "with --build\n  to pin a comparable set again.")
        return 1
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
