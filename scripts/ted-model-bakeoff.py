#!/usr/bin/env python3
"""Run the same real TED turns through several models and compare what comes back.

    P=~/.hermes/hermes-agent/venv/bin/python3
    $P scripts/ted-model-bakeoff.py                       # dry run, costs nothing
    $P scripts/ted-model-bakeoff.py --run                 # spends, and says how much first
    $P scripts/ted-model-bakeoff.py --against openai/gpt-4o-mini,claude-haiku-4-5

WHY. Roadmap T15 asks for task-based model routing, and its definition of done
is "expensive models are used only where **evals justify them**". There is no
eval suite (that is T16), and the honest position on 19 Sep 2026 is that TED
runs one model for everything: `claude-sonnet-5` for chat and for all 60 cron
jobs. Moving reminders to a cheaper tier without measuring first is the exact
thing that definition forbids, and it would be a live experiment on real
people.

So this is the smallest honest instrument: the **real** system prompt and the
**real** cron turn that already went over the wire, replayed through each
candidate, scored on the same countable SOUL.md rules `ted-voice-check.py`
uses, and priced from the provider's own live rates. Two definitions of
"sounds like Ted" would eventually disagree and the quiet one would be the one
that mattered.

WHICH INTERPRETER. `~/.hermes/hermes-agent/venv/bin/python3`. The repo's own
`.venv` has neither `anthropic` nor `openai`, and a script that discovers that
at the moment it tries to spend money is the failure
`ted-spread-reminder-times.py` already learned to refuse up front.

WHAT IT DOES NOT ANSWER, and this is the important half.

  * **Tool calling.** Replays run with no tools. A real reminder turn may call
    `ted_day_summary` before it writes a word, and a model that writes
    beautifully and calls the tool wrong is worse than useless. This measures
    wording only. The tool question needs a shadow run against the live
    harness, not this.
  * **Warmth.** The six rules are the countable ones. A reply can pass all six
    and still be a bad reminder. Every caveat at the top of
    `ted-voice-check.py` applies here unchanged.
  * **Persona drift across a conversation.** Anthropic's own Haiku 4.5 notes
    say it is "less reliant on the user's stated persona throughout the
    exchange". A cron turn is one shot, so that risk cannot show up here at
    all, and it is the reason **chat** is not a candidate for a cheaper tier on
    this evidence. Reminders are.

WHOSE WORDS. The user's half of the prompt is read and **never printed**. What
prints is Ted's output and counts, the same rule `ted-voice-check.py` follows
and for the same reason: `ted-log-retention.py` exists because 4,998 lines of
users' own words ended up in a log file.

IT REFUSES TO SPEND BY ACCIDENT. The default is a dry run that shows the
cases, the models, the live rates and the estimate, then stops.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

STATE_DB = Path.home() / ".hermes" / "state.db"
_HERE = Path(__file__).resolve().parent

# The interpreter that can actually do this. Named, not guessed: the repo's
# `.venv` has neither SDK installed.
HERMES_PYTHON = Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "python3"

# Copied from Hermes' own caller rather than written from memory:
# `hermes_constants.OPENROUTER_BASE_URL`, and the attribution headers in
# `agent/auxiliary_client.py`, which OpenRouter's dashboard reads.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://heyted.in",
    "X-Title": "TED model bakeoff",
}
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

BASELINE = "claude-sonnet-5"

# The shortlist, cheapest last. Every one of these is reachable through a path
# TED already has: Claude direct, or OpenRouter, which is already the
# configured `fallback_model`.
#
# Deliberately NOT on this list: `sarvamai/sarvam-m`. It is the obvious
# candidate for a Hinglish product and it is **no longer served by
# OpenRouter** — checked live on 19 Sep 2026, not found, no near match. Reading
# it in an article and adding it here would have put a model in the router that
# cannot be called. Sarvam would need a new provider integration, which is real
# work and not a config change.
DEFAULT_CANDIDATES = [
    "claude-haiku-4-5",
    "google/gemini-3.8-flash",
    "openai/gpt-4o-mini",
]


# Families to take one candidate from, rather than ten spellings of Qwen.
#
# The point of a shortlist is to span the price range with models that are
# actually different from each other. OpenRouter lists 298 chat models that
# could serve a cron turn, and 22 of the 30 cheapest are variants of the same
# four base models — a bakeoff of those measures rounding, not choice.
_FAMILY_ORDER = (
    "anthropic", "google", "openai", "deepseek", "qwen", "mistralai",
    "meta-llama", "amazon", "inclusionai", "ibm-granite", "cohere",
)

# Kinds of model that cannot do this job whatever they cost. A coder model, a
# vision encoder or a moderation classifier will not write a reminder in
# Hinglish, and pricing them beside Sonnet is noise dressed as a finding.
_NOT_A_CHAT_MODEL = (
    "coder", "embed", "-vl-", "vision", "whisper", "tts", "image",
    "guard", "rerank", "moderation", "schematron",
)


def _load(name: str, filename: str):
    """Import a sibling script so its definitions are used, not copied."""
    spec = importlib.util.spec_from_file_location(name, _HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# NOT DONE, ON PURPOSE: borrowing the keys out of Hermes.
#
# Hermes has public resolvers for exactly this — `auth.get_anthropic_key()` and
# `config.get_env_value_prefer_dotenv` — and calling them would save whoever
# runs this from finding a key. It was written, and then taken back out.
#
# A script whose job is to spend money on replays should not also be the thing
# that fetches the credential to spend it with. Those are two capabilities, and
# the safety here is that they stay apart: `--run` releases the money, and a
# human supplies the key in the same breath. The convenience saved is one
# environment variable; what it costs is that the repo gains a tool that can
# pay for things by itself.


def shortlist(need_context: int, want: int) -> list[str]:
    """The cheapest usable candidate from each family, cheapest family first.

    Built from OpenRouter's live listing rather than written here, so it
    reflects what can actually be called today. An article dated this month
    said Sarvam-M was available and it is not; a hardcoded list ages the same
    way.

    Three filters, each for a reason that costs money if skipped:

      * `:free` is excluded. Those carry rate limits, and TED already has one
        open finding about `:free` rows landing in the spend report unpriced —
        a model whose bill reads zero while it serves real people is the exact
        failure `ted-api-spend.py` exists to prevent.
      * `:batch` is excluded. A reminder is due at a minute.
      * anything under twice the biggest real prompt is excluded. A model that
        fits today's 16K turn and not next month's is a failure that arrives
        later, quietly, on one person's thread.
    """
    try:
        with urllib.request.urlopen(OPENROUTER_MODELS_URL, timeout=30) as response:
            listing = json.loads(response.read())
    except Exception:  # noqa: BLE001
        return []
    ranked: list[tuple[float, str, str]] = []
    for row in listing.get("data", []):
        model_id = str(row.get("id") or "")
        if not model_id or model_id.endswith(":free") or ":batch" in model_id:
            continue
        if any(bad in model_id.lower() for bad in _NOT_A_CHAT_MODEL):
            continue
        if (row.get("context_length") or 0) < need_context * 2:
            continue
        pricing = row.get("pricing") or {}
        try:
            price_in = float(pricing["prompt"]) * 1_000_000
            price_out = float(pricing["completion"]) * 1_000_000
        except (KeyError, TypeError, ValueError):
            continue
        if price_in <= 0:
            continue
        # A cron turn is ~16,000 tokens in and ~120 out, so input dominates
        # almost entirely. Weighting them equally would rank on the wrong half.
        blended = price_in * 0.95 + price_out * 0.05
        family = model_id.split("/")[0].lstrip("~")
        ranked.append((blended, family, model_id))
    ranked.sort()
    seen: set[str] = set()
    picked: list[str] = []
    for _blended, family, model_id in ranked:
        if family in seen or family not in _FAMILY_ORDER:
            continue
        seen.add(family)
        picked.append(model_id)
        if len(picked) >= want:
            break
    return picked


def is_openrouter(model: str) -> bool:
    """A slashed id is an OpenRouter id. Claude's own ids carry no slash."""
    return "/" in model


