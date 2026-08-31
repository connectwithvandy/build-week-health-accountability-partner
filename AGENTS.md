<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## Project rules

Read before every session, in this order:

- `IDEA_SCOPE.md` — scope control plane and parking-lot rules
- `PRODUCT_BUILD_GUARDRAILS.md` — non-negotiable engineering rules
- `SCOPING.md` — user-facing V1 contract
- `TED_PERSONALITY.md` — voice; never put user data in this file
- `PROGRESS.md` — current true state; update it at the end of each session

If a change does not improve the active milestone's acceptance test, put it in the `IDEA_SCOPE.md` parking lot.

Never commit keys, phone numbers, tokens, or Hermes session data.
