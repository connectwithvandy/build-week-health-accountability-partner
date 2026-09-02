# IDEA_SCOPE.md

> This document is the control plane for the build. You wrote it; your coding agent reads it before every session. If a proposed change does not improve the active milestone's acceptance test or the rubric strategy, it goes in the parking lot.

Read and apply `PRODUCT_BUILD_GUARDRAILS.md` alongside this document before making product or engineering decisions.

## 0. scope status

| Field | Value |
|---|---|
| Event | GrowthX Build Week · Season 03 |
| Builder | Vandy, solo, plus Codex |
| Build starts | Sat 29 Aug 2026, 11:00 AM IST |
| Submission deadline | Sat 5 Sep 2026, 11:00 AM IST |
| Demo | Sat 5 Sep 2026, 3:00 PM IST |
| Current build state | See `PROGRESS.md`, the single source of truth for implemented, local, live, verified, blocked, and next-step status |
| Last updated | Sun 30 Aug 2026 |

### status language

- **Specified:** described here but not implemented.
- **Implemented:** code exists.
- **Working locally:** the golden path runs in the development environment.
- **Live:** the golden path runs at the Vercel URL, logged out, on a phone.
- **Verified:** acceptance tests have passed on the live URL.
- **Demo-ready:** reset, fallback, timing and the numbers screenshot have been rehearsed.

## 1. idea lock

| Decision | Locked answer |
|---|---|
| Product name | Ted |
| One-sentence product | Ted is a personal health accountability partner on WhatsApp that learns each user's goals, logs meals and progress from supported inputs, sends selected reminders and gives a daily progress review. |
| The one person | Vandy, 33, a sales professional working 9–10 hour desk-based days who already tries to exercise, eat well and follow a health routine. |
| The one moment | Around dinner, when Vandy realizes that steps, protein or another commitment slipped and there is little time left to recover the day. |
| Current workaround | Separate alarms, calorie apps, notes and repeated manual checking of a diet plan. |
| Core action (user does X → gets Y) | User sets daily fitness commitments in WhatsApp → coach remembers them, nudges at useful times, accepts progress updates and closes the day with a review. |
| The one outcome the product must deliver | At day's end, the user knows what they logged, what they completed or missed and the single next improvement. |
| Hard input or hard case | A mixed-language voice note or unclear photo of an Indian meal. |
| Primary track | AI Agent as a Service |
| Riskiest assumption | An AI coach that remembers and proactively follows up will actually improve users’ follow-through. If users ignore the nudges or do not change what they do next, the product becomes just another tracker. |
| The 30-minute no-code test for it | Run a compressed-day conversation: record one real commitment, send a timely manual nudge and one follow-up, then observe whether the person completes or meaningfully reschedules something they otherwise would have missed. |
| First users (names, where they are) | Ankita, Richa, Khushboo and Arpit, reached by direct WhatsApp message on Mon 31 Aug. Vandy uses the ordinary WhatsApp account paired to Hermes. |
| Tuesday channel (where those users already gather) | Elfina Health community if posting is permitted; otherwise direct WhatsApp invitations. |
| Personal artifact a user would screenshot | Daily review: meals logged, estimated totals, commitments completed and one realistic action still possible today. |
| Saturday numbers I expect to report | 3+ real users; 9+ real inputs; all three input types used; 3+ automatic reminders delivered; 3+ daily reviews generated. |
| Library lineage (card or proven build, if any) | No library card. Public rebuild informed by Vandy's private Coachy; the Vercel/Convex multi-user product and its public workflow are built during Build Week. |

### product discovery decisions — 30 Aug 2026

#### specific user and frustration

- **User:** Vandy, 33, works in sales for 9–10 hours a day in a mostly desk-based role.
- **Existing routine:** Gym or walking about three days a week, a step goal, daily water, protein intake and meal awareness.
- **Frustrating moment:** Around dinner, Vandy realizes that one or more parts of the routine have slipped—steps are short, water was missed, or meals lacked protein. There is little time left to recover, so the day ends with guilt.
- **Current workaround:** Several fitness apps, alarms and self-messages. Alarms get snoozed, app notifications get disabled and self-messages disappear among unrelated WhatsApp notes. After one or two weeks, tracking usually stops.

