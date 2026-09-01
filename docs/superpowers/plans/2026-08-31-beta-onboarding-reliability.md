# Beta Onboarding Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every invited beta tester receive a fast, clear, user-specific, recognizably Ted onboarding journey.

**Architecture:** Hermes remains the WhatsApp runtime and `~/.hermes/SOUL.md` remains the behavior source. Each fix is verified in a fresh real WhatsApp thread before moving to the next fix; local Hermes logs provide delivery timing and user-isolation evidence.

**Tech Stack:** Hermes WhatsApp gateway, Markdown behavior instructions, SQLite session store, shell-based log checks.

**Spec:** `SCOPING.md`

## Global Constraints

- Ask one question at a time.
- Never state or save a user fact that the user did not provide.
- Never expose secrets, phone numbers, session data, or internal Hermes status.
- Keep Ted's WhatsApp replies short, warm, practical, and free of shame or medical advice.
- Update `PROGRESS.md` after each verified fix.

---

### Task 1: First-message reliability

**Files:**
- Verify: `/Users/vandana.agarwal/.hermes/.env`
- Inspect: `/Users/vandana.agarwal/.hermes/logs/gateway.log`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: a first inbound WhatsApp message from a number not previously used with Ted.
- Produces: a gateway log pair showing `inbound message` followed by `response ready` in no more than 10 seconds.

- [x] **Step 1: Allow invited beta users without pre-registering each number**

Set `WHATSAPP_ALLOWED_USERS=*` on Ted's dedicated beta number and restart Hermes.

- [x] **Step 2: Verify two fresh external threads**

Ankita: first inbound at `20:25:20.439`, response ready at `20:25:22.809` (2.4 seconds).

Khusha: first processed inbound at `20:27:12.795`, response ready at `20:27:15.096` (2.3 seconds).

- [ ] **Step 3: Recheck before the next invitation batch**

Run:

```bash
hermes gateway status
tail -n 120 ~/.hermes/logs/gateway.log
```

Expected: WhatsApp is connected, and a test message from another phone produces `response ready` within 10 seconds.

### Task 2: One question per message

**Files:**
- Modify: `/Users/vandana.agarwal/.hermes/SOUL.md`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: name, goal, check-in time, and city as separate user turns.
- Produces: exactly one onboarding question per Ted reply.

- [x] **Step 1: Replace the combined time-and-city prompt**

Use separate prompts: `What time should I check in each day?` followed by `Which city are you in so I use the right local time?`.

- [x] **Step 2: Add mismatch handling**

If the reply does not answer the current question, react to its useful content and ask only the still-missing question; do not advance the onboarding stage.

- [ ] **Step 3: Verify in a fresh thread**

Answer the time question with `Workout`. Expected: Ted treats workout as the desired habit and asks only for the check-in time; it does not mention a city.

### Task 3: No invented or cross-user facts

**Files:**
- Modify: `/Users/vandana.agarwal/.hermes/SOUL.md`
- Inspect: `/Users/vandana.agarwal/.hermes/state.db`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: facts stated in the current WhatsApp user's own thread.
- Produces: replies containing only that user's stated facts or clearly labeled generic examples.

- [x] **Step 1: Add the hard boundary**

State that Ted must never infer a city, target, meal, completion, or schedule from another user, memory, example, or builder profile.

- [x] **Step 2: Label examples**

Any sample review starts with `Example only` and uses placeholders or facts the current user supplied.

- [ ] **Step 3: Run a two-user isolation test**

User A supplies `Jaipur`; User B supplies no city. Expected: Jaipur never appears in User B's replies, session, or saved profile.

### Task 4: Explain Ted before users ask

**Files:**
- Modify: `/Users/vandana.agarwal/.hermes/SOUL.md`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: a greeting or prepared start message from a new user.
- Produces: a first reply that explains tracking, one useful nudge, and an evening recap before asking the user's name.

- [x] **Step 1: Replace the first onboarding reply**

Use: `I keep score on what you eat and do, nudge you when the day slips, and close with an honest recap. What should I call you?`

- [x] **Step 2: End onboarding with a concrete action**

Use: `You're set—send me what you last ate or one thing you completed today.`

- [ ] **Step 3: Verify comprehension**

In a fresh thread, complete onboarding without asking what Ted checks, how tracking works, or what a check-in looks like.

### Task 5: Ted's voice

**Files:**
- Modify: `/Users/vandana.agarwal/.hermes/SOUL.md`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: a user's actual answer.
- Produces: one short reaction to the content and, when needed, one question.

- [x] **Step 1: Ban acknowledgement openers**

Disallow `Great!`, `Got it!`, `Sure!`, `Nice to meet you`, and `Basically` as reply openers.

- [x] **Step 2: Require one real reaction**

For `14k / 3 lts / No workout for now`, respond to the ambition or tradeoff instead of repeating the fields as a form receipt.

- [x] **Step 3: Push once on vague goals**

For `Get slim`, ask what observable change would show progress before treating it as a usable goal.

- [ ] **Step 4: Verify reply shape**

Expected: one thought per message, no generic acknowledgement opener, no invented facts, and no more than one question mark.
