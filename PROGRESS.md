# Ted — WhatsApp Fitness Coach V1 Progress

Last updated: Mon 31 Aug 2026, Asia/Kolkata

## What we decided

- The product name is Ted.
- The pre-filled user message is “Okay Ted, let's do this”.
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
- Its language balance, media replies, internal-message leakage, and other behaviour are Hermes/SOUL.md concerns, not web-app code.
- Legacy local adapter, worker, simulator, API route, and tests remain in the repository but are not the product direction and must not be extended.

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
- The WhatsApp buttons pre-fill “Okay Ted, let's do this” and read Ted's number from `NEXT_PUBLIC_TED_WHATSAPP_NUMBER`; the number is configured locally and on Vercel.
- Mascot and WhatsApp profile-picture exploration is parked for V2. No generated image has been uploaded to WhatsApp.
- The latest landing page is live in production at `https://whatsapp-accountability-partner-ted.vercel.app`. It uses the shorter four-section story, the WhatsApp conversation hero, the new split `Message Ted` action, and no visible dash punctuation in user-facing copy.
- Current official OpenAI documentation confirms support for typed text, meal photos, voice-note transcription and health-plan PDFs. The chosen starting models are `gpt-5.6-terra` for Responses API inputs and `gpt-transcribe` for voice notes.
- OpenAI accepted the locally configured API key. Paid model responses and output quality are not yet tested.
- The default production Convex deployment is `hardy-scorpion-901` in Europe (Ireland).
- Vercel deploys Convex functions and the Next.js application together on every production build.
- The production build deliberately uses Webpack during Build Week because this is the path already verified locally and on Vercel. Reconsider the default Turbopack build after the demo instead of changing the build path mid-week.
- A local Convex schema now defines user-owned records for consent and identity, resumable onboarding, targets, reminder settings, and day-scoped progress entries. It includes user/date indexes, deduplication keys, and a separate pending-clarification state so uncertainty is not saved as confirmed data.
- The Convex data-contract tests, Convex TypeScript check, and lint pass. The schema has not been deployed, and no public database write functions have been exposed yet.

## Web product we are building

The public web app explains Ted, sends interested visitors into the existing WhatsApp experience, captures leads, and stores/shows web data. WhatsApp message handling belongs entirely to Hermes.

## Foundation result

The stripped-down landing page passes its focused tests, lint, TypeScript, and a production build. The prepared WhatsApp message remains in the button link but is no longer revealed on the page. Full tests still fail because an obsolete Hermes test expects the removed `TED_PERSONALITY.md`; that legacy test was not changed during the landing-page work. Visual browser review is still pending because no browser was connected in the coding session.

## Exact next step

- Website track: collect feedback on the live landing page from desktop and mobile visitors, then revise the look and copy before adding lead capture.
- Beta track: Vandy copies the opener from `docs/BETA_TESTER_FLOW.md` into Hermes `SOUL.md`, verifies it in the real WhatsApp thread, then sends the tester invitation to known adult users.
- Backend track: Convex onboarding writes and a resume-from-field engine are parked until real-user behavior shows they are needed.
- Build check: focused page tests, lint, and the production build pass for the restored local design.
