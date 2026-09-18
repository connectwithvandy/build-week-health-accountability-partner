#!/usr/bin/env python3
"""What Ted remembers about people, sorted into the layers T14 asks for.

Roadmap task T14, whose first line is the job:

    Separate profile memory, today-state, recent conversational context and
    learned behavioural memory.

You cannot define which task retrieves which category until the categories
exist, and today they do not. `userFacts` is one flat table with a free-text
`key` the model invents per turn, and `getUserMemory` hands the whole of it to
every turn as `- key: value` lines. There is no layer, no expiry, no type, and
supersession is an exact string match on that invented key.

This sorts what is actually stored into the four layers and reports what the
sorting exposes. It changes nothing.

WHERE EACH NUMBER COMES FROM:

  facts, users  `npx convex data <table> --deployment` against production.
                Read-only. The per-user `/ted-memory` endpoint the gate uses
                cannot answer a question about everybody at once, which is why
                this reaches for the table rather than the gate's own door.

  layers        The table at LAYERS below, by key. Keys the model has invented
                that nothing here recognises are reported as `unclassified`
                rather than guessed at — an audit that silently buckets what it
                does not understand is worse than one that admits the gap.

  reuse         `userFacts.useCount` and `lastUsedAt`, written by the gate from
                the delivered text since commit d554a88 (16 Sep 2026). That
                commit says in as many words that a zero means "not measured
                yet" until the gateway has served with it for a week, so this
                refuses to draw a conclusion before RIPENS_AT and says why.

NO FACT VALUES ARE PRINTED, and none are written to disk. Keys are the
schema's words; values are the user's, and some of them are the reason
`ted-log-retention.py` had to exist. Lengths, counts and keys only. The one
exception is `--show-keys`, which prints the invented key names so a missing
entry in LAYERS can be added — key names, still never values.

    python3 scripts/ted-memory-audit.py
    python3 scripts/ted-memory-audit.py --show-keys
    python3 scripts/ted-memory-audit.py --json
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
DEPLOYMENT = os.environ.get("TED_CONVEX_DEPLOYMENT", "hardy-scorpion-901")

# Commit d554a88 shipped fact-reuse counting on 16 Sep 2026 22:51 IST and asked
# for a week of live serving before a zero is read as an answer. 23 Sep.
RIPENS_AT = "2026-09-23"

# ── The layers, and which invented key belongs to which ────────────────
#
# T14 names four. A fifth had to be added on contact with the real table:
# "instruction" — facts that are not about the person at all but about how Ted
# should speak. The model has been writing SOUL.md back into user memory.
#
#   profile      durable, and already has a typed column in `users`. Two homes
#                for one fact is the condition that produced Order 24 and the
#                nine repair scripts; they agree today, which is not the same
#                as being safe.
#   behavioural  learned about the person from how they live. Durable, no
#                structured home, and the layer T14's "learned behavioural
#                memory" actually means.
#   health       durable and sensitive. Supplements, symptoms, conditions.
#   preference   what the person likes. Durable, theirs.
#   instruction  how Ted should talk. Not a fact about the person. SOUL.md
#                already says all of it, at 14,670 tokens a turn.
#
# today-state and recent conversational context are deliberately absent: the
# first lives in `dailyEntries`, the second in the session, and neither is in
# this table. That they are elsewhere is the finding, not an omission here.
LAYERS: Dict[str, str] = {
    # profile — mirrored by a typed column in `users`
    "name": "profile",
    "age": "profile",
    "sex": "profile",
    "gender": "profile",
    "height_cm": "profile",
    "weight_kg": "profile",
    "goal": "profile",
    "goal_raw": "profile",
    "goal_target_weight_kg": "profile",
    # behavioural — learned from how they live
    "activity_level": "behavioural",
    "work_schedule": "behavioural",
    "wake_time": "behavioural",
    "habit_note": "behavioural",
    "mindset": "behavioural",
    # health — durable and sensitive
    "health_note": "health",
    "symptom_note": "health",
    "supplements": "health",
    "intimacy_status": "health",
    "relationship_status": "health",
    # preference — theirs. Four of these were filed as `instruction` in the
    # first version of this table, on the strength of the key name, and reading
    # the values proved it wrong. "wants end of day check for missed items" and
    # "meals, water, supplements, moving" are this person's choices, not Ted's
    # house style; deleting them as duplicated voice rules would have thrown
    # away the only record of what they asked for.
    #
    # That mistake is the argument for a fixed key vocabulary before a layer
    # scheme: a layer decided from a key the model invented is a layer decided
    # from a guess, and `nudge_preferences` sounds exactly like an instruction.
    "diet_preference": "preference",
    "drink_preference": "preference",
    "coaching_preference": "preference",
    "logging_preference": "preference",
    "daily_preference": "preference",
    "nudge_preferences": "preference",
    # instruction — Ted's own voice, stored per user. Every one of these
    # restates SOUL.md's "How I talk" and "How I actually sound": short,
    # lowercase, hinglish, one thought, no dashes, no receipt-style replies.
    "tone_preference": "instruction",
    "chat_style_preference": "instruction",
    "voice_style_preference": "instruction",
    "meal_reply_rule": "instruction",
}

# Any key beginning with this is a health fact whatever follows, because the
# model names each supplement its own key and the list cannot be enumerated.
# The typo "suppplement_vitamin_b12" is caught by this and by nothing else,
# which is the point.
_HEALTH_PREFIXES = ("supplement_", "suppplement_", "medication_", "condition_")

# Which `users` column each profile key duplicates, and whether the two can be
# compared by value at all.
#
# `goal` cannot. `users.goal` is an enum — loseWeight, maintainWeight — and
# `userFacts.goal` is whatever the model typed: "lose weight", "losing weight",
# "holding steady", "holding_steady". Comparing them as strings reported eight
# disagreements where seven were the same goal in two vocabularies. That the
# two stores have no shared words for one concept is itself the finding, and it
# is reported as that rather than dressed up as drift.
MIRRORS: Dict[str, Tuple[str, bool]] = {
    "name": ("name", True),
    "age": ("age", True),
    "sex": ("sex", True),
    "gender": ("sex", True),
    "height_cm": ("heightCm", True),
    "weight_kg": ("weightKg", True),
    "goal": ("goal", False),
    "goal_raw": ("goal", False),
}


def layer_of(key: str) -> str:
    if key in LAYERS:
        return LAYERS[key]
    if key.startswith(_HEALTH_PREFIXES):
        return "health"
    return "unclassified"


# ── Reading the tables ─────────────────────────────────────────────────


def read_table(table: str, limit: int = 2000) -> Tuple[List[str], List[List[str]]]:
    """One Convex table, as a header and rows of already-split cells.

    `npx convex data` is the only read that answers a question about every
    user at once; the gate's `/ted-memory` door takes one `whatsappUserId` and
    is the wrong shape for an audit. Its column set follows whatever the
    sampled rows contain, so the header is read rather than assumed.
    """
    try:
        out = subprocess.run(
            ["npx", "convex", "data", table, "--deployment", DEPLOYMENT,
             "--limit", str(limit)],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"Could not read {table} from {DEPLOYMENT}: {exc}")
    if out.returncode != 0:
        detail = (out.stderr or out.stdout).strip().splitlines()
        raise SystemExit(
            f"Could not read {table} from {DEPLOYMENT}.\n  "
            + "\n  ".join(detail[-4:] or ["no output"])
        )
    lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
    if len(lines) < 2:
        return [], []
    header = [c.strip() for c in lines[0].split("|")]
    rows = []
    for line in lines[2:]:
        if line.startswith("Showing"):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) == len(header):
            rows.append(cells)
    return header, rows


def _norm(value: str) -> str:
    """Loose normal form for comparing one store against the other.

    "175" against "175.0", "Male" against "male". A strict match would report
    a disagreement that is only a formatting difference, which is the wrong
    direction to be wrong in for a number somebody might act on.
    """
    text = value.strip().lower()
    # Only a *fractional* zero is noise. An earlier version stripped trailing
    # zeros from any digit string, which turned 1000 into 1 and would have
    # called a 1000mcg dose and a 100mcg one the same fact.
    if "." in text and text.replace(".", "", 1).isdigit():
        text = text.rstrip("0").rstrip(".")
    return text


def cell(header: List[str], row: List[str], name: str) -> str:
    try:
        return row[header.index(name)].strip().strip('"')
    except (ValueError, IndexError):
        return ""


def load() -> Dict[str, Any]:
    fh, frows = read_table("userFacts")
    uh, urows = read_table("users")

    facts = []
    for row in frows:
        key = cell(fh, row, "key")
        if not key:
            continue
        value = cell(fh, row, "value")
        facts.append(
            {
                "key": key,
                "user": cell(fh, row, "userId"),
                "layer": layer_of(key),
                "value_chars": len(value),
                # Held in memory only, for the mirror comparison below, and
                # never printed or written. Claiming two stores agree without
                # comparing them is the error this whole audit exists to catch.
                "value_norm": _norm(value),
                "use_count": int(cell(fh, row, "useCount") or 0),
                "last_used": cell(fh, row, "lastUsedAt"),
            }
        )

    users = {}
    for row in urows:
        uid = cell(uh, row, "_id")
        if not uid:
            continue
        users[uid] = {col: cell(uh, row, col) for col in uh if col}
    return {"facts": facts, "users": users}


# ── The findings ───────────────────────────────────────────────────────


def analyse(data: Dict[str, Any]) -> Dict[str, Any]:
    facts: List[Dict[str, Any]] = data["facts"]
    users: Dict[str, Dict[str, str]] = data["users"]
    total = len(facts) or 1

    by_layer = collections.Counter(f["layer"] for f in facts)
    per_user = collections.Counter(f["user"] for f in facts)

    # Profile facts that also have a typed column, and whether the two agree.
    # `uncompared` is kept separate from `agreeing` on purpose: a fact whose
    # counterpart could not be read is not a fact that matches.
    mirrored, agreeing, uncompared, disagreeing = 0, 0, 0, []
    incomparable: collections.Counter = collections.Counter()
    for fact in facts:
        mirror = MIRRORS.get(fact["key"])
        if not mirror:
            continue
        column, comparable = mirror
        stored = users.get(fact["user"], {}).get(column, "")
        if not stored:
            continue
        mirrored += 1
        if not comparable:
            incomparable[fact["key"]] += 1
            continue
        a = _norm(stored)
        b = fact.get("value_norm", "")
        if not a or not b:
            uncompared += 1
        elif a == b or a in b or b in a:
            agreeing += 1
        else:
            disagreeing.append(fact["key"])

    # Two keys for one thing, inside one user. Exact-match supersession cannot
    # see these, so a correction saved under a near-miss key becomes a second,
    # contradictory row instead of replacing the first.
    collisions = []
    keys_by_user = collections.defaultdict(list)
    for fact in facts:
        keys_by_user[fact["user"]].append(fact["key"])
    for uid, keys in keys_by_user.items():
        for i, one in enumerate(sorted(keys)):
            for other in sorted(keys)[i + 1 :]:
                if one == other:
                    continue
                # A near miss: one contains the other, or they differ by a
                # single repeated character (the "suppplement" case).
                squashed_one = "".join(
                    c for j, c in enumerate(one) if j == 0 or c != one[j - 1]
                )
                squashed_other = "".join(
                    c for j, c in enumerate(other) if j == 0 or c != other[j - 1]
                )
                if squashed_one == squashed_other:
                    collisions.append((one, other, "repeated character"))
                elif one in other or other in one:
                    collisions.append((one, other, "one contains the other"))

    reused = [f for f in facts if f["use_count"] > 0]
    return {
        "deployment": DEPLOYMENT,
        "facts": len(facts),
        "users_with_facts": len(per_user),
        "users_total": len(users),
        "facts_per_user": {
            "mean": round(len(facts) / max(len(per_user), 1), 1),
            "max": max(per_user.values()) if per_user else 0,
            "distribution": dict(sorted(collections.Counter(per_user.values()).items())),
        },
        "layers": {
            name: {"facts": count, "share": round(count / total * 100)}
            for name, count in by_layer.most_common()
        },
        "mirrored_in_users_table": {
            "facts": mirrored,
            "share": round(mirrored / total * 100),
            "agreeing": agreeing,
            "uncompared": uncompared,
            "disagreeing": disagreeing,
            "incomparable": dict(incomparable),
        },
        "key_collisions": collisions,
        "reuse": {
            "facts_ever_reused": len(reused),
            "share": round(len(reused) / total * 100),
            "ripens_at": RIPENS_AT,
        },
        "unclassified_keys": sorted(
            {f["key"] for f in facts if f["layer"] == "unclassified"}
        ),
    }


def report(found: Dict[str, Any], show_keys: bool) -> None:
    print(f"Ted's memory, {found['deployment']}")
    print()
    print(
        f"  {found['facts']} facts across {found['users_with_facts']} of "
        f"{found['users_total']} users — "
        f"mean {found['facts_per_user']['mean']}, max {found['facts_per_user']['max']}"
    )
    print()
    print("  This is the first thing worth knowing: the memory block is small.")
    print("  Three facts a turn is not a token problem, and shrinking it is not")
    print("  the T14 that matters. What it lacks is shape.")
    print()

    print("By layer")
    print()
    for name, row in found["layers"].items():
        print(f"  {name:<14} {row['facts']:>4}  {row['share']:>3}%")
    print()

    instruction = found["layers"].get("instruction", {}).get("facts", 0)
    if instruction:
        # Six of the original seven were deleted on 19 Sep 2026 by
        # `ted-purge-voice-rules.py`. Arpit's was kept on purpose: it carries
        # "bangalore vibe", the one fragment SOUL.md does not already say, and
        # that is where he lives rather than how Ted talks. So the line has to
        # be able to report a small number without calling it an infestation.
        row = "fact is a rule" if instruction == 1 else "facts are rules"
        print(
            f"  `instruction` is the layer T14 does not name, and it should not\n"
            f"  exist: {instruction} {row} about how Ted talks, stored per\n"
            f"  user, injected every turn, on top of a SOUL.md that already says\n"
            f"  all of it. The model has been writing Ted's voice back into the\n"
            f"  user's memory.\n"
            f"  The gate refuses new ones; `npm run memory:voice-rules` lists\n"
            f"  what is left and deletes only with --apply."
        )
        print()

    mirror = found["mirrored_in_users_table"]
    print("Two homes for one fact")
    print()
    print(
        f"  {mirror['facts']} facts ({mirror['share']}%) mirror a typed column in "
        f"`users`."
    )
    print(
        f"  compared by value: {mirror['agreeing']} agree, "
        f"{len(mirror['disagreeing'])} disagree, {mirror['uncompared']} unreadable."
    )
    if mirror["disagreeing"]:
        print(f"  DISAGREEING: {', '.join(sorted(set(mirror['disagreeing'])))}")
        print("  Two writable copies of one fact, and they have drifted apart.")
    else:
        print("  Agreeing today is not the same as safe: `users.weightKg` is typed")
        print("  and validated, `userFacts.weight_kg` is free text the model writes,")
        print("  and only the second one reaches the prompt.")
    if mirror["incomparable"]:
        total_inc = sum(mirror["incomparable"].values())
        keys = ", ".join(sorted(mirror["incomparable"]))
        print()
        print(f"  {total_inc} more ({keys}) cannot be compared at all: the two")
        print("  stores hold the same concept in different words. `users.goal` is an")
        print("  enum — loseWeight, maintainWeight — and the fact beside it says")
        print('  "lose weight", "losing weight", "holding steady", "holding_steady".')
        print("  Nothing can tell a correction from a rephrasing, which is exactly")
        print("  what T14's supersession rule has to be able to do.")
    print()

    print("Supersession")
    print()
    if found["key_collisions"]:
        print("  Keys that mean one thing and are stored as two, inside one user:")
        for one, other, why in found["key_collisions"]:
            print(f"    {one}  +  {other}   ({why})")
        print()
        print("  `by_user_and_key` supersedes on an exact string match, so a")
        print("  correction saved under a near-miss key does not replace the")
        print("  original — it sits beside it, and both go into the next prompt.")
    else:
        print("  No near-miss key pairs found inside a single user today.")
    print()

    reuse = found["reuse"]
    print("Reuse")
    print()
    print(
        f"  {reuse['facts_ever_reused']} of {found['facts']} facts "
        f"({reuse['share']}%) have ever changed a reply."
    )
    print(
        f"  NOT A FINDING YET. Commit d554a88 shipped this counter on 16 Sep and\n"
        f"  asked for a week of live serving before a zero means anything.\n"
        f"  Ripe on {reuse['ripens_at']}. Until then this line is an instrument\n"
        f"  check, not a measurement."
    )
    print()

    if found["unclassified_keys"]:
        print(
            f"Unclassified: {len(found['unclassified_keys'])} key(s) this script "
            "does not recognise."
        )
        if show_keys:
            for key in found["unclassified_keys"]:
                print(f"    {key}")
        else:
            print("  Run with --show-keys to see them and add them to LAYERS.")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="T14. What Ted remembers, sorted into layers."
    )
    parser.add_argument(
        "--show-keys",
        action="store_true",
        help="print unrecognised key names (names only, never values)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    found = analyse(load())
    if args.json:
        print(json.dumps(found, indent=2))
    else:
        report(found, args.show_keys)
    return 0


if __name__ == "__main__":
    sys.exit(main())