def require_interpreter(models: list[str]) -> None:
    """Refuse a half-equipped interpreter before anything is attempted.

    `ted-spread-reminder-times.py` refuses to start under a python that cannot
    do its job, because the alternative there was a reminder that silently
    never fired again. The alternative here is smaller and the same shape: a
    run that reads five prompts, calls one model, and dies on the import for
    the second.
    """
    missing = []
    if any(not is_openrouter(m) for m in models):
        if importlib.util.find_spec("anthropic") is None:
            missing.append("anthropic (for the claude-* models)")
    if any(is_openrouter(m) for m in models):
        if importlib.util.find_spec("openai") is None:
            missing.append("openai (for the OpenRouter models)")
    if not missing:
        return
    print("This interpreter cannot run the models asked for.")
    for item in missing:
        print(f"  missing: {item}")
    print(f"\nUse the one that has them:\n\n    {HERMES_PYTHON} "
          f"{Path(__file__).name} ...\n")
    raise SystemExit(2)


def live_rates(models: list[str]) -> dict[str, dict]:
    """Input/output price per million and context window, from the provider.

    OpenRouter publishes this unauthenticated, so the numbers come from the
    thing that will send the bill rather than from this file. That matters more
    than it sounds: an article dated this month said Sarvam-M was available
    here and it is not, and the same article's prices would have been just as
    stale.

    A model the endpoint does not list is returned unpriced rather than
    guessed. `ted-api-spend.py` makes the same choice for the same reason.
    """
    rates: dict[str, dict] = {}
    try:
        with urllib.request.urlopen(OPENROUTER_MODELS_URL, timeout=30) as response:
            listing = json.loads(response.read())
    except Exception:  # noqa: BLE001 — offline is a state, not a crash
        return rates
    by_id = {row["id"]: row for row in listing.get("data", [])}
    for model in models:
        # Claude's direct ids differ from OpenRouter's spelling of the same
        # model (`claude-haiku-4-5` against `anthropic/claude-haiku-4.5`), and
        # the rates are identical, so the listing answers for both.
        candidates = [model, f"anthropic/{model.replace('-4-5', '-4.5')}"]
        for key in candidates:
            row = by_id.get(key)
            if not row:
                continue
            pricing = row.get("pricing", {})
            try:
                rates[model] = {
                    "input": float(pricing["prompt"]) * 1_000_000,
                    "output": float(pricing["completion"]) * 1_000_000,
                    "context": row.get("context_length"),
                }
            except (KeyError, TypeError, ValueError):
                pass
            break
    return rates


