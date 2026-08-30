# Ted — WhatsApp Fitness Coach V1 Build Plan

This plan implements the complete V1 defined in `SCOPING.md`. No V1 requirement may be moved to a later bucket without first changing the scoping document.

## 1. FEATURE SORT

### MUST HAVE

| Feature | One-line reason |
|---|---|
| Mobile-first landing page | Users need to understand the product before opening WhatsApp. |
| “Start on WhatsApp” button | This is the shortest path from interest to first use. |
| Pre-filled starting message | Removes friction and makes onboarding predictable. |
| Privacy and medical disclaimer consent | Health information should not be stored before clear consent. |
| WhatsApp number as identity | Avoids building a separate login system. |
| Basic conversational setup | The coach needs goals and preferred times to give useful replies. |
| All setup fields mandatory | V1 setup is complete only after every scoped field is provided. |
| Resume abandoned setup | Ted must remember the last unanswered setup question. |
| Custom commitments | Users can track routines written in their own words. |
| Existing health plans by text, photo, voice note, or PDF | Ted must use a user's existing plan; PDFs are limited to this flow. |
| Mifflin–St Jeor maintenance estimate | Gives an optional estimate without prescribing a calorie deficit. |
| Text meal logging | This is the simplest version of the core action. |
| Meal-photo logging | Photo logging is central to making tracking feel easier. |
| Voice-note logging for meals and progress | Voice notes are a supported input for all daily updates. |
| Calories, protein, carbs, fat, and fiber estimates | Users need useful feedback from meal logs. |
| Water, steps, exercise, and commitment logging | The coach must remember more than food. |
| Today’s progress | Proves the coach remembers what has happened today. |
| “How am I doing today?” request | Users can request totals and remaining commitments directly. |
| One practical next action | Turns tracking into coaching. |
| Immediate corrections | AI estimates will sometimes be wrong. |
| Unclear-input handling | The coach must ask before saving uncertain information. |
| Blurry-photo handling | It must not invent meal details from a poor image. |
| Duplicate detection | Prevents accidental double logging. |
| Exact-date confirmation | Updates for another day must be confirmed before saving. |
| Supportive, non-shaming replies | Unsafe or judgmental coaching would break trust. |
| User-chosen reminders | Timely prompts are part of the central product promise. |
| User-selected morning commitment | The morning message contains only the chosen commitment. |
| User-controlled reminder quantity | Reminder volume follows each user's preference. |
| One follow-up after an ignored reminder | Adds accountability without becoming noisy. |
| Quiet hours and reminder pause | Users need control over interruptions. |
| Evening review | Helps users notice what slipped while action is still possible. |
| Medical and extreme-diet safety response | The coach must refuse unsafe guidance. |
| Temporary-failure message | It must never claim that unsaved data was logged. |
| Permanent data deletion command | Users need control over sensitive health information. |
| Saved data across sessions | Memory is a defining product promise. |
| Full conversation and raw-media retention | Conversations, photos, voice notes, and PDFs remain until account deletion. |
| Wrong or unsafe response reporting | Users need a safe fallback without a promise of human escalation. |
| Complete landing-page content | Benefits, chat examples, how it works, privacy information, and repeated buttons are required. |

### PARKED — NOT IN V1

| Feature | One-line reason |
|---|---|
| No additional product features | Anything absent from `SCOPING.md` requires discussion before it is added. |

### NOT THIS WEEK