#### core product decision

> Vandy sets daily fitness commitments in WhatsApp → the coach remembers them, nudges Vandy at useful times, accepts completion and meal updates, and closes the day with an accountable review.

The product is intentionally a **whole-routine accountability partner**, not a single-purpose water or calorie tracker. The first version must connect steps, water, workouts, custom commitments and meals in one continuous conversation.

#### website entry point

The product also needs a public landing page for discovery and user acquisition. Its role is deliberately narrow:

> Website attracts and explains → WhatsApp onboards and coaches.

The landing page must explain the product, show a realistic example conversation and move an interested user into WhatsApp through a clear **Start on WhatsApp** action. Personal fitness onboarding remains inside WhatsApp so users do not enter the same information twice.

##### v1 public pages and states

1. **Landing page:** product promise, benefits, supported inputs, how it works, example WhatsApp conversation, privacy and safety information, and repeated Start on WhatsApp actions.
2. **WhatsApp handoff:** opens WhatsApp with the prepared first message—“Okay Ted, let's do this 💪”.
3. **Privacy policy:** collected data, raw-media retention, service providers, deletion requests and health-data boundaries.

##### website data and measurement

Measure the acquisition path:

> Visited → tapped WhatsApp → sent first message → completed onboarding → logged first update.

Internal acquisition measurement may record landing-page visits, traffic source and WhatsApp-button clicks. This is build evidence, not a user-facing Ted feature. A page visit is not consent to process fitness information; explicit consent is still required inside WhatsApp before collecting goals, meals or health routines.

##### website v1 boundary

Essential: a responsive landing page, clear explanation, realistic conversation example, WhatsApp handoff and privacy information.

Later: website login, a personal web dashboard, blog, payments, complex animation, unverified testimonials and advanced analytics. The website must not become a second version of the WhatsApp product.

#### onboarding choices

- Keep beta onboarding to three questions: the one thing the user wants to change, what Ted should call them, and their daily check-in time plus city.
- Open with the name question so the exchange feels conversational. Put the storage, medical boundary, and deletion disclosure in the following message with the goal question. Answering after that disclosure records beta consent.
- Ask for age, height, weight, diet plan, calorie target, step, water, workout, quiet-hours, and custom-commitment details only when they become relevant during coaching.
- Ask the 18+ question immediately before first discussing or calculating a calorie target. Invite only known adults to the beta.
- If the user has no calorie target when nutrition coaching becomes relevant, offer a Mifflin–St Jeor maintenance-calorie estimate and clearly label it as an estimate, not a prescribed diet.

#### realistic failure cases

1. The coach ignores current context, such as “no water reminder today,” and sends the reminder anyway.
2. It misreads a meal or quantity and records it without asking for confirmation.
3. It sends a reminder at the wrong time or mixes progress from different days.

Current instructions, pauses, corrections and reminder changes must override previously saved routine settings without erasing the underlying routine accidentally.

#### scope buckets

##### must have

- Three-question WhatsApp beta onboarding for goal, name, and check-in time plus city.
- Unified tracking for steps, water, workouts, custom commitments and meals.
- Nutrition onboarding through a health plan supplied by text, photo, voice note or PDF, a user-provided calorie target, or a Mifflin–St Jeor maintenance estimate. PDFs are only for health plans.
- Meal and progress logging through text or voice notes, plus meal logging through photos.
- Meal clarification when food or quantity is uncertain.
- Estimated calories and macros, plus comparison with the user's diet plan or targets.
- Multiple reminders across the saved routine—for example water, steps, workouts and custom commitments—plus exactly one follow-up after an ignored reminder.
- Let the user choose reminder quantity and times, select the single morning commitment, change reminders through WhatsApp, respect quiet hours, and pause or resume reminders until a stated time or date.
- Replies including done, later, skip, pause and reschedule.
- Persistent memory for routine, preferences, corrections, daily progress and temporary instructions.
- A personalized daily review covering meals, nutrition estimates, water, steps, exercise, wins, missed commitments and one realistic action still possible today.
- Full conversation and raw-media retention until the user requests deletion.
- A confirmed “delete my data” command that removes the profile, plans, logs, raw media, reminders, reviews and conversation history.
- Confirmation before saving a duplicate or an update for another date.
- Direct progress requests through “How am I doing today?”
- Wrong or unsafe response reporting with a safe fallback and no promise of human follow-up.
- Safety boundaries: no diagnosis, medical advice, supplement prescription or automatic calorie-deficit prescription.

