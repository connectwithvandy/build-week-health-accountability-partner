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
