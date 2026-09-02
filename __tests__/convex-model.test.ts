import { describe, expect, it } from "vitest";

import {
  dailyEntryStates,
  dailyEntryTypes,
  goals,
  inputSources,
  isLocalDateKey,
  isLocalTimeKey,
  buildDedupeKey,
  normaliseMealItems,
  onboardingFields,
  summariseDay,
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

describe("Daily entry dedupe keys", () => {
  const base = {
    localDate: "2026-09-02",
    entryType: "meal" as const,
    occurredAt: 1_788_350_000_000,
    meal: {
      items: ["Paneer roll", "dal"],
      calories: 380,
      proteinGrams: 19,
      carbohydrateGrams: 40,
      fatGrams: 14,
      fiberGrams: 6,
    },
  };

  it("collapses a re-delivered WhatsApp message to one key", () => {
    const first = buildDedupeKey({ ...base, externalMessageId: "wamid.ABC" });
    const second = buildDedupeKey({
      ...base,
      externalMessageId: "wamid.ABC",
      occurredAt: base.occurredAt + 4_000,
    });
    expect(first).toBe(second);
    expect(first).toBe("msg:wamid.ABC");
  });

  it("does not collapse two separate messages", () => {
    expect(buildDedupeKey({ ...base, externalMessageId: "wamid.A" })).not.toBe(
      buildDedupeKey({ ...base, externalMessageId: "wamid.B" }),
    );
  });

  it("keeps two glasses of water an hour apart as separate entries", () => {
    const morning = buildDedupeKey({
      localDate: "2026-09-02",
      entryType: "water",
      occurredAt: 1_788_350_000_000,
      waterMl: 250,
    });
    const later = buildDedupeKey({
      localDate: "2026-09-02",
      entryType: "water",
      occurredAt: 1_788_353_600_000,
      waterMl: 250,
    });
    expect(morning).not.toBe(later);
  });

  it("ignores item order and casing when signing a meal", () => {
    expect(normaliseMealItems(["Dal ", "  paneer  roll"])).toEqual([
      "dal",
      "paneer roll",
    ]);
    const a = buildDedupeKey({ ...base, meal: { ...base.meal, items: ["dal", "Paneer roll"] } });
    const b = buildDedupeKey({ ...base, meal: { ...base.meal, items: ["Paneer roll", "dal "] } });
    expect(a).toBe(b);
  });
});

describe("Day summary", () => {
  const entry = (overrides: Record<string, unknown>) => ({
    localDate: "2026-09-02",
    entryType: "meal" as const,
    state: "confirmed" as const,
    ...overrides,
  });

  const meal = (calories: number, proteinGrams: number) => ({
    items: ["something"],
    calories,
    proteinGrams,
    carbohydrateGrams: 0,
    fatGrams: 0,
    fiberGrams: 0,
  });

  it("adds up the day the way Ted reads it back", () => {
    const summary = summariseDay("2026-09-02", [
      entry({ meal: meal(380, 19) }),
      entry({ meal: meal(450, 22) }),
      entry({ meal: meal(350, 12) }),
      entry({ entryType: "water", waterMl: 250 }),
      entry({ entryType: "water", waterMl: 750 }),
      entry({ entryType: "steps", steps: 4200 }),
      entry({ entryType: "workout", workoutMinutes: 20 }),
      entry({ entryType: "commitment", commitmentId: "morning-walk" }),
    ]);

    expect(summary.meals).toBe(3);
    expect(summary.calories).toBe(1180);
    expect(summary.proteinGrams).toBe(53);
    expect(summary.waterMl).toBe(1000);
    expect(summary.steps).toBe(4200);
    expect(summary.workoutMinutes).toBe(20);
    expect(summary.commitmentsDone).toBe(1);
  });

  it("counts a correction once, not twice", () => {
    const summary = summariseDay("2026-09-02", [
      entry({ state: "corrected", meal: meal(520, 31) }),
      entry({ meal: meal(380, 19) }),
    ]);
    expect(summary.meals).toBe(1);
    expect(summary.calories).toBe(380);
  });

  it("leaves an unconfirmed guess out of the totals", () => {
    const summary = summariseDay("2026-09-02", [
      entry({ state: "pendingClarification", meal: meal(999, 40) }),
    ]);
    expect(summary.meals).toBe(0);
    expect(summary.calories).toBe(0);
  });

  it("treats steps as a running total, not an increment", () => {
    const summary = summariseDay("2026-09-02", [
      entry({ entryType: "steps", steps: 4200 }),
      entry({ entryType: "steps", steps: 9100 }),
    ]);
    expect(summary.steps).toBe(9100);
  });

  it("ignores another day's entries", () => {
    const summary = summariseDay("2026-09-02", [
      entry({ localDate: "2026-09-01", meal: meal(600, 30) }),
      entry({ meal: meal(380, 19) }),
    ]);
    expect(summary.calories).toBe(380);
  });
});

describe("Local time keys", () => {
  it("accepts real clock times and rejects the rest", () => {
    expect(isLocalTimeKey("20:00")).toBe(true);
    expect(isLocalTimeKey("00:00")).toBe(true);
    expect(isLocalTimeKey("23:59")).toBe(true);
    expect(isLocalTimeKey("24:00")).toBe(false);
    expect(isLocalTimeKey("8:00")).toBe(false);
    expect(isLocalTimeKey("20:60")).toBe(false);
  });
});
