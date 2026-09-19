# Ted — WhatsApp Health Accountability V1 Progress

Last updated: Fri 18 Sep 2026, Asia/Kolkata

**How to read this file.** Numbered Orders run in date order down to
**Order 29 — 18 Sep 2026**, which is the newest and sits directly above the
tail. Everything after it, from "Web product we are building" to the end, is
early material from 1 to 4 Sep kept as a record; nothing there describes how
the product works now.

Two **Open** sections list findings written up rather than fixed, and neither
has been marked resolved: **Open — 16 Sep 2026** (two findings) and the older
**Open — 5 Sep 2026** (three findings). Read the newer one first. Before acting
on either, check the code and the gateway rather than trusting the write-up,
because some of it has been overtaken by later Orders without the section
being edited.

## What we decided

- The product name is Ted.
- The pre-filled user message is “Okay Ted, let's do this 💪”.
- Beta onboarding is three questions: the one thing the user wants to change, what Ted should call them, and their daily check-in time plus city.
- Ted's first reply combines a short storage, medical-boundary, and deletion disclosure with the goal question. Answering it records consent for the invited beta.
- The Hermes built-in WhatsApp agent is the product; there is no separate Ted worker.
- Ted's WhatsApp behaviour lives in `~/.hermes/SOUL.md` and is edited by Vandy.
- The web-app scope is the landing page, lead capture, and storing/showing data. It does not receive or send WhatsApp messages.
- Codex must not change the Hermes WhatsApp connection. Suggested Hermes changes are reported to Vandy instead.
- Do not use Twilio or build a Telegram fallback.
- Use Convex for stored state and scheduling and Vercel for the public web application.
- Ted's live conversational model runs through OpenRouter with `anthropic/claude-sonnet-5` as primary and `openai/gpt-5.3-codex` as the automatic fallback.
- Voice transcription remains a separate OpenAI speech service because the Codex model does not accept audio input.
- Voice notes work for health plans, meals and all progress updates. PDFs work only for health plans.
- Store raw photos, voice notes and PDFs until the user deletes their data.
- Use Mifflin–St Jeor for optional maintenance-calorie estimates.
- Age, height, weight, plans, targets, quiet hours, and commitments are asked only when relevant. The 18+ check happens immediately before first discussing or calculating a calorie target.
- Sleep tracking is not part of V1; revisit it with a future Apple Health connection.

## Hermes boundary

- The Hermes built-in agent is already connected to the Ted WhatsApp account and has produced a real conversation.
- With Vandy's permission, Codex updated `~/.hermes/SOUL.md` with the three-question beta opener, contextual profile questions, the point-of-need 18+ check, and honest deletion handling. The WhatsApp connection and session files were not changed.
- Its language balance, media replies, internal-message leakage, and other behaviour are Hermes/SOUL.md concerns, not web-app code.
- After the first builder onboarding test, Hermes was configured to send one `Listening…` acknowledgement for a voice note while hiding the transcript, tool progress, memory updates, self-improvement notices and other internal status. `SOUL.md` now forbids invented calorie targets, target comparisons without confirmation, and claims that unsaved meals were stored. The false 1400 kcal target was removed from Vandy's Hermes memory. A fresh WhatsApp session is still needed to verify these changes.
- Hermes now accepts messages from any WhatsApp sender for the limited beta. Ted's opener follows the user's actual first message: a plain greeting gets a greeting and invitation, while the prepared start message begins onboarding. Fresh external threads verified first-response processing for Ankita in 2.4 seconds and Khusha in 2.3 seconds after the allowlist fix; the earlier 26-minute silence was caused by their messages arriving before public beta access was enabled.
- The remaining onboarding fixes are sequenced in `docs/superpowers/plans/2026-08-31-beta-onboarding-reliability.md` and will be implemented and verified one at a time.
- The one-question-per-message onboarding rule is implemented in Hermes: name, goal, check-in time, and city are separate turns, and an answer to a different question does not advance setup. A fresh WhatsApp thread still needs to verify this behavior.
- A real cross-user leak was traced to Hermes's profile-wide memory, which mixed Vandy and Khusha facts and caused Ted to mention Bangalore to Ankita. The shared store is empty and disabled; durable user facts now use the isolated Convex path described below.
- The shared Hermes memory store is now empty, both `memory_enabled` and `user_profile_enabled` are false, and the memory tool is unavailable on WhatsApp. Per-user facts now use a production Convex `userFacts` table keyed by a one-way hash of the current WhatsApp sender. An authenticated Hermes plugin hook loads only that sender's facts into each turn, and `ted_memory_save` writes only to the sender bound to the active session; the model cannot supply or select an identity. Production write/read-back succeeded for Vandy's already-provided name. The next real WhatsApp turn still needs to prove hook loading and model tool use end to end before another tester is onboarded.
- Ted's opening now explains the full loop before asking for a name and shows a clearly labeled example evening recap. Onboarding now ends with one immediate action: send the last thing eaten or one thing completed today. A fresh tester thread still needs to verify that users no longer have to interview Ted to understand the product.
- Ted's voice rules now ban support-desk acknowledgement openers, require a reaction to what the user's answer means, push once on vague goals, and limit each message to one thought and one question. `Chalo, set.` is reserved for genuinely settled choices or saved actions, and evening reviews end with one specific move for tomorrow. Fresh-chat verification is still pending.
- Ted's persona has now been rebuilt around response mechanics instead of canned lines. Onboarding is treated as a state machine; the product loop is explained before personal questions; city is requested only when the first real check-in is scheduled; reactions vary among opinion, observation, direct question, consequence, playful skepticism, and one concise disagreement. The example library and fixed catchphrases were removed. Emoji use is limited to one natural reaction at the end, and normal WhatsApp recaps forbid document-style headers, bullets, dividers, tables, and metric emojis. Fresh-user verification is pending.
- A fresh `Hello` test at 9:24 PM failed because OpenRouter returned HTTP 402: Hermes requested a 16,384-token output allowance that exceeded the account's remaining credit. Ted's model output cap is now 1,024 tokens, which is ample for the two-sentence WhatsApp contract and avoids that oversized reservation. A new real message still needs to verify recovery.
- The 9:26 PM retry proved provider recovery but exposed an onboarding regression: `gpt-4o-mini` interpreted the soft rule “a greeting gets a greeting” as permission to send a generic assistant reply. `SOUL.md` now has a non-negotiable first-turn contract requiring identity, product loop, neutral recap preview, and exactly one name question; generic “How can I assist?” replies are explicitly forbidden. A reset fresh-chat test is pending.
- The first-turn contract now also explains input formats and their limits: text and voice notes for meals or progress, meal photos for meals, and PDFs only for existing health plans. It states that meal logging includes estimated calories and macros, then closes onboarding by inviting a typed update, voice note, or meal photo.
- WhatsApp prompt reduction is implemented before any model change. The platform toolset is now empty: computer tools dropped from 30 to 0, tool-schema payload from 51,636 bytes to 2, and the skills index from 8,186 characters to 0. `SOUL.md` was compressed from 12,137 to 5,715 characters while retaining identity, onboarding, voice, coaching, input boundaries, recaps, and safety. The full fixed system prompt fell from 33,825 to 10,082 characters; roughly 4,300 remaining characters are Hermes's own platform guidance and cannot be removed through supported profile configuration. A fresh five-message test is pending before any model change.
- Legacy local adapter, worker, simulator, API route, and tests remain in the repository but are not the product direction and must not be extended.
- Ted's calorie safety rules now run as the enabled `ted-safety-gates` Hermes plugin instead of prompt-only instructions. The live output gate requires a supplied adult age before any calorie number, requires height, weight, formula sex, and activity one at a time before maintenance, calculates Mifflin–St Jeor maintenance from those supplied values, and never returns a deficit target. The 27 focused Python tests cover the original 2,300/1,400 failure, the exact ragi-roti replay, under-18 blocking, missing inputs, onboarding order, and unproven action claims.
- Consent is also hard-gated by the same plugin: after a user answers the name question, the disclosure with the privacy URL replaces any attempted next response until it appears in that conversation. The plugin logs `consent_disclosure_sent` when the gated disclosure is produced. A fresh real WhatsApp thread is still needed for the four-message delivery proof.
- The same output gate now removes claims such as “saved”, “scheduled”, or “noted” unless a tool succeeded in that turn. This was added after an earlier model test produced “33 noted” without a save call. The focused Python tests now pass.
- The calorie gate now includes the current incoming message when extracting the age profile, including a bare reply such as “33”. This closes the loop caused by Hermes delivering a transformed age prompt without persisting that transformed text into the durable transcript. The golden-path replay reaches beyond the age gate; a fresh WhatsApp turn is still the final live proof.
- On 2 September, the previous provider stream stalled for 4,491.5 seconds and exhausted five retries. Hermes exposed raw provider and gateway errors in WhatsApp. Those internal errors must be replaced with one short user-safe retry message before public beta.
- The later repeated “What should I call you?” replies are a separate consent-gate bug, not a model outage. The gate replaces the model's answer with the name question but Hermes persists the original answer, so the next name reply cannot advance onboarding. This loop was reproduced locally and is not fixed yet.
- Hermes was restarted after the primary/fallback change. The gateway is running, but a later status check again reported the launch service as not loaded and the process as detached. Automatic startup and crash recovery are therefore still not reliable.
- Order 09 (2 Sep, evening). The "stalled provider" was a sleeping laptop. `agent.log` records `Stream stale for 1019s (threshold 180s)` five times, and `pmset -g log` shows a `Clamshell Sleep` covering each gap; the one detection made while the machine was awake fired at 192s, correctly. Every Hermes stall watchdog measured silence with `time.time()`, which keeps counting through suspend, so the closed lid was charged to OpenRouter. All four watchdogs (streaming, non-streaming, Codex, Bedrock) now use `time.monotonic()`, which pauses with the machine. `HERMES_STREAM_STALE_GIVEUP=2` in the launchd plist lets a genuinely wedged call reach the configured `fallback_model` in minutes instead of never. Lowering `providers.openrouter.stale_timeout_seconds` would not have helped: the reasoning floor in `agent/reasoning_timeouts.py` raises any configured value back to 180s for `claude-sonnet-5`.
- Provider failure text is no longer Hermes' own diagnostics. `display.provider_messages.*` in `config.yaml` supplies the user-facing copy (defaults unchanged, so Hermes' tests still pass) and Ted's entries speak plainly: "That didn't go through. Send it again." Mid-call stall notices, which named the model and context size and repeated once per reconnect, are suppressed on chat surfaces; the raw text still goes to `agent.log`, and CLI/API/webhook surfaces are untouched. Both Hermes-side changes live outside this repo and are saved as re-appliable patches in `scripts/hermes-patches/`.
- A failed save now says so. `_convex_request` tags storage outages, every write goes through `_convex_write` (which also invalidates the cached facts), and the turn ends with "that didn't save — send it again in a minute." instead of the claim gate's "I haven't completed that action." — two different failures that a tester could not previously tell apart. The per-turn Convex read is cached for 5 minutes and invalidated on every write, measured at ~678 ms saved per turn against production; its timeout dropped from 5s to 2s, while writes keep 5s. 95 Python tests and 19 vitest tests pass, and the six never-break behaviours were re-checked individually.
- Order 11 (2 Sep, evening) is written and tested but **not deployed and not live**. Milestone 10: `logDailyEntry` now refuses to write and returns a question when a log clashes with something already recorded (`findClashingEntry` — meals and workouts inside two hours, the same commitment twice; water and steps are never questioned because accumulating is normal), and when the user names a date that is not today. Both confirmations default to false and only a real boolean `True` counts. Milestone 11: a `reportedReplies` table, a `report` phrase the gate recognises in the user's own words, the reported turn stored verbatim by the gate rather than by the model, a fixed confirmation the model cannot rewrite, and `npm run reports` to read them back. Milestone 12 and SCOPING #8/#10: quiet hours, pause, and the per-day cap are now one pure function (`decideReminderDelivery`) behind a `reminderGate` mutation that counts only what it clears; PDFs can no longer log a daily update and photos can only log a meal.
- The milestone 12 work exposed a bigger hole. Reminders are Hermes cron jobs, and `cron/scheduler.py` builds its agent with `platform="cron"`, so every Ted gate returned early: scheduled pings reached a real WhatsApp thread with no claim gate, no calorie gate and no quiet hours — nothing was enforcing the prompt instructions because nothing was reading them. The gate now recovers the job id from the `cron_<id>_<timestamp>` session id, looks up the job's WhatsApp origin, resolves the same hashed user key a live turn would, and applies the rules. A blocked ping returns cron's `[SILENT]` sentinel. A cleared ping still goes through the claim gate, and any calorie number in a one-line reminder is dropped outright — there is no conversation behind a cron run to prove the recipient is an adult.
- Order 12 is part-done, and **held locally on purpose — none of it is pushed or live**. Items 3 and 6 are written: openGraph and twitter tags with `ted-whatsapp-cover.png` (1600x900) so a Ted link shared in WhatsApp stops rendering as bare text, a canonical URL, `robots: index:false`, a `robots.txt` with `Disallow: /` while the beta is private, and a 404 in the site's own colours with a way back. The 404 uses inline styles reading the CSS variables, defining no classes of its own, so it cannot break while the landing page is being reworked. Item 5 (a public contact address on the privacy page) is deliberately not done — no verified address yet. Items 2 and 4 touch `src/app/page.tsx` and `globals.css`, which were being edited at the time, so they were left alone. Nothing under `src/` or `public/` has been pushed: the live site still shows the previous landing page, has no share tags and no robots.txt.
- Two of the order 14 point 4 findings are now fixed rather than only listed (2 Sep, night). `_disclosure_was_sent` treated **any** assistant turn containing the privacy URL as proof the disclosure had gone out, so a model that helpfully volunteered the link read as consent and the disclosure — with the consent record — would be skipped for good. It now reads the recorded state first (`_DISCLOSURE_SENT_KEYS`, which `_log_disclosure` writes only after a real send and the model cannot influence), and the transcript scan that remains as a fallback requires Ted's own opening sentence, not the bare URL. `consent_gate`, `transform_response` and `_awaiting_name` pass the user key through. `_claim_types` was widened for the seven phrasings confirmed to slip: “Done ✓”, “Sorted ✅”, “consider it logged”, “consider it in your log”, “that's in the system now”, “your log is up to date” and “I'll keep that in mind for 8pm”. The tick is what separates “Done ✓” from “water done, walk done”, and the “up to date” pattern needs a data noun so “your target was updated last week” stays a description; every sentence in the day-summary suite still passes through untouched. 151 Python tests.
- The prepared message ends in 💪, not 🫡 (2 Sep, night). The saluting face is Unicode 14 (2021) and rendered as � in both WhatsApp and the wa.me page on a current Mac — the bytes were correct end to end (`f0 9f ab a1` in `page.tsx`, `%F0%9F%AB%A1` in the live href), so this was the client failing to draw the glyph, not mangled data. 💪 is Unicode 6.0 (2010) and renders everywhere. `SCOPING.md`, `IDEA_SCOPE.md`, `BUILD_PLAN.md`, `page.tsx` and `page.test.tsx` all agree on it; the dated plans under `docs/superpowers/plans/` keep 🫡 because they record what was decided at the time, and `__tests__/hermes-message.test.ts` keeps it as a deliberate non-BMP payload fixture. **The held-back landing rework in `c2d82be` still carries 🫡 and will reintroduce it unless that line is changed before the rework ships.**
- Orders 08, 13 and 14, plus the two non-design items in 12 (2 Sep, night). **Written and tested, not deployed and not live** — the gateway still runs the pre-order-08 gate. Order 08: SCOPING.md §3.4 already said the disclosure and the goal question go out in one message and the code sent two, the second from a daemon thread after `time.sleep(1.0)` with no retry, so a failed send or a restart inside that second stalled onboarding with no record that a goal question was owed. Joining them at send time deleted `_schedule_goal_question`, `_send_goal_question`, the thread and the sleep instead of adding a retry around the failure; `DISCLOSURE_MESSAGE` stays the disclosure alone so the privacy text keeps one definition. Order 13: `_clean_name` strips emoji from both ends, refuses an emoji-only name and refuses one over 40 characters instead of truncating it mid-word silently; a second press of the WhatsApp button is acknowledged rather than falling through to a model reply that acknowledged nothing; an empty or media-only message while the name is outstanding asks for the name, scoped to onboarding only so a meal photo is still the product. Voice transcription is **whisper-1** — nothing in the repo or in Hermes reads `OPENAI_TRANSCRIPTION_MODEL`, and `gpt-transcribe` is not a name Hermes accepts (`whisper-1`, `gpt-4o-mini-transcribe`, `gpt-4o-transcribe` are); the live setting is `stt.openai.model` in `~/.hermes/config.yaml`, overridable with `STT_OPENAI_MODEL`, and `.env.example` now says so instead of naming a dead variable and a model that does not exist.
- Order 14 found a real hole in a load-bearing rule, and it is now closed. The under-18 refusal sat **behind** a regex over the model's own prose: `calorie_gate` returned early unless `_response_has_calorie_number` matched, and that pattern required the literal word `kcal` or `calories` beside the digits. Reproduced against a history the gate had already parsed as age 15: "that's about 500 cal", "500 cals", "roughly 1.6k a day", "that's around 2,000 for the day", "call it 500 for that plate", "~1800 a day" and "about sixteen hundred a day" all returned `None` — the number reached the minor. The age is now read before the early return, and a known minor is checked with `_minor_unsafe_response`, which is deliberately not a phrasing list: any digit, any nutrition word, or a spelled-out amount is enough. `_response_has_calorie_number` was widened too (`cal`/`cals`, `1.6k a day`, `2,000 for the day`, spelled amounts beside a nutrition word). Blast radius is minors only — for an unknown age or an adult outside a target conversation the gate returns `None` exactly as before, and "nice work today, keep it up" is still not a refusal. Mifflin–St Jeor still gives 1,630 for 33 F / 170 cm / 62 kg / sedentary, and a deficit request still returns maintenance.
- Order 14 also added the end-to-end replay the queue asked for: prepared start → name → goal → time → meal → correction → "how am i doing today?" → evening review → "delete my data" → confirm, asserting the exact user-visible reply at each step, that the name is asked exactly once, that the disclosure goes out exactly once, that corrected numbers and daily totals survive the claim gate, and that a deletion confirmation only appears once the delete tool actually succeeded. 145 Python tests, 44 vitest tests, `npm run build` clean.
- Order 14 point 4, the remaining places the gate infers state from prose a model wrote, each reproduced rather than guessed: `_asks_for_name` (line 673) needs a question mark plus "call you"/"your name", so "and you are…?", "what's your name" without the mark, "how should i address you?" and "got a name?" all read as *not asking*; `_answer_after_question` (line 866) anchors every profile parser to the wording of the question, so "how many cm are you?" loses a bare "170"; `_claim_types` (line 1278) misses "Done ✓", "consider it in your log", "that's in the system now", "your log is up to date" and "I'll keep that in mind for 8pm"; `_disclosure_was_sent` (line 588) treats any assistant turn containing the privacy URL as proof the disclosure was sent, so the model mentioning the link would skip the consent record; `_last_assistant_turn` (line 1965) recognises Ted's own fixed lines by substring, which drifts if the copy is reworded. `_calorie_flow_active` and the `_find_*` parsers read the *user's* words, which is a different and milder risk. The structural answer is the same as orders 1, 2 and 10: read state the gate itself recorded, not text a model chose.
- Order 12 items 4 and 5 are done. The footer privacy link — the only route to the privacy page on a phone, where the header nav is hidden — now has a 44px tap target while the text keeps its size and position, so the footer looks unchanged. The privacy page has a contact route: the WhatsApp chat, with no email published, and it says plainly that the chat is the only route so a user can decide whether to keep it. `__tests__/page.test.tsx` was asserting the old CTA copy ("free during beta" inside every link); the CTA says "Message Ted" and the beta note sits beside the closing CTA, so the test moved rather than the page.
- `npm run convex:check` now answers the question that trap depended on nobody asking: does the deployed Convex understand the code in this repo? It compares the actions the gate declares against a read-only `capabilities` call, and proves argument compatibility by sending the exact arguments the gate sends with one field deliberately malformed, so the mutation throws on it after validation and before touching the database — no rows written. A deployment too old to answer `capabilities` still gets a specific report rather than "too old". Run it before every gateway restart: `npm run convex:check && hermes gateway restart && npm run gates:guard`.
- Order 11 is deployed and live as of 2 Sep 20:43. The deploy path is Vercel, not the local Convex CLI: the project's build command is `npx convex deploy --cmd 'npm run build'` with `CONVEX_DEPLOY_KEY` in its production env, so pushing to `main` deploys Convex and the site together. The local CLI's "no access to the selected project" is a red herring — `.env.local` was written by `vercel env pull` and names a `dev:` deployment nobody uses. Verified in order: `npm run convex:check` green, gateway restarted, `npm run gates:guard` green, then the four behaviours exercised against production and the test rows deleted.
- Pointing the new reminder gate at a real account before trusting it caught a regression that had already shipped. Vandy's five vitamin reminders are Hermes cron jobs with no row in the `reminders` table, and `decideReminderDelivery` refused on a missing row, so all five would have been silently suppressed the next morning. The reasoning was wrong on its own terms: SCOPING #21 puts the number of reminders down to the user's preferences, so absent a preference there is no cap, and a default `maxPerDay` of 3 would have cut five to three even once a row existed. No stored row now means default quiet hours and no cap; the same fix was applied to the Python outage path, which had suppressed everything when Convex could not be read. Confirmed against live Convex: 08:45, 10:30 and 16:00 all allowed, 23:30 and 03:00 both refused.

