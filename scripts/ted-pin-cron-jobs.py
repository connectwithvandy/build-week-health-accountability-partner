#!/usr/bin/env python3
"""Pin every Hermes cron job to an explicit provider and model.

Why this exists. On 4 Sep 2026 Ted moved from OpenRouter to Anthropic direct.
Every cron job had been created under OpenRouter with no provider or model of
its own, so each one followed the global default. Hermes has a fail-closed
guard for exactly that (#44585): an unpinned job whose global config changed
since creation is skipped rather than run, because the change could be a
switch to a costlier model that nobody approved.

The guard is right. What it does next is the problem. The skip raises a
RuntimeError, and the scheduler delivers that error text to the job's WhatsApp
recipient, so a real user gets a raw Python traceback signed as Ted. Three went
out at 21:00 on 4 Sep, to Vandy and to at least one beta user.

Pinning is the documented fix and it is also the right one on the merits: a
product with live users should say which model it runs on rather than inherit
whatever the global config happens to be that week. The cost is that a future
deliberate switch means re-running this script, which is the trade worth making.

`hermes cron edit` has no flag for either axis, so this goes through
`cron.jobs.update_job`, which takes the same file lock the tool would and
re-reads jobs.json from disk rather than trusting a cached copy.

    python3 scripts/ted-pin-cron-jobs.py            # show what would change
    python3 scripts/ted-pin-cron-jobs.py --apply    # write it
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

HERMES_AGENT = Path.home() / ".hermes" / "hermes-agent"
JOBS_FILE = Path.home() / ".hermes" / "cron" / "jobs.json"

# Read from ~/.hermes/config.yaml rather than hardcoded, so this script cannot
# quietly pin yesterday's answer after the next switch.
CONFIG = Path.home() / ".hermes" / "config.yaml"


def current_config() -> tuple[str, str]:
    """(provider, model) from the `model:` block of config.yaml.

    Deliberately a small hand parse and not a yaml import: this runs under the
    system python, which has no PyYAML, and the block is two flat keys.
    """
    provider = model = ""
    in_model_block = False
    for line in CONFIG.read_text().splitlines():
        if line and not line[0].isspace():
            in_model_block = line.strip() == "model:"
            continue
        if not in_model_block:
            continue
        stripped = line.strip()
        if stripped.startswith("provider:"):
            provider = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("default:"):
            model = stripped.split(":", 1)[1].strip()
    if not provider or not model:
        raise SystemExit(
            f"Could not read provider/model from {CONFIG}. Refusing to guess."
        )
    return provider, model


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="write the change (default is a dry run)")
    args = parser.parse_args()

    provider, model = current_config()
    print(f"config.yaml says: provider={provider} model={model}\n")

    sys.path.insert(0, str(HERMES_AGENT))
    try:
        from cron.jobs import load_jobs, update_job
    except ImportError as exc:
        raise SystemExit(f"Could not import Hermes cron jobs from {HERMES_AGENT}: {exc}")

    jobs = load_jobs()
    todo = []
    for job in jobs:
        pinned_p = (job.get("provider") or "").strip()
        pinned_m = (job.get("model") or "").strip()
        if pinned_p and pinned_m:
            continue
        snap_p = (job.get("provider_snapshot") or "").strip()
        snap_m = (job.get("model_snapshot") or "").strip()
        drifts = (snap_p and snap_p.lower() != provider.lower()) or (
            snap_m and snap_m.lower() != model.lower()
        )
        todo.append((job, drifts))

    if not todo:
        print("Every job is already pinned. Nothing to do.")
        return 0

    breaking = [j for j, d in todo if d]
    fine = [j for j, d in todo if not d]
    print(f"{len(breaking)} job(s) currently FAILING and sending errors to users:")
    for job in breaking:
        state = job.get("state", "?")
        print(f"   {job['id']}  [{state}]  {str(job.get('name'))[:44]}")
    if fine:
        print(f"\n{len(fine)} job(s) not failing, pinned anyway so the next "
              f"config change cannot break them:")
        for job in fine:
            print(f"   {job['id']}  {str(job.get('name'))[:44]}")

    if not args.apply:
        print(f"\nDry run. Re-run with --apply to pin all {len(todo)} to "
              f"{provider}/{model}.")
        return 0

    backup = JOBS_FILE.with_suffix(f".json.bak.{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(JOBS_FILE, backup)
    print(f"\nBacked up jobs.json to {backup.name}")

    changed = 0
    for job, _ in todo:
        try:
            update_job(job["id"], {"provider": provider, "model": model})
            changed += 1
        except Exception as exc:
            print(f"   FAILED {job['id']}: {exc}")
    print(f"Pinned {changed} of {len(todo)} job(s) to {provider}/{model}.")
    print("\nPaused jobs stay paused. Resume them with:")
    print("   hermes cron resume <job_id>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