def connect() -> sqlite3.Connection:
    if not STATE_DB.is_file():
        raise SystemExit(f"No message history at {STATE_DB}")
    db = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def cases(db: sqlite3.Connection, limit: int) -> list[dict]:
    """Real cron turns, newest first: the system prompt and the turn's prompt.

    `sessions.system_prompt` is the exact string that went over the wire for
    that session, not a reconstruction — the same source `ted-prompt-audit.py`
    insists on, and for the same reason. A session with no stored prompt is
    skipped rather than given a substitute; a replay against a prompt TED never
    sent answers a question nobody asked.
    """
    rows = db.execute(
        """
        SELECT s.id, s.system_prompt, m.content AS prompt, m.timestamp
        FROM sessions s
        JOIN messages m ON m.session_id = s.id AND m.role = 'user'
        WHERE s.id LIKE 'cron_%'
          AND s.system_prompt IS NOT NULL AND s.system_prompt != ''
        ORDER BY m.timestamp DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "system": str(row["system_prompt"] or ""),
            "prompt": str(row["prompt"] or ""),
            "when": float(row["timestamp"] or 0),
        }
        for row in rows
    ]


def prompt_tokens(case: dict) -> int:
    """Characters over 2.92, the ratio `ted-prompt-audit.py` measured on TED's
    own Hinglish-and-emoji text. Four-per-token is an English-prose number and
    undercounted SOUL.md by 27% there, in the direction that makes a run look
    cheaper than it is."""
    return int((len(case["system"]) + len(case["prompt"])) / 2.92)


def estimate(case_list: list[dict], models: list[str], rates: dict) -> float:
    total = 0.0
    for case in case_list:
        tokens = prompt_tokens(case)
        for model in models:
            rate = rates.get(model)
            if not rate:
                continue  # unpriced is not zero
            total += tokens / 1_000_000 * rate["input"]
            total += 120 / 1_000_000 * rate["output"]  # a reminder is ~120 out
    return total


def ask_claude(model: str, case: dict, max_tokens: int) -> tuple[str, dict]:
    """One replay against Claude directly.

    No thinking, deliberately: Hermes skips extended thinking for Haiku
    entirely (`"haiku" not in model.lower()` in `agent/anthropic_adapter.py`),
    so asking for it would test a configuration TED never sends.
    """
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=case["system"],
        messages=[{"role": "user", "content": case["prompt"]}],
    )
    text = "".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    )
    return text.strip(), {
        "input": response.usage.input_tokens,
        "output": response.usage.output_tokens,
    }


def ask_openrouter(model: str, case: dict, max_tokens: int) -> tuple[str, dict]:
    """One replay through OpenRouter, the road TED's fallback already uses."""
    from openai import OpenAI

    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=os.environ["OPENROUTER_API_KEY"],
        default_headers=OPENROUTER_HEADERS,
    )
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": case["system"]},
            {"role": "user", "content": case["prompt"]},
        ],
    )
    usage = response.usage
    return (response.choices[0].message.content or "").strip(), {
        "input": getattr(usage, "prompt_tokens", 0) or 0,
        "output": getattr(usage, "completion_tokens", 0) or 0,
    }


