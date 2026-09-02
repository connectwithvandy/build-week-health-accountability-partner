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

// ---------------------------------------------------------------------------
// Milestone 10 — near-duplicates and dates that are not today.
//
// buildDedupeKey above collapses an exact re-delivery: the same message id, or
// byte-identical content at the same instant. It cannot catch the case a
// tester actually hits — telling Ted about the same lunch twice, in different
// words, twenty minutes apart. That is not a re-delivery and it is not
// obviously a second meal either, so the only honest answer is to ask.

/** How long after a meal another meal is more likely a repeat than a second one. */
export const SAME_MEAL_WINDOW_MINUTES = 120;

/** Same for a workout — two gym sessions inside two hours is worth querying. */
export const SAME_WORKOUT_WINDOW_MINUTES = 120;

export type ClashCandidate = {
  entryType: DailyEntryType;
  state: (typeof dailyEntryStates)[number];
  occurredAt: number;
  dedupeKey: string;
  meal?: MealDetail | null;
  commitmentId?: string | null;
};

/**
 * The already-logged entry a new one probably repeats, or null.
 *
 * Deliberately narrow. Water, steps and anything the user is plainly
 * accumulating are never flagged: a second glass of water is a second glass of
 * water, and `summariseDay` already treats steps as a running total rather
 * than an increment. Flagging those would train the user to ignore the
 * question, which costs more than the duplicate row it saves.
 *
 * Only `confirmed` entries can clash. A `corrected` row has already been
 * superseded, and a `pendingClarification` row is itself an open question.
 */
export function findClashingEntry(
  existing: readonly ClashCandidate[],
  candidate: Pick<ClashCandidate, "entryType" | "occurredAt" | "commitmentId">,
): ClashCandidate | null {
  const confirmed = existing.filter((entry) => entry.state === "confirmed");

  if (candidate.entryType === "commitment") {
    // A commitment is a named thing done once a day. The same one twice is a
    // repeat regardless of how many hours apart, so there is no window here.
    if (!candidate.commitmentId) return null;
    return (
      confirmed.find(
        (entry) =>
          entry.entryType === "commitment" &&
          entry.commitmentId === candidate.commitmentId,
      ) ?? null
    );
  }

  const windowMinutes =
    candidate.entryType === "meal"
      ? SAME_MEAL_WINDOW_MINUTES
      : candidate.entryType === "workout"
        ? SAME_WORKOUT_WINDOW_MINUTES
        : 0;
  if (windowMinutes === 0) return null;

  const windowMs = windowMinutes * 60 * 1000;
  const inWindow = confirmed.filter(
    (entry) =>
      entry.entryType === candidate.entryType &&
      Math.abs(entry.occurredAt - candidate.occurredAt) <= windowMs,
  );
  if (inWindow.length === 0) return null;

  // The nearest in time is the one worth naming back to the user.
  return inWindow.reduce((nearest, entry) =>
    Math.abs(entry.occurredAt - candidate.occurredAt) <
    Math.abs(nearest.occurredAt - candidate.occurredAt)
      ? entry
      : nearest,
  );
}

/**
 * Whether a log needs the date said out loud before it is written.
 *
 * "I had dal yesterday" is easy to mishear, and a meal written to the wrong day
 * quietly corrupts two daily reviews. Anything that is not the user's today
 * has to be confirmed once, explicitly.
 */
export function needsDateConfirmation(
  localDate: string,
  today: string,
  confirmed: boolean,
): boolean {
  if (confirmed) return false;
  if (!isLocalDateKey(localDate) || !isLocalDateKey(today)) return false;
  return localDate !== today;
}

// ---------------------------------------------------------------------------
// Milestone 12 — quiet hours, pause/resume, and the per-day reminder cap.
//
// These were prompt instructions with nothing behind them. Worse, reminders
// are delivered by Hermes cron jobs, which run with platform "cron" — so the
// WhatsApp safety gates never saw them at all and no instruction was being
// checked by anything. The decision is made here, as one pure function, so the
// answer is the same wherever it is asked from.

export type ReminderPolicy = {
  quietHoursStart: string;
  quietHoursEnd: string;
  maxPerDay: number;
  pausedUntil?: number | null;
  sentLocalDate?: string | null;
  sentCount?: number | null;
};

export type ReminderDecision = {
  allowed: boolean;
  reason: "ok" | "quietHours" | "paused" | "dailyCap" | "noPolicy";
};

/**
 * Whether HH:MM falls inside the quiet window.
 *
 * The window normally wraps midnight (22:00 → 07:00), which is exactly the
 * case a naive start <= now < end comparison gets wrong, so it is handled
 * explicitly. Start equal to end means no quiet hours at all rather than a
 * 24-hour blackout — the safer reading of an unset pair.
 */
export function isWithinQuietHours(
  nowLocalTime: string,
  start: string,
  end: string,
): boolean {
  if (!isLocalTimeKey(nowLocalTime) || !isLocalTimeKey(start) || !isLocalTimeKey(end)) {
    return false;
  }
  if (start === end) return false;
  if (start < end) return nowLocalTime >= start && nowLocalTime < end;
  // Wraps midnight: late evening OR early morning.
  return nowLocalTime >= start || nowLocalTime < end;
}

/** Whether reminders are paused at this instant. */
export function isPaused(now: number, pausedUntil?: number | null): boolean {
  return typeof pausedUntil === "number" && pausedUntil > now;
}

/**
 * May this reminder go out right now?
 *
 * Order matters for the answer the user gets back: an explicit pause is a
 * thing they chose and should be reported as such, ahead of quiet hours, which
 * is a standing setting, ahead of the cap, which is a limit they may not know
 * about.
 */
export function decideReminderDelivery(
  policy: ReminderPolicy | null,
  nowLocalTime: string,
  today: string,
  now: number,
): ReminderDecision {
  // No row means the user never set anything up. Nothing scheduled, nothing
  // to send — refuse rather than invent a default that pings someone at 3am.
  if (!policy) return { allowed: false, reason: "noPolicy" };

  if (isPaused(now, policy.pausedUntil)) {
    return { allowed: false, reason: "paused" };
  }
  if (isWithinQuietHours(nowLocalTime, policy.quietHoursStart, policy.quietHoursEnd)) {
    return { allowed: false, reason: "quietHours" };
  }
  const sentToday = policy.sentLocalDate === today ? (policy.sentCount ?? 0) : 0;
  if (sentToday >= policy.maxPerDay) {
    return { allowed: false, reason: "dailyCap" };
  }
  return { allowed: true, reason: "ok" };
}

// ---------------------------------------------------------------------------
// What the deployed backend claims to support.
//
// The gate in hermes/ted_safety_gates talks to this backend over HTTP, and the
// two are deployed separately — the gateway reloads from the repo the moment
// the file changes, while Convex only changes when someone runs a deploy. That
// gap is not theoretical: on 2 Sep the gate gained three new logDailyEntry
// arguments that production rejected with ArgumentValidationError, which would
// have broken every meal log the moment the gateway restarted.
//
// Listed here so `npm run convex:check` can ask a deployment what it is rather
// than assume.
export const TED_HTTP_ACTIONS = [
  "get",
  "save",
  "delete",
  "log",
  "day",
  "target",
  "reminder",
  "onboarding",
  "report",
  "reports",
  "reminderGate",
] as const;
