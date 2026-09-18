"""The routing decision for a scheduled reminder on the official path.

Every case here is a real cron job from `~/.hermes/cron/jobs.json` on 18 Sep
2026, or a failure that reaches a real person if it is wrong. Nothing in this
module sends; what it can get wrong is sending the wrong words, or refusing to
send words that were fine.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hermes.ted_whatsapp_templates import (
    DAILY_REVIEW,
    QUIET_CHECK,
    SCHEDULED_REMINDER,
    decide,
    is_daily_review,
    reminder_phrase,
    render,
    window_is_open,
)

NOW = datetime(2026, 9, 19, 18, 30, tzinfo=timezone.utc)


def ago(**kwargs) -> datetime:
    return NOW - timedelta(**kwargs)


# --- the window --------------------------------------------------------------


def test_a_recent_message_leaves_the_window_open():
    assert window_is_open(ago(hours=2), NOW) is True


def test_a_message_yesterday_has_closed_it():
    assert window_is_open(ago(hours=30), NOW) is False


def test_no_inbound_on_record_counts_as_shut():
    # Not the same fact as "long ago", deliberately the same answer: an
    # unprovable window is treated as shut.
    assert window_is_open(None, NOW) is False


def test_the_last_ten_minutes_are_given_away():
    # 23h55m is inside Meta's window and outside ours. Losing that race means
    # the API refuses the send and the person gets nothing at all, which is a
    # worse outcome than ₹0.115.
    assert window_is_open(ago(hours=23, minutes=55), NOW) is False
    assert window_is_open(ago(hours=23, minutes=45), NOW) is True


def test_a_naive_timestamp_is_read_as_utc_rather_than_crashing():
    naive = ago(hours=2).replace(tzinfo=None)
    assert window_is_open(naive, NOW) is True


# --- what a job is about -----------------------------------------------------


@pytest.mark.parametrize(
    "job_name, expected",
    [
        ("ted:27b6eabe8c71:coq10", "CoQ10"),
        ("ted:27b6eabe8c71:vitamin_b12", "vitamin B12"),
        ("ted:27b6eabe8c71:omega3", "omega 3"),
        ("ted:27b6eabe8c71:chelated_iron", "chelated iron"),
        ("ted:21978f1ff0fd:meals", "your meals"),
        ("ted:21978f1ff0fd:movement", "moving a bit"),
    ],
)
def test_the_real_structured_jobs_read_as_english(job_name, expected):
    assert reminder_phrase(job_name) == expected


def test_both_water_jobs_are_about_water():
    assert reminder_phrase("ted:21978f1ff0fd:water_1") == "water"
    assert reminder_phrase("ted:21978f1ff0fd:water_2") == "water"


def test_a_kind_nobody_has_added_yet_still_reads():
    # The point of deriving rather than mapping: a supplement added tomorrow
    # needs no edit here.
    assert reminder_phrase("ted:27b6eabe8c71:magnesium_glycinate") == (
        "magnesium glycinate"
    )


@pytest.mark.parametrize(
    "job_name, expected",
    [
        ("Vitamin D reminder", "vitamin D"),
        ("meditation morning nudge", "meditation"),
        ("workout evening nudge", "workout"),
    ],
)
def test_the_hand_made_jobs_lose_their_trailing_noise(job_name, expected):
    # "this is the reminder you asked me for: vitamin d reminder" is how a
    # machine writes. The template already supplies the word.
    assert reminder_phrase(job_name) == expected


def test_a_daily_review_has_no_phrase_because_it_has_its_own_template():
    assert reminder_phrase("ted:fa65c5bf229d:daily_review") is None
    assert is_daily_review("ted:fa65c5bf229d:daily_review") is True
    assert is_daily_review("ted:21978f1ff0fd:water_1") is False


@pytest.mark.parametrize("job_name", ["", "   ", "reminder", "nudge nudge"])
def test_a_job_with_nothing_left_refuses_to_answer(job_name):
    assert reminder_phrase(job_name) is None


# --- the payload -------------------------------------------------------------


def test_the_daily_review_payload_is_shaped_as_meta_wants_it():
    payload = render(DAILY_REVIEW, ["Ankiita"])
    assert payload["messaging_product"] == "whatsapp"
    assert payload["type"] == "template"
    assert payload["template"]["name"] == DAILY_REVIEW
    assert payload["template"]["language"] == {"code": "en"}
    body = payload["template"]["components"][0]
    assert body["type"] == "body"
    assert body["parameters"] == [{"type": "text", "text": "Ankiita"}]


def test_the_scheduled_reminder_carries_both_parameters_in_order():
    payload = render(SCHEDULED_REMINDER, ["Gourav", "omega 3"])
    assert payload["template"]["components"][0]["parameters"] == [
        {"type": "text", "text": "Gourav"},
        {"type": "text", "text": "omega 3"},
    ]


def test_the_wrong_number_of_parameters_is_refused_here_not_by_meta():
    with pytest.raises(ValueError, match="takes 2 parameter"):
        render(SCHEDULED_REMINDER, ["Gourav"])
    with pytest.raises(ValueError, match="takes 1 parameter"):
        render(DAILY_REVIEW, ["Ankiita", "water"])


def test_an_empty_parameter_is_refused():
    # Meta accepts it and the person reads "hey , this is the reminder".
    with pytest.raises(ValueError, match="empty parameter"):
        render(SCHEDULED_REMINDER, ["Gourav", "  "])


def test_an_unknown_template_name_is_refused():
    with pytest.raises(ValueError, match="Unknown template"):
        render("ted_something_never_submitted", ["Vandy"])


def test_the_quiet_check_is_defined_but_takes_one_parameter():
    # Drafted, not adopted — the decision is Vandy's. Defined so that adopting
    # it is a routing change rather than a new payload shape.
    assert render(QUIET_CHECK, ["Vishal"])["template"]["name"] == QUIET_CHECK


# --- the routing decision ----------------------------------------------------


def test_inside_the_window_nothing_changes():
    decision = decide("ted:21978f1ff0fd:water_1", "Ankiita", ago(hours=3), NOW)
    assert decision.route == "model"
    assert decision.needs_model is True
    assert decision.payload is None


def test_outside_the_window_a_supplement_becomes_a_template():
    decision = decide("ted:27b6eabe8c71:coq10", "Vandy", ago(days=3), NOW)
    assert decision.route == "template"
    assert decision.template == SCHEDULED_REMINDER
    assert decision.parameters == ("Vandy", "CoQ10")
    assert decision.needs_model is False
    assert decision.payload["template"]["name"] == SCHEDULED_REMINDER


def test_outside_the_window_a_daily_review_uses_its_own_template():
    decision = decide("ted:b75ccdaa2420:daily_review", "Ram", ago(days=2), NOW)
    assert decision.route == "template"
    assert decision.template == DAILY_REVIEW
    assert decision.parameters == ("Ram",)


def test_a_user_with_no_stored_name_is_held_rather_than_greeted_generically():
    # Every draft opens with the name. Inventing "friend" is a voice decision
    # this module does not get to make.
    decision = decide("ted:27b6eabe8c71:coq10", None, ago(days=3), NOW)
    assert decision.route == "hold"
    assert "no stored name" in decision.reason


def test_a_job_that_maps_to_nothing_is_held_rather_than_guessed():
    decision = decide("nudge", "Vandy", ago(days=3), NOW)
    assert decision.route == "hold"
    assert decision.payload is None
    assert "no phrase maps" in decision.reason


def test_a_held_reminder_says_which_job_it_was():
    # A hold is a person not hearing from Ted. Whatever logs it needs to be
    # able to name the job without going back to the scheduler.
    decision = decide("daily check", "Vandy", ago(days=3), NOW)
    assert decision.route == "hold"
    assert "'daily check'" in decision.reason


def test_the_window_is_checked_before_the_name():
    # An open window needs no template, so a missing name is not a problem
    # there. Checking the name first would silence a reminder that was fine.
    decision = decide("ted:27b6eabe8c71:coq10", None, ago(hours=1), NOW)
    assert decision.route == "model"
