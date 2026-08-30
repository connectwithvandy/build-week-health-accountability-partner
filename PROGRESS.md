# Ted — WhatsApp Fitness Coach V1 Progress

Last updated: Sun 30 Aug 2026, Asia/Kolkata

## What we decided

- The product name is Ted.
- The pre-filled user message is “Okay, let’s do this 🫡”.
- Ted's first reply is “Chalo, scene set karte hain 😌 First things first: what are we trying to fix?”
- Use Meta WhatsApp Cloud API directly.
- Do not use Twilio.
- Do not build a Telegram fallback.
- Use Vandy's spare WhatsApp Business number as the eventual Cloud API sender.
- The number does not need to remain usable in the WhatsApp Business phone app.
- Evidence must say whether a Meta test number or the real sender number produced it. Do not call test-number output production-sender output.
- Use Convex for stored state and scheduling and Vercel for the web application; both accounts are ready, but projects have not been created.
- Codex builds the application. For now, the live product uses the OpenAI API for interpretation and transcription.
- Voice notes work for health plans, meals and all progress updates. PDFs work only for health plans.
- Store raw photos, voice notes and PDFs until the user deletes their data.
- Use Mifflin–St Jeor for optional maintenance-calorie estimates.
- Every scoped setup field is mandatory.
- Sleep tracking is not part of V1; revisit it with a future Apple Health connection.

## Documentation updated

`IDEA_SCOPE.md` now records:

- Meta Cloud API as the WhatsApp dependency.
- Honest rubric evidence for Meta's test number.
- The five-recipient test-number cap: Ankita, Richa, Khushboo, Arpit and Vandy.
- Reminder and daily-review template approval as the main WhatsApp risk.
- A Sun 30 Aug decision-log entry dropping Twilio and Telegram.

## Meta setup status

- Vandy signed in to Meta for Developers.
- Meta required developer-account verification.
- SMS verification did not deliver a code and the flow became blocked.
- Meta offered credit-card verification, but we paused before completing it.
- Do not remove the spare number from WhatsApp Business until the Meta developer account is verified and the Cloud API app is ready to add the number.

## Code status

- No application code exists yet.
- The repository currently contains the scope and progress documents only.
- No webhook has been created or tested.
- No Meta credentials have been generated or stored.

## Product we are building

A WhatsApp fitness coach where a user sends a meal or activity update, the app understands and saves it, replies against that person's targets, sends one reminder and produces a daily review.

First working path:

`WhatsApp message → Meta webhook → understand typed input → save in Convex → reply on WhatsApp`

Text is implemented first to establish the shared path. Photo, voice and PDF health-plan support remain required V1 scope and are added after the typed path works end to end.

## Exact next step

Complete Meta developer-account verification by SMS or credit card. Then create a Meta Business app, add the WhatsApp product and obtain the test Phone Number ID, WhatsApp Business Account ID and temporary access token. Never save access tokens or verification codes in this file or in Git.
