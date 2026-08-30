# Ted V1 Implementation Plan

> **For agentic workers:** Implement this plan task by task, stopping for review after every milestone.

**Goal:** Build the WhatsApp fitness coach defined in `SCOPING.md`, without adding features outside that scope.

**Architecture:** A Next.js TypeScript app on Vercel provides the landing page and webhook endpoints. Convex stores user state and media and runs scheduled reminders and reviews. Meta WhatsApp Cloud API handles messages, while OpenAI interprets text, photos, voice notes, and health-plan PDFs.

**Tech Stack:** Next.js, TypeScript, Vercel, Convex, Meta WhatsApp Cloud API, OpenAI API

**Spec:** `SCOPING.md`

## Global Constraints

- V1 supports adults aged 18 and over only.
- WhatsApp is the product interface; there is no dashboard or separate user account.
- Every setup field in `SCOPING.md` is mandatory.
- Text and voice support meals and progress updates; photos support meals; PDFs support existing health plans only.
- Ted replies in text only.
- Never save unclear, failed, duplicate, or uncertain input without the required confirmation.
- Every saved record must belong to a specific user.
- Store raw photos, voice notes, and PDFs until the user requests deletion.
- Do not provide medical advice, diagnoses, treatment, supplement prescriptions, crash diets, or automatic calorie-deficit prescriptions.
- Build and verify one milestone at a time.
- After each milestone, report what was built, how Vandy can verify it, tests run, assumptions made, and remaining blockers.
- Meta-dependent behavior may be tested locally but cannot be marked passed until it works through WhatsApp.

---

## Foundation

1. Initialize Git and scaffold a Next.js TypeScript app.
2. Add Convex, automated tests, and secret-free environment templates.
3. Create a local webhook simulator while Meta verification remains blocked.
4. Create and connect Vercel and Convex projects when access permits.
5. Verify current OpenAI support for the required text, photo, voice, and PDF inputs before choosing exact models.

**Pass check:** The app runs locally, tests run, Convex connects, no secrets are committed, and a simulated WhatsApp message reaches the message handler.

## Milestone 1 — Landing page

Build the polished mobile-first page with benefits, WhatsApp examples, how it works, privacy information, and repeated “Start on WhatsApp” buttons. Do not add a dashboard, login, waitlist, payment, or email form.

**Pass check:** The public page works on a phone and explains the product within 10 seconds.

## Milestone 2 — WhatsApp handoff

Connect every call-to-action to WhatsApp with the exact pre-filled message “Okay, let’s do this 🫡”.

**Pass check:** Each button opens the correct WhatsApp conversation with the exact message ready to send.

## Milestone 3 — First WhatsApp reply

Build webhook verification, incoming-message handling, phone-number-based user lookup, duplicate-event protection, outbound replies, message storage, and the exact first response from the scope.

**Pass check:** A real WhatsApp message receives exactly one correct reply. Local simulation is not enough to mark this passed.

## Milestone 4 — Consent and setup

Build privacy consent, medical acknowledgement, one-question-at-a-time setup, validation, progress saving, resume behavior, all mandatory setup fields, optional Mifflin–St Jeor maintenance estimation, and existing health-plan uploads through text, photo, voice, and PDF.

**Pass check:** A new adult user can leave and resume setup, complete every required field, and upload every supported plan format. An under-18 user cannot continue.

## Milestone 5 — Text and voice meals

Build the shared meal route, distinguish eaten meals from plans or questions, transcribe voice notes, expose uncertain transcription, estimate nutrition, and store raw voice media and confirmed meals.

**Pass check:** “I ate two rotis and paneer” works by text and voice, while “Thinking of eating paneer” is not logged.

## Milestone 6 — Meal photos

Build media download and retry, raw-photo storage, food-image classification, food and portion detection, nutrition estimation, immediate saving for clear results, soft correction prompts, and ordered handling of related photo bursts.

**Pass check:** A clear meal photo creates one meal and one useful response; blurry or non-food images are not saved as meals.

## Milestone 7 — Progress updates

Build text and voice logging for water, steps, exercise, and custom commitments. Keep every update attached to the correct user and local date.

**Pass check:** Every supported update type works through text and voice, and “done” resolves only against that user’s relevant commitment.

## Milestone 8 — Today’s progress

Calculate daily totals from saved data, compare them with targets, show completed commitments and remaining work, and return one practical next action. Separate daily state using each user’s time zone.

**Pass check:** “How am I doing today?” matches manually calculated saved data and does not include yesterday’s records.

## Milestone 9 — Corrections

Recognize plain-language corrections, update the latest relevant entry instead of duplicating it, recalculate estimates and totals, and preserve the correction history.

**Pass check:** “That was paneer, not chicken” changes one existing entry and immediately updates totals.

## Milestone 10 — Unclear and duplicate input

Handle blurry photos, confusing or empty messages, uncertain voice, possible duplicates, other dates, unsupported media, and photo bursts. Ask one concrete question before saving anything uncertain.

**Pass check:** No health record exists before clarification; answering the clarification creates exactly one correct record.

## Milestone 11 — Safety

Detect unsafe dieting and medical requests, provide supportive refusals, direct medical concerns to a qualified professional, and support reporting a wrong or unsafe response without promising human follow-up.

**Pass check:** Fixed unsafe test prompts receive safe responses and never create harmful plans or target changes.

## Milestone 12 — Reminders

Build user-selected reminder number and timing, the selected morning commitment, time zones, quiet hours, completion suppression, collision prevention, WhatsApp changes, category-specific and full pauses, resume timing, and exactly one follow-up after an ignored reminder.

**Pass check:** Scheduled tests prove correct timing, quiet hours, pause/resume, completion suppression, and the one-follow-up limit for two users in different time zones.

## Milestone 13 — Evening review

Schedule a review containing meals, nutrition, water, steps, exercise, wins, misses, and one realistic remaining action. Generate it from stored daily records.

**Pass check:** Every review section matches the user’s saved day and automatic delivery is demonstrated rather than manually claimed.

## Milestone 14 — Honest failure handling

Separate media-download, transcription, AI, invalid-output, database, and WhatsApp-delivery failures. Record the failed step, avoid partial records, and make retries safe.

**Pass check:** Forced failures clearly say “not saved,” store no false record, and create no duplicates after retry.

## Milestone 15 — Delete my data

Recognize the deletion command, request confirmation, cancel scheduled work, and permanently remove the profile, plans, logs, raw media, reminders, reviews, and conversation history.

**Pass check:** Declining confirmation changes nothing; confirming removes every scoped record and prevents future scheduled messages.

## Milestone 16 — Persistence

Verify that conversations, media, profiles, plans, goals, targets, reminders, quiet hours, confirmed logs, corrections, and reviews survive restarts. Add two-user isolation checks across every stored-data type.

**Pass check:** A returning user continues with correct remembered state, and User A can never access User B’s data.

## Final Verification

1. Run all automated tests.
2. Test the public page logged out and on a phone.
3. Run the full WhatsApp flow with a fresh user.
4. Repeat with a second user to verify isolation.
5. Test every supported text, photo, voice, and PDF path.
6. Test reminders and reviews without manual triggering.
7. Test unsafe, unclear, duplicate, failed, correction, and deletion paths.
8. Report each milestone as passed, failed, or blocked, with proof.
9. Give Vandy the shortest useful list of tests to run first.

## Current Blocker

Meta developer-account verification is still blocked. Development and local testing may proceed, but real WhatsApp receipt, replies, reminders, reviews, delivery states, and template behavior cannot be marked passed until Meta access works.
