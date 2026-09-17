# Ted Product Hardening and Optimisation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Ted's privacy, isolation, delivery, onboarding, release, and website risks in priority order without weakening its tested coaching loop.

**Architecture:** Keep Convex authoritative for durable per-user state and use the local Hermes layer only for delivery/session details it alone can observe. Remove broad WhatsApp capabilities, represent outbound delivery and deletion as explicit durable records, and make all externally visible claims match tested behaviour. Each task is independently testable and deployable.

**Tech Stack:** Python/Hermes plug-in, Convex/TypeScript, Next.js 16 App Router, Vitest, pytest, Vercel.

**Spec:** `docs/PRODUCT_REVIEW_AND_OPTIMISATION.md`

## Global Constraints

- V1 is adults-only and must never choose a calorie deficit on the user's behalf.
- Every persisted record belongs to one explicit user key.
- Health text must not be added to operational metrics or logs.
- Do not commit keys, tokens, Hermes sessions, or tester phone numbers.
- Preserve existing uncommitted user work in `package.json`, `scripts/ted-api-spend.py`, and `scripts/test_ted_api_spend.py`.
- No production deployment, secret rotation, gateway restart, or real-user message without explicit confirmation.

---

### Task 1: Remove WhatsApp file access and enforce the boundary

**Files:**
- Modify: `hermes/machine/hermes-config.yaml`
- Modify: `hermes/SOUL.md`
- Modify: `scripts/ted-gate-guard.py`
- Modify: `scripts/test_ted_gate_guard.py`
- Create: `scripts/ted-lock-whatsapp-tools.py`
- Create: `scripts/test_ted_lock_whatsapp_tools.py`

**Interfaces:**
- Produces: `unsafe_whatsapp_toolsets() -> list[str]`, returning forbidden toolset names.

- [ ] Add a failing test where WhatsApp includes `file` and assert `unsafe_whatsapp_toolsets()` returns `['file']`.
- [ ] Add a passing test for exactly `cronjob`, `ted`, and `vision`.
- [ ] Parse only the `platform_toolsets.whatsapp` block and reject `file`, `terminal`, `web`, `browser`, `computer_use`, `code_execution`, and `delegation`.
- [ ] Remove `file` from the checked-in machine config and remove the file capability from Ted's live capability description.
- [ ] Add a dry-run-first command that applies the same allowlist to the live Hermes config atomically.
- [ ] Run `pytest -q scripts/test_ted_gate_guard.py` and the Hermes gate tests.

### Task 2: Make reminder delivery append-only

**Files:**
- Modify: `convex/schema.ts`
- Modify: `convex/model.ts`
- Modify: `convex/ted.ts`
- Modify: `convex/http.ts`
- Modify: `hermes/ted_safety_gates/__init__.py`
- Modify: `__tests__/convex-model.test.ts`
- Modify: `hermes/test_ted_safety_gates.py`
- Modify: `scripts/ted-release-undelivered-reminders.py`
- Modify: `scripts/test_ted_release_undelivered_reminders.py`

**Interfaces:**
- Produces: a `reminderDeliveries` table keyed by `deliveryId`, with `userId`, `kind`, `allowedAt`, `localDate`, `status`, `resolvedAt`, and optional failure reason.
- Produces: `deliveryStatus` HTTP action accepting `deliveryId` and `status`.

- [ ] Add model tests for pending → delivered and pending → failed transitions, retry idempotency, and refusal to rewrite a resolved send.
- [ ] Add the delivery table and indexes by delivery ID, user/status, and allowed time.
- [ ] Insert one row whenever reminder permission is granted; stop storing a single overwritable object on the reminder policy.
- [ ] Update the gateway callback and reconciliation script to resolve the exact delivery ID.
- [ ] Preserve compatibility while old reminder rows still contain `pendingDelivery`.
- [ ] Run Vitest, the reminder Python tests, TypeScript checking, and the Convex compatibility check.

