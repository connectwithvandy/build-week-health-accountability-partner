# Ted — a WhatsApp health accountability partner

Ted remembers your meals, movement, water and commitments in WhatsApp, then
gives you one useful thing you can still do today. It is in a private, invited
beta.

Live: <https://heyted.vercel.app>

## How the pieces fit

Ted is two programs, and the split matters:

- **Hermes** is the product. It is a WhatsApp gateway that runs beside this repo
  (in `~/.hermes`, not in it) and holds the actual conversation. Ted's persona
  lives in its `SOUL.md`.
- **This repo** is the public website, the Convex data layer, and the safety
  gates that Hermes loads as a plugin. It never sends or receives a WhatsApp
  message.

What lives where:

| Path | What it is |
| --- | --- |
| `public/landing-v6.html` | The live landing page. One self-contained static file, served at `/` by a `beforeFiles` rewrite in `next.config.ts` — so what ships is byte-for-byte the design that was reviewed. There is deliberately no `src/app/page.tsx`. |
| `src/app/privacy/` | The privacy page. Ordinary React, and the only route a user reaches besides `/`. |
| `src/app/api/hermes/` | A local-only test endpoint. Disabled in production; it never touches WhatsApp. |
| `convex/` | Schema, queries, mutations, and the authenticated `/ted-memory` HTTP endpoint. |
| `hermes/ted_safety_gates/` | The safety gates Hermes loads as a plugin — the calorie, consent and claim rules. This is the load-bearing code. |
| `scripts/` | Operational checks (see below) and re-appliable patches for the Hermes gateway. |
| `design-experiments/` | The landing-page lineage. Not imported, not routed, not deployed. |

## Running it

```bash
npm install
npm run dev          # http://localhost:3000
```

Copy `.env.example` to `.env.local` and fill it in. Note that the gateway reads
`~/.hermes/.env`, **not** this file — several variables must be set in both
places, and `.env.example` says which.

Send a Hermes-shaped message through the local handler, with the dev server
running in another terminal:

```bash
npm run simulate:hermes
npm run simulate:hermes -- "I ate two rotis and paneer"
```

## Tests

```bash
npm test                        # web tests (vitest)
.venv/bin/python -m pytest -q   # safety-gate tests
npm run lint
npx tsc --noEmit
npm run build
```

Run the Python tests **with pytest**, never `python3 -m unittest` — pytest loads
the root `conftest.py`, which redirects every machine path away from
`~/.hermes` and drops inherited Convex credentials. Without it a test run writes
fixture keys into live gateway state.

## Operational checks

| Command | What it answers |
| --- | --- |
| `npm run gates:guard` | Are the safety gates actually loaded in the running gateway? Run after every restart, rename or gate edit. |
| `npm run hermes:patch:check` | Are all 8 gateway patches still applied? |
| `npm run convex:check` | Does the deployed Convex backend still match this repo? |
| `npm run reports` | Replies users reported as wrong. |
| `npm run submission:report` | Build Week numbers from production Convex. Read-only, but it **rewrites `SUBMISSION.md`**. |

`gates:guard` is the hard stop for an ungated Ted: Hermes swallows a plugin load
failure and keeps serving WhatsApp, so the check has to come from outside.

## Project rules

`AGENTS.md` lists what to read before changing anything. `PROGRESS.md` is the
current true state and is updated at the end of each session.
