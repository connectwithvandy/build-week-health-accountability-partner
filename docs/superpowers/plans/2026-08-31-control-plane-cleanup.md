# Control Plane Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repository instructions and status documents agree without changing Ted’s positioning, onboarding, privacy behavior, or production application.

**Architecture:** `AGENTS.md` will load the project documents in a fixed order, `PROGRESS.md` will remain the only current-state source, and `IDEA_SCOPE.md` will retain intent and decisions only. Copy fixtures will use the corrected WhatsApp opening message everywhere.

**Tech Stack:** Markdown project documentation, JSON skill lock, Next.js/Vitest fixtures

**Spec:** External review notes dated Mon 31 Aug 2026

## Global Constraints

- Do not change positioning or landing-page structure while positioning is under discussion.
- Do not implement or revise onboarding.
- Do not add privacy-policy work in this cleanup.
- Do not change Hermes transport code.
- Never commit keys, phone numbers, tokens, or Hermes session data.

---

### Task 1: Load the control plane

**Files:**
- Modify: `AGENTS.md`
- Keep: `CLAUDE.md`

**Interfaces:**
- Consumes: the existing generated Next.js rules marker
- Produces: a fixed reading order below the generated marker

- [x] **Step 1: Confirm `CLAUDE.md` contains only `@AGENTS.md` and keep it as a non-duplicating compatibility pointer**
- [x] **Step 2: Append the project reading order and secret-handling rules below the generated Next.js block**
- [x] **Step 3: Verify the new rules are outside the generated markers**

### Task 2: Make progress state single-source

**Files:**
- Modify: `IDEA_SCOPE.md`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: current status from `PROGRESS.md`
- Produces: scope status rows and a current-state section that point to `PROGRESS.md`

- [x] **Step 1: Replace stale milestone, URL, and repository rows with a `PROGRESS.md` pointer**
- [x] **Step 2: Remove the stale current-state claims from `IDEA_SCOPE.md`**
- [x] **Step 3: Record why the verified Webpack build command remains during Build Week**

### Task 3: Align safe configuration and copy fixtures

**Files:**
- Modify: `skills-lock.json`
- Modify: all files containing the WhatsApp opening message

**Interfaces:**
- Consumes: the agreed message `Okay Ted, let's do this 🫡`
- Produces: one exact string across code, tests, simulator, and documentation

- [x] **Step 1: Remove the unused `convex-auth` skill entry**
- [x] **Step 2: Correct spacing in every opening-message occurrence**
- [x] **Step 3: Run a repository search proving the old string is gone**
- [x] **Step 4: Run tests, lint, and JSON validation**