##### nice to have

- Weekly progress reports.
- Streaks and consistency tracking.
- Progress trends over time.
- Challenge or goal mode, such as a no-sugar month or workout-frequency goal.
- Coaching informed by previous behaviour.
- Repeated or escalating reminders for the same commitment.
- Sleep tracking through a future Apple Health connection.

##### not this week

- Coach-generated voice-note replies.
- Accountability voice calls. A future version may call after roughly four or five unanswered check-ins.
- Fully adaptive motivation that learns which coaching style works for each user.
- Apple Health and other wearable integrations.
- Oura integration.
- Medical advice, diagnoses, bloodwork interpretation or supplement recommendations.
- Automatic calorie-deficit prescriptions.

### why this idea

#### the pain I feel

Vandy follows a health routine while managing SDR teams across APAC and EMEA. Meals, water, gym, steps and follow-ups compete with a demanding workday. She already built a private coach because alarms and separate trackers did not complete the job. Ankita, Richa, Khushboo and Arpit share the fitness follow-through problem and are reachable this week.

#### decisive proof

A stranger completes onboarding in WhatsApp, sends a fresh meal as text, photo or voice, sees it interpreted against their own targets, receives an automatic reminder and later receives a daily review. At the demo, a fresh input and the resulting run are shown live, followed by Convex records and a real timestamped messaging thread.

## 2. user and job

### user

- Who (name, age, situation): Vandy as the archetype; 33, busy SaaS sales manager with a demanding desk schedule.
- Context: Already has fitness intentions or a plan but execution is fragmented across the day.
- Frequency: Daily.
- Existing behaviour: Uses reminders, WhatsApp, notes and separate health or calorie tools.
- Existing cost, delay, risk or frustration: Missed actions, incomplete tracking, repeated mental load and guilt-driven restarts.

### job to be done

> When work disrupts my health routine, I need one coach to remember my meals and commitments and follow up at useful times, so that I can recover before the day ends instead of restarting tomorrow with guilt.

### definition of completion

The job is complete only when:

1. A user input is understood or the coach asks for clarification; failed estimates are never recorded as zero.
2. The activity is saved against the correct user and reflected in the running day.
3. A scheduled follow-up and daily review reach the user's real messaging thread without Vandy triggering them.

## 3. product contract

### golden path

1. User opens WhatsApp and receives one short message explaining storage, the medical boundary, and the deletion command, followed immediately by the goal question.
2. The user's answer records beta consent. Ted asks only their name and daily check-in time plus city before starting.
3. Ted gathers other profile and target details later, when each detail becomes useful to the current conversation.
4. User logs a meal by text, photo or voice, or sends a progress update by text or voice.
5. Coach interprets the update, asks one question when uncertain, saves the confirmed result and replies against the user's plan or targets.
6. Coach sends the saved reminders and an end-of-day review automatically.

### inputs

| Input | Format/source | Hard characteristics | Validation |
|---|---|---|---|
| Onboarding answers | WhatsApp text | Informal dates, units and timezones | Confirm parsed summary before activation |
| Meal text | WhatsApp text | Indian foods, mixed language, vague portions | Show interpreted items and allow correction |
| Meal photo | WhatsApp image | Multiple dishes, unclear scale, poor light | Ask for dish or portion clarification if confidence is low |
| Meal voice note | WhatsApp audio | Hinglish, noise, food names | Echo transcript before saving when uncertain |
| Health plan | WhatsApp text, image, audio or PDF | Different layouts, units and levels of detail | Extract the plan and retain the original media; PDFs are not accepted for daily updates |
| Progress update | WhatsApp text or audio | Short replies such as “done” or “later” | Resolve against latest open reminder only |

### outputs and state changes