- Order 15 (2-3 Sep, night) came out of watching a real beta thread live rather than replaying a fixture. A new tester ran a full session — onboarding, a name, a protein target, three meals, a correction, a voice note, a reminder, an under-18 claim and a data deletion — and four things held that had never been proven on a stranger: the fixed opener replaced the model's improvised 372-character greeting with `OPENING_MESSAGE` (308 chars sent); the consent disclosure went out joined to the goal question exactly as order 08 intended (208 chars = `hey <name>` + disclosure + privacy URL + question); the order-14 under-18 rule fired **live** when the tester typed "I am 15", replacing both the model's "15, noted" and a following "800 kcal total, 45g protein" with `UNDER_18_REFUSAL`; and "delete my data" really deleted — 3 daily entries, 1 onboarding, 1 target and the user row, confirmed gone by a read-back against production. The meal correction did not double-count: the 700 kcal entry is marked `state: corrected` and excluded, leaving the 800 kcal / 45g the tester was told.
- The same thread exposed a real cross-user leak. `cronjob` is a Hermes platform tool over a machine-wide store, so `action='list'` inside the tester's thread returned **every** job on the box — five of Vandy's supplement reminders with her name and doses (CoQ10 200mg, Omega 3 1500mg, B12 1500mcg, Iron 29mg, Vitamin D 60,000 IU) — and handed the model live job ids it could have removed, rescheduled or paused. Ted did not repeat them out loud, but nothing stopped it. This is the same class of leak the isolated `userFacts` path closed for memory, still open for reminders. It is now closed by ownership: `_cron_scope_guard` (a `pre_tool_call` hook) blocks `update/pause/resume/remove/run` against a job whose origin chat is not the caller's, and blocks a `create` whose `deliver` is anything but `origin` — `all` fans out to every connected channel and `platform:chat_id` targets someone else outright. `_filter_cron_listing` (a `transform_tool_result` hook) strips other chats' jobs from a listing. Scoping is by the WhatsApp chat a job was created from, the only identity Hermes records on a job; a session with no WhatsApp turn context is the builder at a terminal and is deliberately left untouched.
- Chasing that leak found the bigger one: **the entire milestone-12 cron gate had never run in production.** `_cron_whatsapp_recipient` read `~/.hermes/cron/jobs.json` with `list(raw.values())`, but Hermes writes `{"jobs": [...], "updated_at": ...}` — so that expression yielded the job *list* and a timestamp *string*, never a job dict. Every lookup missed, the recipient was always `None`, and `_cron_reminder_gate` returned early on every single run: quiet hours, the claim gate and the calorie suppression were all dead code from the day they shipped. The live proof is in the same thread — a reminder was delivered at 23:55, inside the documented 22:00–07:00 quiet window, with no `ted_reminder_suppressed` line anywhere. The reader is now `_load_cron_jobs`, which accepts the documented wrapper, a bare list and an id-keyed mapping. The reason the tests stayed green is worth keeping: `CronReminderGateTest` wrote its fixture as a bare list, a shape production never produces, so the suite was proving the gate against a file Hermes does not write. `CronJobsFileShapeTest` now pins the real shape.
- Order 15 fix 1 is done: the under-18 block is now durable. The age was read only out of conversation history, and with `compression.threshold: 0.5` and `protect_last_n: 20` the "I am 15" turn is compacted out of the *same* conversation after enough messages — the refusal that fired correctly on 2 Sep would then have stopped firing with nothing said anywhere. `calorie_gate` now takes the user key, records a stated age through `_remember_age`, and reads it back with `_stored_age` / `_is_known_minor`. The store is the gate's own onboarding-state file, not Convex `userFacts`, for a specific reason: `userFacts` is writable by the model through `ted_memory_save`, and the one rule that must not be talked around cannot live somewhere the thing being gated can edit. The flag is deliberately sticky — "i'm 15" then "actually i'm 30" leaves the block in place — and the only thing that clears it is `_forget_user`, because erasure has to be honest and a record kept after a deletion request would not be. Reading the age back also restores an adult age that scrolled out of the window, which stops the age question repeating. Mifflin-St Jeor still returns 1,630 for 33 F / 170 cm / 62 kg / sedentary and a deficit request still returns maintenance. 169 Python tests, 44 web tests.
- Still open after order 15, in the order they matter. (2) The transcript stores what the model wrote, not what the gate sent: every gated turn diverges, so Ted's own history says it told a 15-year-old "800 kcal total" when the user saw a refusal. (3) Ted told the tester a delivered reminder had never fired — the one-shot job had already run and been cleaned up, `cronjob` returned "not found", and the model covered with "guess the old one just ran out of patience", which is an invented account of a system state. (4) Onboarding never completed: the check-in time was asked four times, dodged four times, and then dropped with "All set", so this user would never have received a daily recap. (5) A destructive, irreversible wipe was accepted on the typo "Ges".
- The live site was checked in the same pass: `/` and `/privacy` both return 200, so the privacy URL the disclosure sends a real user resolves. `robots.txt` still 404s and the landing page carries no `noindex`, so the private beta is indexable — that is the undeployed half of order 12, unchanged.

## Order 16 — 3 Sep 2026, pre-launch review

Written and tested. **Not deployed and not live**: Convex is missing `week` and
`replied`, and the running gateway still holds the gate it loaded at 10:54. Both
guard scripts say so and name the order:

    npx convex deploy && hermes gateway restart && npm run gates:guard