### Task 3: Unify deletion behind a durable request

**Files:**
- Modify: `convex/schema.ts`
- Modify: `convex/ted.ts`
- Modify: `convex/http.ts`
- Modify: `hermes/ted_safety_gates/__init__.py`
- Modify: `scripts/ted-forget-user.py`
- Create: `scripts/ted-process-deletions.py`
- Create: `scripts/test_ted_process_deletions.py`
- Modify: `src/app/privacy/page.tsx`
- Modify: `__tests__/privacy-page.test.tsx`

**Interfaces:**
- Produces: `deletionRequests` with user key, request time, Convex completion, local completion, and non-personal error class.
- Produces: idempotent worker command `python3 scripts/ted-process-deletions.py --apply`.

- [ ] Write tests proving a request can be retried without deleting another user's data.
- [ ] Record the request before deleting user-linked Convex rows.
- [ ] Process local session, media, cron, routing, queued replies, and gate state only for the resolved sender.
- [ ] Mark completion without retaining the person's message content or phone number.
- [ ] Make the privacy page describe the single workflow and its completion timing accurately.
- [ ] Run deletion tests, full Python tests, Vitest, and TypeScript checking.

### Task 4: Restore progressive onboarding and correct activation

**Files:**
- Modify: `hermes/ted_safety_gates/__init__.py`
- Modify: `hermes/test_ted_safety_gates.py`
- Modify: `convex/model.ts`
- Modify: `convex/site.ts`
- Modify: `__tests__/convex-model.test.ts`
- Modify: `src/app/metrics/summary.ts`
- Modify: `src/app/metrics/dashboard.tsx`
- Modify: `__tests__/metrics-dashboard.test.tsx`
- Modify: `docs/BETA_TESTER_FLOW.md`

**Interfaces:**
- Produces: `coachingReady` based on disclosure, name, and goal.
- Produces: separate `profileComplete` and `firstUsefulLog` measures.

- [ ] Add a failing replay proving a new user can log before calorie-profile questions.
- [ ] Reduce the compulsory opener to name plus disclosure/goal; collect check-in when scheduling a review.
- [ ] Trigger the adult/body/activity sequence only when calorie targets become relevant and accept a skip.
- [ ] Update metrics so useful logging is not blocked by profile completeness.
- [ ] Run onboarding replays, model tests, metrics tests, and the full suites.

### Task 5: Make calorie rules and estimate provenance consistent

**Files:**
- Modify: `hermes/SOUL.md`
- Modify: `hermes/ted_safety_gates/__init__.py`
- Modify: `hermes/test_ted_safety_gates.py`
- Modify: `convex/schema.ts`
- Modify: `convex/ted.ts`

**Interfaces:**
- Produces: target provenance containing formula version, inputs, maintenance estimate, selected target, source, and confirmation time.

- [ ] Add tests for maintenance, gain, bounded loss, safety-floor collision, minor refusal, and skipped formula input.
- [ ] Replace “never below maintenance” with “never below the calculated safety floor and never choose loss for the user.”
- [ ] Persist the formula inputs and explicit selection with the target.
- [ ] Run the gate, Convex, and full test suites.

### Task 6: Split runtime and administrator access

**Files:**
- Modify: `convex/http.ts`
- Modify: `.env.example`
- Modify: `scripts/ted-reports.py`
- Modify: `scripts/ted-reconcile-setup.py`
- Modify: `scripts/ted-release-undelivered-reminders.py`
- Modify: `scripts/ted-convex-check.py`

**Interfaces:**
- Consumes: `TED_HERMES_RUNTIME_SECRET` for per-user actions.
- Consumes: `TED_HERMES_ADMIN_SECRET` for cross-user reads and repair actions.

- [ ] Add authorization tests proving a runtime secret cannot call reports, setup audit, pending deliveries, or repair actions.
- [ ] Route actions through explicit runtime/admin allowlists before parsing their payloads.
- [ ] Update scripts and environment documentation.
- [ ] Run the complete TypeScript and Python suites.

