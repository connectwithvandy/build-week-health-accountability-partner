#!/usr/bin/env python3
"""
Write three answers the users gave that no store kept.

    python3 scripts/ted-repair-missing-answers.py            # dry run
    python3 scripts/ted-repair-missing-answers.py --apply

Not a general tool. Three named people, one field each, each one quoted from
where it was actually decided.

VENKY, `name`. He answered the very first question — "hey 👋 i'm ted. what
should i call you?" at 23:12:46 on 16 Sep 2026 — with "venky" eight seconds
later, and Ted replied "haha venky it is 😄". The gate's own state file holds
`"name": "venky"`; Convex holds no name at all, so `setupStateFor` counts him
as one requirement short and the model kept re-asking for a name it had been
given. `_clean_name("venky")` accepts it, so this is not a parsing failure, it
is a write that never reached the second store.

ANKIE and PRITIKA, `goal`. Neither was ever asked. Pritika was onboarded on
4 Sep by the five-question flow, which asked "which city you in" and had no
goal question at all; Ankie was never asked a single numbered question. Both
have age, height, weight and sex on file and have been logging for days, and
`goal` is the only thing standing between them and a finished setup. The value
is the builder's decision, recorded here as that rather than dressed up as an
answer they typed.

  * Ankie    38, 147 cm, 71 kg, BMI 32.9
  * Pritika  33, 157 cm, 58 kg, BMI 23.5

Pritika's BMI is inside the healthy range. That is written down here because a
goal decides the direction of every calorie number that follows it, and this
one was not hers.

WHAT IT DOES NOT DO. No calorie target is written for anybody. `saveOnboarding`
stores the profile and nothing else; the number is `setTarget`'s job and it is
deliberately left alone. Venky's own target is the open case that proves the
point: he said "gaining", was offered 2,100 or 1,910, answered "do it", and is
tracked against 1,910. That is not repaired here because nobody has asked him
which he meant, and choosing for him is the failure this file exists to avoid.

`currentField` is read back and echoed unchanged, the same way
`ted-land-missed-answers.py` does it, so no write moves anybody's place in
their own conversation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

HERMES_ENV = os.path.expanduser("~/.hermes/.env")
REQUIRED_ENV = ("TED_CONVEX_SITE_URL", "TED_HERMES_SHARED_SECRET")

# whatsappUserId -> (who, field, value, why)
WRITES = {
    "whatsapp:sha256:7aa60675bdb2a46b38a2f95e343a38c0647b01d176b6ed415f0438d58cb3b6a6": (
        "Venky", "name", "venky",
        'answered "venky" at 23:12:54 on 16 Sep; held in the gate file, never in Convex',
    ),
    "whatsapp:sha256:dd52ca42fd743a8d93cf419027fc7bb3187cd039725f973eadf0b75ccdaa2420": (
        "Ankie", "goal", "loseWeight",
        "never asked; builder's decision, BMI 32.9",
    ),
    "whatsapp:sha256:9e878c98f63d44875e8e1eb1a34beb1485f4fa3a81b6a2112135e8f462502b1d": (
        "Pritika", "goal", "loseWeight",
        "never asked; builder's decision, BMI 23.5 which is inside the healthy range",
    ),
}


def load_env() -> dict[str, str]:
    found = {name: os.environ.get(name, "") for name in REQUIRED_ENV}
    if all(found.values()) or not os.path.exists(HERMES_ENV):
        return found
    with open(HERMES_ENV, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() in REQUIRED_ENV and not found.get(key.strip()):
                found[key.strip()] = value.strip().strip('"').strip("'")
    return found


def convex(action: str, whatsapp_user_id: str, **body) -> dict:
    env = load_env()
    missing = [n for n in REQUIRED_ENV if not env.get(n)]
    if missing:
        raise SystemExit(f"{' and '.join(missing)} is not set")
    request = urllib.request.Request(
        env["TED_CONVEX_SITE_URL"].rstrip("/") + "/ted-memory",
        data=json.dumps(
            {"action": action, "whatsappUserId": whatsapp_user_id, **body}
        ).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {env['TED_HERMES_SHARED_SECRET']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return {
            "success": False,
            "error": f"HTTP {error.code}: "
            f"{error.read().decode('utf-8', errors='replace')[:200]}",
        }
    except urllib.error.URLError as error:
        return {"success": False, "error": f"could not reach Convex: {error.reason}"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write them")
    args = parser.parse_args()

    audit = convex("setupAudit", "builder-readback")
    if not audit.get("success"):
        print(f"could not read Convex: {audit.get('error')}", file=sys.stderr)
        return 1
    rows = {u.get("whatsappUserId"): u for u in audit.get("users", [])}

    planned = []
    for key, (who, field, value, why) in WRITES.items():
        row = rows.get(key)
        if row is None:
            print(f"  {who}: no such user in Convex, skipped", file=sys.stderr)
            continue
        missing = row.get("missing") or []
        already = row.get(field)
        current = row.get("currentField") or "complete"
        state = "already set" if already else ("missing" if field in missing else "absent")
        print(f"  {who:9} {field:5} = {value!r}")
        print(f"            currently {state}{' (' + str(already) + ')' if already else ''}")
        print(f"            still missing: {', '.join(missing) or 'nothing'}")
        print(f"            why: {why}")
        print()
        if already:
            # Someone answered it in the meantime, which is a better source
            # than this file. Never overwrite a real answer with a decision.
            print(f"            -> skipping, {field} already has a value\n")
            continue
        planned.append((key, who, field, value, current))

    if not planned:
        print("Nothing to write.")
        return 0
    if not args.apply:
        print(f"Dry run. {len(planned)} write(s) pending. Re-run with --apply.")
        return 0

    for key, who, field, value, current in planned:
        result = convex(
            "onboarding", key, currentField=current, profile={field: value}
        )
        ok = result.get("success")
        print(f"  {who}: {field} -> {value!r}  {'ok' if ok else result.get('error')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
