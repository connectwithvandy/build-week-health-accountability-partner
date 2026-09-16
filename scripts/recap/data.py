#!/usr/bin/env python3
"""Turn one person's last seven days into the card's JSON. Read-only."""
from __future__ import annotations
import datetime, json, sys

def card_for(entries, users, name, today):
    user = next(u for u in users if str(u.get("name")) == name)
    week = [today - datetime.timedelta(days=i) for i in range(6, -1, -1)]
    keys = {d.isoformat() for d in week}
    mine = [
        e for e in entries
        if e["userId"] == user["_id"] and e.get("state") != "corrected"
        and e["localDate"] in keys
    ]
    logged = {e["localDate"] for e in mine}
    meals = [e for e in mine if e["entryType"] == "meal"]
    items = sum(len((e.get("meal") or {}).get("items", [])) for e in meals)
    counts = {
        "meals": len(meals),
        "workouts": len([e for e in mine if e["entryType"] == "workout"]),
        "water": len([e for e in mine if e["entryType"] == "water"]),
        "steps": len([e for e in mine if e["entryType"] == "steps"]),
    }
    # Zeros are dropped, the same rule the meal card follows: a line reading
    # "0 workouts" is not a recap, it is a reprimand.
    stats = [{"value": len(logged), "label": "days logged"}]
    if counts["meals"]:
        stats.append({"value": counts["meals"], "label": "meals"})
    if items:
        stats.append({"value": items, "label": "things logged"})
    for key, label in (("workouts", "workouts"), ("water", "waters"), ("steps", "step counts")):
        if counts[key] and len(stats) < 3:
            stats.append({"value": counts[key], "label": label})

    bits = []
    if counts["meals"]:
        bits.append(f"{counts['meals']} meals")
    if items:
        bits.append(f"{items} things logged")
    if counts["workouts"]:
        bits.append(f"{counts['workouts']} workouts")
    line = ", ".join(bits) + ", all from the chat." if bits else "you kept it going this week."

    return {
        "daysLogged": len(logged),
        "days": [
            {"letter": d.strftime("%a")[0], "logged": d.isoformat() in logged}
            for d in week
        ],
        "stats": stats[:3],
        "line": line,
    }

if __name__ == "__main__":
    entries = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
    users = [json.loads(l) for l in open(sys.argv[2]) if l.strip()]
    today = datetime.date.fromisoformat(sys.argv[4])
    print(json.dumps(card_for(entries, users, sys.argv[3], today)))
