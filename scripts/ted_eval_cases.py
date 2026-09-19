"""The case set T16 asks for: real turns, pinned, with no user text in the repo.

T16 wants "anonymised cases for text meals, photos, voice, Hinglish,
correction, pause/reschedule, goal change, safety boundary, ambiguous input
and user frustration", and a suite that "produces comparable pass/fail/quality
results for old vs proposed behavior".

WHAT ALREADY EXISTED, so this builds rather than duplicates:

  * `ted-model-bakeoff.py` already replays real turns through several models,
    prices the run before spending, and scores the replies with
    `ted-voice-check.py`'s rules. What it replays is **only cron turns** —
    `s.id LIKE 'cron_%'` — so 209 chat sessions with a stored system prompt
    have never been used. Those are where meals, Hinglish, corrections and
    frustration live.
  * The deterministic half of T16 is largely done: 48 docstrings in
    `hermes/test_ted_safety_gates.py` cite a dated production incident, which
    is the "past incidents as tests rather than prompt stories" clause.

WHY THE FILE HOLDS HASHES AND NOT TEXT. This is a public repository. Every
category here is somebody's health message, and "anonymised" in T16 cannot
mean "with the name removed" — the sentence itself identifies. So a case is
stored as a sha256 of the message, truncated, plus its category. The text
stays in `state.db` on the machine, exactly like the media in
`ted-forget-user.py` and the chat id in `docs/T09_DELETION_AUDIT.md`.

The session id is not stored either, for the same reason: it is per-person,
and pinning a case to a person is the thing a deletion is supposed to undo. A
case whose message has been erased simply stops resolving, which is the
correct behaviour and is how a deleted user leaves the suite.

WHY NINE CATEGORIES AND NOT TEN. **Voice cannot be built from this data.**
A voice note reaches `messages` already transcribed, as ordinary text with no
marker: four turns in the whole store mention audio at all, and none of them
is a marker. There is no way to tell a transcribed note from a typed
sentence after the fact, so a "voice" case would be a typed case with a label
on it. Saying so is better than a category that quietly tests nothing.

THE CLASSIFIERS ARE COARSE ON PURPOSE. They select candidates out of 1,473
turns; they are not a judgement about what the turn meant. The file they
produce is meant to be read and curated by a person, which is why it is
versioned and checked in.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

SUITE_VERSION = 1

# T16's ten, minus voice, which the data cannot distinguish. Order is the
# roadmap's.
CATEGORIES = (
    "meal_text",
    "meal_photo",
    "hinglish",
    "correction",
    "pause_reschedule",
    "goal_change",
    "safety_boundary",
    "ambiguous",
    "frustration",
)

# Not a category. Recorded so the gap is in the artefact rather than only in
# this docstring, because a reader counts nine and asks.
UNAVAILABLE = {
    "voice": (
        "arrives already transcribed, with no marker: indistinguishable from "
        "typed text after the fact"
    )
}

_IMAGE = re.compile(r"\[image received\]|\[Image att", re.IGNORECASE)
_FOOD = re.compile(
    r"\b(roti|rotis|dal|rice|chawal|paneer|sabzi|idli|dosa|poha|upma|egg|eggs|"
    r"chicken|paratha|curd|dahi|chai|oats|smoothie|salad|khana|bhaji|rajma|"
    r"chole|biryani|sandwich|maggi|banana|apple|milk|protein)\b",
    re.IGNORECASE,
)
# Romanised Hindi that is not also an English word. "aur" and "hai" are the
# giveaways; "main" and "to" are not, and putting them here would label most
# of the corpus Hinglish.
_HINGLISH = re.compile(
    r"\b(aur|hai|hain|nahi|nahin|kya|kaise|karo|kar|raha|rahi|mera|meri|"
    r"tha|thi|bhi|abhi|kal|aaj|khaya|khana|thoda|bohot|bahut|accha|theek)\b"
    r"|[ऀ-ॿ]",
    re.IGNORECASE,
)
_CORRECTION = re.compile(
    r"\b(actually|sorry|i meant|not \w+ it was|no it was|correction|"
    r"galat|wrong)\b",
    re.IGNORECASE,
)
_PAUSE = re.compile(
    r"\b(pause|stop|break|later|reschedule|band karo|hold on|not now|"
    r"busy|travel|travelling|holiday)\b",
    re.IGNORECASE,
)
_GOAL = re.compile(
    r"\b(lose|gain|maintain|target|goal|bulk|cut|deficit|surplus|"
    r"weight loss|put on)\b",
    re.IGNORECASE,
)
# The boundary cases the gates exist for. Matching here does not mean the turn
# was unsafe: it means a reply to it is worth scoring.
_SAFETY = re.compile(
    r"\b(doctor|medicine|medication|diagnos\w*|thyroid|diabet\w*|pcos|pcod|"
    r"pregnan\w*|bp|blood pressure|starv\w*|fast(?:ing)? for \d|skip meals|"
    r"years old|year old|i am \d{1,2}\b|anorexi\w*|bulimi\w*)\b",
    re.IGNORECASE,
)
_FRUSTRATION = re.compile(
    r"\b(confused|useless|not working|doesn'?t work|stupid|wtf|"
    r"why (?:are|do|is) you|forget it|leave it|ridiculous)\b|\?\?+",
    re.IGNORECASE,
)


def fingerprint(text: str) -> str:
    """A case's stable name. No text, no session, no person."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def classify(text: str) -> list[str]:
    """Every category this turn is a candidate for. Coarse by design."""
    said = (text or "").strip()
    if not said:
        return []
    hits: list[str] = []

    if _IMAGE.search(said):
        hits.append("meal_photo")
    elif _FOOD.search(said):
        hits.append("meal_text")

    for name, pattern in (
        ("hinglish", _HINGLISH),
        ("correction", _CORRECTION),
        ("pause_reschedule", _PAUSE),
        ("goal_change", _GOAL),
        ("safety_boundary", _SAFETY),
        ("frustration", _FRUSTRATION),
    ):
        if pattern.search(said):
            hits.append(name)

    # Ambiguous is the absence of a signal, not a signal. A turn that matched
    # something is not ambiguous however short it is, or "ok" after a meal
    # would be filed both ways.
    if not hits and len(said.split()) <= 3:
        hits.append("ambiguous")
    return hits


