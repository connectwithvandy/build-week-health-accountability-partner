# Ted Recovery-Led Design Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reviewable landing-page design experiment that applies the supplied brand, accessibility, copy, and product-proof critique without changing any Next.js route or the live website.

**Architecture:** The experiment lives in `design-experiments/ted-recovery-led/` as standalone HTML and CSS. It does not import from, write to, or route through `src/app`, so a normal Next.js build and deployment cannot expose it. A short README records the experiment boundary and local preview command.

**Tech Stack:** Semantic HTML, standalone CSS, local static HTTP preview, existing npm checks for regression safety.

**Spec:** User critique supplied on 2026-09-01, plus `IDEA_SCOPE.md`, `PRODUCT_BUILD_GUARDRAILS.md`, and `SCOPING.md`.

## Global Constraints

- Do not modify `src/app/page.tsx`, `src/app/globals.css`, `src/app/layout.tsx`, or any production route.
- Keep the three approved lines exactly: “Your day slipped away. You can still turn it around.”, “No pretending the day was perfect. Just an honest close.”, and “One useful move. No guilt trip.”
- Use plum as the brand owner, dark coral only as a warm emphasis, and WhatsApp green only where it communicates WhatsApp or completion.
- Use two type roles with no monospace labels.
- Demonstrate meal-photo understanding, correction memory, and “How am I doing today?” context in one continuous example.
- Include the 18+ beta boundary, privacy before the final action, the prepared message “Okay Ted, let's do this 🫡”, and a truthful operator line without inventing contact information.
- Respect visible keyboard focus, semantic landmarks, responsive layouts, and reduced-motion preferences.
- Never commit keys, phone numbers, tokens, or Hermes session data.

---

### Task 1: Create the isolated experiment

**Files:**
- Create: `design-experiments/ted-recovery-led/index.html`
- Create: `design-experiments/ted-recovery-led/styles.css`
- Create: `design-experiments/ted-recovery-led/README.md`

**Interfaces:**
- Consumes: The approved landing-page copy and V1 product contract.
- Produces: A standalone page opened only through its local `index.html`; no Next.js route or shared stylesheet.

- [x] **Step 1: Write semantic page structure**

Create a header, hero, continuous memory demonstration, evening recovery section, privacy section, final WhatsApp action, and operator footer. Use an inline meal illustration so the experiment has no asset dependency.

- [x] **Step 2: Add a small brand token system**

Define CSS custom properties for `--plum-900`, `--plum-700`, `--coral-700`, `--whatsapp`, `--done`, `--paper`, `--white`, `--ink`, `--muted`, and `--line`. Apply the coral only to short highlighted text and a small recovery marker.

- [x] **Step 3: Add responsive and accessible states**

Add a wide asymmetric desktop grid, a single-column mobile layout, `:focus-visible` outlines, minimum 44px action targets, and a `prefers-reduced-motion` rule.

- [x] **Step 4: Document isolation and preview**

State that the folder is not imported by Next.js and provide `python3 -m http.server 4173 --directory design-experiments/ted-recovery-led` as the local preview command.

### Task 2: Verify without touching production

**Files:**
- Modify: `PROGRESS.md`
- Test: `design-experiments/ted-recovery-led/index.html`

**Interfaces:**
- Consumes: The standalone experiment from Task 1.
- Produces: Visual review evidence and a progress note that clearly distinguishes the experiment from the live page.

- [x] **Step 1: Check required and rejected content**

Search the experiment for the three protected lines, correction flow, progress question, privacy text, 18+ notice, salute emoji, operator line, and exactly one “Free during beta” phrase. Confirm no lime token or monospace font remains.

- [x] **Step 2: Measure critical color contrast**

Calculate the dark coral against paper and white, and the button text against plum. Require at least 3:1 for large text and 4.5:1 for normal text.

- [x] **Step 3: Run repository checks**

Run `npm test`, `npm run lint`, and `npm run build`. Existing dirty backend and Hermes files are user work and must remain untouched.

- [ ] **Step 4: Review in a browser**

Serve the standalone folder locally, inspect desktop and mobile widths, verify the WhatsApp action and privacy anchor, and take screenshots for comparison.

- [x] **Step 5: Update true state**

Add a dated `PROGRESS.md` note saying the standalone experiment exists locally, has not changed `src/app`, and is not deployed.