def ask(model: str, case: dict, max_tokens: int) -> tuple[str, dict]:
    if is_openrouter(model):
        return ask_openrouter(model, case, max_tokens)
    return ask_claude(model, case, max_tokens)


# An empty reply is the loudest failure here, not a clean sheet.
#
# The first run of this bakeoff scored `qwen/qwen3.7-flash` as breaking none of
# the six rules. It had returned an empty string on three of four cases, and an
# empty string contains no dash, no receipt opening and no emoji beside a
# metric, so every rule passed. The scoreboard read "rules broken: none" for a
# model that would have said nothing to three people.
#
# TED already has this scar. On 4 Sep 2026 a turn ended having composed nothing
# at all, Palak and Vishwas Mishra received silence, and neither ever wrote
# again; `check_silent` in `ted-watch.py` exists because of it. Shipping a
# model that does that by design, on the strength of a clean rule sheet, would
# be the same incident scheduled twenty times a day.
#
# Why it happens is worth naming rather than guessing at: those models put
# their output in a reasoning field and left `message.content` empty — qwen
# billed 2,007 output tokens to return 14 characters of visible text. A model
# that needs special handling to emit one line is not a cheap model.
def empty_replies(texts: list[str]) -> int:
    return sum(1 for text in texts if not (text or "").strip())


