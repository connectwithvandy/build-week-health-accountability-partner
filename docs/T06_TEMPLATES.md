# T06 step 3 — the reminder templates

**Status: drafted, not submitted.** Submission needs the Meta developer app
from step 1, which nobody has created yet. Everything below is ready to paste
the moment it exists.

Step 3 is first because it is the only step with a queue in front of it. Meta
reviews a template on its own schedule, and every later step — the full flow on
the test number, the parallel week, the cutover — needs approved templates to
be a real test rather than a partial one.

---

## 1. When a template is used at all

Only outside the 24-hour window. Inside it, nothing changes: Ted writes what he
would write today, in his own words, free.

From `npm run window`, 30 days to 18 Sep 2026:

```
inside the 24h window, free        321   79.1%
outside it, needs a template        85   20.9%
```

All 85 are scheduled reminders. A reply is never a problem, because by
definition somebody has just written.

**So a template is not a replacement for Ted's voice. It is a knock on the
door.** Its whole job is to get a tap, which reopens the window, after which
the real message is the improvised one Ted would have sent anyway. That is the
answer to the product question section 4 of `T06_OFFICIAL_WHATSAPP_PATH.md`
left open: the nudge becomes a fixed opener, and the conversation happens on
the other side of it.

This costs one tap of friction and buys back the thing that would otherwise be
lost. The alternative — approving a library of improvised-sounding reminders —
is not possible: every sentence would need approval weeks earlier, and Ted's
reminders are generated per person, per day, by the model.

## 2. What the reminders actually are

The 20 enabled cron jobs on 18 Sep 2026, by kind:

| kind | jobs | example |
| --- | --- | --- |
| daily review | 8 | "how did today go" at the user's review time |
| named supplement | 5 | vitamin D, CoQ10, B12, chelated iron, omega 3 |
| meals, water, movement | 4 | water twice a day, a movement nudge |
| personal | 3 | meditation, an evening workout, a 40-day chalisa count |

Three templates cover all twenty, because the last three groups are the same
shape: *a thing, at a time, that this person asked for.*

## 3. The templates

Category **UTILITY** for all three. Meta's test is two-part and both halves
have to hold: the content "must be non-promotional, not containing any
promotional or persuasive intent" and must be "specific to or requested by the
user (clearly related to their order, account, services, or transactions)".
A reminder a person set for themselves is as specific to them as it gets. The
trap is the second half of the same page: utility messages "should not promote,
recommend, upsell, or cross-sell products; include offers; or attempt to secure
renewals", and a template with mixed content is re-categorised as marketing —
7.5x the price and a different approval bar.

**So nothing below sells anything, including selling Ted.** No "don't miss
out", no streak-breaking language, no urgency. The voice stays Ted's: lowercase,
warm, at most one emoji, which SOUL.md already requires and which happens to be
exactly what keeps a template inside the category.

Limits these are written against, read from Meta's own component reference on
19 Sep 2026: **body 1024 characters, header 60, footer 60, up to 10 quick reply
buttons at 25 characters each.** All three drafts are far inside them.

---

### 3.1 `ted_daily_review`

Covers the 8 daily review jobs.

```json
{
  "name": "ted_daily_review",
  "category": "UTILITY",
  "language": "en",
  "components": [
    {
      "type": "BODY",
      "text": "hey {{1}}, it's your usual check-in time. want to run through the day and see where you landed?",
      "example": { "body_text": [["Ankiita"]] }
    },
    {
      "type": "BUTTONS",
      "buttons": [
        { "type": "QUICK_REPLY", "text": "let's do it" },
        { "type": "QUICK_REPLY", "text": "not today" }
      ]
    }
  ]
}
```

`{{1}}` is the stored first name. "not today" is a real answer, not a decoy:
it reopens the window too, and Ted can then offer a pause in his own words —
which is the existing break flow, unchanged.

### 3.2 `ted_scheduled_reminder`

Covers the 5 supplements, the meals, water and movement jobs, and the 3
personal ones. One template, one variable, twelve jobs.