| Output/state change | Consumer | Required format | Proof of completion |
|---|---|---|---|
| Confirmed meal record | User and daily review | Items, estimated calories/macros, timestamp | Convex row plus WhatsApp reply |
| Reminder delivery | User | Short message at chosen time | Provider delivery record and run trace |
| Daily review | User | Meals, nutrition, water, steps, exercise, wins, misses and one action still possible today | Timestamped real message |
| Run trace | Builder/reviewer | Ordered steps, status, time, cost and error | Read-only dashboard URL |

### what the product must remember

- within one session: current onboarding question, recent meal awaiting correction and latest open reminders.
- across sessions (Convex tables and media storage): full conversation and raw media, user profile, uploaded plans, goals, targets, reminders, quiet hours, confirmed logs, corrections, daily reviews and internal run traces.
- what it must deliberately forget: secrets and unsupported medical conclusions. User data and raw media remain until the user confirms “delete my data.”

### human review boundary

- What can be automated: onboarding routing, transcription, meal extraction, saving confirmed logs, reminders and daily review.
- What requires confirmation: unclear food/quantity, changed targets and deletion of an account.
- What must be escalated: symptoms, diagnoses, bloodwork interpretation, supplement prescriptions, eating-disorder signals and emergencies.
- How uncertainty is exposed: plain statement of what is uncertain plus one concrete clarification question.

## 4. what makes it different

### the obvious version

A calorie chatbot that estimates a meal and returns numbers.

### the non-obvious choice

One continuous coach connects logging, reminders and the daily review. It uses the user's own targets and schedule, remembers corrections and stays quiet when it has nothing useful to say.

### the moment they screenshot

The daily review shows meals logged, estimated totals, completed commitments and one realistic action still possible today. It is personal evidence, not a generic motivational quote.

### ideas deliberately rejected

| Rejected mechanic | Reason |
|---|---|
| Automatic calorie deficit or target-weight prescription | Avoidable health and trust risk |
| Bloodwork and supplement advice | Medical scope and sensitive-data risk |
| Wearable/Apple Health/Oura sync | Integration work does not protect the core flow |
| Voice calls | Telephony risk; voice notes are sufficient for v1 |

## 5. dependencies

### verified capability matrix

| Required capability | Product/API/model | Exact endpoint/access | Limits | Verified how |
|---|---|---|---|---|
| Live web product | Vercel | Project connected to public GitHub repo | Hobby functions have duration and usage limits | Official Vercel docs checked 29 Aug 2026; deploy still unverified |
| Database and durable scheduling | Convex | Tables, actions, scheduled functions and cron | Scheduled jobs and function limits apply | Account ready; project creation and end-to-end access unverified |
| WhatsApp send/receive | Hermes | Local process paired by QR code to an ordinary WhatsApp account | The WhatsApp worker must run on the same machine as Hermes; QR session persistence, reconnect behavior and the installed local interface must be tested | End-to-end delivery unverified; verify in M0 |
| Text, image, voice and PDF understanding | OpenAI API for now | Responses request and speech transcription | Exact model names, price, rate and file limits must be verified before implementation | Provider chosen; account access and hard-input test remain unverified |

### unsupported assumptions

- Hermes can send into real WhatsApp threads after QR pairing. Evidence must show the paired ordinary account and a real end-to-end exchange.
- Hermes session persistence, reconnect behavior and scheduled outbound messages must be tested early.
- Precise high-frequency Vercel cron is not assumed; use Convex scheduling.
- Medical advice and exact nutrition accuracy are unsupported. Raw-media storage until user-requested deletion is required V1 behavior.

### secrets and access

Store provider keys in local or hosted environment variables as appropriate. Never put keys, phone numbers, tokens or Hermes session data in this document or the repository.

## 6. rubric strategy

### primary track

| Decision | Answer |
|---|---|
| Primary track | AI Agent as a Service |
| Why this track fits the idea and my advantage | Vandy has lived coaching experience, four reachable users and a product whose value is an unattended task reaching a real messaging surface. |
| The one thing the track needs | A real coaching task completed unattended in a real person's WhatsApp thread through the QR-paired Hermes bridge. |

### the track's rows

