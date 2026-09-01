# Ted — WhatsApp Fitness Coach V1 Progress

Last updated: Tue 1 Sep 2026, Asia/Kolkata

## What we decided

- The product name is Ted.
- The pre-filled user message is “Okay Ted, let's do this!”.
- Beta onboarding is three questions: the one thing the user wants to change, what Ted should call them, and their daily check-in time plus city.
- Ted's first reply combines a short storage, medical-boundary, and deletion disclosure with the goal question. Answering it records consent for the invited beta.
- The Hermes built-in WhatsApp agent is the product; there is no separate Ted worker.
- Ted's WhatsApp behaviour lives in `~/.hermes/SOUL.md` and is edited by Vandy.
- The web-app scope is the landing page, lead capture, and storing/showing data. It does not receive or send WhatsApp messages.
- Codex must not change the Hermes WhatsApp connection. Suggested Hermes changes are reported to Vandy instead.
- Do not use Twilio or build a Telegram fallback.
- Use Convex for stored state and scheduling and Vercel for the public web application.
- The live product uses the OpenAI API for interpretation and transcription.
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
- Ted's calorie safety rules now run as the enabled `ted-safety-gates` Hermes plugin instead of prompt-only instructions. The live output gate requires a supplied adult age before any calorie number, requires height, weight, formula sex, and activity one at a time before maintenance, calculates Mifflin–St Jeor maintenance from those supplied values, and never returns a deficit target. Eight focused Python tests cover the original 2,300/1,400 failure, the exact ragi-roti replay, under-18 blocking, missing inputs, onboarding order, and unproven action claims.
- Consent is also hard-gated by the same plugin: after a user answers the name question, the disclosure with the privacy URL replaces any attempted next response until it appears in that conversation. The plugin logs `consent_disclosure_sent` when the gated disclosure is produced. A fresh real WhatsApp thread is still needed for the four-message delivery proof.
- The same output gate now removes claims such as “saved”, “scheduled”, or “noted” unless a tool succeeded in that turn. This was added after the Sonnet 5 test produced “33 noted” without a save call. Eight focused Python tests now pass.
- The calorie gate now includes the current incoming message when extracting the age profile, including a bare reply such as “33”. This closes the loop caused by Hermes delivering a transformed age prompt without persisting that transformed text into the durable transcript. The golden-path replay reaches beyond the age gate; a fresh WhatsApp turn is still the final live proof.

## Code status

- A Next.js 16 TypeScript application exists and passes lint and production builds.
- The public GitHub repository is `connectwithvandy/whatsapp-accountability-partner-ted`.
- GitHub `main` is connected to Vercel and deploys automatically.
- The public Vercel URL is `https://whatsapp-accountability-partner-ted.vercel.app`.
- Convex is connected to the Next.js application.
- Vitest and React Testing Library are configured.
- A secret-free `.env.example` documents Convex, OpenAI, Hermes and Vercel settings without containing credentials.
- The redesigned mobile-first landing page is intentionally short: one promise, one clearly labelled example day centered on the 7:42 PM recovery moment, one evening review, a plain privacy/safety note, and repeated WhatsApp handoff.
- The warmer, playful design experiment was rejected and removed. The previous local landing design is restored. Reduced-motion settings are respected.
- The WhatsApp buttons pre-fill “Okay Ted, let's do this!” and read Ted's number from `NEXT_PUBLIC_TED_WHATSAPP_NUMBER`; the number is configured locally and on Vercel.
- The website-matched Ted profile picture and cover image are saved in `docs/brand/` and have been uploaded to the WhatsApp Business profile.
- The latest landing page is live in production at `https://whatsapp-accountability-partner-ted.vercel.app`. It uses the shorter four-section story, the WhatsApp conversation hero, the new split `Message Ted` action, and no visible dash punctuation in user-facing copy.
- Current official OpenAI documentation confirms support for typed text, meal photos, voice-note transcription and health-plan PDFs. The chosen starting models are `gpt-5.6-terra` for Responses API inputs and `gpt-transcribe` for voice notes.
- OpenAI accepted the locally configured API key. Paid model responses and output quality are not yet tested.
- The default production Convex deployment is `hardy-scorpion-901` in Europe (Ireland).
- Vercel deploys Convex functions and the Next.js application together on every production build.
- The production build deliberately uses Webpack during Build Week because this is the path already verified locally and on Vercel. Reconsider the default Turbopack build after the demo instead of changing the build path mid-week.
- The production Convex schema defines user-owned records for consent and identity, resumable onboarding, per-user facts, targets, reminder settings, and day-scoped progress entries. It includes user/date indexes, deduplication keys, corrections, and a separate pending-clarification state so uncertainty is not saved as confirmed data.
- The Convex data-contract tests, Convex TypeScript check, and lint pass. The schema and authenticated `/ted-memory` endpoint are deployed to production. The endpoint accepts only the shared Hermes secret; internal queries and mutations are not public.
- Hermes `SOUL.md` was rolled back from the compressed 5,715-character rewrite to the exact earlier Ted persona recovered from the 9:24 PM request snapshot (11,270 bytes). WhatsApp access and gateway settings were not changed.
- A static `/privacy` route now answers what is stored, who can see it, how long it is kept, and exactly how to request deletion. The existing landing-page footer links to it. It is live at `https://whatsapp-accountability-partner-ted.vercel.app/privacy` and returned HTTP 200 from an unauthenticated public request. All 9 web tests, lint, and the production build pass; no interactive browser was connected in this session.
- OpenRouter's model endpoint verified the exact ID `anthropic/claude-sonnet-5`, which is the model already selected in Hermes. A five-message test ran against that model and then through the live gates: name onboarding, linked disclosure, age request before calories, removal of the unproven “33 noted” claim, and a single height request before maintenance.

## Web product we are building

The public web app explains Ted, sends interested visitors into the existing WhatsApp experience, captures leads, and stores/shows web data. WhatsApp message handling belongs entirely to Hermes.

## Foundation result

The stripped-down landing page passes its focused tests, lint, TypeScript, and a production build. The prepared WhatsApp message remains in the button link but is no longer revealed on the page. The obsolete `TED_PERSONALITY.md` dependency and its test have been removed because Ted's personality belongs only in Hermes `SOUL.md`. Visual browser review is still pending because no browser was connected in the coding session.

## Exact next step

- Website track: visually check the live `/privacy` page in a signed-out browser when one is connected, then collect landing-page feedback.
- Beta track: send one fresh message from Vandy, verify the per-user Convex facts were loaded and a new confirmed fact was saved, then resume tester onboarding. Do not onboard another tester before this proof.
- Backend track: per-user fact memory is live in production. Full Convex onboarding writes, meal/progress logs, and a resume-from-field engine remain next; Hermes shared memory must stay disabled.
- Build check: focused page tests, lint, and the production build pass for the restored local design.

## Local design experiment — 1 Sep 2026

- A standalone recovery-led landing-page experiment now lives in `design-experiments/ted-recovery-led/`. It is not imported by `src/app`, creates no Next.js route, and has not been deployed.
- The experiment keeps the approved recovery and no-shame copy, gives plum clear brand ownership, limits dark coral to warm emphasis, removes lime and monospace labels, simplifies the WhatsApp action, widens the desktop story, and adds one continuous meal-photo → correction → daily-progress conversation to prove memory.
- It also adds the adult-only beta notice, uses the scoped salute-emoji opening message inside the experiment only, and names Vandana Agarwal as the independent beta operator. A verified public contact email is still required before any production use.
- Static contrast checks pass for the intended text sizes. All 9 web tests, lint, and the production build pass. Browser review is still pending because no browser was connected in this session.
