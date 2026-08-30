# Hermes–Ted Personality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route real WhatsApp messages from the local Hermes bridge through Ted and give every generated reply Ted's agreed coaching personality.

**Architecture:** `TED_PERSONALITY.md` is the human-readable source of truth for Ted's voice and behaviour. A TypeScript module exposes the fixed opening reply and loads the personality text for future OpenAI calls. A small local Node worker polls Hermes at `GET /messages`, converts each Hermes event into Ted's internal message shape, calls the shared handler, and sends one reply through `POST /send`.

**Tech Stack:** Node.js, TypeScript, Next.js 16, Vitest, Hermes local HTTP bridge

**Spec:** `SCOPING.md`

## Global Constraints

- Hermes remains the only WhatsApp bridge.
- The worker runs on the same machine as Hermes.
- Ted replies in text only.
- Replies are supportive and never use shame, punishment, or exercise as compensation for eating.
- Known facts such as totals, targets, timestamps, and completion state are calculated in code, not invented by the language model.
- A real WhatsApp message must receive exactly one correct reply.
- `TED_PERSONALITY.md` is the source of truth; personality rules must not be copied into a second prompt that can drift.

---

### Task 1: Load Ted's agreed personality into one reusable module

**Files:**
- Read: `TED_PERSONALITY.md`
- Create: `src/lib/coach/ted-personality.ts`
- Modify: `src/lib/hermes/handle-message.ts`
- Test: `__tests__/hermes-message.test.ts`

**Interfaces:**
- Produces: `loadTedPersonality(): Promise<string>`, `FIRST_REPLY: string`
- Consumes: `TED_PERSONALITY.md` plus the product boundaries in `SCOPING.md` and `PRODUCT_BUILD_GUARDRAILS.md`

- [ ] **Step 1: Write a failing personality contract test**

```ts
import { FIRST_REPLY, loadTedPersonality } from "@/lib/coach/ted-personality";

expect(FIRST_REPLY).toBe(
  "Chalo, scene set karte hain 😌 First things first: what are we trying to fix?",
);
const personality = await loadTedPersonality();
expect(personality).toContain("One question at a time");
expect(personality).toContain("I never count their failures back at them");
expect(personality).toContain("I never write during quiet hours");
expect(personality).toContain("I do not diagnose");
```

- [ ] **Step 2: Run the test and verify the missing module fails**

Run: `npm test -- __tests__/hermes-message.test.ts`

Expected: FAIL because `src/lib/coach/ted-personality.ts` does not exist.

- [ ] **Step 3: Add the personality loader**

Read `TED_PERSONALITY.md` from the project root with `node:fs/promises` and cache the resulting string after the first read. Fail clearly if the file is missing or empty. Export the exact deterministic first reply from the same module. Do not restate or shorten the personality inside TypeScript.

- [ ] **Step 4: Import `FIRST_REPLY` into the Hermes handler**

Remove the duplicate reply constant from `handle-message.ts` and re-export the imported constant if existing tests rely on that import path.

- [ ] **Step 5: Run the focused test**

Run: `npm test -- __tests__/hermes-message.test.ts`

Expected: PASS.

### Task 2: Match Hermes's real event format

**Files:**
- Modify: `src/lib/hermes/handle-message.ts`
- Test: `__tests__/hermes-message.test.ts`

**Interfaces:**
- Consumes: Hermes events containing `id`, `chatId`, `senderId`, and `body`
- Produces: `HandledHermesMessage` containing the original `chatId` and `messageId` needed for a reply

- [ ] **Step 1: Add a failing test using the installed bridge's real event shape**

