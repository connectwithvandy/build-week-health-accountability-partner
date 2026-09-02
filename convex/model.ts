import { v } from "convex/values";

export const onboardingFields = [
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
] as const;

export const goals = [
  "maintainWeight",
  "loseWeight",
  "gainWeight",
  "improveConsistency",
] as const;

export const inputSources = ["text", "voice", "photo", "pdf", "system"] as const;

export const dailyEntryTypes = [
  "meal",
  "water",
  "steps",
  "workout",
  "commitment",
] as const;

export const dailyEntryStates = [
  "pendingClarification",
  "confirmed",
  "corrected",
] as const;

export const onboardingFieldValidator = v.union(
  v.literal("consent"),
  v.literal("name"),
  v.literal("age"),
  v.literal("height"),
  v.literal("weight"),
  v.literal("timeZone"),
  v.literal("goal"),
  v.literal("nutrition"),
  v.literal("steps"),
  v.literal("water"),
  v.literal("workouts"),
  v.literal("customCommitments"),
  v.literal("reminders"),
  v.literal("dailyReview"),
  v.literal("quietHours"),
  v.literal("morningCommitment"),
  v.literal("confirmation"),
  v.literal("complete"),
);

export const goalValidator = v.union(
  v.literal("maintainWeight"),
  v.literal("loseWeight"),
  v.literal("gainWeight"),
  v.literal("improveConsistency"),
);

export const inputSourceValidator = v.union(
  v.literal("text"),
  v.literal("voice"),
  v.literal("photo"),
  v.literal("pdf"),
  v.literal("system"),
);

export const dailyEntryTypeValidator = v.union(
  v.literal("meal"),
  v.literal("water"),
  v.literal("steps"),
  v.literal("workout"),
  v.literal("commitment"),
);

export const dailyEntryStateValidator = v.union(
  v.literal("pendingClarification"),
  v.literal("confirmed"),
  v.literal("corrected"),
);

export function isLocalDateKey(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(Date.UTC(year, month - 1, day));

  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
  );
}

// ---------------------------------------------------------------------------
// Structured logging helpers.
//
// The mutations in ted.ts stay thin on purpose: everything that makes a
// decision lives here as a pure function, so it can be tested directly.

export type DailyEntryType = (typeof dailyEntryTypes)[number];
export type InputSource = (typeof inputSources)[number];
export type Goal = (typeof goals)[number];
export type OnboardingField = (typeof onboardingFields)[number];

export type MealDetail = {
  items: string[];
  calories: number;
  proteinGrams: number;
  carbohydrateGrams: number;
  fatGrams: number;
  fiberGrams: number;
};

export type DailyEntryInput = {
  localDate: string;
  entryType: DailyEntryType;
  externalMessageId?: string;
  occurredAt: number;
  meal?: MealDetail;
  waterMl?: number;
  steps?: number;
  workoutMinutes?: number;
  commitmentId?: string;
};

export function isLocalTimeKey(value: string): boolean {
  const match = /^(\d{2}):(\d{2})$/.exec(value);
  if (!match) return false;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  return hours >= 0 && hours <= 23 && minutes >= 0 && minutes <= 59;
}

/** Lowercase, trim, drop empties, and sort, so "dal, rice" == "Rice,  dal". */
export function normaliseMealItems(items: readonly string[]): string[] {
  return [...items]
    .map((item) => item.trim().toLowerCase().replace(/\s+/g, " "))
    .filter((item) => item.length > 0)
    .sort();
}

/**
 * The value written to dailyEntries.dedupeKey.
 *
 * WhatsApp re-delivers messages, and Hermes retries a turn that timed out, so
 * the same meal can arrive twice with the same message id. That is the case
 * this key exists to collapse. Two genuinely separate glasses of water an hour
 * apart are NOT duplicates, so without a message id the key stays unique and
 * the write goes through.
 */
export function buildDedupeKey(entry: DailyEntryInput): string {
  const messageId = entry.externalMessageId?.trim();
  if (messageId) {
    return `msg:${messageId}`;
  }

  const parts: string[] = [entry.localDate, entry.entryType];
  if (entry.meal) {
    parts.push(normaliseMealItems(entry.meal.items).join("|"));
    parts.push(String(entry.meal.calories));
  }
  if (typeof entry.waterMl === "number") parts.push(`water:${entry.waterMl}`);
  if (typeof entry.steps === "number") parts.push(`steps:${entry.steps}`);
  if (typeof entry.workoutMinutes === "number") {
    parts.push(`workout:${entry.workoutMinutes}`);
  }
  if (entry.commitmentId) parts.push(`commitment:${entry.commitmentId}`);
  parts.push(`at:${entry.occurredAt}`);
  return `auto:${parts.join(":")}`;
}

export type DaySummary = {
  localDate: string;
  meals: number;
  calories: number;
  proteinGrams: number;
  waterMl: number;
  steps: number;
  workoutMinutes: number;
  commitmentsDone: number;
};

type SummarisableEntry = {
  localDate: string;
  entryType: DailyEntryType;
  state: (typeof dailyEntryStates)[number];
  meal?: MealDetail | null;
  waterMl?: number | null;
  steps?: number | null;
  workoutMinutes?: number | null;
  commitmentId?: string | null;
};

/**
 * Totals for "how am I doing today?".
 *
 * Corrected entries are excluded: when a user says "that was paneer not
 * chicken" the original row stays for the audit trail with state "corrected",
 * and the replacement carries the real numbers. Counting both double-counts
 * the meal. Entries still waiting on a clarification are excluded too — an
 * unconfirmed guess must never appear in a total Ted reads back.
 */
export function summariseDay(
  localDate: string,
  entries: readonly SummarisableEntry[],
): DaySummary {
  const summary: DaySummary = {
    localDate,
    meals: 0,
    calories: 0,
    proteinGrams: 0,
    waterMl: 0,
    steps: 0,
    workoutMinutes: 0,
    commitmentsDone: 0,
  };

  for (const entry of entries) {
    if (entry.localDate !== localDate) continue;
    if (entry.state !== "confirmed") continue;

    if (entry.entryType === "meal" && entry.meal) {
      summary.meals += 1;
      summary.calories += entry.meal.calories;
      summary.proteinGrams += entry.meal.proteinGrams;
    }
    if (entry.entryType === "water" && typeof entry.waterMl === "number") {
      summary.waterMl += entry.waterMl;
    }
    // Steps are a running total for the day, not an increment. Two "12,000
    // steps" messages mean twelve thousand steps, not twenty-four.
    if (entry.entryType === "steps" && typeof entry.steps === "number") {
      summary.steps = Math.max(summary.steps, entry.steps);
    }
    if (
      entry.entryType === "workout" &&
      typeof entry.workoutMinutes === "number"
    ) {
      summary.workoutMinutes += entry.workoutMinutes;
    }
    if (entry.entryType === "commitment" && entry.commitmentId) {
      summary.commitmentsDone += 1;
    }
  }

  return summary;
}