### Task 7: Harden analytics and metrics access

**Files:**
- Modify: `src/lib/site-analytics.ts`
- Modify: `src/app/api/site-event/route.ts`
- Create: `src/app/metrics/access/route.ts`
- Modify: `src/app/metrics/page.tsx`
- Modify: `__tests__/site-analytics.test.ts`
- Modify: `__tests__/metrics-dashboard.test.tsx`

**Interfaces:**
- Produces: `visitorHash()` returning `null` when no private salt exists.
- Produces: HTTP-only `ted_metrics_session` cookie with short expiry.

- [ ] Add tests proving no hash/event is produced without a salt.
- [ ] Add event deduplication by visitor, type, placement, and short time bucket.
- [ ] Exchange the metrics key once for an HTTP-only, secure, same-site cookie and redirect to a clean URL.
- [ ] Add `no-store` and `no-referrer` behaviour to metrics responses.
- [ ] Run Vitest, lint, type checking, and build.

### Task 8: Harden and lighten the website

**Files:**
- Modify: `next.config.ts`
- Modify: `public/landing-v6.html`
- Modify: `__tests__/landing-page.test.ts`
- Create: `public/landing/meal.webp`
- Create: `public/landing/ted.webp`

**Interfaces:**
- Produces: security headers for all routes and asset-based landing images with no metadata.

- [ ] Add tests for copy claims, external font absence, image URLs, and security headers.
- [ ] Replace misleading copy about exact estimates, automatic rescheduling, default silence, and the public calorie target.
- [ ] move embedded images to compressed responsive files and remove their metadata.
- [ ] self-host fonts and remove browser requests to Google.
- [ ] replace the permanent animation loop with visibility-controlled animation.
- [ ] add CSP, referrer, MIME, clickjacking, and permissions headers.
- [ ] run a desktop/mobile/reduced-motion browser pass, Vitest, lint, type checking, and build.

### Task 9: Add release automation and operational events

**Files:**
- Create: `.github/workflows/verify.yml`
- Modify: `convex/schema.ts`
- Modify: `convex/ted.ts`
- Modify: `hermes/ted_safety_gates/__init__.py`
- Modify: `README.md`

**Interfaces:**
- Produces: content-free operational events and pull-request checks for tests, lint, type, build, and patch manifest.

- [ ] Add event tests that reject message text and health values.
- [ ] Record received, processed, stored, delivered, failed, provider, fallback, and latency facts.
- [ ] Add the verification workflow using the repository's pinned Node and Python versions.
- [ ] Document staging/preview environment requirements without copying production secrets.
- [ ] Run the same commands locally.

### Task 10: Reconcile documentation and record proof

**Files:**
- Modify: `IDEA_SCOPE.md`
- Modify: `SCOPING.md`
- Modify: `BUILD_PLAN.md`
- Modify: `README.md`
- Modify: `docs/BETA_TESTER_FLOW.md`
- Modify: `PROGRESS.md`

**Interfaces:**
- Produces: one current product contract and a dated record of what remains external.

- [ ] Update the onboarding, PDF, deletion, patch-count, provider, deployment, and activation descriptions from verified code.
- [ ] Add commands and expected results for the two-user, deletion, reminder-delivery, failover, restart, and browser checks.
- [ ] Run a stale-term search for “three questions”, “counted five”, “all 8 patches”, and old provider claims.
- [ ] Run all automated checks and record exact results in `PROGRESS.md`.

## Work that cannot be completed only from this repository

- A real simultaneous two-phone WhatsApp isolation test.
- Moving the gateway to an always-on host and confirming lid-close independence.
- Rotating live secrets and configuring separate production/preview values.
- A lawyer's review of the privacy notice and consent flow.
- Production deployment, gateway restart, and live reminder/deletion proof.