| Row | Weight | Max base | Current level | Target level | Target points (L−1)×weight | Observable proof | Work required | Milestone |
|---|---:|---:|---|---|---:|---|---|---|
| Working product shipping real output | 20x | 80 | L1: no new live product | L4: real output on a real surface with limited babysitting | 60 | Timestamped real WhatsApp threads for fresh inputs, reminders and reviews through the paired account | Complete golden path through Hermes | M1–M4 |
| Agent org structure | 5x | 20 | L1: not implemented | L2: 2–3 roles with fixed handoffs | 5 | Trace names intake, interpreter and coach steps | Fixed routing only; no dynamic manager | M1 |
| Observability | 7x | 28 | L1: no new run records | L3: open a run and see every step | 14 | Read-only run page and Convex rows | Store step, status, duration, estimated cost and error | M1–M3 |
| Evaluation and iteration | 5x | 20 | L1: no evals | L3: named test set run manually | 10 | Results for 3 text, 3 photo and 3 voice cases | Save expected outcome and pass/fail | M1–M4 |
| Agent handoffs and memory | 2x | 8 | L1: no new memory | L4: persistent memory across tasks | 6 | Later reminder/review correctly uses earlier targets and logs | Convex profile and daily state | M1 |
| Cost and latency per task | 1x | 4 | L1: not measured | L4 if both 1–5 min and $0.10–$0.50 | 3 | Separate timing/cost fields for each run | Measure; do not claim if unknown | M1–M4 |
| Management UI | 1x | 4 | L1: none | L3: functional UI a PM can use with docs | 2 | Reviewer opens users/runs without editing | Small read-only dashboard | M3 |
| **AI Agent as a Service total** | | **164** | | | **100 target** | | | |

### bonus-eligible rows from the other tracks

| Source track | Row | Bonus weight | Will I claim it? | Proof |
|---|---|---:|---|---|
| Revenue | Signups | 10x | Yes, only if first use is completed | Convex account plus first-use event |
| Revenue | Live product quality | 4x | Yes | Stranger completes onboarding and one input on phone |
| Virality | Signups | 12.5x | No separate claim unless the evidence rules allow it without reuse | Separate verified count required |

### where the points are

Build first for working product shipping real output (20x), then observability (7x). Bonus work is accepted only when it comes from the same required product work without weakening these rows.

### competence floor

Fixed agent roles, a manual eval set, persistent memory, measured latency/cost and a functional read-only UI must work but will not receive polish before real output does.

### rubric traps

A “multi-agent” label on one prompt, simulated output called real WhatsApp output, a dashboard without real runs, test accounts counted as signups, the same evidence used for two rows, or L4/L5 claims without screenshots and links.

## 7. gtm plan

### where the users already are

| Channel | Who is there | How I reach them | When |
|---|---|---|---|
| Direct WhatsApp | Ankita, Richa, Khushboo, Arpit | Personal invite and setup link | Mon 31 Aug |
| Elfina Health community | People already discussing health follow-through | Ask permission, then post in Vandy's own words | Tue 1 Sep |
| GrowthX | Builders and potential secondary testers | Shipped update only after core users | Wed–Sat |

### distribution posts, in my own words

- Monday: “I rebuilt the fitness coach I use personally for busy people. Can I watch you set it up and log one real meal? I need honest friction, not compliments.”
- Tuesday: “I know what to do for my health; my workday is what breaks it. I built a WhatsApp coach that remembers your targets, accepts a meal by text/photo/voice and closes the day with you. I am opening a few free test spots.”
- Wednesday to Friday: one concrete change and one verified number each evening.
- Saturday: what shipped, who used it, real completed tasks and the live URL.

### targets, per band of my track's rows

| Row | Floor I will hit | Stretch | How I will know |
|---|---|---|---|
| Real output | L3: working output on test surface | L4: real surface with limited babysitting | Timestamped message threads |
| Observability | L3: inspect one run step by step | L4: trace tree plus token/cost and filters | Read-only dashboard |
| Agent structure | L2 fixed handoffs | L3 manager + specialists, static routing | Stored trace roles |
| Evaluation | L3 named manual eval set | L4 only if automated without delaying output | Versioned result table |
| Memory | L4 persistent across tasks | L4 | Convex records and later correct use |

### analytics setup (do this on Sunday, not Saturday)

- Analytics tool installed on the live URL: Vercel Web Analytics or another tool with read-only access, chosen in M1.
- Read-only access created and the link saved: required by M3.
- Signup or first-use event writes to Convex: required by M1.
- Payment link: none; product is free this week.

