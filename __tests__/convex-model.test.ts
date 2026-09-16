import { describe, expect, it } from "vitest";

import {
  firstHealthValueProblem,
  pauseProblem,
  nextCompletedAt,
  healthValueProblem,
  HEALTH_RANGES,
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
  calorieFloorFor,
  countsTowardDay,
  isSetUp,
  restingEnergy,
  setupRequirements,
  setupStateFor,
  type SetupSnapshot,
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

  it("sums carbs, fat and fibre for the day, not only calories and protein", () => {
    // Stored per meal from the start and thrown away at the day boundary, so
    // the Daily Overview could say what one plate held and then go quiet on
    // what the day held. Nothing about storage changed; the totals simply
    // stopped being discarded.
    const plate = (
      calories: number,
      proteinGrams: number,
      carbohydrateGrams: number,
      fatGrams: number,
      fiberGrams: number,
    ) => ({
      items: ["something"],
      calories,
      proteinGrams,
      carbohydrateGrams,
      fatGrams,
      fiberGrams,
    });
    const summary = summariseDay("2026-09-02", [
      entry({ meal: plate(380, 19, 40, 12, 6) }),
      entry({ meal: plate(450, 22, 55, 14, 8) }),
    ]);
    expect(summary.calories).toBe(830);
    expect(summary.proteinGrams).toBe(41);
    expect(summary.carbohydrateGrams).toBe(95);
    expect(summary.fatGrams).toBe(26);
    expect(summary.fiberGrams).toBe(14);
  });

  it("leaves a corrected meal's macros out of the day as well", () => {
    const summary = summariseDay("2026-09-02", [
      entry({ state: "corrected", meal: meal(520, 31) }),
      entry({ meal: meal(380, 19) }),
    ]);
    expect(summary.carbohydrateGrams).toBe(0);
    expect(summary.fatGrams).toBe(0);
    expect(summary.fiberGrams).toBe(0);
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

  it("lets the evening check-in through inside quiet hours", () => {
    // Shruthi, 7 Sep 2026. Ted's setup question offers "something like 9pm or
    // 10:30pm", she picked 10:30pm and was told "that's when your day gets
    // added up". The job ran at 22:30:20 and was dropped with reason
    // quietHours, because quiet hours start at 22:00. Nine of nineteen people
    // with a check-in time were inside their own quiet window.
    expect(
      decideReminderDelivery(base, "22:30", "2026-09-02", now, "dailyReview"),
    ).toEqual({ allowed: true, reason: "ok" });
    for (const clock of ["22:00", "23:00", "02:00", "06:30"]) {
      expect(
        decideReminderDelivery(base, clock, "2026-09-02", now, "dailyReview")
          .allowed,
      ).toBe(true);
    }
  });

  it("still silences an ordinary nudge at the same hour", () => {
    // The exemption is for the time the user named, not for the whole night.
    for (const clock of ["22:00", "22:30", "23:00", "02:00", "06:30"]) {
      expect(
        decideReminderDelivery(base, clock, "2026-09-02", now, "nudge").reason,
      ).toBe("quietHours");
      // Absent a kind, a caller gets the stricter of the two answers.
      expect(decideReminderDelivery(base, clock, "2026-09-02", now).reason).toBe(
        "quietHours",
      );
    }
  });

  it("exempts the check-in from quiet hours with no stored settings too", () => {
    expect(
      decideReminderDelivery(null, "23:30", "2026-09-02", now, "dailyReview"),
    ).toEqual({ allowed: true, reason: "ok" });
    expect(
      decideReminderDelivery(null, "23:30", "2026-09-02", now, "nudge").reason,
    ).toBe("quietHours");
  });

  it("keeps pause and the daily cap over the check-in", () => {
    // The hour of the day is not what pause or the cap are answering, so the
    // exemption must not reach either of them.
    const paused = { ...base, pausedUntil: now + 60_000 };
    expect(
      decideReminderDelivery(paused, "22:30", "2026-09-02", now, "dailyReview")
        .reason,
    ).toBe("paused");
    const capped = { ...base, sentCount: 3 };
    expect(
      decideReminderDelivery(capped, "22:30", "2026-09-02", now, "dailyReview")
        .reason,
    ).toBe("dailyCap");
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

  it("still sends the evening check-in to somebody who went quiet", () => {
    // SCOPING §23 stops *nudges* after four unanswered. The evening review is
    // §24 and is something the user asked for at an hour they named, which is
    // the same argument that already exempts it from quiet hours. Eleven of
    // the twenty-four people with reminder settings were in this state on
    // 16 Sep and receiving nothing at all.
    const decision = decideReminderDelivery(
      { ...base, unansweredNudges: 9, awaitingBreakReply: true } as never,
      "21:00",
      "2026-09-02",
      now,
      "dailyReview",
    );
    expect(decision.allowed).toBe(true);
    expect(decision.reason).toBe("ok");
  });

  it("does not ask a second time about the break it already offered", () => {
    // Without this the exemption above would replace somebody's evening
    // check-in with another copy of a question they have already ignored.
    const decision = decideReminderDelivery(
      { ...base, unansweredNudges: 9, awaitingBreakReply: true } as never,
      "21:00",
      "2026-09-02",
      now,
      "dailyReview",
    );
    // Asserted together, because `offerBreak` being absent on a decision that
    // was refused anyway proves nothing: this has to be a review that is
    // actually going out, carrying no second break question.
    expect(decision).toEqual({ allowed: true, reason: "ok" });
  });

  it("still silences the evening check-in for somebody who actually paused", () => {
    // Going quiet is not the same as asking to be left alone. An explicit
    // pause is a thing they chose and it outranks everything.
    const decision = decideReminderDelivery(
      { ...base, awaitingBreakReply: true, pausedUntil: now + 60_000 } as never,
      "21:00",
      "2026-09-02",
      now,
      "dailyReview",
    );
    expect(decision.allowed).toBe(false);
    expect(decision.reason).toBe("paused");
  });

  it("still holds the nudges back while the break question is open", () => {
    const decision = decideReminderDelivery(
      { ...base, unansweredNudges: 9, awaitingBreakReply: true } as never,
      "09:00",
      "2026-09-02",
      now,
      "nudge",
    );
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

// ---------------------------------------------------------------------------
// Setup readiness, derived rather than declared.
//
// Every case here is a real row from the 6 Sep production audit. The two that
// matter most are the ones that used to go wrong in opposite directions: a
// user with everything on file who was still filed as onboarding because the
// flow that collected it never sent the closing write, and a user filed active
// with no age, height, weight or target because the model said so.
describe("setup readiness", () => {
  const complete: SetupSnapshot = {
    privacyNoticeSentAt: 1_788_000_000_000,
    name: "Ankit",
    age: 29,
    heightCm: 175,
    weightKg: 78,
    goal: "loseWeight",
    calories: 1900,
    dailyReviewTime: "21:00",
  };

  it("lists the requirements in the order they should be asked", () => {
    expect(setupRequirements).toEqual([
      "privacyNotice",
      "name",
      "age",
      "height",
      "weight",
      "goal",
      "calorieTarget",
      "checkInTime",
    ]);
  });

  it("calls a complete record ready", () => {
    expect(setupStateFor(complete)).toEqual({ missing: [], blocked: null, ready: true });
    expect(isSetUp(complete)).toBe(true);
  });

  it("is ready for a record whose onboarding row still says mid-flow", () => {
    // Ankit on 6 Sep: gate setup done, two cron jobs firing, Convex parked at
    // "confirmation". Nothing about the stored data justified the label.
    expect(isSetUp(complete)).toBe(true);
  });

  it("is not ready for a record the model called complete", () => {
    // Pradosh on 6 Sep: status "active", nothing to compute a calorie number
    // from, and three days of coaching already delivered.
    const pradosh: SetupSnapshot = {
      privacyNoticeSentAt: 1_788_000_000_000,
      name: "Pradosh",
      goal: "loseWeight",
      dailyReviewTime: "22:00",
    };
    const state = setupStateFor(pradosh);
    expect(state.ready).toBe(false);
    expect(state.missing).toEqual(["age", "height", "weight", "calorieTarget"]);
  });

  it("names the next question first", () => {
    const state = setupStateFor({ ...complete, privacyNoticeSentAt: null, age: null });
    expect(state.missing[0]).toBe("privacyNotice");
  });

  it("treats absent, null, empty and zero alike", () => {
    for (const empty of [undefined, null, 0]) {
      expect(setupStateFor({ ...complete, calories: empty }).missing).toContain(
        "calorieTarget",
      );
    }
    for (const empty of [undefined, null, "", "   "]) {
      expect(setupStateFor({ ...complete, name: empty }).missing).toContain("name");
    }
  });

  it("rejects a check-in time that is not a real clock time", () => {
    for (const bad of ["", "9pm", "25:00", "21:60", "evening"]) {
      expect(setupStateFor({ ...complete, dailyReviewTime: bad }).missing).toContain(
        "checkInTime",
      );
    }
    expect(setupStateFor({ ...complete, dailyReviewTime: "07:30" }).ready).toBe(true);
  });

  it("blocks a minor rather than treating the age as unanswered", () => {
    const state = setupStateFor({ ...complete, age: 15 });
    // The age is on file, so it is not missing. What stops them is the block,
    // and re-asking would be the one response worse than doing nothing.
    expect(state.missing).not.toContain("age");
    expect(state.blocked).toBe("minor");
    expect(state.ready).toBe(false);
  });

  it("still reports the other gaps for a blocked record", () => {
    const state = setupStateFor({ age: 15 });
    expect(state.blocked).toBe("minor");
    expect(state.missing).toContain("name");
  });

  it("requires the privacy notice, which was sent but never recorded", () => {
    // Convex held this for 0 of 32 users on 6 Sep while the gate's own record
    // covered 31. Sent and written down nowhere the rest of the system can
    // read is, for every practical purpose, not sent.
    expect(setupStateFor({ ...complete, privacyNoticeSentAt: null }).missing).toEqual([
      "privacyNotice",
    ]);
  });

  it("does not depend on the onboarding flow that collected the data", () => {
    // The five-question flow, the six-question flow and open conversation all
    // produce the same eight facts or they do not. Nothing here can tell which
    // one ran, which is the point.
    expect(isSetUp(complete)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// The floor under every calorie target.
//
// Pinned against the gate's Python `_resting_energy`, which computes the same
// formula in another language on another machine. Both real cases below were
// numbers the model wrote to Convex in open conversation, where the gate's own
// floor was not listening.
describe("calorie floor", () => {
  const gourav = { age: 33, heightCm: 178, weightKg: 80, sex: "male" };
  const ud = { age: 28, heightCm: 177.8, weightKg: 98, sex: "male" };

  it("matches the gate's resting energy for the real profiles", () => {
    expect(restingEnergy(gourav)).toBe(1752);
    expect(restingEnergy(ud)).toBe(1956);
  });

  it("never rounds above the gate, so a gate-computed target still saves", () => {
    // Gourav's raw figure is exactly 1752.5. Python's round() is banker's
    // rounding and gives 1752; Math.round is half-up and gives 1753. A floor of
    // 1753 would refuse the gate's own 1752, so this rounds down instead.
    expect(restingEnergy(gourav)).toBeLessThanOrEqual(1752);
  });

  it("would have caught both targets the model actually wrote", () => {
    // Gourav, 5 Sep 2026: "*1,550* it is" against a 1,752 floor.
    expect(1550).toBeLessThan(calorieFloorFor(gourav).known ? restingEnergy(gourav) : 0);
    // UD, 7 Sep 2026: 1,850 against a 1,956 floor.
    expect(1850).toBeLessThan(restingEnergy(ud));
  });

  it("uses the lower female term when sex is unknown, never the higher", () => {
    const unknown = calorieFloorFor({ age: 28, heightCm: 177.8, weightKg: 98 });
    const male = calorieFloorFor({ ...ud });
    expect(unknown.known && male.known && unknown.floor < male.floor).toBe(true);
    // 166 is the gap between the two Mifflin-St Jeor sex terms, +5 and -161.
    expect(unknown.known && male.known && male.floor - unknown.floor).toBe(166);
  });

  it("refuses to guess a floor from an incomplete profile", () => {
    // Blocking a target on a floor built from missing data would stop real
    // users for no gain. 20 of 32 users had no calorie target at all on 6 Sep,
    // and most of them are missing a height or a weight too.
    expect(calorieFloorFor({ age: 28, heightCm: 177.8 })).toEqual({ known: false });
    expect(calorieFloorFor({ age: 0, heightCm: 177.8, weightKg: 98 })).toEqual({
      known: false,
    });
    expect(calorieFloorFor({})).toEqual({ known: false });
  });

  it("allows a target at the floor exactly, and anything above it", () => {
    const floor = restingEnergy(ud);
    expect(floor).toBe(1956);
    // The mutation refuses `calories < floor`, so the floor itself passes.
    expect(floor < floor).toBe(false);
    expect(2000 < floor).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// A correction has to hold in the sentence, not only in the totals.
describe("what counts toward the day", () => {
  const entry = (state: string) => ({ state });

  it("counts only confirmed entries", () => {
    expect(countsTowardDay(entry("confirmed"))).toBe(true);
    expect(countsTowardDay(entry("corrected"))).toBe(false);
    expect(countsTowardDay(entry("pendingClarification"))).toBe(false);
  });

  it("uses the same rule the totals use", () => {
    // The owner's 7 Sep morning: a masala omelette read from a photo, corrected
    // to besan chilla, then the portion corrected again. Only the last one is
    // real, and the two superseded rows must be invisible to anything that
    // reads the day back in words.
    const meal = (calories: number, proteinGrams: number) => ({
      items: ["something"], calories, proteinGrams,
      carbohydrateGrams: 0, fatGrams: 0, fiberGrams: 0,
    });
    const day = [
      { localDate: "2026-09-07", entryType: "meal" as const,
        state: "corrected" as const, meal: meal(240, 16) },
      { localDate: "2026-09-07", entryType: "meal" as const,
        state: "corrected" as const, meal: meal(240, 14) },
      { localDate: "2026-09-07", entryType: "meal" as const,
        state: "confirmed" as const, meal: meal(456, 25) },
      { localDate: "2026-09-07", entryType: "meal" as const,
        state: "confirmed" as const, meal: meal(356, 16) },
    ];
    const summary = summariseDay("2026-09-07", day);
    expect(summary.meals).toBe(2);
    expect(summary.calories).toBe(812);
    // The same rule, applied to the list rather than the arithmetic.
    expect(day.filter(countsTowardDay)).toHaveLength(summary.meals);
  });
});

describe("what a stored health number is allowed to be", () => {
  it("refuses the measurement that started this: a 4cm height", () => {
    // Pallavi's height sat on her profile as 4cm for nine days. The gate does
    // bound this, but only where a fact is promoted to a column, and the
    // mutation is reachable without passing through that.
    expect(healthValueProblem("heightCm", 4)).toMatch(/outside the range/);
    expect(healthValueProblem("heightCm", 163)).toBeNull();
  });

  it("stores an age below 18 rather than refusing it", () => {
    // The single most important case here. The beta is adults only, but that
    // is enforced by setupStateFor returning blocked: "minor", which it can
    // only do if the age was written down. Refusing 17 would mean a minor's
    // age never lands, nothing could ever block them, and they would read as
    // merely incomplete. Refusing the write would be the safety regression,
    // not the safety check.
    expect(healthValueProblem("age", 17)).toBeNull();
    expect(healthValueProblem("age", 13)).toBeNull();
    // What is refused is a number that cannot be anybody's age at all.
    expect(healthValueProblem("age", 0)).toMatch(/outside the range/);
    expect(healthValueProblem("age", 500)).toMatch(/outside the range/);
  });

  it("does not argue with an unusual person", () => {
    // The bounds exist to catch a value that cannot be a person, not to
    // second-guess one. Every number here is somebody's real day.
    expect(healthValueProblem("steps", 42000)).toBeNull();
    expect(healthValueProblem("waterMl", 5000)).toBeNull();
    expect(healthValueProblem("weightKg", 140)).toBeNull();
    expect(healthValueProblem("workoutMinutes", 300)).toBeNull();
    expect(healthValueProblem("calories", 4200)).toBeNull();
  });

  it("refuses negatives everywhere, because no measurement here can be one", () => {
    for (const field of ["steps", "waterMl", "calories", "workoutMinutes", "weightKg"]) {
      expect(healthValueProblem(field, -1)).toMatch(/outside the range|finite/);
    }
  });

  it("refuses a number that is not one", () => {
    expect(healthValueProblem("steps", Number.NaN)).toMatch(/finite/);
    expect(healthValueProblem("calories", Number.POSITIVE_INFINITY)).toMatch(/finite/);
    expect(healthValueProblem("weightKg", "70")).toMatch(/finite/);
  });

  it("lets an absent value through, since not every field is sent every time", () => {
    expect(healthValueProblem("steps", undefined)).toBeNull();
    expect(healthValueProblem("steps", null)).toBeNull();
  });

  it("fails open on a field nobody gave a range", () => {
    // Adding an argument to a mutation without adding it here must not block a
    // write that nobody meant to block.
    expect(healthValueProblem("somethingNew", 99999)).toBeNull();
  });

  it("names the field and the number, because the log is the only record", () => {
    const problem = healthValueProblem("heightCm", 4);
    expect(problem).toContain("heightCm");
    expect(problem).toContain("4");
    expect(problem).toContain("cm");
  });

  it("reports the first problem in the caller's own field order", () => {
    const problem = firstHealthValueProblem({ steps: -5, waterMl: -5 });
    expect(problem).toContain("steps");
  });

  it("says nothing when every field is storable", () => {
    expect(
      firstHealthValueProblem({ steps: 8000, waterMl: 2000, calories: 1800 }),
    ).toBeNull();
  });

  it("covers every number the three mutations can write", () => {
    // A field a mutation writes but this table does not know about passes
    // silently, so the list is worth asserting rather than trusting.
    for (const field of [
      "age", "heightCm", "weightKg",
      "calories", "proteinGrams", "carbohydrateGrams", "fatGrams", "fiberGrams",
      "steps", "waterMl", "workoutMinutes", "workoutsPerWeek",
    ]) {
      expect(HEALTH_RANGES[field], `${field} has no range`).toBeDefined();
    }
  });
});

describe("when onboarding counts as finished", () => {
  const NOW = 1789560000000;

  it("stamps the moment setup first becomes ready", () => {
    expect(nextCompletedAt(undefined, true, NOW)).toBe(NOW);
  });

  it("leaves it unset while anything is still missing", () => {
    expect(nextCompletedAt(undefined, false, NOW)).toBeUndefined();
  });

  it("keeps the original moment once earned", () => {
    // Not re-stamped on every subsequent write, or the column would drift
    // forward and stop meaning "when they finished".
    const earned = NOW - 86_400_000;
    expect(nextCompletedAt(earned, true, NOW)).toBe(earned);
  });

  it("never clears it when a field is later lost", () => {
    // Somebody who finished and then had a field cleared is a user with a gap
    // to close, not somebody who never started. This is why Pradosh and
    // Pritika keep theirs.
    const earned = NOW - 86_400_000;
    expect(nextCompletedAt(earned, false, NOW)).toBe(earned);
  });

  it("only ever moves from unset to set", () => {
    // The property the whole rule reduces to, checked over every combination
    // rather than the four spelled out above.
    for (const current of [undefined, 1, NOW]) {
      for (const ready of [true, false]) {
        const next = nextCompletedAt(current, ready, NOW);
        if (current !== undefined) expect(next).toBe(current);
        else expect(next === undefined || next === NOW).toBe(true);
      }
    }
  });
});

describe("a pause that would silence nothing", () => {
  const now = Date.UTC(2026, 8, 16, 16, 0);
  const day = 24 * 60 * 60 * 1000;

  it("refuses the pause that actually happened", () => {
    // Sarah asked to pause on 16 Sep 2026. Ted said "back on 23rd" and wrote
    // 26 Sep 2025, a year in the past, so isPaused returned false and her
    // 21:00 check-in reached her eight hours later.
    const problem = pauseProblem(Date.UTC(2025, 8, 26), now);
    expect(problem).toMatch(/in the past/);
  });

  it("accepts the pause she was actually promised", () => {
    expect(pauseProblem(now + 7 * day, now)).toBeNull();
  });

  it("leaves un-pausing alone", () => {
    // null is how "resume now" arrives, and it must not be read as a pause in
    // the past and refused.
    expect(pauseProblem(null, now)).toBeNull();
    expect(pauseProblem(undefined, now)).toBeNull();
  });

  it("refuses the same mistake pointed the other way", () => {
    expect(pauseProblem(now + 400 * day, now)).toMatch(/more than 365 days/);
  });

  it("does not argue with a long but real break", () => {
    expect(pauseProblem(now + 60 * day, now)).toBeNull();
  });

  it("refuses something that is not a timestamp", () => {
    expect(pauseProblem("next tuesday", now)).toMatch(/finite timestamp/);
    expect(pauseProblem(Number.NaN, now)).toMatch(/finite timestamp/);
  });
});
