# Ted — WhatsApp Health Accountability V1 Progress

Last updated: Fri 4 Sep 2026, Asia/Kolkata

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

## Web product we are building

The public web app explains Ted, sends interested visitors into the existing WhatsApp experience, captures leads, and stores/shows web data. WhatsApp message handling belongs entirely to Hermes.

## Foundation result

The stripped-down landing page passes its focused tests, lint, TypeScript, and a production build. The prepared WhatsApp message remains in the button link but is no longer revealed on the page. The obsolete `TED_PERSONALITY.md` dependency and its test have been removed because Ted's personality belongs only in Hermes `SOUL.md`. Visual browser review is still pending because no browser was connected in the coding session.

## Exact next step — 4 Sep 2026

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
   and stop the raw `ArgumentValidationError` strings the Convex actions return on
   a bad payload from reaching a chat.
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
- The test suite is **536 Python tests** (880 subtests) and **78 vitest tests**,
  measured 4 Sep — earlier counts of 81, 464 and 179 are all superseded. Run the
  Python tests with pytest and the root `conftest.py`; `python3 -m unittest` skips
  conftest and writes fixture keys into `~/.hermes/state`, which happened again on
  4 Sep and had to be cleaned by hand.
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