```ts
const result = handleHermesMessage({
  id: "wamid-1",
  chatId: "123@s.whatsapp.net",
  senderId: "123@s.whatsapp.net",
  body: "Okay let's do this",
});

expect(result).toMatchObject({
  messageId: "wamid-1",
  chatId: "123@s.whatsapp.net",
  text: "Okay let's do this",
  reply: FIRST_REPLY,
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `npm test -- __tests__/hermes-message.test.ts`

Expected: FAIL because the handler currently accepts only the simulator shape.

- [ ] **Step 3: Normalize both real and simulated events**

Keep simulator compatibility, validate non-empty string fields, and preserve the exact Hermes `chatId` for outbound delivery.

- [ ] **Step 4: Run the focused test**

Run: `npm test -- __tests__/hermes-message.test.ts`

Expected: PASS for valid real/simulated events and rejection cases.

### Task 3: Add the local Ted WhatsApp worker

**Files:**
- Create: `scripts/run-hermes-worker.mjs`
- Modify: `package.json`
- Modify: `.env.example`
- Test: `__tests__/hermes-worker.test.ts`

**Interfaces:**
- Consumes: `HERMES_BASE_URL`, Hermes `GET /messages`, and the shared Ted adapter route
- Produces: one Hermes `POST /send` request `{ chatId, message, replyTo }` for each accepted inbound message

- [ ] **Step 1: Add tests for polling, mapping, and exactly-once sending**

Use stubbed `fetch` responses to prove an empty poll sends nothing, one valid message sends one reply, and a repeated message ID is not answered twice within the worker process.

- [ ] **Step 2: Run the worker test and verify it fails**

Run: `npm test -- __tests__/hermes-worker.test.ts`

Expected: FAIL because the worker module does not exist.

- [ ] **Step 3: Implement the worker loop**

Poll `http://127.0.0.1:3000/messages`, pass valid messages to Ted, send replies to `/send`, log truthful errors without claiming delivery, and back off briefly after failures. Keep an in-memory set of handled message IDs for this milestone.

- [ ] **Step 4: Add the command and environment example**

Add `"hermes:worker": "node scripts/run-hermes-worker.mjs"` and document `HERMES_BASE_URL=http://127.0.0.1:3000`. The worker must fail clearly if the Next.js handler is unavailable.

- [ ] **Step 5: Run tests, lint, and build**

Run: `npm test && npm run lint && npm run build`

Expected: all commands pass.

### Task 4: Switch ownership from Hermes's default AI to Ted and verify WhatsApp

**Files:**
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: the installed Hermes bridge on `127.0.0.1:3000`
- Produces: one timestamped real WhatsApp exchange using Ted's exact first reply

- [ ] **Step 1: Stop the Hermes gateway cleanly**

Use the Hermes CLI's documented stop command so its built-in AI no longer drains `/messages`. Do not kill the QR session files.

- [ ] **Step 2: Start the bridge without the default Hermes agent**

Run the installed bridge in bot mode with the existing session and allowed-user settings. Verify `GET /health` returns `status: connected`.

- [ ] **Step 3: Start Next.js on a non-conflicting port and start Ted's worker**

Use port 3001 for Next.js because Hermes owns port 3000, point the adapter URL at `http://127.0.0.1:3001/api/hermes/messages`, then run `npm run hermes:worker`.

- [ ] **Step 4: Perform the real acceptance test**

Send `Okay let's do this` in WhatsApp and verify exactly one response: `Chalo, scene set karte hain 😌 First things first: what are we trying to fix?`

- [ ] **Step 5: Record only observed results**

Update `PROGRESS.md` with the tested interface, port ownership, command sequence, actual inbound/outbound result, and any remaining reconnect limitation. Do not mark the milestone passed unless the WhatsApp thread shows the exact reply once.

## Self-review

- Spec coverage: routing ownership, exact first reply, the complete agreed personality, relapse behaviour, useful memory, consent-before-saving, quiet hours, uncertainty handling, safety boundaries, and real WhatsApp proof are covered.
- Placeholder scan: no `TBD`, `TODO`, or unspecified implementation step remains.
- Type consistency: `messageId`, `chatId`, `text`, and `reply` are used consistently across normalization and sending.
