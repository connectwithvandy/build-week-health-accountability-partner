#!/usr/bin/env python3
"""What Ted actually sends to the model, split four ways, from real traffic.

Roadmap task T13. Its first line is the whole job:

    Measure current system prompt, tools, memory and history tokens
    separately.

Separately is the word that matters. `session_model_usage` already knows what
a turn cost, and T12's baseline reads it back, but one number for the whole
prompt cannot tell you whether the bill is SOUL.md, ten tool schemas, or a
conversation nobody trimmed. You cannot shrink what you cannot name.

WHERE EACH NUMBER COMES FROM, so a wrong one can be chased:

  system prompt   `sessions.system_prompt` in state.db — the exact string that
                  went over the wire, per session, not a reconstruction. Split
                  further by markdown heading, which is how this file can say
                  that example dialogues are a fifth of Ted's identity.

  tools           `model_tools.get_tool_definitions()`, the real builder the
                  gateway calls, with the real toolsets from config.yaml
                  `platform_toolsets`. The same function, not a copy of the
                  schemas, so a tool added tomorrow shows up here without
                  anybody remembering to update this file.

  history         `messages` in state.db, per session. Lengths only.

  billed          `session_model_usage`. Input counted as input + cache read +
                  cache write, for the reason T12 gives: the three are
                  separate columns and the first alone is a sixth of the truth.

COUNT THE TOKENS, DO NOT GUESS THEM. The first version of this file divided
characters by four, which is Hermes' own pre-flight estimate, and it
undercounted SOUL.md by 27% — 10,696 tokens against a real 14,670. Four
characters per token is an English-prose number. Ted is written in Hinglish
with emoji and tokenizes at **2.92 characters per token**, so every conclusion
drawn from the estimate was a quarter too small, in the direction that makes
the prompt look cheaper than it is.

So this counts for real, through `messages.count_tokens`, which is free and
is not billed against the balance. Counts are cached in
`~/.hermes/cache/ted-prompt-tokens.json` keyed by a hash of the text, so a
second run costs nothing and an offline run still works. With no API key it
falls back to characters ÷ 2.92 — the measured ratio for Ted's own text, not
the generic 4 — and says so in the output rather than quietly pretending.

WHAT IT FOUND ON 19 SEP 2026, and why the cheapest fix is not the obvious one:

  Every single call, before one word of conversation, carries 15,835 tokens of
  system prompt (93% of it SOUL.md) and 5,525 tokens of tool schemas. That
  floor is ~21,400 tokens and it is paid on every turn of every session.

  The obvious move is to cut SOUL.md. The numbers say something else first. A
  WhatsApp turn reads its prompt from cache 88% of the time, so those tokens
  cost a tenth of list. A cron firing reads it 27% of the time and pays the
  cache-write premium on the rest — 593 sessions in 30 days, each carrying
  Ted's full chat persona, meal-logging rules and example dialogues in order
  to send one line like "kitna khaya piya aaj?".

  Same text, same size, several times the price, because of who is reading it.
  That is a routing question before it is an editing question.

NO MESSAGE CONTENT IS READ OR PRINTED, for T35's reason: an audit you cannot
run without opening somebody's food diary is one that gets run once. Lengths,
counts and headings only. The system prompt and the tool schemas are Ted's own
text and are counted in full; nothing a user typed ever is.

    python3 scripts/ted-prompt-audit.py                # 7 days
    python3 scripts/ted-prompt-audit.py --days 30
    python3 scripts/ted-prompt-audit.py --soul-only    # section table, no db
    python3 scripts/ted-prompt-audit.py --no-api       # never call out
    python3 scripts/ted-prompt-audit.py --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE_DB = HERMES_HOME / "state.db"
SOUL_PATH = HERMES_HOME / "SOUL.md"
REPO_SOUL = Path(__file__).resolve().parent.parent / "hermes" / "SOUL.md"
TOKEN_CACHE = HERMES_HOME / "cache" / "ted-prompt-tokens.json"

# The model Ted actually runs on. Token counts are model-specific, so counting
# against a different one would be a different number for the same text.
COUNT_MODEL = "claude-sonnet-5"

# Measured 19 Sep 2026 against count_tokens on SOUL.md and the live cron system
# prompt: 42,799 chars -> 14,670 tokens, 46,400 -> 15,835. Both 2.92. This is
# the fallback divisor when no API key is available. It is right for Ted's
# prose and wrong for JSON, which is why tool schemas are never estimated —
# they are counted or reported as unknown.
CHARS_PER_TOKEN = 2.92

# Anthropic bills a cache write above list input and a cache read far below it.
# Exact per-model rates belong to ted-api-spend.py, which prices by exact model
# name. These are only used for "was writing this cache worth it?", a ratio
# question that survives being approximate.
CACHE_WRITE_MULTIPLIER = 2.0
CACHE_READ_MULTIPLIER = 0.1


class TokenCounter:
    """Exact Claude token counts, cached on disk, degrading to a ratio.

    `messages.count_tokens` is free and unbilled, but it is a network call, so
    every result is cached by content hash. `mode` says which way a given run
    answered, and the report prints it: a number you cannot source is worse
    than no number.
    """

    def __init__(self, allow_api: bool = True) -> None:
        self.mode = "estimated"
        self._client = None
        self._base = 0
        self._cache: Dict[str, int] = {}
        self._dirty = False
        self._load_cache()
        if allow_api:
            self._connect()

    def _load_cache(self) -> None:
        try:
            self._cache = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._cache = {}

    def save(self) -> None:
        if not self._dirty:
            return
        try:
            TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_CACHE.write_text(json.dumps(self._cache), encoding="utf-8")
        except OSError:
            pass

    def _connect(self) -> None:
        load_hermes_env()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return
        try:
            from anthropic import Anthropic  # type: ignore
        except ImportError:
            return
        try:
            self._client = Anthropic()
            # One reference call: the fixed overhead the API adds to any
            # request. Subtracting it is what makes a block's count the
            # block's own size rather than the size of a request containing it.
            self._base = self._client.messages.count_tokens(
                model=COUNT_MODEL, messages=[{"role": "user", "content": "x"}]
            ).input_tokens
            self.mode = "counted"
        except Exception:  # noqa: BLE001 - no key, no network, no quota: same answer
            self._client = None

    def count(self, text: str) -> int:
        if not text:
            return 0
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
        if key in self._cache:
            return self._cache[key]
        if self._client is not None:
            try:
                got = self._client.messages.count_tokens(
                    model=COUNT_MODEL,
                    messages=[{"role": "user", "content": text}],
                ).input_tokens
                value = max(0, got - self._base)
                self._cache[key] = value
                self._dirty = True
                return value
            except Exception:  # noqa: BLE001
                pass
        return round(len(text) / CHARS_PER_TOKEN)

    def count_tools(self, tool_defs: List[Dict[str, Any]]) -> Optional[int]:
        """Tokens the tool schemas add to a request, as the API sees them.

        Counted as one payload rather than per tool and summed: the API adds a
        fixed overhead the moment any tool is present, so summing per-tool
        counts double-counts it once per tool (8,711 against a real 5,525).
        Returns None rather than a guess when it cannot count — tool schemas
        are JSON and the prose ratio does not apply to them.
        """
        if not tool_defs or self._client is None:
            return None
        key = hashlib.sha256(
            json.dumps(tool_defs, sort_keys=True).encode("utf-8")
        ).hexdigest()[:32]
        if key in self._cache:
            return self._cache[key]
        try:
            got = self._client.messages.count_tokens(
                model=COUNT_MODEL,
                messages=[{"role": "user", "content": "x"}],
                tools=[_to_anthropic_tool(d) for d in tool_defs],
            ).input_tokens
        except Exception:  # noqa: BLE001
            return None
        value = max(0, got - self._base)
        self._cache[key] = value
        self._dirty = True
        return value


def _to_anthropic_tool(definition: Dict[str, Any]) -> Dict[str, Any]:
    """OpenAI-shaped tool definition to the Anthropic wire shape.

    Hermes keeps tools in the OpenAI envelope and its Anthropic adapter
    converts them on the way out. count_tokens rejects the envelope with a
    400, so the same conversion happens here.
    """
    fn = definition.get("function", definition)
    return {
        "name": fn.get("name", "?"),
        "description": fn.get("description", ""),
        "input_schema": fn.get("parameters")
        or fn.get("input_schema")
        or {"type": "object", "properties": {}},
    }


def load_hermes_env() -> None:
    """Load ~/.hermes/.env the way the gateway does.

    Without it every Convex-backed tool fails its check_fn and the toolset
    measures one tool instead of ten — a tenth of the truth, reported
    confidently. The gateway reads this file; so must anything claiming to
    measure what the gateway sends.
    """
    env_path = HERMES_HOME / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    except OSError:
        return


# ── SOUL.md, by section ────────────────────────────────────────────────


def split_sections(markdown: str) -> List[Tuple[str, str]]:
    """Split on markdown headings. Returns (heading, body-including-heading).

    A section owns the text under it until the next heading of any level,
    because that is how the model reads it — nesting is presentation, not
    payload. Text before the first heading comes back as "(preamble)" so the
    parts add up to the file.
    """
    sections: List[Tuple[str, str]] = []
    heading = "(preamble)"
    buf: List[str] = []
    for line in markdown.split("\n"):
        if re.match(r"^#{1,6} ", line):
            if buf:
                sections.append((heading, "\n".join(buf)))
            heading = line.strip()
            buf = [line]
        else:
            buf.append(line)
    if buf:
        sections.append((heading, "\n".join(buf)))
    return [(h, b) for h, b in sections if b.strip()]


def audit_soul(path: Path, counter: TokenCounter) -> Optional[Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    rows = [
        {
            "heading": h.lstrip("# ").strip() or "(preamble)",
            "chars": len(body),
            "tokens": counter.count(body),
            "lines": body.count("\n") + 1,
        }
        for h, body in split_sections(text)
    ]
    rows.sort(key=lambda r: -r["tokens"])
    return {
        "path": str(path),
        "chars": len(text),
        "tokens": counter.count(text),
        "sections": rows,
    }


# ── Tools, from the real builder ───────────────────────────────────────


def platform_toolsets() -> Dict[str, List[str]]:
    """`platform_toolsets` from config.yaml, or the known defaults."""
    fallback = {"whatsapp": ["cronjob", "ted", "vision"], "cron": ["ted"]}
    config = HERMES_HOME / "config.yaml"
    try:
        import yaml  # type: ignore
    except ImportError:
        return fallback
    try:
        loaded = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - a corrupt config is not fatal here
        return fallback
    found = loaded.get("platform_toolsets")
    if not isinstance(found, dict):
        return fallback
    picked = {
        str(k): [str(t) for t in v]
        for k, v in found.items()
        if isinstance(v, list) and str(k) in ("whatsapp", "cron")
    }
    return picked or fallback


def audit_tools(counter: TokenCounter) -> Dict[str, Any]:
    """Size the tool payload the gateway would send, per platform.

    An empty toolset is never reported as a measurement. Under the repo's own
    `python3` the tool modules fail to import for want of PyYAML and this
    returned "0 tools", which silently took 5,525 tokens off the floor and
    made the payload look a quarter smaller than it is — the same class of
    error as estimating the tokens. A number that could not be measured is
    reported as unknown, with the reason, and is left out of the floor.
    """
    agent_root = HERMES_HOME / "hermes-agent"
    result: Dict[str, Any] = {"available": False, "platforms": {}, "note": None}
    if not agent_root.exists():
        result["note"] = f"no hermes-agent at {agent_root}"
        return result
    load_hermes_env()
    sys.path.insert(0, str(agent_root))
    try:
        import model_tools  # type: ignore
    except Exception as exc:  # noqa: BLE001
        result["note"] = f"could not import model_tools: {exc}"
        return result
    result["available"] = True
    for platform, toolsets in platform_toolsets().items():
        try:
            defs = model_tools.get_tool_definitions(
                enabled_toolsets=list(toolsets), quiet_mode=True
            )
        except Exception as exc:  # noqa: BLE001
            result["platforms"][platform] = {"error": str(exc)}
            continue
        if not defs:
            # Requested toolsets that resolve to nothing means this
            # interpreter cannot see the tools, not that Ted has none.
            result["platforms"][platform] = {
                "toolsets": list(toolsets),
                "count": None,
                "tokens": None,
                "names": [],
                "error": (
                    f"{', '.join(toolsets)} resolved to no tools under "
                    f"{Path(sys.executable).name} — the tool modules need "
                    "PyYAML and the gateway's other deps. Run this with "
                    "~/.hermes/hermes-agent/venv/bin/python3."
                ),
            }
            continue
        names = [d.get("function", d).get("name", "?") for d in defs]
        result["platforms"][platform] = {
            "toolsets": list(toolsets),
            "count": len(defs),
            "tokens": counter.count_tools(defs),
            "names": sorted(names),
        }
    return result


# ── What really went over the wire ─────────────────────────────────────


def audit_sessions(
    db: sqlite3.Connection, days: int, counter: TokenCounter
) -> Dict[str, Any]:
    """Per-source prompt composition and cache economics from state.db."""
    cutoff = f"strftime('%s','now') - {int(days)} * 86400"
    rows = db.execute(
        f"""
        SELECT s.source                                   AS source,
               COUNT(DISTINCT s.id)                       AS sessions,
               CAST(AVG(LENGTH(s.system_prompt)) AS INT)  AS sp_chars_avg,
               MIN(LENGTH(s.system_prompt))               AS sp_chars_min,
               MAX(LENGTH(s.system_prompt))               AS sp_chars_max
        FROM sessions s
        WHERE s.started_at > {cutoff}
          AND s.system_prompt IS NOT NULL AND s.system_prompt != ''
        GROUP BY s.source
        """
    ).fetchall()

    # The most recent prompt per source gets counted exactly. Averaging
    # character lengths across a window and then dividing would carry the
    # ratio's error; counting one real string does not.
    latest = {
        r["source"]: r["system_prompt"]
        for r in db.execute(
            f"""
            SELECT s1.source AS source, s1.system_prompt AS system_prompt
            FROM sessions s1
            WHERE s1.started_at > {cutoff}
              AND s1.system_prompt IS NOT NULL AND s1.system_prompt != ''
              AND s1.started_at = (
                  SELECT MAX(s2.started_at) FROM sessions s2
                  WHERE s2.source = s1.source
                    AND s2.system_prompt IS NOT NULL AND s2.system_prompt != ''
              )
            GROUP BY s1.source
            """
        ).fetchall()
    }

    history = {
        r["source"]: r
        for r in db.execute(
            f"""
            SELECT s.source                              AS source,
                   COUNT(m.id)                           AS messages,
                   COALESCE(SUM(LENGTH(m.content)), 0)   AS chars
            FROM sessions s JOIN messages m ON m.session_id = s.id
            WHERE s.started_at > {cutoff}
            GROUP BY s.source
            """
        ).fetchall()
    }

    billed = {
        r["source"]: r
        for r in db.execute(
            f"""
            SELECT s.source                  AS source,
                   SUM(u.api_call_count)     AS calls,
                   SUM(u.input_tokens)       AS input_tokens,
                   SUM(u.cache_write_tokens) AS cache_write,
                   SUM(u.cache_read_tokens)  AS cache_read,
                   SUM(u.output_tokens)      AS output_tokens
            FROM sessions s JOIN session_model_usage u ON u.session_id = s.id
            WHERE s.started_at > {cutoff}
            GROUP BY s.source
            """
        ).fetchall()
    }

    tools = audit_tools(counter)
    out: List[Dict[str, Any]] = []
    for row in rows:
        source = row["source"]
        sessions = row["sessions"] or 0
        hist = history.get(source)
        bill = billed.get(source)
        calls = (bill["calls"] or 0) if bill else 0

        platform = tools.get("platforms", {}).get(source)
        tool_tokens: Optional[int] = None
        if isinstance(platform, dict) and isinstance(platform.get("tokens"), int):
            tool_tokens = platform["tokens"]

        sp_text = latest.get(source) or ""
        sp_tokens = counter.count(sp_text)

        hist_chars = (hist["chars"] if hist else 0) or 0
        hist_tokens = round(hist_chars / CHARS_PER_TOKEN)
        hist_per_session = round(hist_tokens / sessions) if sessions else 0

        # The floor: what every single call carries before anybody says
        # anything. This is the number a shrink has to move. It is None when
        # the tool payload could not be measured, because a floor missing its
        # tools is not a smaller floor — it is an unknown one.
        floor = None if tool_tokens is None else sp_tokens + tool_tokens

        billed_total = 0
        if bill:
            billed_total = (
                (bill["input_tokens"] or 0)
                + (bill["cache_write"] or 0)
                + (bill["cache_read"] or 0)
            )
        billed_per_call = round(billed_total / calls) if calls else 0

        cache_write = (bill["cache_write"] or 0) if bill else 0
        cache_read = (bill["cache_read"] or 0) if bill else 0
        cached_share = cache_read / billed_total if billed_total else 0.0
        read_per_write = (cache_read / cache_write) if cache_write else None

        out.append(
            {
                "source": source,
                "sessions": sessions,
                "calls": calls,
                "system_prompt": {
                    "chars_avg": row["sp_chars_avg"],
                    "chars_min": row["sp_chars_min"],
                    "chars_max": row["sp_chars_max"],
                    "tokens": sp_tokens,
                },
                "tools": {
                    "tokens": tool_tokens,
                    "count": platform.get("count") if isinstance(platform, dict) else None,
                },
                "history": {
                    "messages": (hist["messages"] if hist else 0),
                    "tokens_per_session": hist_per_session,
                },
                "floor_tokens_per_call": floor,
                "billed": {
                    "input_tokens": (bill["input_tokens"] or 0) if bill else 0,
                    "cache_write": cache_write,
                    "cache_read": cache_read,
                    "total_prompt_tokens": billed_total,
                    "per_call": billed_per_call,
                    "cached_share": round(cached_share, 3),
                    "read_per_write": (
                        round(read_per_write, 2) if read_per_write is not None else None
                    ),
                },
            }
        )
    out.sort(key=lambda r: -r["billed"]["total_prompt_tokens"])
    return {"days": days, "sources": out, "tools": tools, "token_mode": counter.mode}


# ── Reporting ──────────────────────────────────────────────────────────


def _fmt(n: Optional[int]) -> str:
    return "—" if n is None else f"{n:,}"


def report_soul(soul: Optional[Dict[str, Any]], mode: str) -> None:
    if not soul:
        print("No SOUL.md found — the identity block cannot be sized.")
        return
    ratio = soul["chars"] / soul["tokens"] if soul["tokens"] else 0
    print(
        f"SOUL.md — {_fmt(soul['chars'])} chars, {_fmt(soul['tokens'])} tokens "
        f"({ratio:.2f} chars/token, {mode})"
    )
    print(f"  {soul['path']}")
    print()
    print(f"  {'tokens':>7}  {'share':>6}  section")
    print(f"  {'-'*7}  {'-'*6}  {'-'*50}")
    total = soul["tokens"] or 1
    for row in soul["sections"]:
        print(
            f"  {row['tokens']:>7,}  {row['tokens']/total*100:>5.1f}%  "
            f"{row['heading'][:50]}"
        )
    print()


def report_tools(tools: Dict[str, Any]) -> None:
    if not tools.get("available"):
        print(f"Tool schemas not measured: {tools.get('note')}")
        print()
        return
    for platform, data in sorted(tools.get("platforms", {}).items()):
        if "error" in data:
            print(f"{platform} tools — NOT MEASURED")
            print(f"    {data['error']}")
            print()
            continue
        size = (
            f"{data['tokens']:,} tokens"
            if isinstance(data.get("tokens"), int)
            else "size unknown without an API key"
        )
        print(
            f"{platform} tools — {data['count']} tools, {size}  "
            f"(toolsets: {', '.join(data['toolsets'])})"
        )
        print(f"    {', '.join(data['names'])}")
        print()


def report_sources(audit: Dict[str, Any]) -> None:
    print(f"Where the prompt goes — last {audit['days']} days")
    print()
    header = (
        f"  {'source':<9} {'sess':>5} {'calls':>6} {'system':>8} {'tools':>7} "
        f"{'hist/sess':>10} {'floor':>8} {'billed/call':>12} {'cached':>7} {'r/w':>6}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    unknown_floor = False
    for row in audit["sources"]:
        b = row["billed"]
        rw = b["read_per_write"]
        tools = row["tools"]["tokens"]
        floor = row["floor_tokens_per_call"]
        if floor is None:
            unknown_floor = True
        print(
            f"  {row['source']:<9} {row['sessions']:>5,} {row['calls']:>6,} "
            f"{row['system_prompt']['tokens']:>8,} "
            f"{('?' if tools is None else f'{tools:,}'):>7} "
            f"{row['history']['tokens_per_session']:>10,} "
            f"{('?' if floor is None else f'{floor:,}'):>8} {b['per_call']:>12,} "
            f"{b['cached_share']*100:>6.0f}% "
            f"{('—' if rw is None else f'{rw:.1f}'):>6}"
        )
    print()
    if unknown_floor:
        print("  ? = not measured on this run. See the tool section above; the")
        print("      floor is left unknown rather than reported without them.")
        print()
    print("  floor       system prompt + tools: what every call carries before")
    print("              anybody says anything. This is what a shrink must move.")
    print("  billed/call input + cache read + cache write, from the provider")
    print("  cached      share of billed prompt tokens that came from cache")
    print("  r/w         cache tokens read per token written. Below 1.0 means")
    print("              the cache was written more than it was read.")
    print()


def report_findings(audit: Dict[str, Any]) -> None:
    sources = {r["source"]: r for r in audit["sources"]}
    print("What this says")
    print()

    for name in ("whatsapp", "cron"):
        row = sources.get(name)
        if not row:
            continue
        floor = row["floor_tokens_per_call"]
        billed = row["billed"]["per_call"]
        if not floor or not billed:
            continue
        share = floor / billed * 100
        print(
            f"  {name}: {floor:,} tokens of floor against {billed:,} billed per "
            f"call — the\n    fixed payload is {share:.0f}% of every call."
        )
    print()

    cron = sources.get("cron")
    chat = sources.get("whatsapp")
    if cron and chat:
        print(
            f"  The same text costs different money. A chat turn reads "
            f"{chat['billed']['cached_share']*100:.0f}% of its prompt\n"
            f"  from cache; a cron firing reads "
            f"{cron['billed']['cached_share']*100:.0f}%. Cron pays close to list "
            "price for the\n  identity block, plus the write premium, on every "
            "firing."
        )
        rw = cron["billed"]["read_per_write"]
        if rw is not None and rw < 1.0:
            print()
            print(
                f"  Cron's cache is written {1/rw:.1f}x more than it is read "
                f"(r/w {rw:.2f}). A cache\n"
                "  entry that expires unread costs more than not caching at all.\n"
                "  Check the gap between firings against config.yaml "
                "prompt_caching.cache_ttl."
            )
    if audit.get("token_mode") != "counted":
        print()
        print(
            "  Tokens were ESTIMATED at 2.92 chars each, not counted. That ratio\n"
            "  was measured on Ted's own text and is close for prose and wrong\n"
            "  for JSON. Run with an ANTHROPIC_API_KEY for exact counts; "
            "count_tokens\n  is free."
        )
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="T13. What Ted sends to the model, split four ways."
    )
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument(
        "--soul-only",
        action="store_true",
        help="just the SOUL.md section table; reads no database",
    )
    parser.add_argument(
        "--no-api",
        action="store_true",
        help="never call count_tokens; estimate from the measured ratio",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    counter = TokenCounter(allow_api=not args.no_api)
    try:
        soul_path = SOUL_PATH if SOUL_PATH.exists() else REPO_SOUL
        soul = audit_soul(soul_path, counter)

        if args.soul_only:
            if args.json:
                print(json.dumps({"soul": soul, "token_mode": counter.mode}, indent=2))
            else:
                report_soul(soul, counter.mode)
            return 0

        if not STATE_DB.exists():
            raise SystemExit(f"No database at {STATE_DB}.")
        db = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            audit = audit_sessions(db, args.days, counter)
        finally:
            db.close()

        if args.json:
            print(json.dumps({"soul": soul, **audit}, indent=2))
            return 0

        report_soul(soul, counter.mode)
        report_tools(audit["tools"])
        report_sources(audit)
        report_findings(audit)
        return 0
    finally:
        counter.save()


if __name__ == "__main__":
    sys.exit(main())
