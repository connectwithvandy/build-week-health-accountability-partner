# Ted Landing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the starter screen with a polished mobile-first landing page that explains Ted and opens WhatsApp with the agreed first message.

**Architecture:** Keep the landing page as a static Next.js Server Component so it ships without client-side JavaScript. Build the WhatsApp link from a public environment variable and render the complete page from semantic HTML and global CSS.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Tailwind CSS 4/global CSS, Vitest, React Testing Library

**Spec:** `SCOPING.md`

## Global Constraints

- The primary action is “Start on WhatsApp”.
- The pre-filled message is exactly “Okay Ted, let's do this 🫡”.
- The page includes benefits, supported inputs, a realistic chat, how it works, privacy and safety information, and repeated calls to action.
- Personal onboarding stays inside WhatsApp; there is no login, payment, waitlist, or dashboard.
- Health information is not collected until consent is accepted inside WhatsApp.
- The WhatsApp number comes from `NEXT_PUBLIC_TED_WHATSAPP_NUMBER` and is not committed.

---

### Task 1: Landing page behavior and copy

**Files:**
- Modify: `__tests__/page.test.tsx`
- Modify: `src/app/page.tsx`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `process.env.NEXT_PUBLIC_TED_WHATSAPP_NUMBER`
- Produces: a WhatsApp `wa.me` link containing the configured number and encoded opening message

- [x] **Step 1: Write failing tests for the page promise, repeated WhatsApp actions, pre-filled message, and privacy copy**
- [x] **Step 2: Run `npm test -- __tests__/page.test.tsx` and confirm the starter page fails the new expectations**
- [x] **Step 3: Implement the semantic landing-page sections and environment-backed WhatsApp URL**
- [x] **Step 4: Add `NEXT_PUBLIC_TED_WHATSAPP_NUMBER=` to `.env.example`**
- [x] **Step 5: Run the focused test and confirm it passes**

### Task 2: Visual system and page metadata

**Files:**
- Modify: `src/app/globals.css`
- Modify: `src/app/layout.tsx`

**Interfaces:**
- Consumes: semantic class names from `src/app/page.tsx`
- Produces: responsive layout, visible keyboard focus, reduced-motion support, and Ted-specific search/share metadata

- [x] **Step 1: Define the navy, cobalt, safety-orange, paper-white, and mint token system**
- [x] **Step 2: Build the mobile-first training-log layout and WhatsApp conversation card**
- [x] **Step 3: Add desktop composition, accessible focus states, and reduced-motion behavior**
- [x] **Step 4: Replace starter metadata with Ted’s title and description**
- [x] **Step 5: Run `npm test`, `npm run lint`, and `npm run build`**

### Task 3: Browser verification

**Files:**
- Verify: `src/app/page.tsx`
- Verify: `src/app/globals.css`

**Interfaces:**
- Consumes: locally rendered landing page
- Produces: evidence that the mobile and desktop page renders and the WhatsApp link is correct

- [ ] **Step 1: Start the site on a port that does not conflict with Hermes**
- [ ] **Step 2: Inspect the page at mobile and desktop widths**
- [ ] **Step 3: Check the browser console and WhatsApp link target**
- [ ] **Step 4: Fix any visible layout or accessibility problems and repeat the checks**

### Task 4: Replace the template-like page with Ted's daily accountability story

**Files:**
- Modify: `__tests__/page.test.tsx`
- Modify: `src/app/page.tsx`
- Modify: `src/app/globals.css`
- Modify: `src/app/layout.tsx`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: the existing `getWhatsAppUrl()` behavior and `NEXT_PUBLIC_TED_WHATSAPP_NUMBER`
- Produces: a static, responsive landing page organized around Ted's core dinner-time recovery moment

- [x] **Step 1: Replace the old promise test with expectations for the dinner-time problem, remembered context, one practical next action, privacy, and the repeated WhatsApp action**
- [x] **Step 2: Run `npm test -- __tests__/page.test.tsx` and confirm the new story expectations fail**
- [x] **Step 3: Rewrite the page around four real moments: set the plan, log during the day, recover at 7:42 PM, and close with an honest review**
- [x] **Step 4: Replace the blue blob, numbered feature cards, and generic three-step block with a WhatsApp-native day timeline and a single prominent 7:42 PM rescue conversation**
- [x] **Step 5: Use a deep aubergine, electric lime, warm cloud, WhatsApp green, coral, and muted lavender token system; keep Space Grotesk for display, Manrope for body, and IBM Plex Mono for time and data labels**
- [x] **Step 6: Update the page title and description to promise follow-through during a busy workday without claiming unverified results**
- [ ] **Step 7: Run the focused test, full tests, lint, and production build**
- [ ] **Step 8: Render desktop and mobile screenshots, inspect overflow, focus states, text hierarchy, and the WhatsApp target, then fix visible problems**
- [x] **Step 9: Record the verified result and any remaining live-browser limitation in `PROGRESS.md`**