### the numbers I will report on Saturday

One line and separate proof for each AI Agent row: completed real tasks, agent roles, inspectable runs, eval results, cross-task memory, median cost/latency and dashboard usability. Also report real users and first-use events without calling test accounts signups.

## 8. the milestone ladder

### M0 — feasibility and setup (Sat 29 Aug, before 2:00 PM; complete immediately if late)

Required: run the 30-minute hard-input test; verify current model/media capability; create a new GitHub repo; scaffold the required Vercel/Convex stack; deploy an empty app.

Acceptance test: the empty app opens publicly, the repo exists and the hard-input test has a written result.

If behind: deploy one empty page and test text plus one photo. If the critical capability fails by 4:00 PM, cut voice first, then photo.

### M1 — one ugly complete flow (Sat 29 Aug evening → Sun 30 Aug)

Required: three-question WhatsApp onboarding, typed meal, check-in, daily review, live Vercel URL and GitHub push. Photo and voice may be tested through Hermes, but neither may delay a real-user test.

Acceptance test: a fresh user answers the three onboarding questions, logs a typed meal, receives a check-in and gets a useful review in the real WhatsApp thread.

If behind: one WhatsApp user, typed meals, two fixed routine reminders and a text daily review; hardcode everything else. Use the Hermes-paired account and label simulated versus real evidence accurately.

### M2 — media completion and first users (Mon 31 Aug, stop building at 5:00 PM)

Required before invitations: add the three-question opener and disclosure to Ted's `SOUL.md`, send the tester invitation, and verify the Hermes session remains connected. Attempt photo and voice in the real thread, but stop building before these delay invitations. That evening, the invited users try the working product and Vandy records one sentence about where each person stops.

Acceptance test: at least three non-builder users answer the opener and send one real update; one sentence per user records the biggest stop, and Hermes remains connected throughout the test.

If behind: one user on screen share using typed meals. Do not delay testing for photo or voice.

### M3 — distribute (Tue 1 Sep, evening)

Required: analytics with read-only access; permitted Elfina post or direct invites; invite count; visitor/first-use counts and screenshots.

Acceptance test: post or direct invites are sent and the day's verified numbers are saved.

If behind: twenty direct messages, no community post.

### M4 — build, user calls, build again (Wed 2 → Fri 4 Sep, evenings)

Each evening: one user conversation, one blocker fixed and deployed, one update with one number, rubric re-scored and one changelog line. Add only the media input that users asked for or fix the failure affecting the most users.

Acceptance test: three deploys with three user-capability changelog lines; real output and inspectable runs still work.

If behind: fix only the blocker stopping the most users. No new features.

### M5 — verify and submit (Fri 4 Sep night → Sat 5 Sep, 11:00 AM)

No new features. Test logged out, on phone and another device; verify persistence, public repo, evidence screenshots, read-only access, honest self-score, two demo rehearsals and submission before 11:00 AM.

If behind: submit the smallest verified live flow with honest numbers; hide broken inputs.

### M6 — demo (Sat 5 Sep, 3:00 PM)

Show what shipped and reproduce the numbers live. Do not pitch future features.

## 9. demo contract (Saturday 3:00 PM)

### one-sentence setup

Busy professionals know their fitness plan; this coach turns daily WhatsApp messages into remembered tracking, timely follow-through and a usable end-of-day review.

### the proof

| Time | What happens | What the reviewer sees | Rubric row it supports |
|---:|---|---|---|
| 0–15s | Name the user and fragmented workaround | One sentence and fresh account | Context only |
| 15–60s | Send a fresh supported meal input | Interpretation, saved state and reply | Real output |
| 60–90s | Open real run and message evidence | Convex records, trace and real threads | Real output, observability, memory |
| 90–120s | Show failed input added to eval set and fix | Before/after result | Evaluation and iteration |

### live input

A fresh text or clear Indian meal photo not used in development.

### fallback input

A previously verified typed meal with a reset test account.

### the number I lead with

Number of real coaching tasks completed on real user messaging threads.

### claims I can prove

- Real users completed the shown tasks.
- The exact steps, time and state are visible.
- The daily review used persisted user data.

### claims I must not make

