# Product Build Guardrails

## Known product and engineering pitfalls to eliminate from the beginning

### Purpose

This is a deliberately thought-through product. Based on hands-on experience using a very similar product recently, we already know several behaviours that create friction, unreliable data, noisy coaching or poor user experience.

This document captures those learnings so we can eliminate known mistakes from the beginning rather than rediscovering them during the build. Treat it as a set of product and engineering guardrails alongside `IDEA_SCOPE.md`.

## 1. Product behaviours worth preserving

### Never turn uncertainty into fake data

If a meal cannot be interpreted reliably, do not save zero calories, blank items or guessed certainty. Ask one concrete clarification question. A silent zero corrupts today's totals and every downstream summary.

### Treat corrections as first-class behaviour

Users naturally say things like “2 rotis not 1”, “big bowl” or “it also had soya”. The product should update the recent meal rather than create a second meal or ignore the correction.

### Distinguish eating from planning

“I had paneer for lunch” is a log. “Thinking paneer for lunch” is not. Questions, cravings, future plans, targets and meal reports must not share a loose keyword route.

### Echo uncertain voice understanding

Voice transcription can mishear Hinglish, food names or noisy audio. When confidence is uncertain, show what was heard before committing important state.

### One user action should feel like one interaction

WhatsApp may deliver multiple photos separately. Do not respond to every image independently if they belong to one burst. Queue and process them coherently, then send one useful response.

### Daily state must actually be daily

Yesterday's meal totals or conversational assumptions must not bleed into today. Persistent profile memory and day-scoped activity state are different things.

### Personal targets are data, not prompt text

Goals, calorie and protein targets, timezone, reminder settings and other user-specific numbers should come from the user's stored profile. Do not bake one person's numbers into the coach persona.

### Remember durable preferences, not everything

Useful long-term facts include routines, food preferences, goals and stable coaching preferences. Passing mood, one-off events and every chat turn should not automatically become permanent memory.

## 2. Reminder and accountability lessons

### More reminders does not mean more accountability

The similar product became noisy when meal-photo prompts and follow-ups accumulated. Default to fewer, useful nudges.

### Respect completion

If the user has already completed or logged the action, suppress the corresponding reminder whenever possible.

### Let users mute specific nudges

“Pause water reminders” should not silence the entire coach. Reminder categories need independent state.

### Support a temporary quiet mode

A user may want the coach silent for a few days while still being able to message it. Proactive messages and reactive chat are separate controls.

### Avoid reminder collisions

Multiple scheduled messages landing together feels robotic and spammy. Scheduling should include spacing and deduplication.

### Context should change tone

If a user explicitly says they are unwell, injured or exhausted, generic hype can become inappropriate. The product should be capable of softening or suppressing a nudge without pretending to diagnose or treat anything.

## 3. Media ingestion lessons

### Do not assume a photo is food

The personal prototype encountered meal photos, body-stat screenshots and diet-plan images. If the public product supports more than food later, classify before processing. For v1, unsupported image types should be handled explicitly.

### Media delivery can be delayed or fail

Messaging providers may fire the webhook before media is immediately retrievable. Downloads need retry and error handling.

### Process photo bursts in order

Parallel processing created rate-limit pressure and state races in the similar product. Serialize related images per user.

### Separate failure stages

Download failure, transcription failure, interpretation failure and save failure should not all produce the same generic message. Distinct failures make both user recovery and debugging much easier.

### Never let background failures disappear

Photo, voice and scheduled work often runs outside the request path. Exceptions must be recorded in the run trace or log rather than swallowed.

## 4. Multi-user rules for the new product

- Every persisted record must belong to an explicit user ID.
- Never use a builder-wide phone number, timezone, target or reminder setting as the implicit default for a real user.
- Test two users before inviting anyone: User A's meals, targets, reminders and corrections must never appear for User B.
- Conversation and session state must also be keyed by user, not only database rows.
- A short reply such as “done” must resolve only against that user's latest open reminder.
- Scheduled jobs must compute the correct local time from each user's stored timezone.
- Changing one user's targets or reminder preferences must not alter global configuration.

## 5. AI and prompting rules

### Use deterministic code for facts; use the model for interpretation and voice

Running totals, stored targets, timestamps, completion state and other known numbers should be calculated from persisted data. Do not ask the conversational model to reconstruct them from chat.

### Validate structured outputs

If an extraction response is missing required fields or cannot be parsed, treat it as a failed interpretation—not a valid zero-value result.

### Keep routing narrow

Meal logging, correction, onboarding, reminder completion and ordinary chat are materially different actions. Route them explicitly rather than letting one giant prompt decide and mutate everything.

### Expose uncertainty

For vague portions, unclear dishes or ambiguous commands, say what is uncertain and ask one question.

### Keep personal facts out of the persona

The tone prompt can define how the coach speaks. User targets, schedules, body data and preferences belong in per-user state injected at runtime.

## 6. Messaging and provider realities

- Do not assume outbound API acceptance means the WhatsApp message was delivered. Store provider delivery status where available.
- Do not assume proactive WhatsApp messages can always be sent as free-form text. Template and session-window constraints must be treated as product constraints and tested early.
- Do not manually trigger a scheduled reminder or review and then present it as autonomous output.
- Retries must be idempotent: a webhook retry must not double-log a meal or send duplicate replies.
- Acknowledge slow media quickly, then process asynchronously where appropriate.

## 7. Guiding principle

> Build the reliable accountability loop before the impressive coach.

The product wins when a real user can tell the coach what happened, the coach records the right thing for the right person, follows up at the right moment without becoming noisy, and closes the day using real remembered state. Any feature that weakens that loop belongs in the parking lot.