- **Ted could not read a PDF, and Hermes was telling it to try.** The WhatsApp
  adapter inlines a document's text only for `.txt .md .csv .json .xml .yaml
  .yml .log .py .js .ts .html .css`. For a binary one it prepends
  `_build_document_context_note`, which instructs the agent to "extract the
  document's text yourself, for example with the terminal tool or the
  ocr-and-documents skill". Ted's WhatsApp toolset is `cronjob file ted vision`
  and has neither. What it does have is `file`, and `.pdf` is deliberately
  absent from Hermes' `BINARY_EXTENSIONS`, so a read returns the raw stream
  decoded as text: an unreadable health plan that looks just readable enough to
  invent calorie targets from. `unreadable_document_gate` now answers it,
  matched on Hermes' own note rather than model prose, and placed ahead of
  `calorie_gate` so an unread plan can never reach the maintenance maths.
  SCOPING #8/#10 promised PDFs; nothing user-facing ever did, so the landing
  page needed no change.
- **The weekly review is real, and conditional.** SOUL.md had described one
  since the start while SCOPING.md §4 parked "Weekly reports" and nothing
  scheduled it, so Ted was carrying a promise it could only keep by accident.
  Now: `summariseWeek` Monday to Sunday, a `getWeekSummary` query, a `week`
  HTTP action, `weeklyReviewEnabled/Day/Time` on the reminders row, and a
  `ted_week_summary` tool. Every metric averages over the days that carry that
  metric, so a water-only Tuesday cannot drag the calorie average down, and an
  empty week returns `null` rather than zero. Each average carries the day count
  it came from so Ted can say "across the four days you logged". Offered once,
  appended to Ted's own sign-off rather than as a second blocking question,
  because §4 also parks "a long setup questionnaire". A no is stored, so the
  offer never repeats.
- **Ted stops nudging someone who has gone quiet.** Four unanswered nudges and
  the next one is replaced by a question: whether they want reminders paused.
  Then silence until they say anything at all, including something that ignores
  the question, because a user who has started logging again has answered it.
  `unansweredNudges` and `awaitingBreakReply` on the reminders row; the count is
  incremented only when a nudge is actually cleared to send, and the offer still
  obeys quiet hours and the daily cap. The reset costs no write for an engaged
  user: `getUserMemory` already returns the counts on the read every turn makes,
  and the `replied` write fires only when there is something to clear.
- **No dashes in Ted's voice.** Vandy's rule: a dash mid-sentence is the
  clearest tell that a machine wrote the line. 13 user-facing strings rewritten,
  the rule added to SOUL.md, and 20 lines of SOUL.md's own prose cleaned, which
  mattered more than it looks: SOUL.md is what the model reads to learn the
  voice, so a document full of em dashes was teaching the habit the rule
  forbids. `~/.hermes/SOUL.md` is a symlink to the repo copy, so this is live on
  the next restart.
- **`display.provider_messages` was already live and the repo snapshot was not.**
  Reading `hermes/machine/hermes-config.yaml` said Ted still answered a provider
  outage with "check gateway logs for diagnostics". It does not. The snapshot is
  re-copied, the copy is rewritten in Ted's voice, and `hermes/machine/README.md`
  now says the thing this cost: a stale snapshot does not read as stale, it
  reads as the truth.
- Tests: 198 Python, 69 vitest. `tsc`, lint and `next build` clean.

### Order 16, second pass

- **Every date is now the user's, not the laptop's.** `users.timeZone` was
  collected at onboarding, written to Convex and read by nothing: `_today()` and
  every `time.strftime` in the gate came off the host clock. `getUserMemory`
  now returns `timeZone` on the read each turn already makes, and the gate
  converts with Python's `zoneinfo` through `_today(user_key)`,
  `_now_local_time(user_key)` and `_local_moment(user_key, ms)`. The conversion
  is in the gate rather than in Convex on purpose: Convex's V8 timezone data
  could not be verified without deploying, and a silent fallback there would be
  worse than the bug. `DEFAULT_TIME_ZONE = "Asia/Kolkata"` is a stated
  assumption rather than an accident of which laptop is running, and it logs
  every time it is used. A name the model invented ("IST", "Bangalore") fails
  validation and falls back rather than raising. The clock read is deferred
  until after every validation in `_log_daily_entry`, so a malformed meal is
  still refused without touching the network.
- **`deleteUserMemory` now clears `reportedReplies`.** Those rows hold the
  user's own message verbatim and Ted's reply to it, survived deletion, and
  were orphaned to a user id that no longer resolved. /privacy promises
  everything goes. Not unit-tested: it is a mutation and there is no Convex
  test harness here, so verify after deploy with `npm run reports` either side
  of a test account's deletion.
- Tests: 205 Python, 69 vitest.

## Order 17 — 3 Sep 2026, the first live session after going live

Vandy tested on WhatsApp within a minute of the restart and it read as broken.
Ted answered a plate of food with "Logged this.", asked for an age, and then
told her "that's not something I asked" when she answered it. She was right on
all three counts, and all three had a cause.

- **Ted did not know what Ted had said.** The root cause, and it was already
  written down as open item (2) after order 15: a gate replaces the outgoing
  reply, but Hermes records the *model's* original text in the transcript. So
  `calorie_gate` sent the age question, Vandy answered "15", and Ted read a
  history containing no age question and said so. Not rudeness. Amnesia. Order
  16 made it more likely by adding three more gates without noticing the
  interaction. `_record_gated_reply` now keeps what was actually delivered and
  `_gated_reply_context` hands it back on the next turn, consumed once, held in
  memory rather than on disk because it is message content and matters for
  exactly one turn. A suppressed cron reminder is explicitly not recorded: "what
  you actually sent was [SILENT]" is worse than silence.
- **The gate was overriding Ted's voice.** `action_claim_gate` ran
  `cleaned[:1].upper()` on whatever survived a claim strip. That single line is
  how a warm lowercase sentence reached a real user as "Logged this." The gate
  removes claims; it does not get a voice. The test that pinned the capital L
  now pins the lowercase, and says why.
- **SOUL.md now specifies the shape of a meal reply** rather than leaving it to
  taste: the food named first, in Ted's words, then the numbers on their own
  short lines, then where the day stands. Opening with a number, or with
  "logged" / "noted" / "got it" / "saved", is named as a receipt and forbidden.
  "Logged this." is called out by name.
- The timezone fallback logged on every read, five identical lines per meal. Now
  once per user per process, cleared by `_forget_user`.
- The photo acknowledgement had no success log, so after the first live test
  there was no way to tell whether it had fired. It logs `ted_photo_ack_sent`
  now. Regenerating that patch went wrong halfway: a reverse-apply took the
  helper out and left the code calling it, so `run.py` parsed but would have
  raised `NameError` on the first photo after a restart. Caught by counting the
  definitions rather than trusting "parses OK", which is the lesson: a Python
  file that parses is not a Python file that runs.

- **The numbers now come from the gate, not the model.** Even with SOUL.md
  loaded in full and untruncated, the first live meal after the fix came back
  as "logged 👍 sprouts bowl in — you're at roughly 1060 kcal, 46g protein":
  no per-meal breakdown, a receipt word in front, and "roughly" attached to a
  figure read out of the database. The session had 84 messages and
  `compression.protect_last_n: 20`, so twenty verbatim examples of the old
  voice sat next to the new rule and won. Writing a stricter rule would have
  lost the same way. So `logDailyEntry` now returns the day's totals with the
  write, the gate holds the saved meal for the turn, and `meal_breakdown`
  appends the figures itself: this meal one metric per line, then the day so
  far, dropping the day line when it would merely repeat the meal and dropping
  any zero macro rather than printing a gap as a fact. SOUL.md tells Ted the
  numbers are appended for it and to never type them itself, so they cannot
  appear twice, and the model keeps the only part it is actually needed for:
  what the food is and what it means.

- **The reminder settings now come from the gate too.** `ted_set_reminder` had
  never been called once, by anyone, in Ted's entire history — so no user had a
  `reminders` row. Checking why found the mechanism rather than a shy model:
  five of the nineteen onboarding steps (`reminders`, `dailyReview`,
  `weeklyReview`, `quietHours`, `morningCommitment`) collect answers that
  `ted_save_onboarding` had no field for, so the only tool that could store a
  check-in time or quiet hours was a second one the model never reached for.
  Ted asked, the user answered, and the answer was dropped. Two halves, because
  they fail separately. Capture: the reminder settings are defined once in
  `_REMINDER_SETTING_PROPERTIES` and offered on both tools, so they ride on the
  `ted_save_onboarding` call the model demonstrably does make. Backstop:
  passing any of those five steps creates the row from `setReminder`'s own
  defaults even when the model sends nothing at all, once per user rather than
  on every later step, because defaults are worth more than an absent row and a
  missing row is what leaves `maxPerDay`, the pause and the quiet-user back-off
  with nothing to read. Saving a preference still proves only `memory` and
  never `cron`, so "8pm check-in is set" is still stripped: storing a time is
  not booking a message. A failed reminder write reports itself and leaves the
  row unmarked so the next step retries, rather than failing the onboarding
  step alongside it.

  What was *not* broken, checked rather than assumed: quiet hours were never
  inert. `decideReminderDelivery` falls back to 22:00–07:00 on a missing row,
  deliberately, so Vandy's directly-created cron pings stayed inside them. What
  a missing row actually cost was the daily cap, the pause, any user-chosen
  quiet hours, and the break offer.

Tests: 340 Python, 75 vitest.

## Order 18 — 3 Sep 2026, afternoon and evening, watching two real users

Everything below was found by watching a live session or by reading what
actually arrived on a phone, not by reasoning about the code. Two testers were
on Ted at once for the first time: Vandy and a second person onboarding fresh.

**Erasure did not survive an open thread.** A wipe at 15:32 cleared Convex and
the durable consent record. The next message was answered inside the same
101-message thread, `_disclosure_was_sent` fell back to scanning the
transcript, found Ted's disclosure from 1 Sep, and reported consent for a user
whose data had just been erased. `_forget_user` now leaves one mark — a hashed
key and a time, strictly less than it removed — and that mark beats the
transcript. The second half was worse: a WhatsApp thread keeps its session id
through a wipe *and* through having every message deleted, and that id had its
own entry in the consent list from 2 Sep. `_capture_turn` read it, wrote
consent back onto the user key, and the reply gate then faked a disclosure into
the empty history on the strength of it — which also swallowed the scripted
opener, because a prepared start needs a history that is genuinely empty.

**"delete my data" failed twice on wording.** First the check wanted the
literal word "delete" and Ted asked "you want me to permanently *wipe*
everything ... all of it?". Then it wanted a question mark and Ted wrote
`reply with the single word "delete" if you mean it.` Both times the user had
asked to be erased, answered clearly, and been told nothing was deleted. A
third vocabulary patch was the same bet again, so the gate asks the question
itself now and remembers asking, with a 30-minute life. "delete" was also
missing from the accepted confirmations while being the exact word Ted was
telling people to reply with.

**Reminders were never scheduled.** `ted_set_reminder` was called for the first
time in Ted's history at 16:35, saved a 10:30 supplement nudge perfectly as its
own item, and nothing scheduled anything — the nudge could not have arrived.
Both save paths now sync the real crontab through `hermes cron create`. The
clock is the user's, not the laptop's: the scheduler runs in Asia/Kolkata and
the second tester is in London. Re-saving edits one job rather than stacking
another; a dropped reminder is unscheduled, but only when the payload actually
carried `items`, because Convex leaves that array alone when it is not sent and
reading its silence as "none" would cancel every nudge a user has. `scheduled`
comes back from the CLI's exit status, so the claim gate now lets "your 10:30
nudge is set" through when it is true and still strips it when it is not.

**Nutrition came out of the model's memory.** It shows its working convincingly
and is soft on any single item, which is how a tester ended up telling Ted a
scoop of whey is "definitely not 120 kcal" and Ted simply agreed. Ted was
right. `ted_food_lookup` reads a 59-food composition table weighted to what
these users eat; the model brings the portion, the table brings the numbers.
Every entry passes the same macro-versus-calorie check the gate applies to a
logged meal, and so does the total a lookup returns, so the two halves cannot
refuse each other. That check is new too: nothing had ever verified a meal was
physically possible.

**The clash guard asked about food that had nothing in common.** First it
compared only time, so a second photo of different food was held back to ask
whether it was the same meal. Then it compared shared words, and a sprouts
salad and a peanut toast both contain onion and tomato — as does half of Indian
food. It is a proportion now, half the shorter list, ignoring words that
describe rather than name a food. The question itself was also wrong: it
offered three options, one of them "replacing" an entry, which is a database
operation and not something anyone eats.

**Ted's words were being deleted.** The block owns the figures and
`words_without_figures` split on `. ! ?` only — but Ted writes short lines,
emoji and usually no full stop. A reply whose middle line held the numbers was
one "sentence" containing figures and went whole. Every logged meal since the
block shipped had arrived as a bare column of numbers with not one human word
attached. This is what "it feels a little off" was.

**Tone, properly.** SOUL.md held 45 "never" rules and six lines of Ted actually
talking, six hundred lines from where the reply gets written, while compression
protects the last twenty messages verbatim — so twenty examples of flat output
sat beside generation and the adjectives sat far away. SOUL.md lost that twice.
Three things: real wrong-beside-right examples in SOUL.md drawn from messages
actually sent on 2 and 3 Sep; `strip_assistant_speak` taking off markdown
furniture and the closing offer nobody asked for; and `VOICE_CARD`, injected
through `pre_llm_call` on every single turn, last, so a few examples sit nearer
than the twenty. Stripping alone was subtraction, and nobody subtracts their
way to a personality.

**Hermes was talking to users directly.** "⚡ Interrupting current task" for
sending two messages in a row, which is how people talk. And "⚠️ Gateway
shutting down — Your current task will be interrupted." eight times in ninety
minutes, one per deploy, all of them ours. Patches 05 and 06. The load-bearing
strings moved to `patches.json`, read by both the guard script and the plugin,
and the gate now checks all six at every boot — `gates:guard` always caught a
dropped patch and always depended on someone remembering to run it.

**Two things this order got wrong and the tests caught.** The macro check
refused "380 kcal, 19g protein", an ordinary partial estimate, until it learned
that too few calories for the macros named is always wrong while too many is
only wrong when all three are present. And blocking the transcript in
`_given_name` also blocked the name given *after* a wipe, which is only ever
read back out of that same transcript — a permanent loop on "what should I call
you?" and a disclosure that never went out. Reverted, with a test naming why.

**A mistake worth recording.** The suite was run once with `python3 -m
unittest`, which does not load `conftest.py` — the file whose whole job is
keeping test state out of `~/.hermes`. It put all eight fixture keys back into
the live state files, including the three cleaned out on 2 Sep. Removed, with
backups, and the pytest requirement is now written into conftest itself.
`TED_GATES_DISABLE_CRON` was added there for the same reason: a test run must
not schedule a real WhatsApp message.

Tests: 340 Python, 75 vitest.

## Order 19 — 4 Sep 2026, the onboarding rebuild

Designed against a real Rex Nutribot transcript (`~/Downloads/WhatsApp Chat - Rex
Nutribot/_chat.txt`) after a morning reading live threads. Vandy's diagnosis:
*"Ted is not understanding the responses well"* and *"people are a little bit in
the mix"*.

**Be sure, or ask.** Eight fixes, all one shape — Ted read something, was wrong,
stored it as fact, and said nothing. `5 foot 4` and `5 feet 4 and a half inches`
both became 152.4 cm. `63.5kgs` became 63.0. `154 lbs` was stored as **154 kg**.
The name parser was a blocklist, so `[image received]`, `Kuch bi yaar` and `31`
all became people's names. Consent only fired when a name was captured, so anyone
who never answered had food logged with no notice, ever. `"9am check-in it is"`
had no save-verb, so two users held promises nothing scheduled. And nothing
handled deferral: "talk after the 15th" got four more onboarding questions.

The damage that made it urgent: Pallavi was told her maintenance was 1,520 when
it is 1,610, inside a sentence promising it was *"worked out only from the numbers
you gave me"*. It used a height 12 cm shorter than she is.

The rule now: a clean answer is stored silently, because confirming everything is
its own kind of pestering. A hedge, a range, a past or goal number, or a converted
unit is read back before it is kept. And a whole-profile summary goes up before
any calorie number — the load-bearing one, because per-field checks only catch
doubt Ted can *detect*, and Pallavi's height parsed cleanly and confidently wrong.
Only she could have caught that.

**One turn at a time.** `display.busy_input_mode` was `interrupt`, which aborts the
turn in flight when a second message lands. On 3 Sep a tester sent five messages in
eighty seconds and Ted answered them out of order. It is `queue` now, and the gate
numbers each inbound message per phone number so a reply that was overtaken can be
recognised as stale.

**The counted five.** The old flow asked for height only when the model was already
about to say a calorie number, so somebody could talk to Ted for days with an empty
profile and then take four questions in a row at the worst moment. Now the name
leads straight into the privacy notice, then *"before i'm any use to you, quick
five questions to get your calorie number. a minute tops."*, then `1/5`. Five in a
fixed order — age, height, weight, sex, activity — which are exactly the
Mifflin–St Jeor inputs, so "five questions" is literally true. **`1/5` is a promise
and a sixth question breaks it**, which is why the city and the check-in time wait
for the first reminder. Then the read-back, then the number as the payoff, then the
goal question, which now falls out of the number instead of being asked of somebody
Ted knows nothing about.

Taken from Rex: the counter, saying *why* before asking, and the number delivered
mid-flow as the reward. **Not** taken: its automatic cut to 80% of TDEE against a
goal weight and a date. A deficit is the one number Ted must never hand anybody, so
the payoff says maintenance and says what maintenance means.

Three asks per question and then Ted stops, and the read-back is bounded the same
way. An unbounded re-ask is the loop that pestered J for a name with a friendlier
face. Giving up costs the calorie estimate and nothing else — `calorie_gate` still
has no age, so the under-18 refusal is untouched.

**A load-bearing bug surfaced while building it.** A correction to a doubted
measurement was read out of the transcript, and Hermes writes the *model's* text to
the transcript, never the gate's. So Ted's confirmation — "so your weight's 60 kg?"
— is not in the history at all; what is there is whatever the model wrote instead,
which was "ok, noting 60kg". "63 actually" found no anchor, fell back to scanning,
and read 60 straight back out of the model's own sentence. The correction was
discarded and the doubted number stood, inside the one mechanism built to stop
exactly that. It is read from the user's own words now, which needs no anchor: a
pending measurement already names its field. **Direct gate calls cannot see this.**
It takes a replay through `_transform_live_response` to get the model's text into
the history, which is what `scripts/ted-onboarding-transcript.py` does.

Also fixed: question 5/5 offers three answers ("desk most of it", "on your feet",
"training regularly") and the parser could read none of them. People answer a
multiple choice by echoing a choice.

464 Python tests. **Existing users are untouched** — with no `setup` key the new
gate is inert, so only new conversations take the counted path.

## Order 21 — 4 Sep 2026, night, the evening review could not read the day

Found in the same log sweep as order 20. At 21:30 a real user's daily review
fired and the tool behind it refused:

    WARNING [cron_6f50de92d4b6_20260904_213033] agent.tool_executor:
    Tool ted_day_summary returned error (0.01s):
    {"success": false, "error": "No WhatsApp user is active"}

Every `ted_*` handler takes the user from `_TURN_CONTEXT`, deliberately, so a
user id in the model's arguments can never redirect a read or a write. The cron
branch of `_capture_turn` returned a voice card and never wrote a context. So
`_cron_reminder_gate` could work out whose evening it was, because it resolves
the recipient itself, and the tools could not.

The user received an evening review with no day in it. That is the product
failing at the one moment nobody is watching, and it fails quietly: the recap
still arrives, so from outside it looks like Ted had nothing to say.

`_remember_cron_turn` now gives a cron run the same turn context a live message
gets. The key comes from the job's own WhatsApp origin, exactly as the output
gate resolves it, so this widens nothing: a cron run reaches the user whose job
fired and nobody else. `_record_turn_arrival` is deliberately not called, since
advancing the live thread's arrival counter could mark a real in-flight turn
stale.

A cron session id is unique per run, and nothing prunes `_TURN_CONTEXT`, so the
registration is bounded at 64 entries. Without that every fired job would leak
one entry for the life of the gateway.

549 Python tests (5 new), 78 vitest, lint, tsc and the build pass.

## Order 20 — 4 Sep 2026, night, the check-in time asked twice

Caught live, in Parth Bhatia's thread, while watching the gateway during a repo
audit. 10:16 pm Ted asked "when should i send your daily check in, evening
usually works best, say around 9?". Parth answered "okay". 10:17 pm Ted asked
again: "one last thing before we start. what time works for your evening
check-in? something like 9pm or 10:30pm."

The second message was `REVIEW_TIME_QUESTION`, character for character. So this
was never the model repeating itself; it was `onboarding_close_gate` doing
exactly its job. That gate refuses to let onboarding sign off while
`dailyReview` is missing from the recorded steps, and `dailyReview` is written
only when the model calls `ted_save_onboarding`. The model asked in its own
words, offered a default, took "okay" as agreement, and saved nothing. The gate
could not tell "answered but not saved" from "dodged", so it asked.

**The asking and the reading were owned by different things.** That is the whole
defect. The model owned the question and was also the only thing that could
record an answer, so an answer it failed to save did not exist.

Both halves now sit in the gate. `review_time_gate` replaces a model-authored
check-in question with `REVIEW_TIME_QUESTION` (once, recording `review_state`),
and reads the next reply itself: `_find_review_time` parses the time, and
`_save_review_time` writes the reminder row and schedules it before marking the
step done. A failed write returns "that didn't save" and leaves the step open,
because a recorded step with no row behind it is the failure the close gate
exists to prevent.

"okay" is settled by design rather than by parsing it. The gate's question
offers examples, not a default, so there is nothing to agree to.

`_find_review_time` reads a bare "9" as 9pm, because the question said evening,
and **refuses** a bare "12" or "0". Midday and midnight are indistinguishable
there, and this file's rule is to ask again rather than store a value nobody
confirmed.

544 Python tests (8 new, including Parth's exact message as a fixture), 78
vitest, lint, tsc and the build all pass.

**Not live.** `npm run gates:guard` reports STALE: the running gateway loaded
the gate at 21:50:31 and the source changed at 22:27:40. Needs
`hermes gateway restart`, which is a human step.

## Order 22 — 5 Sep 2026, night, one nameless exception and an empty credit balance

Two screenshots from Vandy, and the audit behind them.

### The Anthropic key ran out of credit at 19:06

Last Claude call that worked was 19:00:40. From 19:06:30 the log carries 64 of
`Your credit balance is too low to access the Anthropic API`, and every turn
after that was served by `openai/gpt-5.3-codex` over OpenRouter. 32 fallbacks
in one evening. Patch 07 keeps the swap out of chat, correctly, so nothing in
any conversation said Ted had changed model. Credits were topped up at 22:45
and a direct API call confirmed the key live again before the restart.

### Khusha lost a whole day of food to a 1,024-token cap

At 19:36 she sent every meal of her day in one message, about twelve items.
Ted looked all of them up over three `ted_food_lookup` calls and then hit the
output cap while writing the log entry:

    API call #4: model=openai/gpt-5.3-codex in=19359 out=1024 total=20383

`out=1024` exactly, which is `model.max_tokens` in `~/.hermes/config.yaml`.
What she received was the string `Response truncated due to output length
limit`. Nothing was logged.

The recovery already existed. `agent/conversation_loop.py` doubles the token
budget and re-runs, up to four times, and it was gated on an api_mode set of
`chat_completions`, `bedrock_converse` and `anthropic_messages`. The fallback
runs `codex_responses`, which is on none of them, so the truncation fell
straight through to the rollback return. On WhatsApp that return value is not
an operator log line, it is Ted's reply. Fixed as patch 10, plus `max_tokens`
raised to 4096. Output is billed as used, so a short reply costs what it did.

### One nameless exception sent one message three times and five not at all

`plugins/platforms/whatsapp/adapter.py` gives the bridge POST a 30s timeout.
`str(asyncio.TimeoutError())` is the empty string, so the bare
`except Exception as e: error=str(e)` returned `error=""` and the log read
`Send failed: ` with nothing after it.

`_send_with_retry` has a guard for exactly this, whose own comment says the
message "may have been delivered". It matches on the words "timed out". With no
words it could not fire, and the send fell into the branch that assumes
anything not-network and not-timeout must be a formatting problem. Both
symptoms came out of that one blank string:

  * 21:03, Ankita. Her reply was delivered, the bridge was slow to say so, and
    the plain-text fallback sent it again under `(Response formatting failed,
    plain text:)`. Nothing had failed to format. That send timed out the same
    way, so the obligation was never marked delivered, and the 22:16 restart
    redelivered it a third time under the recovered marker. Three copies of one
    message, two of them labelled with claims that were untrue.
  * 21:01, five daily reviews. Wellness Monk, Parth Bhatia, Vishnu, Ankita and
    the owner account all got `delivery error: WhatsApp send failed: ` and
    nothing arrived. Cron has no delivery ledger, so unlike Ankita's message
    they were never retried. Nobody was told, and the schedule shows them `ok`.

Fixed as patch 09, in two places, because either alone leaves the other open:
the adapter names its timeout, and `_send_with_retry` refuses the plain-text
re-send when a failure carries no reason at all.

### The chosen calorie number was stored and never read

`target_choice_gate` asks "want me to track you against *1,700*, or *2,000*?",
records the answer as `tracking_kcal`, and replies "*1,700* it is." Nothing
read it back. `_daily_overview` and `_macro_targets` both used
`maintenance_kcal`, so Gourav, who picked 1,700 at 09:46, was told at dinner he
had 437 kcal left when against his own number he had 137. Four cards, all day,
all wrong. He is the only user affected: everyone else picked maintenance or
was never offered a choice.

`_tracked_kcal` now reads the choice and falls back to maintenance for anyone
onboarded before the choice existed. It cannot smuggle in a deficit, because
the only values reachable are the two the gate computed and said out loud, and
the lower one is floored by `_LOSS_FLOOR_KCAL` before it is ever offered.

Also `Protein: 126g (-6 left)`, which Gourav received at 18:38. A minus sign
doing the work of a word, in a line that still said "left". `_left` now says
`(6 over)`.

### Sent

Apologies to Khusha and Ankita only, at 23:0x, through `hermes send`, which
posts exact text with no model in the loop. The three who silently missed a
9pm review were not messaged: they saw nothing break, and a ping at 11pm to
correct something they had not noticed is more disruption than repair.

### Verified

`gates:guard` green, all 10 patches applied, 603 gate tests and 101 web tests
pass, lint and tsc clean. Gourav's 22:41 day re-rendered against a copy of his
real record reads `Calories: 1,978 (278 over)` at 116%, where it had read
`22 left` at 99%.

### Nine internal sentinels could reach a user, not one

Vandy, after the fixes above: "internal failure message should be in different
language ... not send Response truncated due to output length limit". Correct,
and the string she saw was one of nine. `agent/conversation_loop.py` returns
all of these as the turn's `final_response`, including a thinking-budget block
telling a person in a health chat to run `/thinkon low` or `/model`, and a
no-fallback line telling them to edit `config.yaml`.

The gates cannot catch any of them. `transform_llm_output` fires in
`finalize_turn`, at the end of the loop; every one of these is an early
`return` from inside it. So patch 11 sits at `_sanitize_gateway_final_response`
in `gateway/run.py`, the choke point every chat surface already passes through,
ahead of the existing provider-error rewrite because these are not provider
errors.

One reply covers all nine:

> oops, my brain just blanked there 🙈 that one didn't save, send it again?

It started as three, one per failure shape, and Vandy's note on those drafts
was "it should be generic, not technical, and like fun". Right on both counts:
somebody who just sent a photo of their lunch cannot act on the difference
between an output cap and a dropped stream, so a reply that distinguishes them
is describing the machine to a person who asked about food. What it has to
carry is that the message did not save, so nobody thinks a meal was logged when
it was not, and what to do next. No model name, provider, token count or slash
command.

Reuses patch 02's `display.provider_messages.internal_failure` override, so the
wording is editable in config.yaml without touching the patch. All nine
sentinels verified caught against the live patched file, and five ordinary
replies verified untouched.

### A whole day in one message was logged four times and shown once

Khushboo's second attempt, 22:59, after the truncation fix. One message, her
whole day: "subha do ande ek bread ek cup chai ... phir ek roti thoda sa chawal
and lauki k kofte ... anar ka raita phir sham ki chai or ek mathri ... aadha cup
dudh panch makhane and do natiyal k piece". Four meals, twelve foods.

All four were written. What she received was:

    🍽️ Meal 4 Summary:
    Calories: 160 kcal
    ...
    📊 Daily Overview:
    Calories: 1,053 (857 left)

Her breakfast, lunch and evening tea were in the database and nowhere in the
reply. `_log_daily_entry` held the turn's meal in a single slot and assigned to
it on every call, so three of four were overwritten before the card was drawn.
Ted also told her "lauki kofte aur mathri dono cover ho gaye" when the mathri
was an estimate and the makhana was wrong.

Vandy: "here people can send multiple meals together for the entire day, so
calories has to be a breakdown of all meals together ... it should be a
permanent fix ... bcoz other users will also do it." Four changes, in that
order of importance:

1. **A food is never another food.** `_match_food` matched a table key as a raw
   substring, so `makhan`, the alias of butter at 717 kcal per 100g, matched
   inside `makhana`. Her five fox nuts were logged as ten grams of butter she
   had not eaten. Matching is on whole words now, which fixes the class and not
   the instance.
2. **Describing a food fully no longer loses it.** Coverage was the key's
   character length over the query's, so `chai` found tea and `chai with milk
   and sugar` found nothing at 4/24. She lost both cups that way. Coverage is
   counted in words now, and a word the entry already uses in its own name or
   aliases counts as covered, so the fuller description is the better one
   again. The cutlet the rule was written for is still refused.
3. **Ted says which numbers are guesses.** A food the table cannot answer for is
   still logged, from the model's estimate, and nothing said so. The card now
   ends with "(mathri, coconut and makhana are my estimate, tell me if it's
   off)". 64 rows cannot hold the food of a country, and the permanent answer
   is not to keep adding rows until they can: it is to be honest about which
   numbers are firm, so the person who ate it can correct the guess.
4. **Every meal in a turn is kept and shown.** Meals accumulate rather than
   overwrite, and a turn that logs more than one renders a breakdown. The first
   version of that carried calories alone, which Vandy read and answered with
   "but the meal breakup? calorie and other things". She is right: a calorie
   count on its own is not a breakdown. Each meal carries its own macros now,
   across one row rather than down a column, so four of them still fit a
   screen:

       🍽️ 4 meals logged:

       1. 2 eggs, 1 bread slice, chai
       249 kcal · 16g protein · 11g fat · 18g carbs · 1g fiber

       2. 1 roti, rice, lauki kofta, anar raita
       489 kcal · 14g protein · 16g fat · 68g carbs · 6g fiber

       3. chai, 1 mathri
       155 kcal · 5g protein · 10g fat · 10g carbs

       4. half cup milk, 5 makhane, 2 coconut pieces
       160 kcal · 3g protein · 7g fat · 20g carbs

   A macro the meal has no figure for is left out rather than printed as "0g",
   the same rule the single-meal card already follows. That card is otherwise
   untouched and still reads down a column, because it is the reviewed layout
   and one meal is what most turns are.

Five rows were added to `ted_food_table.json` as well, for the foods real beta
messages asked for and it could not answer: makhana, mathri, coconut, lauki
kofta, and the papad Roshan sent at 15:18. That is the least important of the
five changes and deliberately not the fix.

19 new tests, 622 passing.

## Open — 5 Sep 2026, night, three findings not acted on

Written up rather than fixed. Vandy's call in the morning.

### 1. Ted agreed to a target below his own floor

At 22:42 Gourav asked to keep calories between 1500 and 1600 and Ted replied
"*1550 it is*". His loss target is 1,700 and his resting burn is 1,667, so
1,550 is under both. `target_choice_gate` only listens while
`target_state == "asking"`, and his had closed at 09:46, so a target proposed
later in open conversation reaches no gate at all. This is the one rule
SCOPING.md §9 says Ted must never break, and it was walked around rather than
broken: the model simply agreed.

His card is safe. It counts against `tracking_kcal`, which is 1,700. What is
wrong is the last thing Ted said to him, and the fact that he will probably
get the same answer if he asks again.

The shape of a fix: a gate that reads any number a user proposes as a calorie
target, at any point, and answers with the floor instead of agreeing.

### 2. Check-ins are duplicated on the owner account and mistimed for Pradosh

47 cron jobs are active. Two problems, both visible in `hermes cron list`:

  * **The owner gets everything twice.** `ted:27b6eabe8c71:coq10_am`,
    `:b12_am`, `:vitd_am`, `:omega3_am` and `:iron_pm` deliver to
    `whatsapp:144504426369026@lid`, and `CoQ10 reminder`, `B12 reminder`,
    `Vitamin D reminder`, `omega3 reminder` and `Iron reminder` deliver to
    `origin`, which is the same chat, at the same times. Three daily reviews
    are scheduled too: 21:00 to `origin`, 21:00 to `whatsapp:owner@...` under
    the key `ted:sha256:owner` which is a literal string where a hash belongs,
    and 23:00 to her own chat.
  * **Pradosh's whole schedule is shifted +5:30.** He asked for "2 pm and
    10 pm" and quiet hours from 12am. He has `morning_checkin` at 13:30,
    `midday_checkin` at 18:30, `supplements` at 15:00 and `daily_review` at
    **02:30**, which is inside the quiet hours he asked for. Every one of his
    times is its intended value plus 5:30. No other user's schedule is shifted,
    so this is his record rather than the scheduler.

Separately, and not a bug: Gourav, Vishnu and Roshan each said yes to all four
nudge types and each have six jobs a day. That is what they opted into, but it
is worth knowing what "all of them" buys before more people are asked.

### 3. Ted answers English in Hinglish

Measured across every chat since 3 Sep, counting romanised Hindi markers per
message in what the user wrote against what Ted delivered:

  * 17 of 26 users write **0%** Hinglish.
  * Ted is more Hinglish than the user in **23 of 26** chats. The gap only ever
    runs one way: Ted never answers more English than he was written to.
  * Two users genuinely write it, Khusha at 33% and Vishnu at 28%, and matching
    them is right.
  * The clearest case is Ankita. Five messages, all plain English, "Yes",
    "That's it", "Female", "Desk most of it. 2-3kms walk that's all", "9pm".
    What she got back was "scene set 😌 abhi tak jo last meal khaya hai bhej
    de, start wahi se karein?" and, thanks to the send bug above, she got it
    three times.

This is `SOUL.md`, not gate code. Ted has no rule that says match the language
you were written in, and an India-first persona plus twenty protected Hinglish
examples in context will drift that way every time. Worth a rule rather than
an adjective, on the evidence of everything else in this file that adjectives
lost.

## Order 23 — 6 Sep 2026, evening, one definition of "set up"

Started from a cohort read, not a bug report. 42 people have messaged Ted, 32
have a Convex row, 33 of the 42 showed up on exactly one day. Scheduled nudges
are not the problem: of 47 old enough to judge, 42 got a reply inside 24 hours.
People are lost during onboarding, and the record of who was lost was wrong.

### What was actually broken

`users.status` only ever became "active" when the model wrote
`currentField: "complete"`. "Set up" meant "the model remembered to say so",
which was wrong in both directions at once:

  * **Seven users had everything on file and were still filed as onboarding.**
    Ankit, Ayush, Bhatia, Roshan and three unnamed. Name, age, height, weight,
    goal, a calorie target and a check-in time all present, cron jobs firing,
    and Convex calling them unfinished because the flow that collected the
    answers was a gate flow that never sent the closing write.
  * **Three were filed active on almost nothing.** Pradosh had no age, height,
    weight or calorie target, and had been coached for three days anyway.

Onboarding changed shape repeatedly during the week — five counted questions,
then six, then stretches of open conversation — so which flow a person arrived
through decided which of three stores held their answers: Convex (32 users, 28
onboarding rows), the gate's own file on this laptop (40 users), and the Hermes
cron jobs (16 chats). None of the three reconciled with the others.

A flag cannot survive a flow that keeps changing. A function over the stored
data can, which is also what PRODUCT_BUILD_GUARDRAILS §5 already asked for:
"completion state ... should be calculated from persisted data".

### What was built

`setupStateFor` in `convex/model.ts` is now the single definition, over eight
requirements: privacy notice, name, age, height, weight, goal, calorie target,
check-in time. Everything else in `onboardingFields` is a preference; these
eight are what Ted needs before "how am I doing" has an answer.

  * `users.status` is derived. `refreshSetupStatus` recomputes it after every
    write that can close a gap — `saveOnboarding`, `setTarget`, `setReminder` —
    and is the only thing outside deletion that may move a user between states.
    `currentField: "complete"` from the model no longer sets anything.
  * A stated age under 18 returns `blocked: "minor"` rather than a missing
    field, because re-asking is the one response worse than doing nothing.
    **Tanishka is 17 with a weight-loss goal**, found by this and not before.
  * `privacyNoticeSentAt` is a new optional field, deliberately not
    `consentAcceptedAt`. What Ted sends is a notice with an opt-out, not a
    request for agreement, and recording delivery in a field named "accepted"
    is the fake-confidence §1 forbids. The gate had been sending the notice
    since the first user and writing it only to its own file, so Convex held it
    for nobody while the gate's record covered 31 of 32.
    `_mark_disclosure_sent` now tells Convex as well; without that every new
    user would be permanently one requirement short.
  * `setupAudit` and `refreshSetup` are builder read-backs, reached with the
    shared secret and never model tools, listed in `REQUIRED_CONVEX_ACTIONS` so
    `npm run convex:check` proves production has them.

### The reconcile

`npm run setup:reconcile`, dry run by default, `--apply` to write. It copies
what the gateway already proved into Convex and asks Convex to recompute. It
invents nothing: where no local record holds a value the gap stays open and is
printed as a question a human still has to ask. It creates no users, sends no
message and touches no cron job, so running it cannot make Ted speak.

Applied to production at 18:50 IST. 31 privacy-notice timestamps, 12 names, one
age, one weight, one check-in time. **9 of 32 users now active, and all 32
agree with the derivation** where 5 were labelled active before and only 2
deserved it. A second `--apply` writes nothing, which is the property that
makes it a fix rather than a patch.

24 of the 31 notice timestamps come from the user's own `createdAt` rather than
a delivery record, because `delivery_obligations` only reaches back to 2 Sep.
The notice goes out on the first turn, so that is the tightest defensible
bound. The script prints that count rather than hiding it.

### What this does not do

Nothing reads `users.status` — not the gate, not the model, not the site — so
no user-facing behaviour changed today. This makes the record true, which is
what the next steps stand on. `npm run submission:report` will now say 9 active
rather than 5.

23 users still have a real gap, and no local record can close them:
calorie target 20, check-in time 16, weight 15, goal 14, height 14, age 13.
Those are questions, which is step 4.

### Still open, agreed but not built

  1. **One asker.** The gate's counted flow is deterministic, capped at three
     asks and resumable; the model can still write any of 19 `currentField`
     values in any order. Extend `SETUP_QUESTIONS` to seven with the check-in
     time and drive it from `missingFor` rather than a hardcoded list.
  2. **Revival messages, by tier.** Nobody gets "how's it going". Each person
     is asked for exactly what is missing. Tier 3, the 15 who said hello and
     left, waits until 1 lands or they die on the same question again.
  3. **The silence ladder.** Today it is four unanswered nudges, then the break
     offer, then Ted is silent forever with no way back. Roshan entered that
     state at 13:00 on 6 Sep. Every stop needs a scheduled return.
  4. **Five daily reviews failed to deliver** on 5 Sep at 21:01:58 with
     `WhatsApp send failed` — nagga, Bhatia, Ankit and two others — and
     `last_status` still reads `ok`. No retry, no alert.
  5. **`maxPerDay: 3` against 5 enabled items** for three users, 10 `dailyCap`
     suppressions logged, and two of the five items are both water.

## Order 24 — 7 Sep 2026, the day two stores disagreed in three different ways

Every finding today is the same shape: a fact Ted holds in two places, where
nothing reconciles them and the copy the user sees is the stale one. Order 23
fixed that for "is this person set up". Today it turned up three more times, and
one of them was a child safety hole.

### 1. UD was scored against a surplus while being told he was cutting

Asked "lose, gain, or stay consistent?" he answered "Gaining" at 14:15, then
said "I want to lose weight" five times between 14:36 and 14:50, once with
"idiot" attached. Convex moved him to `loseWeight`. The gate's own record kept
`gainWeight` and `tracking_kcal` 2580, and `_tracked_kcal` is what every meal
card counts against, so his food was being measured against a gaining number.

`setup_gate` computes that figure once when the counted questions close and
nothing updates it when the goal later changes. Namrata drifted the same way at
11:07 the same morning: "holding steady", corrected to "i want to lose weight"
two minutes later.

`scripts/ted-repair-goal-drift.py` realigns the two, taking the number the user
was already told unless it is below their resting burn.

### 2. The number he was told was below his own floor

1,850 against a resting burn of 1,956. `_loss_target` has always refused to go
under resting, but it only ever guarded the number *the gate* computed; a number
agreed in open conversation goes to `ted_set_target` and lands in the `setTarget`
mutation, which checked nothing. Gourav got 1,550 against 1,752 the same way on
5 Sep. Both were agreed after the gate's target question had closed, so nothing
was listening.

`calorieFloorFor` now sits in the mutation, which is where every target lands
however it was reached. It refuses rather than quietly raising: clamping would
leave Ted having said one number while the row held another, which is the whole
of what went wrong above.

`users.sex` is new and the guard does not work without it. The male and female
terms in Mifflin-St Jeor are 166 kcal apart, so a floor that assumes the lower
one sits at 1,790 for UD and would have let his 1,850 through. The gate has
collected sex as question 4 of 6 all along and never sent it.

`restingEnergy` rounds down, not to nearest: Python's `round` is banker's
rounding and `Math.round` is half-up, they disagree on Gourav's exact 1752.5,
and a floor one kcal above the gate's would refuse the gate's own number.

Verified on production with a probe profile matching UD's: 1,850 and 1,955
refused, 1,956 and 2,000 accepted, probe deleted.

### 3. The gate believed a 17-year-old was 50

Tanishka answered "17 I said u brother" on 4 Sep and Convex holds 17. The gate
held **50**, which is her weight: the answer landed on the wrong question, the
same anchoring bug `ted-repair-swallowed-weights.py` was written for, pointed
the other way. The gate is the half that decides whether `calorie_gate` refuses,
so for six days Ted believed she was an adult.

Nothing reached her. Every message she ever received was checked and none
carries a calorie number; she stopped replying before the flow got that far.
That is luck, not a safeguard.

`scripts/ted-repair-profile-drift.py` fixes it, and the age rule is deliberately
not "Convex wins" but **the lower of the two wins**, because the only direction
with a cost is believing a child is an adult. It also sets the `minor` flag. 13
users had some version of the same drift.

The owner reported the harmless version of it twice the same afternoon: setup
restarting mid-conversation (`setup_gate` saw no age) and the "old format" meal
card (`_tracked_kcal` found nothing, so `_daily_overview` dropped the "left"
figure and the bar). One missing profile, two symptoms.

### 4. The win-back

33 of 42 people who ever messaged Ted came on one day and never returned. The
nudges are not the cause: 42 of 47 got a reply inside 24 hours. They are lost
during setup, and the largest leak is the goal question.

`scripts/ted-winback.py` sends each quiet person a message asking for exactly
what `setupStateFor` says they are missing, generated from their own answers,
or handing them their number where nothing needs asking. One per person ever,
recorded; one every 12 minutes; never in their quiet hours; never to someone who
messaged in the last two hours; never to a blocked user.

It quotes the stored target rather than recomputing it. The first draft
recomputed and would have told Amit 1,620 against the 2,400 on his row — a fresh
version of the bug the rest of the day was spent removing.

11 sent on 7 Sep from 15:54. Group E, the 14 who never really started, is held
back deliberately: three of the five in group D are being asked the same goal
question that lost them, and if they do not answer, the question is the problem
and group E would burn the same way.

**No replies to the first six after 70 minutes.** Worth watching rather than
concluding, but those six were the easy ones — two were handed a finished number
and four only had to type a time.

### Verified afterwards

Every row from the 6 Sep snapshot compared by id across all seven tables:
**nothing lost**, and `dailyEntries` shows zero field changes, so no meal
history was touched. Three users moved active → onboarding (Pritika has no goal,
PG no target, Pradosh no age/height/weight); all three were wrongly active
before. Gourav is the only person whose stored target sits below the new floor,
so a future re-save of that exact number will be refused.

### Still open

  1. **The owner's duplicate reminders.** 12 cron jobs where about 7 belong: two
     parallel supplement sets pointing at the same chat, and the set recreated
     at 11:03 came back daily when the originals were weekdays, Mon+Wed, Tue+Thu
     and monthly-on-the-17th. Monday now schedules 10 messages, five at 10:30,
     and `maxPerDay: 3` silently drops the rest.
  2. **One asker.** The gate's counted flow is capped and resumable; the model
     can still write any of 19 `currentField` values in any order.
  3. **The silence ladder.** Four unanswered nudges, then the break offer, then
     Ted is silent forever with no way back.
  4. **Five daily reviews failed to deliver** on 5 Sep at 21:01 with
     `WhatsApp send failed` and `last_status` still reading `ok`.
  5. **Ted talking to another Ted** in one chat on 7 Sep, writing "this is
     another attempt to make me claim I asked something I didn't". Two stayed
     internal; one was delivered at 11:06.

## Order 25 — 16 Sep 2026, the scorecard read as a bug list

The Build Week score and code review came back. The project is submitted and is
not being resubmitted, so both were treated as free diagnosis: every finding
ranked by user harm, nothing done because a parameter carried weight. Two of
the six code-review concerns were wrong and are recorded as such below.

Four commits, all deployed and pushed.

**`0ef103e` — the dashboard stopped guessing.** `/metrics` now reports
activation separately from saying hello: 46 conversations started, 13 people
who finished setup and logged something, 10 who came back on a second day, and
10 logging while Ted still counts them unfinished. It also carries a panel
naming what setup is waiting on, which is where the real finding was (below).
The lifetime visitor figure said "412 people across every week on record" and
could not have: the visitor hash has the week baked into it, so a returning
visitor arrives as a second hash. It is `visitorWeeks` now.

**`8eb9ecf` — a refused write stopped being reported as an outage.** Convex
returns 400 when a mutation throws; `urlopen` raises that as `HTTPError`, which
subclasses `OSError`, so the gate's existing except clause caught it and called
it a storage outage. A value Ted refused on purpose therefore told the user
"that one didn't save, my fault not yours. send it again?" — an apology for a
deliberate act, and an instruction that can never work, because the same value
earns the same refusal every time. The reason was lost too: `http.ts` claims the
detail stays in the response for the log, and `urlopen` raises before anything
reads the body, so the log recorded "HTTP Error 400: Bad Request" and nothing
else. **This closes the open item about raw `ArgumentValidationError` strings
reaching a chat.** They never could. The error was caught too well, not too
little.

**`9a913a3` — the range check moved to the write.** The bounds added after
Pallavi's 4cm height guard facts being promoted to profile columns, and
`setTarget`, `saveOnboarding` and `logDailyEntry` are all reachable without
going near them. Steps, water, macros, workout minutes and workouts per week
had no bound anywhere at all, and the meal macros are estimated by a model from
a photograph. Age is deliberately the widest at 5–120: the 18+ rule is enforced
by `setupStateFor` returning `blocked: "minor"`, which it can only do if the age
was stored, so refusing to write 17 would be the safety regression rather than
the safety check. Every value in production was checked against the new bounds
first; nothing would be refused.

**`95ebf32` — one writer for who finished setup.** `onboarding.completedAt` was
written only inside `saveOnboarding` while `users.status` is derived by
`refreshSetupStatus` from seven call sites, so anyone whose last missing field
was closed by `setTarget` went active without the column. GT and Shreya were
both in that state; Shreya had every requirement on file and 16 logged entries
and counted as neither onboarded nor activated. Pradosh and Pritika were wrong
in the other direction, and because the two cancelled, 17 users were active and
17 rows carried a `completedAt`, so every aggregate check here was green while
four people were wrong. The wrong rows heal on that user's next write.

### The finding no reviewer made

Of the 29 users part-way through setup, the missing requirement is:

    checkInTime 22 · calorieTarget 21 · goal 17 · weight 16 · height 15 · age 13

The check-in time question is where the funnel actually leaks, and it already
has two repairs behind it (orders 20 and 22). Ten people log meals, water and
workouts while Ted counts them unfinished, so setup completion is not what
gates value for them.

### Two concerns the code review got wrong

- **The deletion promise.** `privacy/page.tsx:65` already says in plain words
  that photos, voice notes and conversation records sit on the machine and need
  a manual request. The page is honest. The manual half is still fragile, which
  is a different complaint.
- **The lint suppression.** `eslint.config.mjs` exists and is a real Next
  config. An artifact of the reviewer seeing ten files.

## Open — 16 Sep 2026, two findings not acted on

### 1. Nothing records whether a reminder arrived

`gateReminderDelivery` increments `sentCount` and `unansweredNudges` when a
nudge is *cleared*, not when it is delivered. The common case is already
guarded: `_whatsapp_can_deliver()` sits above `_reminder_allowed()` in
`_cron_reminder_gate` precisely so a down link cannot march a present user
toward a break offer.

`delivery_obligations` holds 226 rows, 223 delivered and 3 abandoned, and every
one is a chat reply: a cron job hands its text straight to the live adapter and
writes no obligation row. But a record does exist, in the wrong place.
`_reached_by_cron_since` in `ted-watch.py` already reads `agent.log` for
"delivered to whatsapp:<chat_id> via live adapter", which is exactly the fact a
refund would need.

The problem is that the log rotates, so a delivery older than the current file
cannot be seen. `check_dropped` can live with that, because being wrong there
only ever means reporting somebody as answered who was. A refund cannot: it
would hand back counts it could not justify.

It is not theoretical. The open list above already records five daily reviews
failing to deliver on 5 Sep at 21:01 with `last_status` still reading `ok`.
Those five were counted.

The shape of a fix, in order: make a cron send write an obligation row like
every other send, so delivery is recorded durably rather than in a file that
rotates, then refund the count against it. That is a gateway change and would
be patch 13.

Counting after delivery instead is the wrong trade: a lost confirmation would
double-send, and two nudges is worse than none.

### 2. ~~Three users were told their save failed and never got the message~~

**Already handled, and this entry was wrong.** Written from the raw
`delivery_obligations` rows without checking what already reads them.
`check_dropped()` in `scripts/ted-watch.py` exists for precisely this, names GT
on 11 Sep and Ankiita on 15 Sep in its own docstring, and correctly closes a
case when a later message reaches the same person, which is why Shreya on
14 Sep is not owed anything. It reported `nobody is waiting` on 16 Sep, so both
have since been reached.

Patch 12 is also not a gap. It cut the redelivery window from 24 hours to ten
minutes on purpose: a reply is worth sending while somebody is still in the
conversation it belongs to and not after, and "that one didn't save, send it
again" arriving three hours later is worse than silence. Retrying those three
would have undone a considered decision.

What the watchdog does not do is alert anywhere except email. `--dry-run`
reports `pushover --- not configured`, and the whole point of that script is an
alert that does not depend on the thing being watched.

### 3. The model has been failing over since 11 Sep

`ted-watch.py --dry-run --force` on 16 Sep at 21:22 reports **"the Anthropic
credit balance is empty, 14 failed calls in the last 24h (seen from at least
2026-09-11 00:23:58)"**. Ted is still answering, on the fallback model, which is
exactly the state the check was written for: nothing looks broken from outside
and every reply for five days has come from the second-choice model.

Top up the primary provider. This costs nothing to fix and is affecting every
conversation.

## Order 26 — 16 Sep 2026, night, the pause that silenced nothing

### The one that matters

Sarah asked to be paused at 12:50. The conversation was correct in every word:

    12:50  Sarah   Yes please do pause
    12:50  Ted     for how many days should i pause the reminders?
    12:55  Sarah   7 days
    12:55  Ted     reminders paused for a week, back on 23rd 🙌

The number written into `reminders.pausedUntil` was **26 Sep 2025**. A year in
the past, so `isPaused` returned false, every guard below it passed, and her
21:00 daily review reached her eight hours after Ted promised a week's silence.

`paused_until` was described to the model as "Epoch milliseconds". It had "7"
right and "the 23rd" right and was only wrong converting one into the other, so
it is no longer asked: the tool takes `pause_days` and `_set_reminder` computes
the moment from `_local_now`, the same clock `_spoken_date` builds the sentence
from. It also calls `_mark_paused` on that path, because Sarah had no
gate-side record at all, which is why the cron check could not save her either.
`pauseProblem` in `model.ts` refuses an already-expired pause at the mutation,
the same way the calorie floor sits there rather than only in the gate.

Her row was corrected by hand to 23 Sep 2026. She was the only user affected;
five others hold correct gate-side pauses. That was luck. The daily-review
change earlier the same evening (`1d5e081`) was argued safe on the grounds that
"an explicit pause still silences everything", and nobody read the column
before believing it. Had one of those eleven held a broken pause, that change
would have made this worse.

### Also shipped

- **`cache_ttl` 5m → 1h** in `~/.hermes/config.yaml`, which is **not version
  controlled**. ~438 Sonnet calls a day each carry ~11k tokens of SOUL.md, and
  the traffic is bursty, so a five-minute cache was written, expired unread and
  written again, costing more than not caching. That, not the length of
  SOUL.md, is why a top-up lasted a single day.
- **`npm run forget -- --who <name>`**, which turns "reply and Vandy deletes it
  by hand" into one command. The machine holds five things, not the two the
  privacy page implies; `delivery_obligations.content` carries reply text and
  nothing else deletes it.
- **`npm run timezones`** and nine backfilled timezones. 18 of 24 people with a
  check-in time had none, because `REVIEW_TIME_QUESTION` had lost its city ask.
  Restored, with a test.
- **A refused write now names the field** rather than saying "i couldn't file
  that one", and a failed write is retried once before the user is asked to
  resend anything.

### Held deliberately, do not lose

`0a0a90e` loosened "a reply is at most two short sentences" to a rule about
nagging rather than length, and `cc93527` reverts it in the tree. It is held,
not rejected: it changes what users see and should land when somebody is
watching. `git revert cc93527` puts it back.

The baseline to judge it against, measured over 238 replies from the seven days
to 16 Sep: **85% one sentence, median 89 characters, 2 over two sentences, and
zero with a second question, a mid-sentence dash or an exclamation mark.**
Re-run that a day after it ships; a jump in the median, or replies that open
with what is missing, is the signal to revert again.

### Still open

Patch 13 (a cron send writing an obligation row, so the reminder count can be
refunded), Hermes being unreviewable from this repo, and the nine users with a
check-in time and no timezone who can only be asked.

## Readiness for inviting beta users — checked 3 Sep 2026, 15:10

Asked directly whether Ted could be distributed. The answer was no, and two of
the reasons were found only by checking rather than by remembering.

1. **`ted_set_reminder` has never been called. By anyone. Ever.** *(Fixed and
   live 3 Sep 15:22 — see the reminder-settings entry above. Left here because
   the count is still the check: a fresh onboarding should now leave a
   `reminders` row behind whether or not that number ever moves.)* Across all of
   Ted's history the model has used `ted_log_entry` (14), `ted_day_summary` (4),
   `ted_save_onboarding` (3), `ted_memory_save` (3), `ted_set_target` (2) and
   `ted_memory_delete` (1). No user therefore has a `reminders` row, which means
   no stored check-in time, no quiet-hours preference, no daily cap, and **the
   quiet-user back-off built in order 17 can never fire**: `unansweredNudges`
   lives on that row and `gateReminderDelivery` returns early when it is
   missing. Reminders still arrive, because they are Hermes cron jobs created
   directly, but the whole policy layer is unexercised in production. The fix is
   the same one the meal numbers needed: stop hoping the model calls the tool.
2. **Two-user isolation has never been tested.** `PRODUCT_BUILD_GUARDRAILS.md`
   §4 makes it the explicit pre-invite gate. Ted has served exactly two distinct
   user keys in its history and never two at once. Everything is designed for
   it; nothing has proved it. This is the one failure that cannot be walked
   back.
3. **Nothing from 3 Sep has run in a fresh session.** Every test that day was
   inside one 84-message thread. A new tester gets a clean session, so
   onboarding, the disclosure, the name question, the check-in time and the new
   meal block are all on the untested path.
4. **`session_reset.mode` is `none`** *(fixed 3 Sep 15:09: `idle`, 720
   minutes)*, so a thread grows without bound. With
   `compression.protect_last_n: 20`, twenty verbatim examples of Ted's recent
   output sit in context permanently. That is what beat SOUL.md twice on 3 Sep,
   and it will do the same to any real user once their thread is long enough.
   Setting `idle` or `daily` would stop it.
5. **Ted runs on Vandy's laptop.** Closing the lid takes Ted down for every
   tester at once. Workable for a handful of people who can be messaged
   directly; not for open distribution.

### Readiness re-checked — 3 Sep 2026, 18:00

Of the five reasons Ted could not be handed out at 15:10, three are closed.

1. **`ted_set_reminder` had never been called** — closed twice over. The
   settings ride on `ted_save_onboarding` now and a row is created with
   defaults regardless, and reminders actually reach the crontab. Confirmed
   live: `ted_onboarding_reminders_saved created=True` at 16:05, and
   `ted_set_reminder` itself finally fired at 16:35.
2. **Two-user isolation has never been tested** — still true, and now the only
   reason left that is a privacy incident rather than a bad experience. It is
   also no longer a pre-invite gate in practice: the WhatsApp account shows at
   least six people have already used Ted. That makes it overdue rather than
   less important.
3. **Nothing from 3 Sep had run in a fresh session** — closed. A second tester
   onboarded from scratch on the new code: scripted opener, disclosure at
   16:03:12, name, goal, check-in time, quiet hours, city, then a logged
   workout and meals.
4. **`session_reset.mode` was `none`** — closed at 15:09, `idle` at 720
   minutes.
5. **Ted runs on Vandy's laptop** — unchanged, and unchangeable this week.
   Workable for people who can be messaged directly when the lid closes.

The honest summary is that the product is much better than it was at 15:10 and
the one thing standing between it and an invite is the same thing that was
standing there then, now with more users already behind it.

### Still open after order 16

1. ~~**`main` is 11 commits behind `ship/landing-v6`**~~ **Resolved.** As of
   4 Sep `main` is 52 commits *ahead* of `ship/landing-v6` and 0 behind, and it
   is in sync with `origin/main`. The held-back `c2d82be` no longer applies.
2. **Preview deployments all fail.** `CONVEX_DEPLOY_KEY` and
   `NEXT_PUBLIC_TED_WHATSAPP_NUMBER` are Production-only, so every git push
   dies at `npx convex deploy` and there is no preview URL to check.
3. **PDFs are refused, not read.** If health-plan PDFs are wanted for real, the
   extraction has to happen somewhere Ted can reach.

## Code status

- The live landing page is the **v8** design, shipped under the older filename `public/landing-v6.html` — the name is the route's history, not the design's version. `design-experiments/ted-landing-v8/README.md` is the authoritative description of what is on the page. It is a static file rather than JSX, served at `/` by a `beforeFiles` rewrite in `next.config.ts` so what ships is byte-for-byte the design that was reviewed. Confirmed on 3 Sep: the bytes served at `heyted.vercel.app/` are identical to the repo copy. `src/app` no longer defines a page at `/`; everything else — `/privacy`, `/robots.txt`, `/api/*` — is still Next.js. To go back to a React landing page, delete the rewrite and add `src/app/page.tsx`.
- The page carries the supported input formats, the nudge, reminders the user controls, the evening review, and the privacy boundary. Its WhatsApp threads now play themselves: each is a scene that runs when it arrives and rewinds once it has left. The earlier version was scrubbed by the scrollbar and froze mid-sentence whenever scrolling stopped. Both `wa.me` links use the agreed opening message, "Okay Ted, let's do this 💪", and the number the rest of the product uses. 78 vitest tests, 536 Python tests, lint, `tsc --noEmit` and the production build all pass (re-run 4 Sep).
- The shipping work started on `ship/landing-v6` (`7f64fb3`) and has since been merged forward: `main` is now 52 commits **ahead** of that branch, 0 behind, and in sync with `origin/main`. Vercel's production branch is the GitHub default, so `main` is what ships. The old warning that `main` was 11 behind, and the held-back `c2d82be`, no longer apply.
- `design-experiments/` holds the lineage that led here — `ted-landing-v5-editorial`, `v6`, `v7`, `v8`, `tbh`, `conversation`, `recovery-led`, `characters`. v8 is the one that shipped (as `public/landing-v6.html`); the rest are not imported and not deployed.
- A Next.js 16 TypeScript application exists and passes lint and production builds.
- The public GitHub repository is `connectwithvandy/build-week-health-accountability-partner`. An earlier note here named `whatsapp-accountability-partner-ted`, which is the Vercel project name, not the repo.
- GitHub `main` is connected to Vercel, but **only production has the environment it needs**. `CONVEX_DEPLOY_KEY` and `NEXT_PUBLIC_TED_WHATSAPP_NUMBER` are set for Production only, so every Preview build dies at `npx convex deploy` with "no Convex deployment configuration found" — every push shows a red X and there is no preview URL to check before shipping. Production is currently updated by running `vercel --prod` from this machine; the live deployment was made that way at 01:43 IST on 3 Sep.
- Two public Vercel URLs serve the same deployment: `https://heyted.vercel.app` (the one to share) and `https://whatsapp-accountability-partner-ted.vercel.app`. Both returned 200 on 3 Sep 2026, and both served byte-identical HTML on 4 Sep.
- Vercel Web Analytics was added on 4 Sep 2026 and needed wiring twice. `/` is a static file served by the `beforeFiles` rewrite and never passes through the App Router, so `@vercel/analytics` alone would have counted only `/privacy`; `public/landing-v6.html` therefore carries `<script defer src="/_vercel/insights/script.js">` directly, and `src/app/layout.tsx` carries `<Analytics />` for every route that is React. Verified live: the tag is served on both hostnames and `/_vercel/insights/script.js` returns 200 (it was 404 before the deploy). **Visitor counts start from 4 Sep — there is no earlier traffic data and none can be recovered.**
- `npm run submission:report` prints the Build Week numbers from the production Convex deployment and writes `SUBMISSION.md`. Read-only by construction: the only command it can run is `npx convex data`, and it refuses to spawn anything else. It reads the deployment from `TED_CONVEX_SITE_URL` in `~/.hermes/.env`, not from `CONVEX_DEPLOYMENT` in `.env.local` — the latter points at a dev deployment holding none of the live data.
- Convex is connected to the Next.js application.
- Vitest and React Testing Library are configured.
- A secret-free `.env.example` documents Convex, OpenAI, Hermes and Vercel settings without containing credentials. It now also names `TED_CONVEX_SITE_URL` and `TED_HERMES_SHARED_SECRET`, which were live in `~/.hermes/.env` but documented nowhere; `register()` names whichever one is missing at WARNING level instead of dropping the memory tool in silence.
- The calorie parsers no longer read quantities as body measurements. `_find_age` needed only "i'm" plus any number within twelve characters, so "i'm having 2 rotis and dal" set the age to 2 and every later turn came back as the under-18 refusal. It now requires a year marker, an `age` label, or "i'm N" with N in 10–99 and no food, unit or measurement word after it. The band deliberately starts at 10 rather than 18: at 18 the parser stops seeing "i am 17" at all, which would silently drop the under-18 refusal. Height, weight, sex and activity gained the answer-context parser age already had, so a bare "170" after "how tall are you?" is accepted within a sanity range, and "i am a woman, mostly at a desk" resolves both fields. The 18+ question is scoped to the calorie-target flow per SCOPING.md section 7, so a per-food estimate is not gated and one nutrition question no longer gates the next six turns; a known minor is still refused any calorie number, and that check now runs ahead of the narrowing. Every gate reply is rewritten in Ted's voice and says why it is asking. The under-18 refusal string and the Mifflin–St Jeor formula are unchanged and covered by tests.
- The test suite no longer touches live gateway state. Three unit-test fixture keys — `real-memory`, `staged-memory` and `wrong-tool` — were sitting in `~/.hermes/state/ted-safety-gates-disclosures.json`, where a key colliding with a real user key would mark that user as already-disclosed and skip a disclosure they are owed. Every machine path is now overridable (`TED_GATES_STATE_DIR`, `TED_GATES_AGENT_LOG`), a root `conftest.py` redirects them before the module imports and drops any inherited Convex credentials so a run cannot write to production, and tests assert no gate path resolves under `~/.hermes`. Confirmed by md5: both live state files are byte-identical before and after a full run. The three fixture keys were removed from the live file on 2 Sep and the gateway restarted so the cleaned file was reloaded.
- Structured writes are live in the code. `ted_log_entry`, `ted_day_summary`, `ted_set_target`, `ted_set_reminder` and `ted_save_onboarding` write `dailyEntries`, `targets`, `reminders` and `onboarding` through new mutations in `convex/ted.ts` and actions in `convex/http.ts`. `convex/schema.ts` is unchanged. Every handler takes the user from the live turn, so a user id in the model's arguments is dropped at two layers. Dedupe collapses a re-delivered WhatsApp message into one entry; two separate glasses of water stay separate. Corrections supersede the original rather than deleting it, so the day counts a corrected meal once. Deployed to Convex production on 2 Sep 2026; all five actions answer in production and reject a bad payload with a validation error rather than "Unsupported action".
- Verified on a live WhatsApp thread on 2 Sep 2026, not only in tests. "i'm having 2 rotis and paneer" got a meal reply instead of the under-18 refusal; the reply kept its numbers through the claim gate; `ted_log_entry` wrote the meal to production Convex; a correction to 3 rotis superseded the original rather than duplicating it, leaving the original at state `corrected` and the day at one meal, 470 calories, 27g protein; and `ted_day_summary` read those same totals back at 19:05 after a gateway restart at 19:00. Orders 03, 05 and 10 are confirmed working in production.
- The gate guard was wrong twice on its first live runs, both fixed. `~/.hermes/gateway.pid` holds a JSON record rather than a bare integer, so the guard reported "gateway is not running" for a gateway that was live — the worst failure this script can have. It also could not tell a loaded gate from a current one, so it reported green while the running gateway served pre-edit code; it now compares the gate source mtime against the load time and reports STALE.
- `scripts/ted-gate-guard.py` is the hard stop for an ungated Ted. Hermes swallows a plugin load failure (`hermes_cli/plugins.py`, `except Exception` in `_load_plugin`) and keeps serving WhatsApp, so the check has to come from outside: the guard imports the shim, confirms the gates registered *after* the last gateway start, and stops the gateway if they did not. Run it after every restart, rename or gate edit.
- *(Describes the pre-v8 page. Kept as the record of the design intent; for what is actually on the page now see `design-experiments/ted-landing-v8/README.md`.)* The redesigned mobile-first landing page is intentionally short: one promise, one clearly labelled example day centered on the 7:42 PM recovery moment, one evening review, a plain privacy/safety note, and repeated WhatsApp handoff.
- The warmer, playful design experiment was rejected and removed. The previous local landing design is restored. Reduced-motion settings are respected.
- The WhatsApp buttons pre-fill “Okay Ted, let's do this 💪”. The live page is static, so the number is written into its markup rather than read from `NEXT_PUBLIC_TED_WHATSAPP_NUMBER` at runtime; `__tests__/landing-page.test.ts` compares the two so they cannot drift apart. The variable is configured locally and on Vercel.
- The website-matched Ted profile picture and cover image are saved in `docs/brand/` and have been uploaded to the WhatsApp Business profile.
- The latest landing page is live in production at `https://heyted.vercel.app` — the URL to share and to submit. The auto-generated `whatsapp-accountability-partner-ted.vercel.app` serves the identical deployment, so it is not wrong, just not the one to hand out. It uses the shorter four-section story, the WhatsApp conversation hero, the new split `Message Ted` action, and no visible dash punctuation in user-facing copy.
- Official OpenAI documentation confirms that `gpt-5.3-codex` accepts text and image input but not audio. Voice-note transcription therefore remains separate from the conversational model.
- Hermes now uses OpenRouter with `anthropic/claude-sonnet-5` as primary and `openai/gpt-5.3-codex` as its sole fallback. Separate direct Hermes calls returned the exact requested replies from Codex before the switch and Sonnet after it. The WhatsApp path and a forced fallback event have not been re-verified after this change.
- The default production Convex deployment is `hardy-scorpion-901` in Europe (Ireland).
- Vercel deploys Convex functions and the Next.js application together on every production build.
- The local Vercel CLI was upgraded to version 59.11.2 on 2 September 2026.
- The production build deliberately uses Webpack during Build Week because this is the path already verified locally and on Vercel. Reconsider the default Turbopack build after the demo instead of changing the build path mid-week.
- The production Convex schema defines user-owned records for consent and identity, resumable onboarding, per-user facts, targets, reminder settings, and day-scoped progress entries. It includes user/date indexes, deduplication keys, corrections, and a separate pending-clarification state so uncertainty is not saved as confirmed data.
- The Convex data-contract tests, Convex TypeScript check, and lint pass. The schema and authenticated `/ted-memory` endpoint are deployed to production. The endpoint accepts only the shared Hermes secret; internal queries and mutations are not public.
- Hermes `SOUL.md` was rolled back from the compressed 5,715-character rewrite to the exact earlier Ted persona recovered from the 9:24 PM request snapshot (11,270 bytes). WhatsApp access and gateway settings were not changed.
- A static `/privacy` route now answers what is stored, who can see it, how long it is kept, and exactly how to request deletion. The existing landing-page footer links to it. It is live at `https://heyted.vercel.app/privacy` and returned HTTP 200 from an unauthenticated public request. All 9 web tests, lint, and the production build pass; no interactive browser was connected in this session.

## Order 27 — 17 Sep 2026, night, the roadmap's first four, and three faults it did not know about

Roadmap v2 arrived with all 48 tasks marked "Not started". Four of them were
not, and the first job was finding out which, because planning 23 days on top
of a status column that is wrong in four places is how the wrong work gets
done. T00 to T03 were taken in dependency order. All four are closed except
one bullet, deferred on purpose, and one thing that needs two real people.

### The one that matters

`_load_onboarding_state` returned `{}` for every kind of failure. That file
holds the 18+ blocks and nothing else does — deliberately, because the
conversation gets compacted and `userFacts` is writable by the model, so
neither can hold the one rule that must not be talked around.

So a truncated write or a bad hand-edit emptied every block at once, and
nothing anywhere said so. The plugin still imported. `ted-gate-guard.py` still
printed "Gates are on". The most serious alarm in the project would have stayed
green while the person it was protecting became a new adult user.

Proven on a truncated copy of the live file: 55 users and 1 minor block become
0, and Ted answers "eat 1200 a day". It now separates the two legitimate empty
states — no file, and a valid file with no users — from a fault, and refuses
with `STATE_UNAVAILABLE` rather than an unguarded reply. Raising was rejected:
Hermes swallows a plugin's import error, so a raise trades an empty state for
no gates at all until the guard's next 15-minute sweep. The refusal sits in
`transform_response`, not `pre_gateway_dispatch`, because patch 13 settled that
a hook must never put its own words into a user's thread.

### The second door

Removing the `file` toolset from WhatsApp (T01) closes one door.
`vision_analyze` is the other, and the lock does not touch it: its schema takes
a local file path, and Hermes' `_permitted_host_read_target` says in its own
docstring "Local backend: any path is permitted (chosen posture)". TERMINAL_ENV
is unset here, so that was the live posture. Credential files and the
magic-byte sniff meant a text file was never readable that way; any *image* on
the laptop was.

Had the lock been applied alone, T01 would have been marked done while the door
stood open. `_vision_scope_guard` now allows the media cache roots and nothing
else, resolved before comparison so `..` and symlinks walk out to where they
really land.

### The deletion that stopped at photos

"delete my data" found 7 of 7 photos and **0 of 29 voice notes**. A voice note
is transcribed on arrival, so the message holds the words and never the path,
and nothing else held it either: not `api_content`, not `tool_calls`, not
`delivery_obligations`, not the session dumps. Recordings of people describing
their meals survived erasure completely and nothing could say whose they were.
Matched by arrival time now, claimed only when exactly one person was messaging
within 60s. All 29 attributed, none ambiguous, none claimed twice.

The same shape of gap sat in the gate's own snapshots: 20 files beside the live
one, holding every user's profile, written by nine repair scripts and cleared
by nothing.

### Status, in the roadmap's own words

| Task | Implemented | Tested | Deployed | Unverified |
|---|---|---|---|---|
| T00 truth sheet | yes | n/a | n/a | goes stale fast; was wrong twice on the day |
| T01 file + vision boundary | yes | yes | 22:15 and 22:33 | dedicated OS account, deferred to T04 |
| T02 two-user separation | yes | yes | n/a (tests) | two real users at once, never observed |
| T03 fail closed | yes | yes | 22:33 | — |
| T09 deletion completeness | yes | yes | n/a (operator script) | never run with `--apply` on a real person |

1039 tests at the start of the session, 1118 at the end. Five suites are
mutation-proven: the isolation set fails 6 when users share one row, the Convex
set fails 4 when the memory cache ignores the user key, the fail-closed set
fails 3 when one assertion is dropped from the import probe.

### Rollback

`~/.hermes/config.yaml.bak.pre-t01` holds the pre-lock toolset. Restoring it
and restarting undoes the `file` lock only; the vision guard and the T03
refusal live in the repo and come back on any restart, so undoing those is a
git revert of `6527665` plus a restart. The lock was applied, verified, rolled
back and re-applied during the session, and the rollback path was exercised for
real rather than assumed.

### Verified live, not just in tests

A real food photo at 22:41: `vision_analyze` 170KB in 0.08s, `ted_food_lookup`,
`ted_log_entry`, delivered first attempt with no retries, and
`ted_vision_path_blocked` still at 0. That is the end-to-end proof the unit
tests could not give.

### Follow-up, in the order it should be picked up

1. **T04.** Still a laptop. It carries T01's remaining bullet: moving to a VM
   or container provides the low-privilege boundary once, instead of paying a
   WhatsApp re-link and an outage twice.
2. **T35, raised from P2.** `~/.hermes/logs/agent.log` holds 23 of 40 recent
   user messages verbatim, 2.8 MB of it. `ted-forget-user.py` already says out
   loud that it cannot reach that log. It undercuts the deletion promise the
   rest of this session strengthened.
3. **T41, raised from P3.** `src/lib/hermes/handle-message.ts` returns a
   hardcoded reply and `scripts/simulate-hermes-message.mjs` posts to it. It
   looks exactly like a test harness for the live WhatsApp path and tests
   nothing.
4. **`known_plugin_toolsets.whatsapp`** is read by neither the lock nor the
   guard. `spotify` is listed there and not installed, so it is inert — until
   something is.


## Order 28 — 17 Sep 2026, night, the service was one Terminal window wide

T04 is "move the runtime to an always-on environment", and the survey found the
problem was worse and narrower than "a sleeping laptop".

### What was actually holding TED up

```
2185  2157  02-11:07:45  caffeinate -dimsu
2157  2156  -zsh
```

A `caffeinate` typed by hand into a Terminal window two and a half days
earlier, parented to a login shell. Closing that window, or rebooting, ended
the service for the 56 chats in it, and nothing anywhere restarted it. The
laptop was also on battery at 71% at the time. Neither fact was watched by
anything: `ted-watch.py` reported five healthy components on a host that was a
countdown.

`ai.ted.awake.plist` makes the hold a supervised job, and it is a stopgap with
its expiry written into it. It survives a closed window, a kill and a reboot.
It does not survive a closed lid, a flat battery or a desktop logout, and
`ai.hermes.gateway` still carries `LimitLoadToSessionType: Aqua`. Installed and
verified live: pid 84759, parent 1, holding `PreventUserIdleSystemSleep` with
"asserting forever"; the hand-typed 2185 retired after, not before.

`check_power` is the half the plist cannot do, because no launchd key charges a
battery. It alerts when nothing holds sleep off, and when the battery is at or
below 30%. Two details are load-bearing. It counts only a **permanent** hold: a
`caffeinate -i -t 300` shows the identical assertion name, and counting it
would report a laptop as safe four minutes before it slept. And it goes quiet
on a host with no `pmset`, so it retires itself the day T04 lands rather than
alerting forever about a laptop TED no longer runs on. Being unplugged and
comfortable is said in the detail line and never alerted: she unplugs this
laptop daily, and a watcher people learn to ignore is worse than one that says
less.

### The re-link we were dreading is not real

Order 27 deferred T01's OS boundary into T04 partly because a host move was
believed to cost a WhatsApp re-link. It does not.

The link is `@whiskeysockets/baileys` 7.0.0-rc13 in
`scripts/whatsapp-bridge/bridge.js`, on `useMultiFileAuthState`. The session is
a directory of JSON files, and `creds.json` holds keys, ids and counters with
**nothing host-specific**. `browser: ['Hermes Agent', 'Chrome', '120.0']` is a
label sent at connect, not a real browser, so no Chromium is involved and the
whole thing runs headless on Linux.

Copy the directory, the new host reconnects as the same linked device, no QR.
The real constraint is different and sharper: **only one instance may hold
those credentials at a time.** Two fighting is what produced
`~/.hermes/whatsapp/session.loggedout-20260909-100854`. So the move is stop
here, copy, start there, never an overlap.

### What T04 still needs

Our own code is portable. The only macOS-specific calls are `launchctl` inside
two install helpers and `osascript` in one alert road, and that road already
does not count as delivered by its own design — the desk notification popped up
to an empty room for seventeen hours on 8 Sep. The remote channels are the half
that counts and they are network-based.

Hermes ships its own `Dockerfile` and `docker-compose.yml`, mounting
`~/.hermes` at `/opt/data` with `restart: unless-stopped` and s6 supervision
inside, so the container is mostly configuration rather than construction.

Decided: a small Linux VM, not hardware at home, because there is no spare
always-on machine to use and buying one for this is not worth it. The known
cost of that choice is a datacenter IP on an unofficial WhatsApp client, which
is a real but secondary signal next to behaviour: TED is low volume, replies
only to people who wrote first, and the number is established. The mitigation
is a verified copy of the session directory taken before the cutover. The
permanent fix is T06, the official WhatsApp path, and this is a reason to move
it up rather than leave it at its current place.

Blocked on Vandy: the VM has to exist before the cutover can be written.

Suite: 1127 Python tests, 2145 subtests, up from 1118.

## Order 29 — 18 Sep 2026, midday, the name we actually own

`heyted.in` was registered this morning through Openprovider and now serves the
product. Until today the URL people were handed was `heyted.vercel.app`, a
hostname the platform lends you.

### What was wired

The registrar's DNS was parked on `luna/neon/odin.mydnsvault.com`. The domain
was added to the Vercel project, its nameservers moved to `ns1/ns2.vercel-dns.com`,
and `www.heyted.in` added alongside so both spellings resolve. Vercel then
issued a Let's Encrypt certificate for the apex and the subdomain on its own.

Verified live rather than assumed: the `.in` registry delegates to the two
Vercel nameservers, the certificate for `CN=heyted.in` validates with return
code 0 and runs to 17 Dec 2026, `http://` answers 308 to `https://`, and `/`,
`/privacy`, `/robots.txt` and `/brand/ted-whatsapp-cover.png` all return 200 on
both `heyted.in` and `www.heyted.in`.

Both older hostnames still serve the same deployment, so every link already
sent to a tester keeps working.

### The one string that was held back

The swap went out in two commits on purpose. `610fd51` moved the seven places
where the site speaks its own name: the canonical and link preview tags on the
landing page, the robots.txt host, the `/privacy` footer, the recap card, the
submission report, the README and the brand profile.

`PRIVACY_URL` in `hermes/ted_safety_gates/__init__.py` waited for `f8365be`,
because that line is the only string in this repo that reaches a user directly,
in the disclosure Ted sends on first contact, and
`~/.hermes/plugins/ted-safety-gates` symlinks straight into the file. A launchd
restart would have shipped it with no deploy step in between. Pointing 56 chats
at a hostname with no delegation was a cost with no upside, so it moved only
after the domain answered.

The quoted transcript at `hermes/test_ted_safety_gates.py:7485` keeps the old
URL. It is copied verbatim out of `agent.log` and is the record of a message
that was really sent, not a link anyone follows.

### And then the site opened to search

The private-beta `noindex` lived in three places, `src/app/robots.ts`,
`src/app/layout.tsx` and a meta tag inside `public/landing-v6.html`, and they
had to go together or not at all. They went together, same afternoon, on
Vandy's call.

Checked before opening rather than after: `/metrics` is the only page on the
site that shows real numbers, and it is reached with `?key=`, returns 404
without one, and sets its own `noindex`. The landing page and `/privacy` are
the only other public pages and neither carries user data.

`robots.txt` now allows `/` and shuts `/api/` and `/metrics`. `/api/` is
machines talking to machines and the beacon endpoint accepts writes. `/metrics`
is the third lock on a door that already has two, which keeps the URL out of
the crawl rather than relying on the page to turn a crawler away once it has
arrived.

`layout.tsx` lost its `robots` key rather than gaining an inverted one, so the
decision lives in `robots.ts` alone. The assertion in
`__tests__/landing-page.test.ts` was inverted rather than deleted: it now fails
if a `noindex` reappears on the landing page, which is the one regression
nothing else would catch, because that file is static and the symptom would be
the site falling out of search weeks later.

Suite: 164 web tests, 826 gate tests and 2124 subtests, all passing, plus lint
and a production build.

## Order 30 — 18 Sep 2026, afternoon, the server was the small number

T04 needed a host. Most of this session went on choosing one, and the useful
finding was that the question was the wrong size.

### The number nobody had looked at

Hosting is about 1,050 rupees a month. `ted-api-spend.py` over seven days:

```
         billed   calls          USD
cron        311     398        33.26
chat         53     587         7.91
all         364     985        41.17
```

About $176 a month, roughly 15,400 rupees. **The model is fifteen times the
server**, and an entire evening had gone into optimising the server.

AWS Activate credits can pay that, which is the only reason AWS is in this at
all. Verified against AWS's own pages, not blogs: Claude Sonnet 5 is on
Bedrock, and Bedrock is absent from the promotional-credit exclusion list.
**AWS Marketplace is on that list**, and Claude can also be bought as "Claude
Platform on AWS", which invoices as Marketplace. Same model, same price, and
credits would not apply. It has to be Bedrock.

Hermes already supports it: `auth_type: aws_sdk`, and `hermes_cli/models.py`
lists `us.anthropic.claude-sonnet-5`, the exact model in `config.yaml`. The
switch is configuration, not code.

### The switch would have zeroed the bill report

`price_row` looked its rate up by exact string match. Under Bedrock every id
becomes `us.anthropic.claude-sonnet-5`, no key matches, and the report prints
**$0.00** under a one-line footnote while credits burn. `normalize_model` now
strips the region prefix, vendor segment, dated build and version suffix, with
a test pinning every Bedrock id Hermes lists, so a rename upstream fails a test
instead of printing a zero. Conservative on purpose: an unknown model stays
unpriced, because unpriced is counted and reported while a wrong rate is not.

A regional inference profile is reported to cost more than the global default.
That could not be confirmed on AWS's pricing page, so the report raises a
caution and never adjusts a figure. Same rule as `ttl_caution`.

### Host and model are separate, so nothing moves twice

The worry was that starting somewhere now means migrating again when the
credits land. It does not. Bedrock is an API call, the same as Anthropic direct
is today. TED can move host now and change model later, or never. A rejected
application costs nothing already spent.

### AWS account state, 18 Sep

On `vandana@heyted.in`, business, paid plan, AutoPay on a card. `$100` of
onboarding credits **survived the upgrade off the free plan**. Spend limit set
to `$40`.

The spend limit is better than expected and also a new way to lose the service.
It is a hard stop: *"If you reach your limit, your project is paused."* That is
a real ceiling, not the email alert this file assumed. It also means a billing
rule can switch TED off, which is the same outage T04 exists to prevent wearing
different clothes. `$40` against `$12` of Lightsail is headroom chosen for that
reason, not for the hosting.

Early cost controls: **stop new resource launches** only. "Pause idle
resources" was refused because a low-traffic WhatsApp bot is what idle looks
like from outside, which is the Oracle reclamation trap again, and "pause top
cost drivers" says plainly that it can take a live app offline.

### The fallback, if TED goes to AWS

1. **The laptop stays able to run it.** `ai.ted.awake` and the gateway stay
   installed, stopped rather than removed. One instance at a time, always.
2. **A verified copy of `~/.hermes/whatsapp/session` before anything moves.**
3. **The watcher does not move.** `ted-watch.py` stays on the laptop watching
   AWS from outside. Moving both means a paused project kills the gateway and
   its alarm together, silently, which is 8 Sep again with a billing rule in
   place of a logout.

### Corrected today

- Activate review is **7 to 10 business days**, not the 24 hours a blog said.
- Founders credits are reported at **12 months**, not 24. AWS's own FAQ would
  not render the answer, so read the date off the credit in the Billing console
  rather than trusting either number.
- The **company website requirement is real**. It was retracted here on the
  strength of AWS's overview page not listing it; AWS's own step-by-step guide
  does.

### Open

- Credit expiry date, unread.
- Whether the Activate application was submitted.
- Whether the spend limit counts gross usage or net of credits. It decides the
  limit before TED ever runs on Bedrock: at `$176` a month gross, a `$40`
  ceiling pauses the project in a week.

## Order 31 — 18 Sep 2026, night, the day the bill read zero and wasn't

This session set out to read the measurement order 27 was waiting for: did the
two cron fixes of 17 Sep work. They did. Something else had happened in the
meantime and the spend report could not see it.

### The balance emptied and nothing stopped

At about 22:31 on 17 Sep the Anthropic credit ran out. Every call since has
failed with `Your credit balance is too low` and fallen back to
`openai/gpt-5.3-codex` through OpenRouter. Users saw nothing: the "switched to
fallback model" notice is suppressed on WhatsApp, and 11 messages went out
today with none abandoned. The voice held, Hinglish and meal cards and the
numbered onboarding intact.

`ted-watch.py`'s `check_model` did its job and has said `model: FAILING` every
fifteen minutes since. Pushover is still not configured; email is, and a test
alert sent successfully, so the alarm has been arriving in an inbox. Nothing
about the alarm is broken. Whether it is being read is a different question.

**The Codex fallback was the one open half of order 09, never force-tested.**
It has now been tested by twenty-two hours of production and it held.

### The measurement, with the contaminated half thrown out

The dollar drop is not the proof, because for most of the window Anthropic
could not bill at all. The tokens are the proof, and they are unambiguous. The
cut lands between 16:00 and 17:00 on 17 Sep:

```
2026-09-17 16:00:35   44,412 prompt tokens per cron call
2026-09-17 17:00:59   22,235
```

Cron firings a day, from `cron/executions.db`: 54, 55, 59, then 39 on 17 Sep,
then 16 today. `ted-idle-nudges.py` now reports nothing left to pause and
nobody to resume, so the 35 paused jobs are holding.

| window | firings | cron $ | chat $ | total |
| --- | --- | --- | --- | --- |
| 16 Sep, full day | 59 | 12.13 | 2.65 | 14.78 |
| 17 Sep to 17:00 | 28 | 3.95 | 1.51 | 5.46 |
| 17 Sep 17:00 to midnight | 11 | 0.81 | 1.53 | 2.34 |
| 18 Sep, all on the fallback | 16 | 0.12 | 0.37 | 0.49 |

**14 and 15 Sep are not a usable baseline.** The balance was empty then too and
most of those calls went to the fallback: 43 of 51 cron rows on 15 Sep carried
no price. The honest "before" is 16 Sep and the morning of 17 Sep.

### Two holes in the bill, not one

`ted-api-spend.py` looked its rates up by exact model name, so anything wearing
another spelling fell out of the total. Over fourteen days the report said
`$115.93`. The real figure is `$136.03`. **About $20, a seventh of the bill,
was invisible.**

- `openai/gpt-5.3-codex`, 921 calls, no rate at all. The one we went looking for.
- `anthropic/claude-sonnet-5`, 245 calls. **The same Sonnet already being paid
  for**, in OpenRouter's spelling. `normalize_model` knew Bedrock's `anthropic.`
  with a dot and not OpenRouter's `anthropic/` with a slash. Found only by
  accident while adding the first one.

Rates were read from `https://openrouter.ai/api/v1/models` on the day, not from
memory, and the source is recorded in the file. That mattered:
**`gpt-4o-mini` caches at half price, not the tenth every Claude model uses.**
Inheriting Claude's shape would have priced it five times under. Non-Claude
models must now state their own cache rates and a test fails if one is added
without them. A `None` write rate means the provider charges no premium to
write cache, which is why every Codex row reports 0 cache-write tokens.

The footnote now names the model. The old line said "388 row(s) on a model with
no rate here", which was true and told nobody that an entire day had moved to
the fallback. `stepfun/step-3.7-flash:free` is deliberately left unpriced: the
`:free` suffix probably means free, the model is no longer listed on
OpenRouter, and this file's rule is to say what it cannot prove.

42 tests in `test_ted_api_spend.py`, up from 36. Two of the six new ones
replace tests that had pinned the bug in place by asserting the fallback stays
unpriced.

### Should Codex be the primary model

Asked directly, and the answer is no, not yet. The same tokens under both price
lists:

| traffic | as Claude | as Codex |
| --- | --- | --- |
| 16 Sep, all day | 14.86 | 6.83 |
| 18 Sep, all day | 0.47 | 0.45 |

Codex was half price on September's traffic and level on today's. The whole
difference is one line item: **Claude charges 2x input to write to cache at the
1h TTL and OpenAI charges nothing extra.** Codex output is 40% dearer, $14
against $10 per million, which does not matter while Ted's replies are 70
tokens. So the saving was never "Claude is expensive", it was "we were writing
3.5 million cache tokens a day", and 17 Sep fixed that.

Switching now buys roughly $10 a month, throws away order 30's Bedrock credit
plan, and does not simplify funding: today worked *because* OpenRouter had
credit when Anthropic did not, and flipping only changes which account must
never run dry. **The fact that decides it is order 30's open item, whether the
Activate application was submitted.** Rejected or never sent, and Codex-primary
becomes reasonable.

### Is it sustainable

At today's size, yes. Roughly ₹39,000 a month before the fixes, roughly ₹1,300
now, against about ₹1,050 of hosting. The model is no longer fifteen times the
server.

The number to watch is not the total. It is **about $0.074 per conversation and
$0.0075 per reminder firing**, so a daily-active user costs ₹250 to ₹600 a
month. At 2 to 5 active that is comfortable. **At all 47 active it is ₹12,000 a
month or more**, which is the same trouble in a different shape.

### Open

- The Anthropic balance is still empty. Only Vandy can top it up.
- Pushover still not configured. Email is the only remote channel that works.
- Delivered messages went 33, 36, then 11 today. Most of that is the paused
  reminders working as designed. Not proven that none of it is a real person
  going unanswered.
- `:free` models are still unpriced and still counted in the footnote.

## Order 32 — 18 Sep 2026, night, four things that were true and one that was not

A long session. The pattern worth keeping is that almost every real fault was
found by running something against the live system, and the one wrong
conclusion came from reading a table and trusting a rule.

### The correction first

**"Ted has sent no proactive message in seven days" was wrong**, said four
times before it was caught. He sends 7 to 21 reminders a day and always has.
The claim came from `delivery_obligations`, following this file's own rule that
the ledger is what a user received. **That rule is true for replies and
silently incomplete for reminders:** a scheduled send never creates an
obligation. The scheduler hands it to the adapter and writes one line to
`agent.log`, which is the only record it happened.

    Job '6e77ad1b48ab': delivered to whatsapp:115650651500637@lid via live adapter

`ted-window-check.py`, written an hour earlier to price T06, was therefore
reading a sixth of the traffic. It reads both sources now and prints replies
and reminders separately, so a zero in the reminder column reads as a bug
rather than as good news.

### T05, closed

Backup had one hand-taken copy and none of what T05 asks for. Now: restore, a
drill that rebuilds a real user's history out of a restored copy, retention
that never prunes the last verified backup, `ai.ted.backup` daily at 04:00
verified by launchd's own exit code, and a re-drill whenever the proof is older
than seven days.

**The backup was missing `~/.hermes/state`** — 56 users' onboarding and 113
disclosure records, the store that enforces the under-18 refusal. Found while
starting the migrations, not while writing the backup. A restore would have
brought back a Ted who had forgotten who consented and who is a minor.

**Three faults in one installer message:** macOS blocks a launchd agent from
reading `~/Documents` under the Command Line Tools python; a stray `-->` made
the plist invalid, which `plistlib` accepted and launchd rejected while
silently keeping the old definition; and `--install` asserted success for a job
it had never seen run. All three fixed, and the installer now kickstarts the
job and reads launchd's exit code.

**Migrations:** eight repair scripts had each been run once with nothing
recording it, which stopped being survivable the moment restore worked.
`ted-migrate.py` keeps the ledger in `~/.hermes/state`, so a restored home
arrives knowing its own history, and marks a repair **AT RISK** when it was
applied after the gateway started, because the gate holds that store in memory.

### T02, closed on real traffic

It had already happened and nobody had looked: Vishal S sent "Cool" nine
seconds into Venky's onboarding on 16 Sep. `npm run concurrency` now checks
every episode — 32 in 30 days, 5 with messages to inspect, all clean.

### T35, closed

**4,998 lines of users' own words** sat in `~/.hermes/logs`, next to their
names, with no retention and outside what "delete my data" can reach. Hermes
patch 14 stops the writing; `ted-log-retention.py` redacted what was there,
keeping every line and only removing the words. All logs read clean.

### arpit, and what the gate was throwing away

He asked "do you read my other messages ?" and Ted wrote a proper answer. He
never saw it: `setup_gate` returned the counted question *instead of* the
reply. He asked again, got the same eleven words, and stopped. **The model was
already doing the human thing and the gate was discarding it.** It composes
both now, count last, figures stripped, Ted's own duplicate question dropped.

Same thread, second bug: he wrote English throughout and got Hinglish, because
the switch needed four of his own messages and he reached four on the last
thing he ever sent. Now two, and a one-word reply no longer votes.

### T06, decided; T07, half done

Both of T06's supposed blockers dissolved. Meta's AI ban binds **AI Providers**
where the AI is "the primary rather than incidental functionality"; Ted sells
meal logging and reminders. Verification is not needed at 56 users against a
250/day cap. **No SIM is needed either** — a developer app is issued a free
test number, which an earlier draft of the document got wrong.

The real constraint is the 24-hour window: **85 of 406 messages in 30 days
(21%) would need a pre-approved template, and every one of them is a
reminder.** About ₹10 a month. The cost is nothing; the question is what a
template can say, because it cannot improvise.

T07's state half was already true and tested. Its user-visible half was not:
Convex refused to log the same meal twice and nothing refused to *answer*
twice. Hermes patch 15 fixes it before the model call, and it is a prerequisite
for T06 because Meta retries webhooks.

### Left open by decision

`docs/FOUND_NOT_FIXED.md`. The user analysis is deferred at Vandy's word: 36 of
56 users have no reminder job, and a user who ignores the break offer is silent
forever with no path back except writing first. Neither is to be acted on
without her.

### Numbers

1,266 Python tests, 2,147 subtests, 123 in the Convex model suite. 15 Hermes
patches. Gateway restarted and gates verified at 22:01.

## Order 33 — 19 Sep 2026, the two things T13 and T14 left behind

Both of these were written down as "found, not fixed" on purpose, and both
were left because the fix needed a decision rather than a keystroke. Neither
is a roadmap task.

### The turn that wrote nothing, and nobody knew

`check_dropped` watches a reply Ted wrote and could not send. On 4 Sep nothing
was written to send: OpenRouter answered 402 on the primary model and on the
fallback, the turn ended empty, and Palak, Vishwas Mishra and Vinit were left
standing there. Two of them never wrote again. It took fifteen days and a check
built for T08 to notice.

`check_silent` in `ted-watch.py` is the watcher that was missing, running every
fifteen minutes under `ai.ted.gatewatch` and alerting off WhatsApp like the
rest. Three things about how it is built:

- **It reads T08's own `unanswered`**, loaded from `ted-ordering-check.py`
  rather than copied. Two files answering "was this message answered"
  differently is how a watcher goes quietly wrong.
- **It is written against the outcome, not the 402.** A dead provider, a crash,
  a hung turn and a gate refusing without saying so all look the same from
  where the person sits. A watcher pinned to the last outage's error string
  only ever catches the last outage.
- **One person cannot raise two alarms.** A delivery obligation created after
  their message means something was composed, so that case stays
  `check_dropped`'s and is skipped here.

Proved against the real event rather than asserted: widened to a 30-day window
it reports "3 people wrote and Ted composed nothing back, longest waiting 15
days", and it correctly leaves out GT, whose reply was written and dropped on
11 Sep. At the shipped 7-day window it is green, which is the honest reading —
nothing has been missed this week.

**Found while wiring it in:** the logged-out branch in `main()` sat ahead of
every per-component branch, so a dead model during a WhatsApp logout was
announced as the logout, with the QR instructions attached. Two things broken
and one of them invisible is the shape of the 8 Sep outage. Now each component
is described as itself, with a test that breaks the link and the model at once.

**Checked and rejected:** adding the credential-pool lines to
`MODEL_DEAD_ENDS`. `credential pool: no available entries (all exhausted or
empty)` appears 645 times in the current log at INFO, and the turn goes on to
succeed on the fallback. It is rotation, not a dead end, and it would have
turned the model alarm into noise.

### The seven voice rules, still in people's memory

T14 closed the door: the gate refuses to save another rule about how Ted
talks. It deliberately left the 7 rows already inside, because deleting live
user data is not a side effect of shipping a gate change.

`scripts/ted-purge-voice-rules.py` (`npm run memory:voice-rules`) is the tool
for doing it, and it has not been run. Dry run by default. It selects with the
gate's own `is_voice_rule_key` — one definition, so what it would delete and
what the gate refuses cannot drift apart — and it prints the rules themselves,
because reading the values is exactly what caught the four misfiled keys in
T14 section 2. `nudge_preferences` and `daily_preference` are the person's own
choices and sound like instructions.

The write is a new `forget-facts` action on `/ted-memory`: named keys only,
capped at ten, never a pattern. `delete` next to it is the privacy teardown
that takes everything, and the two must not be one call with a flag.

**Still open, and Vandy's call:** whether the 7 go at all. All seven read as
Ted's own voice — Aadi, Arpit, GT (two), Shabs, Shreya and Sid — and none of
them is something a person asked for. Convex has to be deployed before the
tool can write.

### The check that was missing behind both of them

Vandy's question on the deletion was the right one: does removing the rules
make Ted worse. Nothing could answer it. Every check in the repo asks whether
Ted worked, none asked whether the reply sounded like him.

`ted-voice-check.py` (`npm run voice`) counts the SOUL.md rules a machine can
count, on Ted's own outgoing words, with cron excluded. Three weeks, by week:
mid-sentence dashes **8.5% to 0.3%**, capitalised openings **18.0% to 1.0%**,
bullets **3.1% to 0%**, average reply **96 chars to 44**. The voice work of the
last fortnight is visible in the traffic, not only in the file.

Split by who holds a stored voice rule, the six are indistinguishable from
everybody else and slightly worse on capitalised openings, so the deletion is
expected to be neutral on voice. **Still breaking the rules today:** 10 receipt
openings and 6 emojis beside a metric in one week, both explicit "never" rules.
Not acted on.

`--skip` was added to the purge tool for Arpit's "friend-first bangalore
vibe", the one fragment of the seven that SOUL.md does not already say, and
which is where he lives rather than how Ted talks.

### Done, 19 Sep: six of the seven are gone

Vandy ran `--apply --skip Arpit`. Six rows deleted across five people (Aadi,
GT twice, Shabs, Shreya, Sid); `userFacts` went 92 to 86 and the `instruction`
layer 7 to 1. Verified three ways: the purge tool, a direct table read and
`npm run memory:audit`. The deleted values are kept at
`~/.hermes/state/ted-voice-rules-removed-20260919.json`, so any one of them
can go back through the `save` action.

Arpit's stays by decision, not by oversight, and the audit no longer reads a
single kept row as an infestation.

**The measurement to re-run in a week:** the five who lost a rule were
indistinguishable from everybody else before it happened, so the prediction is
no change. `npm run voice --days 7 --voice-rules` is the same command that
would show it if the prediction is wrong.

### Numbers

1,498 Python tests, 2,164 subtests, 161 in the web suite. Lint and TypeScript
clean. Convex was deployed to production (the `forget-facts` route, verified by
`npm run convex:check`); no user data was written or deleted.

## Order 34 — 19 Sep 2026, the voice check was reading the wrong copy

One task, and the first thing it found was that the instrument was wrong. The
question was "Ted breaks two of his own SOUL.md rules, fix it". The answer is
that one of the two was never happening and the other was mostly Ted's own
fixed copy, and neither could be seen until the check stopped measuring
drafts.

### What it was reading

`ted-voice-check.py` read the `messages` table and called it "Ted's own
replies". That table holds what the **model** wrote. The gates then edit it,
replace it, and append to it, and nine of the twelve receipt openings a real
person read in the last seven days are fixed strings the gates themselves
write — `got it, all six ✅`, `done, nudges off from right now 🤝`. Those
appear in no draft, so every number this check had ever printed was blind to
them.

The memory rule that names this exactly is "delivered text is not the messages
table". It was written about reminders. It is true of every gated reply, and
the check was written after it and still went the other way.

    receipt opening, last 7 days
      drafted   10/352  (2.8%)   ← what the check used to print
      received  12/165  (7.3%)   ← what people read

It now prints both, labelled, because the gap between them *is* the gates'
contribution to Ted's voice and nothing else measures it. Cron sends are
excluded from the ledger read the same way they were from the draft read
(patch 16 put them there), and so is anything not `delivered`: an abandoned
row is a delivery fault, not a voice one.

The ledger only reaches back to 11 Sep 2026, so the four-week view prints
"no replies" for received on the older weeks and says why, rather than a tidy
zero.

### The rule that was counting its own furniture

"no emoji beside a metric, ever" read **45 hits in 165 replies**, 27%. Forty
three of them were the meal card obeying its own approved spec:

    Fiber: 6g

    📊 Daily Overview:
    🟢🟢⚪⚪⚪⚪ 31%

`\s` crossed the line break, so `6g` and `📊` two lines apart matched as an
emoji beside a metric, and the six-circle calorie bar matched on every card.
Two fixes, because either alone leaves the other:

- the pattern is spaces and tabs now, never a newline;
- `spoken_part` cuts the appended card before counting. The card is a fixed
  block the gate prints, not prose the model wrote, and Vandy approved its
  design. Counting it buried the two real hits under forty three false ones.

The count went 45 to 2, and both survivors are genuine: `yup pakda 😄 1870 pe
lock karein` and `solid, 175 👌`.

### What is actually left, and why it was left

    receipt opening        12/165 (7.3%)   9 gate copy, 3 the model
    two or more questions   4/165 (2.4%)   all one gate string
    emoji beside a number   2/165 (1.2%)   both the model
    everything else            0

**Decided: leave both, measure.** Vandy's call, and the right one. The nine
are three strings of deliberate copy — the setup summary, the break-not-a-
breakup pause reply, the target confirmation — and the four "two question"
hits are one onboarding line that asks one thing and offers three options,
punctuated with two question marks. Rewriting somebody's approved voice to
satisfy a regular expression is the tail wagging the dog.

The model's three were **checked and rejected as a fix**. `got it, 4'10. and
weight, roughly?` is how a person texts. The rule exists for a bare receipt
standing in for a reaction, which `reminder_receipt_gate` already catches, and
a blunt strip would leave three natural lines reading abrupt.

So nothing in the gates changed today. The instrument did, which is the part
that was actually broken.

### Patch 17's first evidence, and it is not the number that proves it

Patch 17 went live at 18 Sep 23:38, one minute after the commit. It was
shipped on a prediction — cron writes a cache nobody reads, so drop the
message-level breakpoints and keep the system one — and the prediction is now
watchable in four rows:

    19 Sep 00:00   write 42,075   read      0
    19 Sep 10:30   write 21,222   read      0     writes the prefix
    19 Sep 11:15   write      0   read 21,222     reads it back, free
    19 Sep 11:30   write      0   read 21,222     reads it again

That is the mechanism doing exactly what the patch claimed. Two firings paid
nothing for a prefix a third had already written, which no cron firing had
ever done before.

The money, cron only, 17 to 18 Sep against 19 Sep:

    cost per firing          $0.124  →  $0.068
    cache written per firing  41,668  →  15,824 tokens
    reads per token written     0.30  →  0.67

**Four firings. Do not bank it.** Today's job mix is lighter than the
comparison window (22k prompt per call against 35k), so some of that drop is
not the patch. The direction is right and the size is not yet known.

**The limit, visible on day one.** The saving needs firings inside the same
hour. 00:00 and 10:30 are ten hours apart, the 1h TTL had expired, and both
wrote the prefix fresh. 10:30, 11:15 and 11:30 are bunched, and two of the
three rode free. The patch README predicted this in the same sentence that
explained why the system breakpoint stays. Spreading reminder times, which
`ted-spread-reminder-times.py` does for a different reason, works against it.

Re-run `npm run spend --since 2026-09-19` around 26 Sep, the same day the
voice-rules prediction comes due.

### Numbers

1,507 Python tests, 2,164 subtests. 9 new, all on the check: the ledger read,
the cron and abandoned exclusions, a missing-ledger database, the newline in
the emoji rule, and the card cut.

## Web product we are building

The public web app explains Ted, sends interested visitors into the existing WhatsApp experience, captures leads, and stores/shows web data. WhatsApp message handling belongs entirely to Hermes.

## Foundation result

The stripped-down landing page passes its focused tests, lint, TypeScript, and a production build. The prepared WhatsApp message remains in the button link but is no longer revealed on the page. The obsolete `TED_PERSONALITY.md` dependency and its test have been removed because Ted's personality belongs only in Hermes `SOUL.md`. Visual browser review is still pending because no browser was connected in the coding session.

## Exact next step — 4 Sep 2026

*Superseded. What is open now is under **Open — 5 Sep 2026** above; the patch
count and gate timestamps here are 4 Sep's and have moved on.*

Ordered by what a real user hits first.

### Blocked on Vandy, not on code

1. ~~**The gateway is serving the old gate.**~~ **Done.** The gateway was
   restarted; `npm run gates:guard` reported "Gates are on" at 4 Sep 21:50:31,
   with the gates loaded after the last start and all 8 patches applied. Order 19
   is live.
2. ~~**Four commits are unpushed**~~ **Done.** `main` is in sync with
   `origin/main`; nothing is held locally.
3. **Three of the five named users still have no reminders.** Pradosh and nagga
   have jobs. UD, harsh, Ankie and J do not. *(Still open — the only item in this
   list that is.)*

### Then, in order

4. **Watch a real thread take the counted five.** Everything in order 19 is proven
   in tests and in an offline replay. No live WhatsApp conversation has been
   through it. The read-back is the step to watch: it is the one that would have
   caught Pallavi's height, and it is also the most likely to feel like an extra
   turn.
5. **The save-my-number ask.** Deliberately unwritten — Vandy disliked every draft.
   It belongs after the number, never before, once Ted has actually been useful.
6. **The meal card**, and it is blocked on two missing things, not on copy:
   `ted_food_table.json` has 59 entries with `calories/protein/carbs/fat/fiber`
   and **no sugars field**, and nothing stores a daily target for "X left" to
   count against. That target must be maintenance, never a cut. The agreed
   structure is Rex's minus the per-macro emojis, with the voice first:
   pic → "ooo a pic 📸 let me look…" → Ted's reaction and his question → on the
   plate → Meal Summary → Daily Overview. `words_without_figures` already strips
   numbers from Ted's prose, so he names the food and asks while the block counts.
7. **Order 09, the half that is left.** Provider error copy is done and the stall
   watchdogs use `time.monotonic()`. Still open: force-test the Codex fallback,
   ~~and stop the raw `ArgumentValidationError` strings the Convex actions return
   on a bad payload from reaching a chat.~~ **Closed 16 Sep, order 25.** They
   never could: the endpoint answers 400 and `urlopen` raises that as
   `HTTPError`, which the gate already caught. The real fault was the opposite
   and is now fixed, so the Codex fallback is the only half still open.
8. ~~**Order 11 is written, tested, and not deployed.**~~ **Merged.**
   `fix/order-11-milestones-10-11-12` is now an ancestor of `main`, so the
   duplicate check, date confirmation, the report-a-bad-reply path and
   `decideReminderDelivery` are all in the shipped tree. `npm run reports` reads
   back one reported reply, so that path has run for real.
   Two branches are still **not** merged into `main`: `fix/orders-08-13-14`
   (3 commits) and `design/landing-rework` (2 commits).

### Open design calls

- **The notice and question one share one bubble.** Vandy asked for two. The hook
  returns a single string, and order 08 deleted the threaded second send because a
  failure inside it stalled onboarding with no record. The notice goes first and
  carries no name, which is the part that actually protected it from a mis-parsed
  name. Two bubbles needs a real Hermes change, not a gate change.
- **The read-back is an extra turn.** It is not numbered, so the promise holds,
  but it does sit between question five and the number.
- **Ted ignores a direct question during the five.** "what do you even do" gets
  `1/5` back, up to three times. Bounded, but it is a version of the complaint
  that started this. Letting genuine questions through without losing the count is
  a change worth making if a real thread shows it landing badly.

### Stale notes now corrected

- `main` is **52 commits ahead** of `ship/landing-v6` and 0 behind, and in sync
  with `origin/main`. The old warning that main was 11 behind, and the held-back
  `c2d82be`, no longer apply.
- The test suite is **964 Python tests** (2,120 subtests) and **164 vitest
  tests**, measured 17 Sep — earlier counts of 81, 464, 179, 536, 78, 743 and
  144 are all superseded. Run the
  Python tests with pytest and the root `conftest.py`; `python3 -m unittest` skips
  conftest and writes fixture keys into `~/.hermes/state`, which happened again on
  4 Sep and had to be cleaned by hand.
- **Which python.** Several scripts import Hermes' own `cron.jobs`, which needs
  PyYAML, and any script that rewrites a schedule also needs `croniter` or
  `update_job` stores `next_run_at: null` and the reminder silently never fires
  again. The repo's `.venv` has the first and not the second. Use
  `~/.hermes/hermes-agent/venv/bin/python3` for anything touching jobs.json;
  `ted-spread-reminder-times.py` and `ted-repair-ghost-jobs.py` now refuse to
  start under an interpreter that cannot do the job, and
  `ted-repair-ghost-jobs.py` finds that state whatever made it.
- **Lint is clean**, 0 errors and 0 warnings. The `index` warning in
  `scripts/recap/card.mjs` was an unused parameter and is gone.
- The live landing page is the **v8** design, not v6. Only the filename
  (`public/landing-v6.html`) still says v6.
- Test counts and branch positions quoted inside the dated order entries above are
  left as written: they record what was true when the entry was made. This section
  is the one that tracks the current numbers.

## Local design experiment — 1 Sep 2026

- A standalone recovery-led landing-page experiment now lives in `design-experiments/ted-recovery-led/`. It is not imported by `src/app`, creates no Next.js route, and has not been deployed.
- The experiment keeps the approved recovery and no-shame copy, gives plum clear brand ownership, limits dark coral to warm emphasis, removes lime and monospace labels, simplifies the WhatsApp action, widens the desktop story, and adds one continuous meal-photo → correction → daily-progress conversation to prove memory.
- It also adds the adult-only beta notice, uses the scoped salute-emoji opening message inside the experiment only, and names Vandana Agarwal as the independent beta operator. A verified public contact email is still required before any production use.
- Static contrast checks pass for the intended text sizes. All 9 web tests, lint, and the production build pass. Browser review is still pending because no browser was connected in this session.

