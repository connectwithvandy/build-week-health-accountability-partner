# TED architecture truth sheet

Roadmap task **T00**. Every line below was verified by running something on
17 Sep 2026, not read from another document. Where a claim could not be
verified it says so.

Re-verify with: `python3 scripts/ted-gate-guard.py --check-only`

## 1. Where TED actually runs

**On this laptop.** There is no cloud runtime. Three launchd jobs:

| Job | Interval | What it does |
|---|---|---|
| `ai.hermes.gateway` | resident | the gateway itself, `hermes_cli.main gateway run` |
| `ai.ted.gatewatch` | 900s | `ted-watch.py`, health checks + out-of-band alerts |
| `ai.ted.idle-nudges` | 3600s | `ted-idle-nudges.py` |
| `ai.ted.awake` | resident | `caffeinate -dimsu`, holds the laptop awake |

`ai.ted.awake` was added 17 Sep 2026 and is a stopgap with an expiry date.
Before it, the only thing keeping TED alive was a `caffeinate` typed by hand
into a Terminal window two and a half days earlier, parented to a login shell,
restarted by nothing. It now survives a closed window, a kill and a reboot. It
does **not** survive a closed lid, a flat battery or a desktop logout, and
`ai.hermes.gateway` still carries `LimitLoadToSessionType: Aqua`. Those are
T04, and this job gets deleted the day T04 lands.

Model is Anthropic direct (`claude-sonnet-5`), moved off OpenRouter on 4 Sep
because its prompt-size cap moved with the credit balance. Fallback is
OpenRouter `openai/gpt-5.3-codex`.

Cron: 60 jobs defined, 25 enabled.

## 2. Inbound path, message to reply

```
WhatsApp
   |
   v
Hermes gateway  (local, launchd, --replace)
   |
   +-- plugin: ted-safety-gates  ~/.hermes/plugins/ted-safety-gates
   |     hooks: pre_gateway_dispatch, pre_llm_call, pre_tool_call,
   |            post_tool_call, transform_tool_result, pre_cron_agent,
   |            transform_llm_output, post_llm_call
   |
   +-- model call (Anthropic direct)
   |
   +-- tools, by toolset:
   |      ted      -> ted_log_entry, ted_food_lookup, ted_day_summary,
   |                  ted_save_onboarding, ted_set_target, ted_set_reminder,
   |                  ted_memory_save, ted_memory_delete   -> Convex
   |      vision   -> vision_analyze                       -> image cache
   |      cronjob  -> cronjob                              -> ~/.hermes/cron
   |
   v
reply  ->  delivery_obligations  (ledger, state.db)
```

Hermes swallows plugin load errors with one warning, so a broken gate would
leave TED answering ungated and silent about it. That is why the stop lives
**outside** Hermes, in `ted-gate-guard.py`, run after every restart.

## 3. Every store holding user data

| Store | Where | Holds | Reached by deletion? |
|---|---|---|---|
| Convex | cloud, `whatsapp-accountability-partner-ted` | `users`, `onboarding`, `userFacts`, `targets`, `reminders`, `reportedReplies`, `dailyEntries`, `siteEvents` | yes, `_delete_user_data` |
| `state.db` | `~/.hermes/state.db`, 67MB | `messages` 6258, `sessions` 824, `delivery_obligations` 265, `session_model_usage` 963, `gateway_routing` | yes, `ted-forget-user.py` |
| Gate JSON (live) | `~/.hermes/state/ted-safety-gates-*.json` | 55 users: age, weight, goal, target, name, disclosure, pause | yes, `_forget_user`, leaves a tombstone |
| **Gate JSON backups** | same dir, 20 `.bak*` files, 3 to 17 Sep | full profile snapshots | **no. Nothing clears these** |
| Media | `~/.hermes/cache/images` 1.2M, `cache/audio` 1.0M | photos, voice notes | yes, `ted-forget-user.py` |
| Request dumps | `~/.hermes/sessions` 6.1M | whole API requests, so full conversation | yes, `ted-forget-user.py` |
| `agent.log` | `~/.hermes/logs` | message text | **no. Declared unreachable, ages out** |

Two stores own the same facts. Convex and the gate JSON both hold age, weight
and target, which is why nine repair scripts exist.

## 4. Privileged surface

**18 scripts that write** behind `--apply`: forget-user, land-missed-answers,
lock-whatsapp-tools, pin-cron-jobs, reconcile-setup, release-undelivered-reminders,
repair-ghost-jobs, repair-goal-drift, repair-language-preference,
repair-missing-answers, repair-profile-drift, repair-swallowed-weights,
scope-cron-tools, spread-reminder-times, backfill-timezone, dedupe-reminders,
idle-nudges, hermes-patch-guard.

**8 read-only**: api-spend, convex-check, gate-guard, onboarding-transcript,
reports, target-direction, watch, winback.

There is no auth boundary between these and normal operation. Anyone with the
laptop has every one. Roadmap T21.

**Secrets**: `.env.local` (Convex, OpenAI, Vercel OIDC) and `~/.hermes/.env`
(`TED_ALERT_EMAIL_TO`, `TED_ALERT_SMTP_USER`, `TED_ALERT_SMTP_PASSWORD`).

## 5. Document status

