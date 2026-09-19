"""Decide whether a scheduled reminder can be Ted's own words, or a template.

Roadmap T06, the half of step 2 that Hermes does not already do.

**Hermes already has the adapter.** `gateway/platforms/whatsapp_cloud.py` is
2,217 lines and covers phases 2 to 4: outbound text over the Graph API, the
webhook server with the verify-token handshake, X-Hub-Signature-256 HMAC
checking, wamid replay protection, media both ways, and interactive buttons and
lists. It was found by looking rather than assumed to be missing, and it means
the migration does not need an adapter written.

Its own docstring lists "Phase 5 — 24-hour conversation window + template
fallback" as scope, and phase 5 is the one that is not built: there is no
template payload anywhere in the file and nothing tracks the window. That is
also the part that could not have been written by Hermes, because which
template a reminder becomes, and what goes in its variable, is a fact about
Ted's cron jobs and nobody else's.

So this module is the decision, and only the decision:

    window open   -> run the model, send Ted's own sentence, exactly as today
    window shut   -> send an approved template whose job is to earn one tap
    no mapping    -> send nothing, and say why

It sends nothing itself, registers no hook and imports no gateway code. The
wiring is a later patch: `pre_cron_agent` (patch 13) is the right hook and the
right moment — before the model is paid for — but it understands `skip` and
`allow` only, so carrying a template back needs a third action added there.

**Submitted 19 Sep 2026, and still not live.** `ted_daily_review` and
`ted_scheduled_reminder` are with Meta and *In review*, filed UTILITY, under
exactly the names used below. `ted_quiet_check` was deliberately held back and
is not with Meta at all. So the names here are no longer drafts for two of the
three — but nothing is approved yet, and an approved template still sends
nothing until the `pre_cron_agent` wiring above exists.

One wording change happened at submission and is already reflected in
`docs/T06_TEMPLATES.md`: `ted_daily_review`'s body now says *"it's the check-in
time you set with me"*. Meta's pre-submit classifier refused the original,
which never said the person had asked for it, and recommended Marketing. If a
future template is pushed to Marketing, that sentence is the thing to add.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

# Meta's customer service window: 24 hours from the user's last inbound
# message. Ours is deliberately shorter. A reminder that loses the race by a
# minute is not sent as Ted's own words and quietly dropped by Meta — it is
# rejected at the API with the window closed, and the person gets nothing. Ten
# minutes of margin costs about ₹0.115 on the occasions it is wrong.
WINDOW = timedelta(hours=24)
WINDOW_MARGIN = timedelta(minutes=10)

# The template names drafted in docs/T06_TEMPLATES.md, with the number of
# positional parameters each body carries. The count is checked before a
# payload is built, because Meta rejects a mismatch at send time and a rejected
# reminder is a person who heard nothing.
DAILY_REVIEW = "ted_daily_review"
SCHEDULED_REMINDER = "ted_scheduled_reminder"
QUIET_CHECK = "ted_quiet_check"

PARAMETER_COUNT = {
    DAILY_REVIEW: 1,
    SCHEDULED_REMINDER: 2,
    QUIET_CHECK: 1,
}

# Ted's cron jobs are named `ted:<user key>:<kind>` when the gate created them
# and freely when a person set one up in conversation. Both shapes are live
# today, so both are read.
STRUCTURED_JOB = re.compile(r"^ted:(?P<user>[0-9a-f]+):(?P<kind>.+)$")

# A kind whose slug does not read well as English. Anything not here is
# derived, so a supplement added tomorrow needs no edit to this file.
PHRASES = {
    "coq10": "CoQ10",
    "vitamin_d": "vitamin D",
    "vitamin_b12": "vitamin B12",
    "omega3": "omega 3",
    "meals": "your meals",
    "movement": "moving a bit",
    "water": "water",
}

# Words that end a job's display name without describing it. "Vitamin D
# reminder" is a reminder about vitamin D, and the template already supplies
# the word "reminder" — repeating it reads like a machine wrote it.
TRAILING_NOISE = ("reminder", "nudge", "morning", "evening", "daily", "check")

# A trailing counter on a kind: water_1 and water_2 are both about water.
TRAILING_INDEX = re.compile(r"_\d+$")


@dataclass(frozen=True)
class Decision:
    """What should happen to one scheduled reminder.

    ``route`` is one of:

    ``model``
        The window is open. Nothing changes: the model writes the line and it
        is sent as it is today.
    ``template``
        The window is shut and an approved template covers this job.
        ``payload`` is ready to POST and no model call is needed.
    ``hold``
        The window is shut and nothing covers this job. Sending is refused
        rather than guessed at, and ``reason`` says what is missing.
    """

    route: str
    reason: str
    template: str | None = None
    parameters: tuple[str, ...] = ()
    payload: dict[str, Any] | None = field(default=None, compare=False)

    @property
    def needs_model(self) -> bool:
        return self.route == "model"


def window_is_open(
    last_inbound_at: datetime | None,
    now: datetime | None = None,
    margin: timedelta = WINDOW_MARGIN,
) -> bool:
    """Whether Ted may still speak freely to this person.

    ``None`` means no inbound message is on record, which is not the same as
    one long ago and is treated the same way on purpose: both mean the window
    cannot be shown to be open, and the safe reading of an unprovable window is
    that it is shut.
    """
    if last_inbound_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    if last_inbound_at.tzinfo is None:
        last_inbound_at = last_inbound_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - last_inbound_at) < (WINDOW - margin)


def reminder_phrase(job_name: str) -> str | None:
    """What this job is about, in words a person would use.

    Returns ``None`` when nothing readable survives, because the alternative is
    putting a slug in front of a real person. The caller must not send.
    """
    job_name = (job_name or "").strip()
    if not job_name:
        return None

    match = STRUCTURED_JOB.match(job_name)
    if match:
        kind = match.group("kind").strip().lower()
        if kind == "daily_review":
            # Its own template, not a phrase. Callers route on this before
            # asking for a phrase; answering here too would be a second
            # opinion nobody asked for.
            return None
        base = TRAILING_INDEX.sub("", kind)
        if base in PHRASES:
            return PHRASES[base]
        return base.replace("_", " ").strip() or None

    words = re.split(r"\s+", job_name.lower())
    while words and words[-1] in TRAILING_NOISE:
        words.pop()
    phrase = " ".join(words).strip()
    if not phrase:
        return None
    # A hand-named job reaches the same override table as a structured one, so
    # "Vitamin D reminder" arrives as "vitamin D" rather than "vitamin d". It
    # is one letter and it is the difference between Ted writing and a script
    # writing.
    return PHRASES.get(phrase.replace(" ", "_"), phrase)


def is_daily_review(job_name: str) -> bool:
    match = STRUCTURED_JOB.match((job_name or "").strip())
    return bool(match) and match.group("kind").strip().lower() == "daily_review"


def render(template: str, parameters: list[str] | tuple[str, ...]) -> dict[str, Any]:
    """The Graph API body for one template send.

    Positional parameters, matching the drafts. Meta also accepts named ones;
    positional is used because the drafts are written that way and a template
    is approved as submitted, so the two cannot drift apart later.
    """
    expected = PARAMETER_COUNT.get(template)
    if expected is None:
        raise ValueError(f"Unknown template: {template}")
    if len(parameters) != expected:
        raise ValueError(
            f"{template} takes {expected} parameter(s), got {len(parameters)}"
        )
    for value in parameters:
        if not str(value).strip():
            raise ValueError(f"{template} was given an empty parameter")

    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": "en"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": str(value)} for value in parameters
                    ],
                }
            ],
        },
    }


def decide(
    job_name: str,
    user_name: str | None,
    last_inbound_at: datetime | None,
    now: datetime | None = None,
) -> Decision:
    """Route one scheduled reminder, without sending anything."""
    if window_is_open(last_inbound_at, now):
        return Decision(route="model", reason="inside the 24h window")

    name = (user_name or "").strip()
    if not name:
        # Every draft template opens with the person's name. Without one there
        # is no template to send, and inventing "there" or "friend" is a voice
        # decision this module has no business making.
        return Decision(
            route="hold",
            reason="outside the window and no stored name for the greeting",
        )

    if is_daily_review(job_name):
        parameters = (name,)
        return Decision(
            route="template",
            reason="outside the window, daily review",
            template=DAILY_REVIEW,
            parameters=parameters,
            payload=render(DAILY_REVIEW, parameters),
        )

    phrase = reminder_phrase(job_name)
    if not phrase:
        return Decision(
            route="hold",
            reason=f"outside the window and no phrase maps from job {job_name!r}",
        )

    parameters = (name, phrase)
    return Decision(
        route="template",
        reason="outside the window, scheduled reminder",
        template=SCHEDULED_REMINDER,
        parameters=parameters,
        payload=render(SCHEDULED_REMINDER, parameters),
    )