| Feature | One-line reason |
|---|---|
| Video understanding | It is not needed to validate the core tracking loop. |
| Live-location understanding | It adds privacy and product questions without helping the first test. |
| Intelligent GIF and sticker understanding | A polite text fallback is enough for now. |
| Replies as voice notes | V1 replies with text. |
| Replies as GIFs or stickers | These do not test whether the coaching itself is useful. |
| Voice calls | Explicitly outside V1 and technically much larger. |
| Personalized meal-plan creation | The product tracks an existing plan; it does not prescribe one. |
| Personalized workout-plan creation | The product tracks commitments; it does not design training. |
| Automatic calorie-deficit prescriptions | This crosses the agreed safety boundary. |
| Editing or deleting individual older entries | Immediate correction is enough for the first build. |
| Weekly reports | Daily usage must be proven first. |
| Sleep tracking | Revisit with a future Apple Health connection. |
| Wearable and health-app integrations | Manual WhatsApp updates are the behavior being tested. |
| Social features | They do not support the core personal-coach loop. |
| Payments | Usage should be proven before charging is built. |
| Human-coach escalation | It requires people and an operating process, not only software. |
| Coaching for users under 18 | This needs stronger safety and consent rules. |
| Medical advice or diagnosis | The product is a habit coach, not a medical service. |
| Bloodwork interpretation | This is medical guidance and outside the product boundary. |
| Supplement prescriptions | This is outside the agreed safety boundary. |
| Automatic decisions from unclear media | The coach should ask instead of guessing. |
| Separate dashboard or app | WhatsApp is the product interface being tested. |

## 2. V1 MILESTONES

| # | Milestone | Layer |
|---:|---|---|
| 1 | I can open the landing page on my phone and understand the product in 10 seconds. | Frontend |
| 2 | I can tap “Start on WhatsApp” and see a pre-filled message ready to send. | Frontend / Integration |
| 3 | I can send that message and receive “Chalo, scene set karte hain 😌 First things first: what are we trying to fix?” in WhatsApp. | Backend / Integration |
| 4 | I can accept the privacy and medical disclaimer and complete every required setup field: name, age, height, weight, time zone, goal, meal and nutrition targets, step, water and workout targets, custom commitments, reminder and daily-review times, quiet hours, and the morning commitment. If I leave, setup resumes at the field where I stopped. I can also upload an existing health plan through text, photo, voice note, or PDF. | Backend / Integration |
| 5 | I can send a text or voice-note meal such as “I ate two rotis and paneer,” then see it logged with estimated nutrition. | Backend / Integration |
| 6 | I can send a clear meal photo and receive detected foods plus estimated calories, protein, carbs, fat, and fiber. | Backend / Integration |
| 7 | I can log water, steps, exercise, or a commitment using a text or voice WhatsApp message. | Backend / Integration |
| 8 | I can send another update or ask “How am I doing today?” and see today’s running totals, completed commitments, what remains, and one practical next action. | Backend |
| 9 | I can correct wrong data by saying “That was paneer, not chicken,” and immediately see the revised entry and totals. | Backend |
| 10 | I can send a blurry photo, confusing message, empty message, duplicate update, or update for another date and see the coach ask before saving anything. | Backend / Integration |
| 11 | I can ask for unsafe dieting or medical advice and see a supportive refusal with a suggestion to contact a qualified professional. I can report a wrong or unsafe reply and receive a safe fallback without a promise of human follow-up. | Backend |
| 12 | I can choose the number and timing of reminders, receive only my selected commitment in the morning, change reminders through WhatsApp, pause and resume them, and trigger exactly one follow-up after an ignored reminder while quiet hours are respected. | Backend / Integration |
| 13 | I can trigger my evening review and see today’s meals, nutrition, water, steps, exercise, wins, misses, and one action still possible today. | Backend / Integration |
| 14 | I can simulate an AI or storage failure and see a clear “not saved” message instead of false confirmation. | Backend / Database / Integration |
| 15 | I can message “delete my data,” confirm the request, and verify that my profile, plans, logs, raw media, reminders, reviews, and conversation history are removed. | Backend / Database / Integration |
| 16 | I can log an update, close and reopen the product, message again, and see that my full conversation and media, profile, uploaded plans, goals, targets, reminders, quiet hours, confirmed logs, corrections, and daily reviews survived. | Backend / Database / Integration |

## Build order

The work is split into three builds, but every V1 requirement above remains required:

1. Website and WhatsApp handoff.
2. Text-message coach and saved daily state.
3. Reminders, daily review, supported media, safety, failure handling, and deletion.

Hermes must be running locally and paired by QR code before the real WhatsApp flow can be tested. The public website remains on Vercel; the WhatsApp worker runs on the same machine as Hermes so it can use the local bridge.