| Current | Historical | Unknown |
|---|---|---|
| `PROGRESS.md` (17 Sep) | `BUILD_PLAN.md` (3 Sep) | `PRODUCT_BUILD_GUARDRAILS.md` (30 Aug) |
| `docs/PRODUCT_REVIEW_AND_OPTIMISATION.md` (17 Sep) | `IDEA_SCOPE.md` (3 Sep) | |
| `README.md` (16 Sep) | `SCOPING.md` (4 Sep) | |
| `SUBMISSION.md` (16 Sep) | `AGENTS.md` (4 Sep) | |
| this file | `docs/BETA_TESTER_FLOW.md` (4 Sep) | |
| | `design-experiments/` 8 landing variants | |

`SCOPING.md` promises PDF support. The runtime refuses PDFs by design
(`unreadable_document_gate`). Roadmap T34 settles which is true.

## 6. Verified state, 17 Sep 2026, 22:34

Re-verify with the commands in section 1 rather than trusting this section. It
was wrong twice on the day it was written.

- **1118 Python tests pass**, plus 2145 subtests. Zero failures.
- Gateway PID 77830, gates loaded 22:33:55, `memory=on`, no STALE.
- All 13 Hermes patches applied. WhatsApp scoped to cronjob, ted, vision.
- Safety state healthy: 55 users loaded, 1 minor blocked, degraded flag empty.

### Closed and deployed today

- **T01 file access.** `file` removed from the WhatsApp toolset. It had been
  called 0 times in three weeks of logs.
- **T01 second door.** `vision_analyze` takes a local path and Hermes permits
  any path under a local terminal backend, which is this machine.
  `_vision_scope_guard` allows only the media cache roots. All 36 real media
  files pass; `/etc/passwd`, `.env`, `state.db` and a `../` escape are refused.
  Measured at 0.10us per unrelated tool call, 13.5us per photo.
- **T01 posture.** No surviving tool can write or delete a file: only
  `cronjob` and `vision_analyze` remain on the Hermes side and neither takes a
  writable path. Tests pin that the gateway is not root, `~/.hermes` is 700,
  and `.env` is private.
- **T02 isolation.** Gate state under real thread concurrency, media, Convex
  and its cache, and logs. Queue/reminder scope already existed
  (`CronScopeTest`, 7 tests, written after the 2 Sep incident). Four suites
  are mutation-proven.
- **T03 fail closed.** `_load_onboarding_state` returned `{}` for every kind
  of failure, so a corrupt file emptied every 18+ block while the plugin still
  imported and the guard still reported "Gates are on". It now distinguishes
  the two legitimate empty states from a fault, and `transform_response`
  answers with `STATE_UNAVAILABLE` instead of an unguarded reply. Proven on a
  truncated copy of the real file: 55 users and 1 minor block become 0, the
  fault is caught, and "eat 1200 a day" never reaches the user. The refusal
  sits in the output gate, not `pre_gateway_dispatch`, because patch 13
  settled that a hook must not put its own words into a user's thread.
- **T09 gate snapshots.** A deleted user is scrubbed from the 20 snapshots
  nothing owned. Live files are left to `_forget_user` deliberately: editing
  them from outside races the running gateway.
- **T09 voice notes.** Deletion found 7 of 7 photos and **0 of 29 voice
  notes**: a transcript holds the words, never the path, and no store held it.
  Now matched by arrival time, claimed only when exactly one person was
  messaging within 60s. All 29 attributed, none ambiguous, none claimed twice.

### Still open

- **T01, OS isolation.** TED runs as `vandana.agarwal`, not a dedicated
  account or container. Deferred to T04 on purpose: moving to always-on
  hosting provides the boundary once instead of paying the migration twice.
- **T01/T02, the live mile.** No real photo and no two real concurrent users
  since the change. Everything above is measured or unit-proven, which is not
  the same thing.
- **T35, logs are a second health store.** 23 of 40 recent user messages
  appear verbatim in `~/.hermes/logs/agent.log` (2.8 MB). The gate itself logs
  no user words; Hermes writes them. `ted-forget-user.py` already says it
  cannot reach that log. Retention is unset.
- **Dead code that looks live.** `src/lib/hermes/handle-message.ts` returns a
  hardcoded reply and `scripts/simulate-hermes-message.mjs` posts to it. It
  resembles a test harness for the WhatsApp path and tests nothing. T41.
- **`known_plugin_toolsets.whatsapp`** is read by neither the lock nor the
  guard. `spotify` is listed and not installed, so it is inert today.
- **T04, the host itself.** The laptop was on battery at 71% while 56 chats
  depended on it, and nothing watched either the power or the sleep hold.
  `check_power` in `ted-watch.py` now does, and it retires itself on a host
  with no `pmset`. The WhatsApp link is **Baileys**
  (`@whiskeysockets/baileys` 7.0.0-rc13, `useMultiFileAuthState`), so the
  session is a directory of JSON files with nothing host-specific in it: a
  host move is a copy and a cutover, **not** a QR re-link. The constraint is
  that only one instance may hold those credentials at a time; two fighting is
  what produced `~/.hermes/whatsapp/session.loggedout-20260909-100854`.
  Hermes ships its own `Dockerfile` and `docker-compose.yml`, mounting
  `~/.hermes` at `/opt/data` with `restart: unless-stopped`.
