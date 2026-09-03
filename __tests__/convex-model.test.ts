import { describe, expect, it } from "vitest";

import {
  dailyEntryStates,
  dailyEntryTypes,
  goals,
  inputSources,
  isLocalDateKey,
  isLocalTimeKey,
  buildDedupeKey,
  decideReminderDelivery,
  findClashingEntry,
  isPaused,
  isWithinQuietHours,
  needsDateConfirmation,
  normaliseMealItems,
  onboardingFields,
  summariseDay,
  summariseWeek,
  weekStartFor,
  weekDates,
  addLocalDays,
  NUDGES_BEFORE_BREAK_OFFER,
  SAME_MEAL_WINDOW_MINUTES,
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
      "weeklyReview",
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

describe("Near-duplicate logs (milestone 10)", () => {
  const noon = Date.UTC(2026, 8, 2, 13, 15);
  const minutes = (n: number) => n * 60 * 1000;

  const meal = (occurredAt: number, state = "confirmed" as const) => ({
    entryType: "meal" as const,
    state,
    occurredAt,
    dedupeKey: `k${occurredAt}`,
    meal: {
      items: ["dal", "rice"],
      calories: 420,
      proteinGrams: 14,
      carbohydrateGrams: 60,
      fatGrams: 9,
      fiberGrams: 6,
    },
  });

  const plate = (items: string[]) => ({
    items,
    calories: 400,
    proteinGrams: 14,
    carbohydrateGrams: 50,
    fatGrams: 10,
    fiberGrams: 5,
  });

  it("flags the same lunch described again twenty minutes later", () => {
    const clash = findClashingEntry([meal(noon)], {
      entryType: "meal",
      occurredAt: noon + minutes(20),
      commitmentId: undefined,
      meal: plate(["rice", "dal"]),
    });
    expect(clash?.dedupeKey).toBe(`k${noon}`);
  });

  it("lets a second photo of different food straight through", () => {
    // 3 Sep: a second photo, of completely different food, was held back to
    // ask "is this a second one or the same thing again?". The window was the
    // only thing being checked, so the answer was always obvious.
    expect(
      findClashingEntry([meal(noon)], {
        entryType: "meal",
        occurredAt: noon + minutes(20),
        commitmentId: undefined,
        meal: plate(["oats", "protein powder", "nuts and seeds"]),
      }),
    ).toBeNull();
  });

  it("still catches the same meal worded differently", () => {
    expect(
      findClashingEntry([meal(noon)], {
        entryType: "meal",
        occurredAt: noon + minutes(10),
        commitmentId: undefined,
        meal: plate(["the rice I just had"]),
      })?.dedupeKey,
    ).toBe(`k${noon}`);
  });

  it("lets a salad and a toast through for sharing onion and tomato", () => {
    // 3 Sep, 17:32. A sprouts salad and a peanut toast were held apart to ask
    // whether they were the same meal, because both contained onion and
    // tomato. Half of Indian food contains onion and tomato.
    const salad = {
      entryType: "meal" as const,
      state: "confirmed" as const,
      occurredAt: noon,
      dedupeKey: `k${noon}`,
      meal: plate(["moong sprouts", "onion", "tomato", "cilantro", "green chili"]),
    };
    expect(
      findClashingEntry([salad], {
        entryType: "meal",
        occurredAt: noon + minutes(118),
        commitmentId: undefined,
        meal: plate([
          "whole wheat toast",
          "chopped bell pepper/tomato/onion topping with peanuts",
        ]),
      }),
    ).toBeNull();
  });

  it("still catches the same plate described at length", () => {
    expect(
      findClashingEntry([meal(noon)], {
        entryType: "meal",
        occurredAt: noon + minutes(15),
        commitmentId: undefined,
        meal: plate(["the rice and dal I just had"]),
      })?.dedupeKey,
    ).toBe(`k${noon}`);
  });

  it("ignores words that describe rather than name a food", () => {
    // "whole", "chopped" and "with" would otherwise count as shared foods.
    expect(
      findClashingEntry([meal(noon)], {
        entryType: "meal",
        occurredAt: noon + minutes(20),
        commitmentId: undefined,
        meal: plate(["whole chopped apple with cinnamon"]),
      }),
    ).toBeNull();
  });

  it("falls back to the window when a meal has no readable items", () => {
    // An empty set must not silently switch the duplicate guard off.
    expect(
      findClashingEntry([meal(noon)], {
        entryType: "meal",
        occurredAt: noon + minutes(20),
        commitmentId: undefined,
        meal: plate([]),
      })?.dedupeKey,
    ).toBe(`k${noon}`);
  });

  it("lets a genuinely separate meal through once the window has passed", () => {
    expect(
      findClashingEntry([meal(noon)], {
        entryType: "meal",
        occurredAt: noon + minutes(SAME_MEAL_WINDOW_MINUTES + 1),
        commitmentId: undefined,
      }),
    ).toBeNull();
  });

  it("never questions water or steps — accumulating is the normal case", () => {
    const water = {
      entryType: "water" as const,
      state: "confirmed" as const,
      occurredAt: noon,
      dedupeKey: "w1",
    };
    expect(
      findClashingEntry([water], {
        entryType: "water",
        occurredAt: noon + minutes(5),
        commitmentId: undefined,
      }),
    ).toBeNull();

    const steps = { ...water, entryType: "steps" as const, dedupeKey: "s1" };
    expect(
      findClashingEntry([steps], {
        entryType: "steps",
        occurredAt: noon + minutes(5),
        commitmentId: undefined,
      }),
    ).toBeNull();
  });

  it("treats the same commitment twice as a repeat, whatever the gap", () => {
    const commitment = {
      entryType: "commitment" as const,
      state: "confirmed" as const,
      occurredAt: noon,
      dedupeKey: "c1",
      commitmentId: "walk",
    };
    expect(
      findClashingEntry([commitment], {
        entryType: "commitment",
        occurredAt: noon + minutes(600),
        commitmentId: "walk",
      })?.dedupeKey,
    ).toBe("c1");
    expect(
      findClashingEntry([commitment], {
        entryType: "commitment",
        occurredAt: noon + minutes(30),
        commitmentId: "stretch",
      }),
    ).toBeNull();
  });

  it("ignores entries that are corrected or still being clarified", () => {
    for (const state of ["corrected", "pendingClarification"] as const) {
      expect(
        findClashingEntry([meal(noon, state as "confirmed")], {
          entryType: "meal",
          occurredAt: noon + minutes(20),
          commitmentId: undefined,
        }),
      ).toBeNull();
    }
  });

  it("names the nearest entry when several are in the window", () => {
    const clash = findClashingEntry(
      [meal(noon - minutes(90)), meal(noon - minutes(10))],
      { entryType: "meal", occurredAt: noon, commitmentId: undefined },
    );
    expect(clash?.dedupeKey).toBe(`k${noon - minutes(10)}`);
  });
});

describe("Date confirmation (milestone 10)", () => {
  it("asks when the user named a day that is not today", () => {
    expect(needsDateConfirmation("2026-09-01", "2026-09-02", false)).toBe(true);
  });

  it("stays quiet for today", () => {
    expect(needsDateConfirmation("2026-09-02", "2026-09-02", false)).toBe(false);
  });

  it("stops asking once the user has confirmed", () => {
    expect(needsDateConfirmation("2026-09-01", "2026-09-02", true)).toBe(false);
  });

  it("does not block on a malformed date — the mutation rejects that already", () => {
    expect(needsDateConfirmation("yesterday", "2026-09-02", false)).toBe(false);
  });
});

describe("Quiet hours (milestone 12)", () => {
  it("covers a window that wraps past midnight", () => {
    for (const t of ["22:00", "23:30", "00:00", "03:15", "06:59"]) {
      expect(isWithinQuietHours(t, "22:00", "07:00")).toBe(true);
    }
    for (const t of ["07:00", "12:00", "21:59"]) {
      expect(isWithinQuietHours(t, "22:00", "07:00")).toBe(false);
    }
  });

  it("covers a daytime window that does not wrap", () => {
    expect(isWithinQuietHours("14:00", "13:00", "17:00")).toBe(true);
    expect(isWithinQuietHours("12:59", "13:00", "17:00")).toBe(false);
    expect(isWithinQuietHours("17:00", "13:00", "17:00")).toBe(false);
  });

  it("reads an empty window as no quiet hours, never as a full blackout", () => {
    expect(isWithinQuietHours("03:00", "22:00", "22:00")).toBe(false);
  });

  it("does not block on a malformed time", () => {
    expect(isWithinQuietHours("nope", "22:00", "07:00")).toBe(false);
    expect(isWithinQuietHours("03:00", "", "07:00")).toBe(false);
  });
});

describe("Reminder delivery decision (milestone 12)", () => {
  const now = Date.UTC(2026, 8, 2, 9, 0);
  const base = {
    quietHoursStart: "22:00",
    quietHoursEnd: "07:00",
    maxPerDay: 3,
    pausedUntil: undefined,
    sentLocalDate: "2026-09-02",
    sentCount: 0,
  };

  it("lets an ordinary daytime reminder through", () => {
    expect(decideReminderDelivery(base, "09:00", "2026-09-02", now)).toEqual({
      allowed: true,
      reason: "ok",
    });
  });

  it("refuses inside quiet hours", () => {
    expect(decideReminderDelivery(base, "23:30", "2026-09-02", now).reason).toBe(
      "quietHours",
    );
  });

  it("refuses while paused, and says paused rather than quiet hours", () => {
    const paused = { ...base, pausedUntil: now + 60_000 };
    expect(decideReminderDelivery(paused, "23:30", "2026-09-02", now).reason).toBe(
      "paused",
    );
  });

  it("resumes on its own once the pause has expired", () => {
    const paused = { ...base, pausedUntil: now - 1 };
    expect(decideReminderDelivery(paused, "09:00", "2026-09-02", now).allowed).toBe(
      true,
    );
  });

  it("stops at the daily cap", () => {
    const capped = { ...base, sentCount: 3 };
    expect(decideReminderDelivery(capped, "09:00", "2026-09-02", now).reason).toBe(
      "dailyCap",
    );
  });

  it("starts the count again on a new day", () => {
    const yesterday = { ...base, sentLocalDate: "2026-09-01", sentCount: 9 };
    expect(
      decideReminderDelivery(yesterday, "09:00", "2026-09-02", now).allowed,
    ).toBe(true);
  });

  it("still sends when the user has no stored settings at all", () => {
    // The five live vitamin reminders are Hermes cron jobs with no row in this
    // table. Refusing on a missing row silently killed every one of them, and
    // SCOPING #21 puts the number of reminders down to the user's preferences
    // — so absent a preference there is no cap to apply.
    expect(decideReminderDelivery(null, "09:00", "2026-09-02", now)).toEqual({
      allowed: true,
      reason: "ok",
    });
  });

  it("still applies default quiet hours with no stored settings", () => {
    for (const clock of ["22:00", "23:30", "03:00", "06:59"]) {
      expect(decideReminderDelivery(null, clock, "2026-09-02", now)).toEqual({
        allowed: false,
        reason: "quietHours",
      });
    }
    for (const clock of ["07:00", "08:45", "16:00", "21:59"]) {
      expect(decideReminderDelivery(null, clock, "2026-09-02", now).allowed).toBe(
        true,
      );
    }
  });

  it("never caps a user who has not asked for a cap", () => {
    // Ten pings on a day with no stored preferences must all be allowed.
    for (let i = 0; i < 10; i += 1) {
      expect(decideReminderDelivery(null, "09:00", "2026-09-02", now).allowed).toBe(
        true,
      );
    }
  });

  it("treats a missing count as nothing sent yet", () => {
    const fresh = { ...base, sentLocalDate: undefined, sentCount: undefined };
    expect(decideReminderDelivery(fresh, "09:00", "2026-09-02", now).allowed).toBe(
      true,
    );
  });

  it("knows when a pause is live", () => {
    expect(isPaused(now, now + 1)).toBe(true);
    expect(isPaused(now, now)).toBe(false);
    expect(isPaused(now, undefined)).toBe(false);
  });
});


describe("Week boundaries", () => {
  it("resolves any day of the week to that week's Monday", () => {
    // Mon 31 Aug 2026 → Sun 6 Sep 2026.
    for (const date of [
      "2026-08-31",
      "2026-09-01",
      "2026-09-03",
      "2026-09-06",
    ]) {
      expect(weekStartFor(date)).toBe("2026-08-31");
    }
    // Monday the 7th starts the next week, not the same one.
    expect(weekStartFor("2026-09-07")).toBe("2026-09-07");
  });

  it("returns seven consecutive dates, Monday first", () => {
    expect(weekDates("2026-08-31")).toEqual([
      "2026-08-31",
      "2026-09-01",
      "2026-09-02",
      "2026-09-03",
      "2026-09-04",
      "2026-09-05",
      "2026-09-06",
    ]);
  });

  it("crosses month and year ends without drifting", () => {
    expect(addLocalDays("2026-08-31", 1)).toBe("2026-09-01");
    expect(addLocalDays("2026-01-01", -1)).toBe("2025-12-31");
    expect(addLocalDays("2028-02-28", 1)).toBe("2028-02-29");
  });

  it("leaves a malformed date alone rather than inventing one", () => {
    expect(weekStartFor("not-a-date")).toBe("not-a-date");
    expect(addLocalDays("2026-13-01", 1)).toBe("2026-13-01");
  });
});

describe("Week summary", () => {
  const meal = (calories: number, proteinGrams: number) => ({
    items: ["something"],
    calories,
    proteinGrams,
    carbohydrateGrams: 0,
    fatGrams: 0,
    fiberGrams: 0,
  });

  const mealOn = (localDate: string, calories: number, proteinGrams: number) => ({
    localDate,
    entryType: "meal" as const,
    state: "confirmed" as const,
    meal: meal(calories, proteinGrams),
  });

  const stepsOn = (localDate: string, steps: number) => ({
    localDate,
    entryType: "steps" as const,
    state: "confirmed" as const,
    steps,
  });

  it("reads the week back Monday to Sunday", () => {
    const summary = summariseWeek("2026-08-31", [mealOn("2026-09-02", 600, 40)]);
    expect(summary.weekStart).toBe("2026-08-31");
    expect(summary.weekEnd).toBe("2026-09-06");
    expect(summary.days).toHaveLength(7);
  });

  it("averages calories over the days with meals, not over seven", () => {
    // Three days of meals. Dividing by seven would report 600 kcal/day for
    // someone eating 1,400 — arithmetically right, factually a lie.
    const summary = summariseWeek("2026-08-31", [
      mealOn("2026-08-31", 700, 40),
      mealOn("2026-08-31", 700, 40),
      mealOn("2026-09-01", 1400, 90),
      mealOn("2026-09-02", 1400, 80),
    ]);
    expect(summary.averageCalories).toEqual({ value: 1400, days: 3 });
    expect(summary.averageProteinGrams).toEqual({ value: 83, days: 3 });
    expect(summary.meals).toBe(4);
  });

  it("does not let a water-only day drag the calorie average down", () => {
    const summary = summariseWeek("2026-08-31", [
      mealOn("2026-08-31", 2000, 100),
      {
        localDate: "2026-09-01",
        entryType: "water" as const,
        state: "confirmed" as const,
        waterMl: 500,
      },
    ]);
    expect(summary.averageCalories).toEqual({ value: 2000, days: 1 });
    expect(summary.daysLogged).toBe(2);
  });

  it("reports nothing logged as null, never as zero", () => {
    const summary = summariseWeek("2026-08-31", []);
    expect(summary.averageCalories).toBeNull();
    expect(summary.averageProteinGrams).toBeNull();
    expect(summary.averageSteps).toBeNull();
    expect(summary.averageWaterMl).toBeNull();
    expect(summary.daysLogged).toBe(0);
    expect(summary.meals).toBe(0);
  });

  it("treats steps as a daily total, then averages those", () => {
    const summary = summariseWeek("2026-08-31", [
      stepsOn("2026-08-31", 8000),
      stepsOn("2026-08-31", 12000),
      stepsOn("2026-09-01", 6000),
    ]);
    expect(summary.averageSteps).toEqual({ value: 9000, days: 2 });
  });

  it("counts a corrected meal once, exactly as the day does", () => {
    const summary = summariseWeek("2026-08-31", [
      { ...mealOn("2026-09-01", 700, 30), state: "corrected" as const },
      mealOn("2026-09-01", 800, 45),
    ]);
    expect(summary.averageCalories).toEqual({ value: 800, days: 1 });
    expect(summary.meals).toBe(1);
  });

  it("leaves an unconfirmed guess out of the week", () => {
    const summary = summariseWeek("2026-08-31", [
      {
        ...mealOn("2026-09-01", 900, 50),
        state: "pendingClarification" as const,
      },
    ]);
    expect(summary.averageCalories).toBeNull();
    expect(summary.daysLogged).toBe(0);
  });

  it("ignores entries from a neighbouring week", () => {
    const summary = summariseWeek("2026-08-31", [
      mealOn("2026-08-30", 3000, 200),
      mealOn("2026-09-07", 3000, 200),
      mealOn("2026-09-02", 1000, 50),
    ]);
    expect(summary.averageCalories).toEqual({ value: 1000, days: 1 });
  });

  it("counts workouts as sessions and total minutes", () => {
    const workout = (localDate: string, workoutMinutes: number) => ({
      localDate,
      entryType: "workout" as const,
      state: "confirmed" as const,
      workoutMinutes,
    });
    const summary = summariseWeek("2026-08-31", [
      workout("2026-08-31", 45),
      workout("2026-08-31", 20),
      workout("2026-09-03", 60),
    ]);
    expect(summary.workouts).toBe(2);
    expect(summary.workoutMinutes).toBe(125);
  });
});


describe("Backing off when someone goes quiet", () => {
  const now = Date.UTC(2026, 8, 2, 9, 0);
  const base = {
    quietHoursStart: "22:00",
    quietHoursEnd: "07:00",
    maxPerDay: 3,
    pausedUntil: undefined,
    sentLocalDate: "2026-09-02",
    sentCount: 0,
  };
  const decide = (policy: Record<string, unknown>) =>
    decideReminderDelivery(
      { ...base, ...policy } as never,
      "09:00",
      "2026-09-02",
      now,
    );

  it("keeps nudging while the count is below the threshold", () => {
    for (let sent = 0; sent < NUDGES_BEFORE_BREAK_OFFER; sent += 1) {
      const decision = decide({ unansweredNudges: sent });
      expect(decision.allowed).toBe(true);
      expect(decision.offerBreak).toBeUndefined();
    }
  });

  it("offers the break instead of the nudge once they have all gone unanswered", () => {
    const decision = decide({ unansweredNudges: NUDGES_BEFORE_BREAK_OFFER });
    expect(decision).toEqual({ allowed: true, reason: "ok", offerBreak: true });
  });

  it("goes silent once the break has been offered and not answered", () => {
    const decision = decide({
      unansweredNudges: NUDGES_BEFORE_BREAK_OFFER,
      awaitingBreakReply: true,
    });
    expect(decision.allowed).toBe(false);
    expect(decision.reason).toBe("awaitingReply");
  });

  it("never lets the break offer itself break quiet hours", () => {
    const decision = decideReminderDelivery(
      { ...base, unansweredNudges: 9 } as never,
      "03:00",
      "2026-09-02",
      now,
    );
    expect(decision.allowed).toBe(false);
    expect(decision.reason).toBe("quietHours");
  });

  it("never lets the break offer past the daily cap", () => {
    const decision = decide({ unansweredNudges: 9, sentCount: 3 });
    expect(decision.allowed).toBe(false);
    expect(decision.reason).toBe("dailyCap");
  });

  it("reports an explicit pause as paused, not as awaiting a reply", () => {
    const decision = decide({
      unansweredNudges: 9,
      awaitingBreakReply: true,
      pausedUntil: now + 60_000,
    });
    expect(decision.reason).toBe("paused");
  });

  it("treats a row with no counters as an engaged user", () => {
    expect(decide({}).offerBreak).toBeUndefined();
    expect(decide({ unansweredNudges: null, awaitingBreakReply: null })).toEqual({
      allowed: true,
      reason: "ok",
    });
  });

  it("still sends to a user who has no stored settings at all", () => {
    expect(decideReminderDelivery(null, "09:00", "2026-09-02", now)).toEqual({
      allowed: true,
      reason: "ok",
    });
  });
});
