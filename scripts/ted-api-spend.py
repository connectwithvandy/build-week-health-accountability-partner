#!/usr/bin/env python3
"""What the API actually cost, split by what asked for it.

    python3 scripts/ted-api-spend.py                      # last 7 days
    python3 scripts/ted-api-spend.py --since 2026-09-01   # from a date
    python3 scripts/ted-api-spend.py --before 2026-09-17T17:42 --label "patch 13"
    python3 scripts/ted-api-spend.py --json               # for piping

WHAT THIS IS FOR.

Two fixes went live on 17 Sep 2026 and neither can be checked from anything in
this repo, because nothing in this repo has ever read the spend. The numbers in
`13-decide-cron-silence-before-the-model.patch` and in
`ted-scope-cron-tools.py` were both read off the Anthropic console by hand. A
number you have to leave the project to find is a number nobody checks twice.

Hermes already records every call. `~/.hermes/state.db` table
`session_model_usage` carries one row per (session, model, provider) with
`api_call_count`, the four token columns and a cost estimate. This reads it
back, groups it the way the spend actually divides, and reprices the part
Hermes gets wrong.

WHY IT REPRICES.

`~/.hermes/hermes-agent/agent/usage_pricing.py` stores ONE cache-write price
per model and no TTL dimension. The `claude-sonnet-5` row is $2.50 per million,
which is Anthropic's 5-minute rate, 1.25x input. `prompt_caching.cache_ttl` in
`~/.hermes/config.yaml` was raised to 1h on 16 Sept, and a 1-hour write is 2x
input, $4.00 per million. Every `estimated_cost_usd` written since then
understates the cache-write half of the bill by 60%.

So the token columns are believed and the dollars are recomputed. Tokens come
from the provider's own `usage` block and are trustworthy. `actual_cost_usd` is
0 on every row on this box, so there is no authoritative local figure to prefer.

WHY CRON IS SPLIT OUT.

Measured 1 to 17 Sep 2026: scheduled reminders were 774 calls of 3,036, and
$53.64 of $96.61. A quarter of the traffic and over half the money, to write
one lowercase sentence at a time. Chat with real users was the cheap half. Any
optimisation that treats the two as one workload will tune the wrong one.

Session ids starting `cron_` are scheduled firings; `cron/scheduler.py` builds
them as `cron_{job_id}_{YYYYmmdd_HHMMSS}`. Everything else is a person.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE_DB = HERMES / "state.db"
CONFIG = HERMES / "config.yaml"
EXECUTIONS_DB = HERMES / "cron" / "executions.db"

# Per million tokens. Input and output are read straight off each vendor's
# own pricing; a Claude row's two cache rates are derived from its input rate
# so a price change only has to be made in one place per model.
#
# Sources, both read on 18 Sep 2026:
#   https://platform.claude.com/docs/en/about-claude/pricing
#   https://openrouter.ai/api/v1/models
#
# The OpenRouter entries are not decoration. When the Anthropic balance
# emptied on 17 Sep 2026 every call fell back to `openai/gpt-5.3-codex` and
# this file had no rate for it, so a full day of real traffic printed as
# $0.00 under a one-line footnote. A bill that reads as zero while money
# leaves is the failure this script exists to prevent, and it had already
# happened here once.
_INPUT_RATE = {
    "claude-sonnet-5": 2.00,
    "claude-opus-5": 5.00,
    "claude-haiku-4-5": 1.00,
    "openai/gpt-5.3-codex": 1.75,
    "openai/gpt-4o-mini": 0.15,
}
_OUTPUT_RATE = {
    "claude-sonnet-5": 10.00,
    "claude-opus-5": 25.00,
    "claude-haiku-4-5": 5.00,
    "openai/gpt-5.3-codex": 14.00,
    "openai/gpt-4o-mini": 0.60,
}
# A cache read is a tenth of input on every current Claude model. A cache
# write depends on how long you asked the cache to live: 1.25x at the
# 5-minute default, 2x at 1h. This multiplier is the whole reason this script
# exists. It describes Claude's shape and nothing else.
_CACHE_READ_MULTIPLIER = 0.10
_CACHE_WRITE_MULTIPLIER = {"5m": 1.25, "1h": 2.00}

# Anything reached through OpenRouter bills on a different shape and states
# its own cache rates rather than inheriting Claude's. This is not caution for
# its own sake: gpt-4o-mini's cached input is HALF price, not a tenth, so the
# multiplier above would have understated it five times over.
#
# A `None` write rate means the provider charges no premium for writing to
# cache, which is why every Codex row on this box reports 0 cache-write
# tokens: those tokens arrive counted as ordinary input. They are priced at
# the input rate rather than dropped, so the day that changes it shows up as
# money and not as silence.
#
# A model here that is not a Claude model must state both rates.
# `test_every_openrouter_model_states_its_own_cache_rates` fails if one is
# added without them, because inheriting Claude's shape by accident is
# exactly how gpt-4o-mini would have been priced wrong.
_CACHE_RATE_OVERRIDE = {
    "openai/gpt-5.3-codex": {"read": 0.175, "write": None},
    "openai/gpt-4o-mini": {"read": 0.075, "write": None},
}


def configured_cache_ttl() -> str:
    """The TTL the gateway is actually sending, or '5m' if it cannot be read.

    Not parsed with a YAML library on purpose. This script must run on the
    stock interpreter with nothing installed, the same way `ted-reports.py`
    does, and the two lines it needs are unambiguous enough to read directly.
    Falling back to '5m' matches `agent_init.py`, which also defaults to '5m'
    for an unknown or missing value, so a misread here can never invent a
    bigger number than the gateway would use.
    """
    try:
        lines = CONFIG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "5m"
    in_block = False
    for line in lines:
        if line.startswith("prompt_caching:"):
            in_block = True
            continue
        if in_block:
            if line and not line.startswith((" ", "\t")):
                break  # left the block without finding it
            stripped = line.strip()
            if stripped.startswith("cache_ttl:"):
                value = stripped.split(":", 1)[1].strip().strip("'\"")
                return value if value in _CACHE_WRITE_MULTIPLIER else "5m"
    return "5m"


# Bedrock dresses the same model up differently: a region prefix, an
# `anthropic.` vendor segment, sometimes a dated build and a version suffix.
# `us.anthropic.claude-haiku-4-5-20251001-v1:0` and `claude-haiku-4-5` are the
# same model at the same price, and an exact-match rate lookup prices the first
# at nothing. Stripped in this order, outermost first.
_BEDROCK_REGION_PREFIX = re.compile(r"^(?:us|eu|apac|global)\.")
# Two spellings of the same vendor segment: Bedrock writes `anthropic.` and
# OpenRouter writes `anthropic/`. The slash form was arriving on this box and
# going unpriced, because the rate table is keyed on the plain name. Checked
# 18 Sep 2026: OpenRouter charges Anthropic's own rates for
# `anthropic/claude-sonnet-5`, input, output and both cache rates alike, so
# the two roads really are the same money and may share one entry.
_VENDOR_PREFIX = re.compile(r"^anthropic[./]")
_VERSION_SUFFIX = re.compile(r"(?:-v\d+)?(?::\d+)?$")
_DATED_BUILD_SUFFIX = re.compile(r"-\d{8}$")


def normalize_model(model: str) -> str:
    """The plain model name, whichever provider's spelling arrived.

    Why this is not cosmetic. `price_row` looks the rate up by exact string,
    so the day the provider changes every row becomes unpriced and the report
    prints $0.00 with a one-line footnote. A bill that reads as zero while
    money is leaving is the exact failure this file was written to prevent,
    and it would land at the moment the spend most needs watching.

    Deliberately conservative. Each pattern is anchored and removes decoration
    only, so an unknown model stays unknown rather than being rounded into a
    known one. Anything that does not match is returned untouched, which is
    why `openai/gpt-5.3-codex` keeps its vendor prefix: it is a different
    model at a different price, and it earns its own row in the rate table
    rather than being normalised into somebody else's.
    """
    name = _BEDROCK_REGION_PREFIX.sub("", model.strip())
    name = _VENDOR_PREFIX.sub("", name)
    name = _VERSION_SUFFIX.sub("", name)
    name = _DATED_BUILD_SUFFIX.sub("", name)
    return name


def is_bedrock_regional(model: str) -> bool:
    """Whether this row came through a regional Bedrock inference profile.

    It matters to the total, not just to the label. Bedrock charges the same
    per-token rate as Anthropic direct on the global default, but a regional
    or multi-region endpoint is reported to carry a premium on current Claude
    models. The rates in this file are Anthropic's, so a regional profile would
    make every figure here an underestimate.

    Not verified against AWS's own pricing page, which is why this raises a
    caution and never adjusts a number. Same rule as `ttl_caution`: say what
    cannot be proven, do not quietly price it.
    """
    return bool(_BEDROCK_REGION_PREFIX.match(model.strip())) and "anthropic." in model


def price_row(row: dict, ttl: str) -> float | None:
    """Dollars for one usage row, or None when the model has no known rate.

    Returning None rather than 0 keeps an unpriced model out of the totals
    instead of silently making the bill look smaller than it is. The caller
    counts those rows and names the model, because a count on its own did not
    get read: `openai/gpt-5.3-codex` sat in that footnote through a day of
    real traffic while the headline said $0.00.
    """
    model = normalize_model(str(row.get("model") or ""))
    inp = _INPUT_RATE.get(model)
    out = _OUTPUT_RATE.get(model)
    if inp is None or out is None:
        return None
    override = _CACHE_RATE_OVERRIDE.get(model)
    if override is None:
        read_rate = inp * _CACHE_READ_MULTIPLIER
        write_rate = inp * _CACHE_WRITE_MULTIPLIER.get(ttl, 1.25)
    else:
        read_rate = override["read"]
        # No write premium on this road, so a written token bills as input.
        write_rate = inp if override["write"] is None else override["write"]
    return (
        row["input_tokens"] * inp
        + row["cache_read_tokens"] * read_rate
        + row["cache_write_tokens"] * write_rate
        + row["output_tokens"] * out
    ) / 1_000_000.0


def is_cron(session_id: str) -> bool:
    """A scheduled firing, per `cron_{job_id}_{stamp}` in cron/scheduler.py."""
    return session_id.startswith("cron_")


def read_rows(since: float, until: float | None) -> list[dict]:
    """Usage rows in a window, read-only.

    Read-only is not politeness. The gateway holds this database open while it
    is serving, and a reporting script has no business being able to write to
    it at all.
    """
    if not STATE_DB.exists():
        raise SystemExit(
            f"No usage database at {STATE_DB}.\n"
            "Nothing has been recorded on this box, or HERMES_HOME points elsewhere."
        )
    try:
        connection = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise SystemExit(f"Cannot open {STATE_DB}: {exc}")
    connection.row_factory = sqlite3.Row
    clause = "last_seen >= ?"
    params: list[float] = [since]
    if until is not None:
        clause += " AND last_seen < ?"
        params.append(until)
    try:
        cursor = connection.execute(
            f"""SELECT session_id, model, billing_provider, api_call_count,
                       input_tokens, output_tokens,
                       cache_read_tokens, cache_write_tokens
                FROM session_model_usage
                WHERE {clause}""",
            params,
        )
        rows = [dict(r) for r in cursor.fetchall()]
    except sqlite3.Error as exc:
        raise SystemExit(
            f"Cannot read session_model_usage: {exc}\n"
            "A Hermes upgrade may have changed the schema."
        )
    finally:
        connection.close()
    return rows


def count_firings(since: float, until: float | None) -> int | None:
    """Scheduled firings attempted in a window, whether or not they cost anything.

    This exists because `session_model_usage` cannot answer it. Patch 13 made a
    suppressed reminder exit before the model is called, and a firing that never
    calls the model writes no usage row at all. Counted from usage alone, the
    cheapest possible firing and a firing that never happened look identical —
    which is exactly backwards on the day you are trying to prove the skip works.

    `cron/executions.db` records one row per firing at claim time, before any of
    that is decided, so it is the honest denominator. Returns None when the
    database is absent, so the caller can say "unknown" instead of "zero".
    """
    if not EXECUTIONS_DB.exists():
        return None
    try:
        connection = sqlite3.connect(f"file:{EXECUTIONS_DB}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        rows = connection.execute("SELECT claimed_at FROM executions").fetchall()
    except sqlite3.Error:
        return None
    finally:
        connection.close()

    total = 0
    for (claimed_at,) in rows:
        try:
            when = datetime.fromisoformat(str(claimed_at)).timestamp()
        except (TypeError, ValueError):
            continue  # a malformed stamp is not worth failing the whole report
        if when >= since and (until is None or when < until):
            total += 1
    return total


def summarise(rows: list[dict], ttl: str) -> dict:
    """Group a window into cron, chat and the total."""
    buckets: dict[str, dict] = {}
    for kind in ("cron", "chat", "all"):
        buckets[kind] = {
            "sessions": set(),
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "usd": 0.0,
            "unpriced_rows": 0,
            "unpriced_models": set(),
            "regional_bedrock_rows": 0,
        }

    for row in rows:
        kinds = ("cron" if is_cron(str(row["session_id"])) else "chat", "all")
        cost = price_row(row, ttl)
        for kind in kinds:
            bucket = buckets[kind]
            bucket["sessions"].add(row["session_id"])
            bucket["calls"] += row["api_call_count"]
            for column in (
                "input_tokens",
                "output_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
            ):
                bucket[column] += row[column]
            if cost is None:
                bucket["unpriced_rows"] += 1
                # Which model, not just how many rows. The count alone was
                # already being printed on 18 Sep and told nobody that the
                # whole day had moved to the fallback.
                bucket["unpriced_models"].add(
                    normalize_model(str(row.get("model") or "")) or "(unnamed)"
                )
            else:
                bucket["usd"] += cost
            if is_bedrock_regional(str(row.get("model") or "")):
                bucket["regional_bedrock_rows"] += 1

    for bucket in buckets.values():
        bucket["sessions"] = len(bucket["sessions"])
        # A set will not survive --json, and this report is piped.
        bucket["unpriced_models"] = sorted(bucket["unpriced_models"])
        served = bucket["cache_read_tokens"] + bucket["cache_write_tokens"] + bucket["input_tokens"]
        # The share of prompt tokens that arrived from cache. This is the
        # number both 17 Sep fixes are supposed to move, and the one that went
        # the wrong way when the TTL was raised without shrinking the prompt.
        bucket["cache_hit_rate"] = (
            bucket["cache_read_tokens"] / served if served else 0.0
        )
        bucket["calls_per_session"] = (
            bucket["calls"] / bucket["sessions"] if bucket["sessions"] else 0.0
        )
        bucket["prompt_tokens_per_call"] = (served / bucket["calls"]) if bucket["calls"] else 0.0
        bucket["usd_per_session"] = (
            bucket["usd"] / bucket["sessions"] if bucket["sessions"] else 0.0
        )
    return buckets


def parse_when(text: str) -> float:
    """A date or a date and time, local, as a unix timestamp."""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    raise SystemExit(
        f"Cannot read '{text}' as a time. Use 2026-09-17 or 2026-09-17T17:42."
    )


def _fmt(number: float) -> str:
    return f"{number:,.0f}"


def print_window(title: str, buckets: dict, ttl: str, firings: int | None = None) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    header = f"{'':<6}{'billed':>9}{'calls':>8}{'calls/fire':>12}{'prompt/call':>13}{'cached':>9}{'USD':>9}"
    print(header)
    for kind, label in (("cron", "cron"), ("chat", "chat"), ("all", "all")):
        b = buckets[kind]
        print(
            f"{label:<6}{_fmt(b['sessions']):>9}{_fmt(b['calls']):>8}"
            f"{b['calls_per_session']:>12.2f}{_fmt(b['prompt_tokens_per_call']):>13}"
            f"{b['cache_hit_rate'] * 100:>8.0f}%{b['usd']:>9.2f}"
        )
    if firings is not None:
        billed = buckets["cron"]["sessions"]
        # A firing above the billed count reached the scheduler and then left
        # without calling the model. Before patch 13 that gap was always zero,
        # because the only place a reminder could be refused ran after the call.
        skipped = max(0, firings - billed)
        share = f" ({skipped / firings * 100:.0f}%)" if firings else ""
        print(
            f"\n  cron firings attempted: {firings}  "
            f"|  reached the model: {billed}  |  skipped free: {skipped}{share}"
        )
    unpriced = buckets["all"]["unpriced_rows"]
    if unpriced:
        named = ", ".join(buckets["all"]["unpriced_models"])
        print(
            f"\n  {unpriced} row(s) left out of USD, on a model with no rate here:\n"
            f"  {named}. Traffic that happened and is not in the totals above."
        )
    regional = buckets["all"]["regional_bedrock_rows"]
    if regional:
        print(
            f"\n  {regional} row(s) came through a regional Bedrock profile. The rates\n"
            "  here are Anthropic's own, and a regional endpoint is reported to cost\n"
            "  more than the global default, so USD above may be an underestimate."
        )
    print(
        f"\n  Claude cache writes priced at {_CACHE_WRITE_MULTIPLIER[ttl]:.2f}x input "
        f"(cache_ttl: {ttl}).\n"
        "  OpenRouter rows carry their own cache rates and no write premium."
    )


def ttl_caution(since: float) -> str | None:
    """Warn when the window predates the TTL that is being applied to it.

    `config.yaml` is not version controlled and keeps no history, so the only
    TTL this script can know is the one set right now. Applying it backwards
    across the 16 Sept change would price five-minute writes at the one-hour
    rate and overstate early September by 60% on the write half.

    The config file's own mtime is the best available evidence of when the
    setting last moved. It is an upper bound rather than a fact, which is why
    this prints a caution and not a correction.
    """
    try:
        changed = CONFIG.stat().st_mtime
    except OSError:
        return None
    if since >= changed:
        return None
    return (
        f"  Caution: this window opens before {datetime.fromtimestamp(changed):%Y-%m-%d %H:%M},\n"
        f"  when config.yaml was last written. cache_ttl has no history, so any\n"
        f"  spend before that moment is priced at today's TTL and may be overstated.\n"
        f"  Narrow the window with --since to compare like with like."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="API spend split by cron versus chat, repriced for the live cache TTL."
    )
    parser.add_argument(
        "--since",
        help="Window start, e.g. 2026-09-01 or 2026-09-17T17:42. Default: 7 days ago.",
    )
    parser.add_argument(
        "--before",
        help="Split here and print two windows, so a fix can be measured either side of it.",
    )
    parser.add_argument(
        "--label",
        default="the change",
        help="What --before is the moment of, for the headings.",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable output.")
    args = parser.parse_args()

    ttl = configured_cache_ttl()
    since = parse_when(args.since) if args.since else (datetime.now() - timedelta(days=7)).timestamp()
    split = parse_when(args.before) if args.before else None

    if split is None:
        windows = {"window": summarise(read_rows(since, None), ttl)}
        firings = {"window": count_firings(since, None)}
    else:
        windows = {
            "before": summarise(read_rows(since, split), ttl),
            "after": summarise(read_rows(split, None), ttl),
        }
        firings = {
            "before": count_firings(since, split),
            "after": count_firings(split, None),
        }

    if args.json:
        print(
            json.dumps(
                {"cache_ttl": ttl, "windows": windows, "cron_firings": firings}, indent=2
            )
        )
        return 0

    caution = ttl_caution(since)

    if split is None:
        print_window(
            f"Since {datetime.fromtimestamp(since):%Y-%m-%d %H:%M}",
            windows["window"],
            ttl,
            firings["window"],
        )
        if caution:
            print(f"\n{caution}")
    else:
        moment = f"{datetime.fromtimestamp(split):%Y-%m-%d %H:%M}"
        print_window(f"Before {args.label} ({moment})", windows["before"], ttl, firings["before"])
        print_window(f"After {args.label} ({moment})", windows["after"], ttl, firings["after"])
        if caution:
            print(f"\n{caution}")
        # "Nothing fired" and "everything that fired was free" are different
        # answers and only the executions table can tell them apart.
        if not firings["after"]:
            print(
                "\nNo scheduled firing has happened since that moment, so the cron\n"
                "half of this is not measured yet. Re-run after the next one."
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