def show(
    label: str, stats: dict, voice, cost: float, tokens: dict, ted_length: int | None,
    blank: int = 0,
) -> None:
    if not stats["replies"]:
        print(f"  {label:26} nothing came back")
        return
    broke = [
        f"{name} {stats[name]}" for name, _why, _pattern in voice.RULES if stats[name]
    ]
    price = f"${cost:.4f}" if cost else "unpriced"
    # Length against Ted's own reminders, not against nothing. "Low tokens" is
    # a quality bar here and not only a cost one: a reminder is one line, and a
    # model that answers with a paragraph has missed the job even when every
    # countable rule passes.
    length = f"{stats['avg chars']} chars avg"
    if ted_length:
        ratio = stats["avg chars"] / ted_length
        length += f" ({ratio:.1f}x Ted's {ted_length})"
    print(
        f"  {label:26} {stats['replies']} replies, {length}, "
        f"{price}, {tokens['input']:,} in / {tokens['output']:,} out"
    )
    # Printed before the rules, and never folded into them. A model that says
    # nothing has not passed; it has failed in the one way this product has
    # already been hurt by.
    if blank:
        print(
            f"    SAID NOTHING: {blank} of {stats['replies']} came back empty. "
            "Disqualifying — see `check_silent`."
        )
    print(f"    rules broken: {', '.join(broke) if broke else 'none'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="actually call the models")
    parser.add_argument("--cases", type=int, default=5, help="how many real turns")
    parser.add_argument(
        "--against",
        default=",".join(DEFAULT_CANDIDATES),
        help="comma-separated candidate models",
    )
    parser.add_argument("--baseline", default=BASELINE, help="what TED runs today")
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument(
        "--shortlist",
        type=int,
        metavar="N",
        help="replace the candidates with the N cheapest usable models, live",
    )
    args = parser.parse_args()

    voice = _load("ted_voice_check", "ted-voice-check.py")

    db = connect()
    case_list = cases(db, args.cases)
    if not case_list:
        print("No cron session carries a stored system prompt. Nothing to replay.")
        return 1
    biggest = max(prompt_tokens(case) for case in case_list)

    if args.shortlist:
        candidates = shortlist(biggest, args.shortlist)
        if not candidates:
            print("Could not reach OpenRouter's listing, so no shortlist was built.")
            return 1
    else:
        candidates = [m.strip() for m in args.against.split(",") if m.strip()]
    models = [args.baseline] + [m for m in candidates if m != args.baseline]

    # What Ted's reminders actually look like today, so "shorter is better" has
    # a number instead of a feeling. A reminder that arrives three times the
    # length of every reminder before it is wrong even if it breaks no rule.
    house_style = voice.measure(
        [t for _model, t in voice.delivered_reminders(db, 0, time.time())]
    )
    ted_length = house_style.get("avg chars")

    rates = live_rates(models)
    print("Real cron turns, replayed through each model.")
    print("No tools, no thinking. This measures wording, not tool calling.")
    print("The user's half of the prompt is read and never printed.\n")

    print("Live rates, from OpenRouter's own listing:\n")
    print(f"  {'model':28} {'in $/1M':>9} {'out $/1M':>9} {'context':>10}")
    for model in models:
        rate = rates.get(model)
        if not rate:
            print(f"  {model:28} {'unpriced':>9} {'unpriced':>9} {'?':>10}")
            continue
        print(
            f"  {model:28} {rate['input']:9.3f} {rate['output']:9.3f} "
            f"{rate['context'] or '?':>10}"
        )

    print()
    for case in case_list:
        print(
            f"  {time.strftime('%d %b %H:%M', time.localtime(case['when']))} "
            f"{case['id']}  ~{prompt_tokens(case):,} prompt tokens"
        )
    for model in models:
        window = (rates.get(model) or {}).get("context")
        if window and biggest > window:
            print(
                f"\n  WARNING: {model} has a {window:,} token context window and the "
                f"biggest case is ~{biggest:,}. It would fail where the baseline passes."
            )

    predicted = estimate(case_list, models, rates)
    print(f"\n  {len(case_list)} cases x {len(models)} models, about ${predicted:.2f}")

    if not args.run:
        print("\nDry run. Nothing was called and nothing was spent.")
        print("Add --run to actually replay these.")
        return 0

    require_interpreter(models)
    needed = []
    if any(not is_openrouter(m) for m in models) and not os.environ.get(
        "ANTHROPIC_API_KEY"
    ):
        needed.append("ANTHROPIC_API_KEY")
    if any(is_openrouter(m) for m in models) and not os.environ.get(
        "OPENROUTER_API_KEY"
    ):
        needed.append("OPENROUTER_API_KEY")
    if needed:
        # Deliberately not read out of `~/.hermes/auth.json`. The gateway's keys
        # live in `credential_pool` there, and a script that reaches into a
        # credential store to spend money is a worse thing to have in the repo
        # than one extra step at the prompt.
        print(f"\n{' and '.join(needed)} not set, so nothing was called and")
        print("nothing was spent. Export them on the same command that runs this;")
        print("see the note above `main` for why this does not fetch them itself.")
        return 1

    print()
    results: dict[str, list[str]] = {m: [] for m in models}
    tokens: dict[str, dict] = {m: {"input": 0, "output": 0} for m in models}
    costs: dict[str, float] = {m: 0.0 for m in models}

    for case in case_list:
        for model in models:
            try:
                text, usage = ask(model, case, args.max_tokens)
            except Exception as exc:  # noqa: BLE001 — the failure IS a result
                print(f"  {model} failed on {case['id']}: {type(exc).__name__}: {exc}")
                continue
            results[model].append(text)
            tokens[model]["input"] += usage["input"]
            tokens[model]["output"] += usage["output"]
            rate = rates.get(model)
            if rate:
                costs[model] += usage["input"] / 1_000_000 * rate["input"]
                costs[model] += usage["output"] / 1_000_000 * rate["output"]

    print("Scored on the countable SOUL.md rules, same table as `npm run voice`.\n")
    for model in models:
        show(
            model,
            voice.measure(results[model]),
            voice,
            costs[model],
            tokens[model],
            ted_length,
            empty_replies(results[model]),
        )

    print("\nWhat each model actually wrote:\n")
    for index, case in enumerate(case_list):
        print(f"  case {index + 1}")
        for model in models:
            if index < len(results[model]):
                print(f"    {model:24} {results[model][index]!r}")
        print()

    print(f"This run cost about ${sum(costs.values()):.4f}.")
    print(
        "Read the words, not just the counts. Six passing rules is not the same\n"
        "as a reminder that sounds like Ted."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
