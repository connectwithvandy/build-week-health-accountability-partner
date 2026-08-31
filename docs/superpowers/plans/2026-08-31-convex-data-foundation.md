# Convex Data Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define the first persistent, multi-user data model for consent, resumable onboarding, fitness targets, reminder preferences, and day-scoped progress.

**Architecture:** Convex remains the provisioned database. Shared validators define the allowed values once, and `convex/schema.ts` composes them into user-owned tables with indexes for identity and daily lookups. This slice does not add public database writes; caller authentication must be designed before mutations are exposed.

**Tech Stack:** Convex 1.45, TypeScript, Vitest

**Spec:** `SCOPING.md`

## Global Constraints

- Every persisted record must belong to an explicit user ID.
- The WhatsApp number identifies the user, but secrets and Hermes session data must never be stored.
- Daily activity must be keyed by the user's local calendar date.
- Unclear input must not become a confirmed or zero-value log.
- Website copy, website design, and the Hermes connection are out of scope.

---

### Task 1: Define and test the data contract

**Files:**
- Create: `convex/model.ts`
- Create: `__tests__/convex-model.test.ts`

**Interfaces:**
- Produces: validators for onboarding fields, goals, entry types, input sources, entry states, and date keys

- [x] **Step 1: Write tests that accept every scoped value and reject invalid local-date keys.**
- [x] **Step 2: Run the focused test and verify it fails because the model does not exist.**
- [x] **Step 3: Implement the validators and `isLocalDateKey(value: string): boolean`.**
- [x] **Step 4: Run the focused test and verify it passes.**

### Task 2: Add the user-owned Convex schema

**Files:**
- Create: `convex/schema.ts`

**Interfaces:**
- Consumes: validators from `convex/model.ts`
- Produces: `users`, `onboarding`, `targets`, `reminders`, and `dailyEntries` tables

- [x] **Step 1: Define user identity and consent fields with a unique-lookup index.**
- [x] **Step 2: Define resumable onboarding and one-record-per-user lookup indexes.**
- [x] **Step 3: Define targets, reminder preferences, and user/date-scoped progress entries.**
- [x] **Step 4: Add deduplication and status fields without treating uncertain entries as confirmed.**
- [x] **Step 5: Typecheck the Convex project.**

### Task 3: Verify and record the new state

**Files:**
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: test, Convex typecheck, lint, and production-build results
- Produces: an honest statement of what is implemented and what remains unverified

- [x] **Step 1: Run the focused data-contract test.**
- [x] **Step 2: Run lint and the production build.**
- [x] **Step 3: Record that the schema is local until deployed and that no database mutations are exposed yet.**

Build note: lint passed, but the production build is blocked by an existing landing-page configuration that requests unsupported DM Mono weight `700`.
