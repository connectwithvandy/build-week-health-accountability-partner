# Ted product review and optimisation register

**Reviewed:** 17 September 2026  
**Purpose:** Turn the product review into an ordered, testable work list.  
**Rule:** A recommendation is complete only when its completion check has passed. Code existing is not enough.

## Overall decision

Ted has a strong product idea, a clear voice, and unusually good regression coverage. The current constraint is not feature depth. It is operational trust: a tester must be isolated from every other tester, the WhatsApp process must not reach unrelated laptop files, a reminder must be traceable until delivery, and deletion must cover every store.

Do not broaden the beta until all P0 items are complete.

## P0 — required before more tester invitations

| Work | Why it matters | Completion check | Status |
|---|---|---|---|
| Remove general file access from WhatsApp | The WhatsApp toolset currently exposes local file read/write/search capability. A health-chat user must never be able to reach unrelated laptop files. | The machine config has no `file` tool under WhatsApp; the live guard refuses unsafe toolsets; an automated test pins both rules. | In progress |
| Prove two-user isolation | Records are designed to be user-scoped, but the complete flow has never been exercised concurrently with two real WhatsApp accounts. | A and B run meals, corrections, targets, reminders, `done`, summaries, and deletion in parallel. Neither output nor stored row contains the other person's data. | Needs two phones |
| Fail closed when safety gates are absent | Hermes can keep responding after a plug-in load failure. That would remove the adult and calorie-safety rules while looking healthy. | A forced gate-load failure prevents replies and raises an alert outside WhatsApp. Recovery is automatic or has a rehearsed owner action. | Planned |
| Move the gateway to an always-on supervised host | A sleeping laptop or logged-out WhatsApp session takes Ted down for everyone. | Process restarts automatically; closing the builder laptop does not stop Ted; an external check detects reply and delivery failure. | External infrastructure |
| Make deletion one complete workflow | Convex deletion and local session/media deletion are separate today. The user should not need to know where their data lives. | One confirmed user command clears Convex, local gate state, session transcript, media, cron jobs, queued replies, routing data, and delivery records; a test account verifies every store is empty. | Planned |
| Track each outbound reminder until delivery | One `pendingDelivery` field is overwritten by the next send and cannot prove which message arrived. | Each send has a unique row with pending/delivered/failed/abandoned state. No unresolved row is overwritten. Automated reconciliation is idempotent. | Planned |

## P1 — next product sprint

| Work | Recommended decision | Completion check | Status |
|---|---|---|---|
| Progressive onboarding | Ask name, disclosure/goal, and check-in preference first. Let the person log immediately. Ask body and activity details only when they request a calorie target. Allow skip. | A fresh user can log before providing calorie-profile data. No calorie target is calculated before the 18+ check. | Planned |
| Activation metrics | Treat first useful log and second-day return as activation signals. Report profile completeness separately. | Dashboard separately reports start, first useful log, D2 return, profile complete, reminder delivered, and reminder acted on. | Planned |
| One onboarding contract | Make `IDEA_SCOPE.md`, `SCOPING.md`, `BUILD_PLAN.md`, `BETA_TESTER_FLOW.md`, dashboard logic, and the gate describe the same flow. | A repository check fails when the documented count or required fields drift. | Planned |
| Remove calorie-rule conflicts | Use one rule: no target below the calculated safety floor, and never choose a loss target for the user. | Prompt, tool description, gate code, and tests agree for maintenance, loss, gain, and unsafe-floor cases. | Planned |
| Split runtime and admin secrets | Runtime actions should not share a key with cross-user audits and reports. | Separate keys protect runtime and admin action groups; both are rate-limited; admin access is logged. | Planned |
| Working preview and release checks | Production is currently the only environment that builds fully. | Every pull request gets test, lint, type, build, patch-manifest, and safe preview checks. Production requires approval. | Planned |
| Operational events without chat content | Message counts, latency, delivery, provider fallback, and failures are not measurable today. | Event rows contain identifiers, timestamps, status, provider, latency, and error class but no health-message text. | Planned |
| Privacy-law readiness | The notice should name data, purpose, retention, processors, rights, complaints, and breach handling. | Legal review completed; consent and rights routes are tested; the contact route survives chat deletion. | Needs legal review |

## P2 — important optimisation

### Website and copy

- Move embedded photos out of the HTML, compress them as responsive WebP/AVIF, and strip metadata.
- Self-host all landing-page fonts.
- Run animations only while their scene is visible.
- Add Content Security Policy, Referrer Policy, MIME-sniffing protection, clickjacking protection, and Permissions Policy headers.
- Replace “same numbers either way” with an honest estimate claim.
- Remove the automatic workout-rescheduling claim unless that action is implemented.
- Describe reminders as user-selected rather than “silent by default.”
- Replace the public 1,400-calorie example with neutral wording or a safer example.

### Privacy, access, and analytics

- Stop custom analytics when `SITE_EVENT_SALT` is missing; never use a public fallback salt.
- Add duplicate suppression and traffic limits to the site-event endpoint.
- Replace the metrics secret in the URL with a short-lived, HTTP-only session cookie.
- Replace whole-table dashboard scans with daily aggregate rows before traffic grows.
- Store calorie calculation inputs, formula version, estimate source, and user confirmation time.

### Cost, maintenance, and operations

- Use fixed text or a small prompt for routine reminders; reserve the main model for interpretation and personalised coaching.
- Split the 9,928-line safety gate by responsibility without changing behaviour in the same step.
- Move incident stories out of the live 712-line prompt and keep them as regression tests.
- Remove the unused global Convex browser provider and the production-disabled legacy Hermes route.
- Either implement isolated, read-only PDF extraction or remove PDFs from the current contract.
- Add encrypted backup, retention, and restore drills for local session/media state.
- Stage minor dependency updates separately from major TypeScript, ESLint, and Vitest upgrades.
- Upgrade Vercel CLI with `npm i -g vercel@latest`.

## P3 — cleanup

- Update the README patch count from 8 to 13.
- Archive or clearly label superseded design experiments.
- Rename `whatsappUserId` to `userKey` in a deliberate migration; it does not hold a phone number.
- Remove stale provider and deployment descriptions from operational documentation.
- Keep `PROGRESS.md` current after every implementation session.

## Verification baseline from this review

- 164 Vitest tests passed.
- 1,022 Python tests and 2,124 subtests passed.
- ESLint, TypeScript checking, and the production build passed.
- The production dependency audit found no known vulnerabilities.
- All 13 Hermes patches were present.
- The public site returned HTTP 200 and served the same landing HTML as the repository.
- The gateway was not running when checked.
- A visual browser pass was not available, so mobile layout, keyboard use, screen-reader behaviour, animation smoothness, and Core Web Vitals still require browser verification.

## Required end-to-end test matrix

1. Fresh adult setup with no calorie target.
2. Adult asks for a target and chooses maintenance.
3. Adult asks for weight loss and explicitly selects the bounded option.
4. Known minor asks for calories.
5. Two users message, log, correct, and schedule concurrently.
6. Reminder delivered, failed, abandoned, retried, and answered with `done`.
7. Quiet hours, pause, daily cap, and back-off after unanswered nudges.
8. Text, photo burst, voice note, unreadable file, and delayed media.
9. Provider failure and fallback.
10. Gateway restart mid-conversation and mid-reminder.
11. Full deletion across every store.
12. Mobile landing page, reduced motion, keyboard navigation, and screen reader.