- Medical or exact nutrition accuracy.
- Real WhatsApp output when only the local simulator was used.
- Autonomous completion for any run Vandy manually triggered or approved.

## 10. test plan

### golden cases

| Case | Why representative | Expected final output | Status |
|---|---|---|---|
| Typed “dal rice and paneer” | Common informal Indian meal | Clarified or saved items and totals | Specified |
| Clear thali photo | Multi-item visual input | Plausible items; clarification for portion uncertainty | Specified |
| Hinglish voice meal | Real user behaviour | Transcript echoed when uncertain, then saved | Specified |

### failure cases

| Failure | Expected behaviour | User recovery | Tested? |
|---|---|---|---|
| Ambiguous input | No record written; one question asked | Reply with food/portion | No |
| Unsupported input | Explain supported text/photo/voice | Retry in supported form | No |
| API timeout or failure | Preserve input reference; friendly retry message | Retry once or use text | No |
| Empty result | Never save zero or blank meal | User names the food | No |

## 11. risk register

| Risk | Probability | Damage | Earliest test | Mitigation | Fallback |
|---|---|---|---|---|---|
| Hermes disconnects or loses its QR-paired session | High | Incoming updates and scheduled coaching messages stop | M0 | Expose connection state, test restart and reconnect, and record send failures | Re-pair locally and disclose the interruption |
| Photo/voice delays core | High | No users Monday | M0/M1 | Shared route; feature flags | Hide broken type at Monday 5 PM |
| Cross-user data leak | Medium | Severe privacy harm | M1 | User ID on every record; two-account tests | Disable invites |
| Unsafe advice | Medium | Trust/health harm | M1 | No diagnosis/prescription; fixed boundaries | Tracking-only responses |
| Free model rate limits | Medium | Failed messages | M0 | Current limits verified; retry and fallback | Text-only/manual retry |

### pre-mortem

It is Saturday 11:00 AM and the product is not submitted, or is submitted with no users, because:

1. Hermes disconnected or lost its paired session, so proactive messages could not be demonstrated.
2. Photo and voice consumed Monday and user testing was postponed.
3. A multi-user privacy or persistence bug made the product unsafe to invite people into.

The corresponding controls are early Hermes connection and restart testing, the Monday 5:00 PM hard stop and a mandatory two-account isolation test before invitations.

## 12. non-goals

1. Bloodwork, supplement prescriptions, symptoms, diagnoses or medical recommendations.
2. Wearable sync, sleep/step automation, voice calls and weekly reports.
3. Payments, calorie-deficit prescriptions, public social feed or native mobile app.

Any change requires a written decision in section 15.

## 13. parking lot

| Idea | Potential value | Why not now | Revisit after |
|---|---|---|---|
| Diet-plan image upload | Coach against professional plan | Parsing and safety scope | M5/submission |
| Wearable sync | Passive evidence | Integration work | Build Week |
| Weekly report | Retention | Cannot gather a full week before launch | Build Week |
| Repeated or escalating reminders for one missed commitment | Stronger follow-through | Can become noisy or annoying | 3 users retain |
| Voice calls | Strong accountability | Consent, cost and telephony risk | Messaging loop proven |
| Ted mascot | Stronger identity across WhatsApp and the website | Current priority is testing the product with users | V2 |

## 14. decision log

| Time | Decision | Evidence/reason | Scope impact |
|---|---|---|---|
| Sat 29 Aug | Build from scratch; use private Coachy only as reference | Fixed stack and prior-work integrity | New repo and implementation |
| Sat 29 Aug | Primary track is AI Agent as a Service | User wants an active coach, not payments or a viral score | Real output and observability first |
| Sat 29 Aug | WhatsApp first, Telegram fallback | WhatsApp fits user behaviour; Sandbox is test-only | Sunday-afternoon switch point |
| Sat 29 Aug | Attempt text, photo and voice before user test | Builder explicitly wants integrated Coachy experience | Monday 5:00 PM hard cutoff protects user milestone |
| Sun 30 Aug | Use Hermes; drop hosted WhatsApp providers, Twilio and the Telegram fallback | Hermes pairs to an ordinary WhatsApp account by QR code and runs as a separate local process | The WhatsApp worker runs locally beside Hermes; no hosted-provider limits are assumed |