```json
{
  "name": "ted_scheduled_reminder",
  "category": "UTILITY",
  "language": "en",
  "components": [
    {
      "type": "BODY",
      "text": "hey {{1}}, this is the reminder you asked me for: {{2}}. tap when it's done and i'll pick up from there.",
      "example": { "body_text": [["Gourav", "omega 3 after lunch"]] }
    },
    {
      "type": "BUTTONS",
      "buttons": [
        { "type": "QUICK_REPLY", "text": "done" },
        { "type": "QUICK_REPLY", "text": "remind me later" }
      ]
    }
  ]
}
```

"the reminder you asked me for" is doing work beyond politeness: it states the
opt-in inside the message, which is the fact the UTILITY category turns on.

`{{2}}` is filled from the job, not from the model. That matters — see §5.

### 3.3 `ted_quiet_check`

For a person whose window has been shut for days and who has no reminder due.
Not in the 85, and the one most likely to be re-categorised, so it is separate
and its wording is deliberately flat.

```json
{
  "name": "ted_quiet_check",
  "category": "UTILITY",
  "language": "en",
  "components": [
    {
      "type": "BODY",
      "text": "hey {{1}}, it's been a while and i didn't want to just go quiet on you. still want me checking in, or should i hold off for now?",
      "example": { "body_text": [["Vishal"]] }
    },
    {
      "type": "BUTTONS",
      "buttons": [
        { "type": "QUICK_REPLY", "text": "keep going" },
        { "type": "QUICK_REPLY", "text": "pause for now" }
      ]
    }
  ]
}
```

**Submit this one last, and separately.** If Meta reads it as marketing, that
answer is worth having on its own rather than tangled with the two that carry
the daily traffic. It also answers, in the product rather than in a script, the
question `FOUND_NOT_FIXED.md` parked on 18 Sep: a user who ignores the break
offer is silent forever today, with no path back except writing first. This
template is that path. **It is drafted, not adopted** — that decision is
Vandy's, and it is about what people receive.

## 4. The language question, unresolved

Ted speaks Hinglish to about half his users, and the gate already tracks which
(`_language_preference`). Meta versions a template by language code, one
version per code per template name. Romanised Hinglish is not a code: it is not
`hi`, which is Devanagari, and only one `en` version can exist per name.

Two ways, neither verified against a live submission:

1. **A second template name per Hinglish variant** (`ted_daily_review_hi`),
   both submitted under `en`. Costs double the approvals and doubles every
   future edit.
2. **English only for the knock.** The template reopens the window; everything
   after it is Ted in whichever language that person gets today. A person who
   reads Hinglish reads English.

Option 2 is the recommendation, and it is a recommendation rather than a
decision, because it is the one place where this design makes the product
slightly colder for half the users. Worth trying option 1 for
`ted_daily_review` alone on the test number to see whether Meta objects to
romanised Hindi under `en`.

## 5. What has to change in the code before these are used

Not a template question, but the templates are unusable without it.

Today the cron path calls the model, gets a sentence and hands it to the
adapter. Outside the window, that sentence cannot be sent — so the decision to
use a template has to be made **before the model runs**, not after, or Ted pays
for a reply nobody can receive.

Hermes patch 13 already established the pattern and the reason: cron silence is
decided before the model call. The window check belongs in the same place. That
makes three things the cron path needs that do not exist yet:

- the last inbound timestamp per user, to know if the window is open. The gate
  has it; `ted-window-check.py` reads both sources for the same reason.
- a mapping from cron job to template name and `{{2}}` text, so a reminder can
  be sent without asking the model to write it.
- the send itself, which is the Cloud API adapter from step 2.

**None of it is startable before the developer app exists**, which is the
honest summary of T06: every remaining step is behind one account creation.

## 6. Unverified, on purpose

- Whether Meta approves any of these. Nothing here has been submitted.
- Whether romanised Hinglish passes under `en` (§4).
- Whether a quick-reply tap on a template opens the window the same way a typed
  message does. It should — it is an inbound message from the user — but it is
  the assumption this entire design rests on, and it is the first thing to test
  on the free test number.
- Whether interactive messages are free inside the window, carried over from
  `T06_OFFICIAL_WHATSAPP_PATH.md` §4b and still unverified.

## Sources

- [Template categorization](https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/template-categorization)
- [Utility templates](https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/utility-templates/utility-templates)
- [Template components](https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/components)
