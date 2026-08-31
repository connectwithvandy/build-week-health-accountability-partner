import { describe, expect, it } from "vitest";

import {
  dailyEntryStates,
  dailyEntryTypes,
  goals,
  inputSources,
  isLocalDateKey,
  onboardingFields,
} from "../convex/model";

describe("Convex data model", () => {
  it("covers every required onboarding section", () => {
    expect(onboardingFields).toEqual([
      "consent",
      "name",
      "age",
      "height",
      "weight",
      "timeZone",
      "goal",
      "nutrition",
      "steps",
      "water",
      "workouts",
      "customCommitments",
      "reminders",
      "dailyReview",
      "quietHours",
      "morningCommitment",
      "confirmation",
      "complete",
    ]);
  });

  it("covers the V1 goals, inputs, progress types, and save states", () => {
    expect(goals).toEqual([
      "maintainWeight",
      "loseWeight",
      "gainWeight",
      "improveConsistency",
    ]);
    expect(inputSources).toEqual(["text", "voice", "photo", "pdf", "system"]);
    expect(dailyEntryTypes).toEqual([
      "meal",
      "water",
      "steps",
      "workout",
      "commitment",
    ]);
    expect(dailyEntryStates).toEqual(["pendingClarification", "confirmed", "corrected"]);
  });

  it("accepts real local calendar dates and rejects impossible ones", () => {
    expect(isLocalDateKey("2026-08-31")).toBe(true);
    expect(isLocalDateKey("2026-02-29")).toBe(false);
    expect(isLocalDateKey("2024-02-29")).toBe(true);
    expect(isLocalDateKey("31-08-2026")).toBe(false);
  });
});