def candidates(db: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every chat turn that can be replayed, with its categories.

    Only turns whose session stored the system prompt that actually went over
    the wire. `ted-model-bakeoff.py` refuses to replay against a reconstructed
    prompt and this must not quietly widen that rule: a case replayed against
    a prompt TED never sent answers a question nobody asked.
    """
    rows = db.execute(
        """
        SELECT m.content AS prompt, m.timestamp AS ts
        FROM sessions s
        JOIN messages m ON m.session_id = s.id AND m.role = 'user'
        WHERE s.id NOT LIKE 'cron_%'
          AND s.system_prompt IS NOT NULL AND s.system_prompt != ''
        ORDER BY m.timestamp DESC
        """
    ).fetchall()

    found: list[dict[str, Any]] = []
    for row in rows:
        text = str(row["prompt"] or "")
        cats = classify(text)
        if not cats:
            continue
        found.append({
            "hash": fingerprint(text),
            "categories": cats,
            "chars": len(text),
            "ts": float(row["ts"] or 0),
        })
    return found


def build(db: sqlite3.Connection, per_category: int) -> dict[str, Any]:
    """Pick up to `per_category` newest cases for each category.

    Newest first because the prompt and the product both move: a case from
    before the onboarding rebuild scores a Ted that no longer exists.
    """
    # Deduplicate by hash before selecting, not after. Identical text is
    # common — "ok", "done", "pause" — and two rows with the same words are
    # one case, because the hash is the case's name. Filling a quota with
    # repeats silently gave a category fewer distinct cases than asked for:
    # `counts` read 6 for pause_reschedule while 4 resolved.
    unique: dict[str, dict[str, Any]] = {}
    for case in candidates(db):  # already newest first
        unique.setdefault(case["hash"], case)
    found = list(unique.values())

    chosen: dict[str, dict[str, Any]] = {}
    for name in CATEGORIES:
        taken = 0
        for case in found:
            if taken >= per_category:
                break
            if name not in case["categories"]:
                continue
            taken += 1
            kept = chosen.setdefault(
                case["hash"],
                {"hash": case["hash"], "categories": [], "chars": case["chars"]},
            )
            if name not in kept["categories"]:
                kept["categories"].append(name)

    # Counted off the cases that actually went in, so the header can never
    # disagree with the body.
    counts = {
        name: sum(1 for case in chosen.values() if name in case["categories"])
        for name in CATEGORIES
    }

    return {
        "version": SUITE_VERSION,
        "per_category": per_category,
        "counts": counts,
        "unavailable": UNAVAILABLE,
        "cases": sorted(chosen.values(), key=lambda c: c["hash"]),
    }


def read(path: Path) -> dict[str, Any]:
    """The checked-in suite, or empty when there is none."""
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve(db: sqlite3.Connection, suite: dict[str, Any]) -> tuple[list[dict], list[str]]:
    """Turn the pinned hashes back into replayable turns.

    Returns the cases found and the hashes that no longer resolve. A missing
    hash is reported, never skipped silently: it means the message was
    deleted — which is what a forgotten user looks like from here — or that
    the store was rebuilt, and both change what a comparison means.
    """
    wanted = {case["hash"]: case for case in suite.get("cases", [])}
    if not wanted:
        return [], []

    found: dict[str, dict] = {}
    for row in db.execute(
        """
        SELECT s.id, s.system_prompt, m.content AS prompt, m.timestamp AS ts
        FROM sessions s
        JOIN messages m ON m.session_id = s.id AND m.role = 'user'
        WHERE s.id NOT LIKE 'cron_%'
          AND s.system_prompt IS NOT NULL AND s.system_prompt != ''
        ORDER BY m.timestamp DESC
        """
    ):
        text = str(row["prompt"] or "")
        key = fingerprint(text)
        if key in wanted and key not in found:
            found[key] = {
                "id": str(row["id"]),
                "system": str(row["system_prompt"] or ""),
                "prompt": text,
                "when": float(row["ts"] or 0),
                "categories": wanted[key]["categories"],
            }
    missing = sorted(key for key in wanted if key not in found)
    return [found[k] for k in sorted(found)], missing
