# Ted — WhatsApp Fitness Coach V1 Progress

Last updated: Sun 30 Aug 2026, Asia/Kolkata

## What we decided

- The product name is Ted.
- The pre-filled user message is “Okay, let’s do this 🫡”.
- Ted's first reply is “Chalo, scene set karte hain 😌 First things first: what are we trying to fix?”
- Hermes is the only WhatsApp bridge.
- Hermes pairs to an ordinary WhatsApp account by QR code, like WhatsApp Web.
- Hermes runs as a separate local process in its own terminal window.
- Ted communicates with Hermes over the local machine; it does not need a hosted messaging service.
- Do not use Twilio or build a Telegram fallback.
- Use Convex for stored state and scheduling and Vercel for the public web application.
- The live product uses the OpenAI API for interpretation and transcription.
- Voice notes work for health plans, meals and all progress updates. PDFs work only for health plans.
- Store raw photos, voice notes and PDFs until the user deletes their data.
- Use Mifflin–St Jeor for optional maintenance-calorie estimates.
- Every scoped setup field is mandatory.
- Sleep tracking is not part of V1; revisit it with a future Apple Health connection.

## Hermes setup status

- The transport decision is recorded across the project notes and implementation plan.
- The local adapter accepts a normalized Hermes message event and reaches Ted's shared text handler.
- The local simulator proves the adapter path without sending a real WhatsApp message.
- The exact Hermes address, event format, send command, media behavior and session lifecycle still need to be confirmed against the installed Hermes process.
- QR pairing and a real inbound/outbound WhatsApp exchange have not been tested yet.
- The public Vercel deployment cannot reach a process bound only to a developer laptop's `localhost`. The WhatsApp worker must run on the same machine as Hermes, while the public site can remain on Vercel.

## Code status

- A Next.js 16 TypeScript application exists and passes lint and production builds.
- The public GitHub repository is `connectwithvandy/whatsapp-accountability-partner-ted`.
- GitHub `main` is connected to Vercel and deploys automatically.
- The public Vercel URL is `https://whatsapp-accountability-partner-ted.vercel.app`.
- Convex is connected to the Next.js application.
- Vitest and React Testing Library are configured.
- A secret-free `.env.example` documents Convex, OpenAI, Hermes and Vercel settings without containing credentials.
- A local-only Hermes adapter and simulator return Ted's first reply for a normalized text event.
- Current official OpenAI documentation confirms support for typed text, meal photos, voice-note transcription and health-plan PDFs. The chosen starting models are `gpt-5.6-terra` for Responses API inputs and `gpt-transcribe` for voice notes.
- OpenAI accepted the locally configured API key. Paid model responses and output quality are not yet tested.
- The default production Convex deployment is `hardy-scorpion-901` in Europe (Ireland).
- Vercel deploys Convex functions and the Next.js application together on every production build.

## Product we are building

A WhatsApp fitness coach where a user sends a meal or activity update, the app understands and saves it, replies against that person's targets, sends one reminder and produces a daily review.

First working path:

`WhatsApp message → local Hermes process → Ted message handler → understand typed input → save in Convex → Hermes reply → WhatsApp`

Text is implemented first to establish the shared path. Photo, voice and PDF health-plan support remain required V1 scope and are added after the typed path works end to end.

## Foundation result

The local Foundation pass check is complete: the app runs and builds, tests pass, Convex connects, environment examples contain no secrets, and a simulated Hermes message reaches the shared message handler. The old transport assumptions have been removed. Real Hermes pairing and delivery remain unverified.

## Exact next step

Confirm the installed Hermes process's local interface, then run one real paired inbound message and one reply. The landing page can be built in parallel with this transport verification.
