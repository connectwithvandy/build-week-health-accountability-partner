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
  "weeklyReview",
  "quietHours",
  "morningCommitment",
  "confirmation",
  "complete",
] as const;

// Monday first, because the week does. Stored as a name rather than a number
// so a row is readable without a lookup table and cannot be off by one.
export const weekdays = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
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
  v.literal("weeklyReview"),
  v.literal("quietHours"),
  v.literal("morningCommitment"),
  v.literal("confirmation"),
  v.literal("complete"),
);

export const weekdayValidator = v.union(
  v.literal("monday"),
  v.literal("tuesday"),
  v.literal("wednesday"),
  v.literal("thursday"),
  v.literal("friday"),
  v.literal("saturday"),
  v.literal("sunday"),
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
  // Summed from 4 Sep 2026. They were stored per meal from the start and
  // thrown away at the day boundary, so the Daily Overview could say what
  // the plate held and then go quiet on what the day held. Nothing about
  // storage changed here; the totals simply stopped being discarded.
  carbohydrateGrams: number;
  fatGrams: number;
  fiberGrams: number;
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
/**
 * Does this entry count as something the user actually did today?
 *
 * The one rule, exported so the totals and the list of what was eaten cannot
 * drift apart. On 7 Sep the owner corrected "masala omelette" to "besan
 * chilla"; the totals were right, because `summariseDay` skips a corrected
 * row, but `getDaySummary` handed the model every row including that one and
 * Ted read her day back as "masala omelette + besan chilla". The correction
 * held in the database and was undone in the sentence.
 */
export function countsTowardDay(entry: { state: string }): boolean {
  return entry.state === "confirmed";
}

export function summariseDay(
  localDate: string,
  entries: readonly SummarisableEntry[],
): DaySummary {
  const summary: DaySummary = {
    localDate,
    meals: 0,
    calories: 0,
    proteinGrams: 0,
    carbohydrateGrams: 0,
    fatGrams: 0,
    fiberGrams: 0,
    waterMl: 0,
    steps: 0,
    workoutMinutes: 0,
    commitmentsDone: 0,
  };

  for (const entry of entries) {
    if (entry.localDate !== localDate) continue;
    if (!countsTowardDay(entry)) continue;

    if (entry.entryType === "meal" && entry.meal) {
      summary.meals += 1;
      summary.calories += entry.meal.calories;
      summary.proteinGrams += entry.meal.proteinGrams;
      summary.carbohydrateGrams += entry.meal.carbohydrateGrams ?? 0;
      summary.fatGrams += entry.meal.fatGrams ?? 0;
      summary.fiberGrams += entry.meal.fiberGrams ?? 0;
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
// The weekly review.
//
// SOUL.md has always described one — "at the end of the user's week … the main
// change, the week's averages, one honest judgement, and one focus for next
// week" — and SCOPING.md §4 listed "Weekly reports" as parked. Nothing
// scheduled one, so Ted was carrying a promise it could only keep by accident,
// which is the worst of both: a user told they will get a Sunday recap, and
// nothing in the product that would ever notice it never arrived.
//
// The week runs Monday to Sunday, matching the worked example in SOUL.md
// ("WEEKLY, MONDAY 10:45am — Your week · 25 Aug to 31 Aug").

/** Monday-to-Sunday. */
export const WEEK_LENGTH_DAYS = 7;

/**
 * A date key shifted by whole days.
 *
 * Parsed and formatted through UTC on purpose. These are calendar keys, not
 * instants: going through the host's local timezone would let a machine in
 * one zone shift a date belonging to a user in another.
 */
export function addLocalDays(localDate: string, days: number): string {
  if (!isLocalDateKey(localDate)) return localDate;
  const [year, month, day] = localDate.split("-").map(Number);
  const shifted = new Date(Date.UTC(year, month - 1, day + days));
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(
    shifted.getUTCDate(),
  )}`;
}

/** The Monday of the week this date falls in — the week's key. */
export function weekStartFor(localDate: string): string {
  if (!isLocalDateKey(localDate)) return localDate;
  const [year, month, day] = localDate.split("-").map(Number);
  const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  // getUTCDay is 0=Sunday. Monday-based offset: Mon→0 … Sun→6.
  return addLocalDays(localDate, -((weekday + 6) % 7));
}

/** The seven date keys of a week, Monday first. */
export function weekDates(weekStart: string): string[] {
  return Array.from({ length: WEEK_LENGTH_DAYS }, (_, index) =>
    addLocalDays(weekStart, index),
  );
}

/**
 * An average, with the number of days it was actually computed from.
 *
 * `null` means the week holds nothing to average, and that is deliberately not
 * the same value as zero. "Never turn uncertainty into fake data" applies hard
 * here: a week where the user logged three dinners and nothing else is not a
 * week of four zero-calorie days, and a recap that reports 790 kcal/day
 * because it divided by seven is worse than one that says nothing.
 */
export type WeekAverage = { value: number; days: number } | null;

export type WeekSummary = {
  weekStart: string;
  weekEnd: string;
  /** Days with at least one confirmed entry of any kind. */
  daysLogged: number;
  meals: number;
  workouts: number;
  workoutMinutes: number;
  commitmentsDone: number;
  averageCalories: WeekAverage;
  averageProteinGrams: WeekAverage;
  averageSteps: WeekAverage;
  averageWaterMl: WeekAverage;
  days: DaySummary[];
};

function averageOver(total: number, days: number): WeekAverage {
  return days > 0 ? { value: Math.round(total / days), days } : null;
}

/**
 * The week read back from what was actually logged.
 *
 * Each metric is averaged over the days that carry *that* metric, not over the
 * seven days of the week and not over the days that carry anything at all. A
 * day where the user logged only water must not drag the calorie average down
 * — that number would be arithmetically correct and factually a lie.
 *
 * Built entirely from `summariseDay`, so a corrected meal is counted once and
 * an unconfirmed guess is counted never, exactly as it is in the daily review.
 */
export function summariseWeek(
  weekStart: string,
  entries: readonly SummarisableEntry[],
): WeekSummary {
  const days = weekDates(weekStart).map((date) => summariseDay(date, entries));

  let daysLogged = 0;
  let daysWithMeals = 0;
  let daysWithSteps = 0;
  let daysWithWater = 0;
  const totals = { calories: 0, protein: 0, steps: 0, water: 0 };
  const summary: WeekSummary = {
    weekStart,
    weekEnd: addLocalDays(weekStart, WEEK_LENGTH_DAYS - 1),
    daysLogged: 0,
    meals: 0,
    workouts: 0,
    workoutMinutes: 0,
    commitmentsDone: 0,
    averageCalories: null,
    averageProteinGrams: null,
    averageSteps: null,
    averageWaterMl: null,
    days,
  };

  for (const day of days) {
    const touched =
      day.meals > 0 ||
      day.steps > 0 ||
      day.waterMl > 0 ||
      day.workoutMinutes > 0 ||
      day.commitmentsDone > 0;
    if (touched) daysLogged += 1;

    if (day.meals > 0) {
      daysWithMeals += 1;
      totals.calories += day.calories;
      totals.protein += day.proteinGrams;
      summary.meals += day.meals;
    }
    if (day.steps > 0) {
      daysWithSteps += 1;
      totals.steps += day.steps;
    }
    if (day.waterMl > 0) {
      daysWithWater += 1;
      totals.water += day.waterMl;
    }
    if (day.workoutMinutes > 0) {
      summary.workouts += 1;
      summary.workoutMinutes += day.workoutMinutes;
    }
    summary.commitmentsDone += day.commitmentsDone;
  }

  summary.daysLogged = daysLogged;
  summary.averageCalories = averageOver(totals.calories, daysWithMeals);
  summary.averageProteinGrams = averageOver(totals.protein, daysWithMeals);
  summary.averageSteps = averageOver(totals.steps, daysWithSteps);
  summary.averageWaterMl = averageOver(totals.water, daysWithWater);
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
/**
 * The words in a meal's items, as a set, ignoring anything too short to
 * identify a food. "oats", "protein powder", "nuts and seeds" gives oats,
 * protein, powder, nuts, seeds — "and" is dropped for being three letters.
 */
const NOT_A_FOOD = new Set([
  "with", "and", "some", "plus", "extra", "side", "chopped", "topping",
  "fresh", "small", "large", "plain", "whole", "half", "little", "bit",
  "homemade", "leftover", "mixed", "cooked", "boiled", "fried", "grilled",
  "sliced", "diced", "raw", "hot", "cold", "cup", "bowl", "plate", "glass",
]);

function foodWords(meal: MealDetail | null | undefined): Set<string> {
  const words = new Set<string>();
  for (const item of meal?.items ?? []) {
    for (const word of String(item).toLowerCase().split(/[^a-z0-9]+/)) {
      if (word.length >= 4 && !NOT_A_FOOD.has(word)) words.add(word);
    }
  }
  return words;
}

/**
 * Whether two entries name any of the same food.
 *
 * Only meals carry food, so anything else falls back to the time window
 * alone, which is the behaviour a workout has always had. A meal with no
 * readable items also falls back, because an empty set would silently stop
 * the duplicate guard from ever firing.
 */
function sharesFood(
  entry: ClashCandidate,
  candidate: Pick<ClashCandidate, "entryType" | "meal">,
): boolean {
  if (candidate.entryType !== "meal") return true;
  const theirs = foodWords(entry.meal);
  const ours = foodWords(candidate.meal);
  if (theirs.size === 0 || ours.size === 0) return true;

  let shared = 0;
  for (const word of ours) {
    if (theirs.has(word)) shared += 1;
  }
  // A proportion, not a single word. One shared word was the first rule and
  // it was too eager by a mile: on 3 Sep a sprouts salad (moong, sprouts,
  // onion, tomato, cilantro, chili) and a peanut toast (wheat, toast, bell,
  // pepper, tomato, onion, peanuts) were held apart to ask whether they were
  // the same meal, because both contained onion and tomato. Half of Indian
  // food contains onion and tomato. Sharing a garnish is not sharing a meal.
  //
  // Measured against the shorter list so that a long description cannot dilute
  // a real repeat: "rice, dal" against "the rice and dal I just had" is still
  // every word of the shorter one.
  return shared / Math.min(theirs.size, ours.size) >= 0.5;
}

export function findClashingEntry(
  existing: readonly ClashCandidate[],
  candidate: Pick<
    ClashCandidate,
    "entryType" | "occurredAt" | "commitmentId" | "meal"
  >,
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
      Math.abs(entry.occurredAt - candidate.occurredAt) <= windowMs &&
      // Two meals close in time are only a possible repeat when they are
      // plausibly the same food. On 3 Sep a second photo, of completely
      // different food, was held back to ask "is this a second one or the
      // same thing again?" — a question with an obvious answer, asked because
      // the window was the only thing being checked. A re-delivered message
      // still carries identical items, so dedupe, which is what this window
      // exists for, is untouched.
      sharesFood(entry, candidate),
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
  /** Nudges sent since the user last said anything at all. */
  unansweredNudges?: number | null;
  /** The break has been offered and they have not answered it yet. */
  awaitingBreakReply?: boolean | null;
};

export type ReminderDecision = {
  allowed: boolean;
  reason: "ok" | "quietHours" | "paused" | "dailyCap" | "awaitingReply";
  /**
   * Send the break offer instead of the nudge that was due.
   *
   * `allowed` is still true: something goes out, it is just not the reminder.
   */
  offerBreak?: boolean;
};

/**
 * How many unanswered nudges before Ted asks instead of nudging again.
 *
 * The failure this prevents is the one that kills these products: a user drifts
 * off, the reminders keep arriving on schedule, and the thread becomes
 * something to mute. Muting is not reversible in any way Ted can see, so the
 * only chance to save the relationship is before it happens.
 *
 * Four is chosen to be past coincidence and short of nagging. One or two
 * unanswered nudges is an ordinary busy couple of days and asking then would
 * itself be the pestering this is meant to avoid.
 */
export const NUDGES_BEFORE_BREAK_OFFER = 4;

// The same values setReminder writes when it creates a row, so a user who has
// never set anything gets the behaviour they would have got by default rather
// than a different one.
export const DEFAULT_QUIET_HOURS_START = "22:00";
export const DEFAULT_QUIET_HOURS_END = "07:00";

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
 * What kind of scheduled message is asking to go out.
 *
 * "dailyReview" is the evening check-in, at the time the user themselves named
 * when Ted asked "what time works for your evening check-in?". Everything else
 * — water, meals, supplements, movement, the morning ping — is Ted deciding to
 * speak, and only Ted's own decisions are what quiet hours exist to silence.
 */
export type ReminderKind = "dailyReview" | "nudge";

/**
 * May this reminder go out right now?
 *
 * Order matters for the answer the user gets back: an explicit pause is a
 * thing they chose and should be reported as such, ahead of quiet hours, which
 * is a standing setting, ahead of the cap, which is a limit they may not know
 * about.
 *
 * QUIET HOURS DO NOT APPLY TO THE DAILY REVIEW. Ted's own setup question
 * offers "something like 9pm or 10:30pm", and quiet hours default to 22:00, so
 * a person who picks either of the two times Ted suggested can land inside a
 * window Ted then enforces against them. On 7 Sep 2026 Shruthi chose 10:30pm
 * and was told "10:30pm it is ✅ that's when your day gets added up"; the job
 * ran at 22:30:20 and was suppressed with `reason=quietHours` before anything
 * reached her. Nine of nineteen people with a check-in time were in that hole,
 * at 22:00, 22:30 and 23:00, and none of them had ever received the one thing
 * the product promises.
 *
 * The alternative was to move quiet hours to start after the chosen time, and
 * it is worse: it silently edits a setting the user never touched in order to
 * honour one they did. `PRODUCT_BUILD_GUARDRAILS.md` already draws this line —
 * "proactive messages and reactive chat are separate controls" — and a check-in
 * somebody asked for at a named hour is not Ted arriving uninvited.
 *
 * Pause, the daily cap and the break offer still apply. Those are about
 * whether Ted should be talking at all, which the hour of the day does not
 * answer.
 */
export function decideReminderDelivery(
  policy: ReminderPolicy | null,
  nowLocalTime: string,
  today: string,
  now: number,
  kind: ReminderKind = "nudge",
): ReminderDecision {
  // No row means the user has never set reminder preferences — which is not
  // the same as having no reminders. Vandy's five vitamin pings are Hermes
  // cron jobs created directly, with nothing in this table, and refusing on a
  // missing row silently killed every one of them.
  //
  // SCOPING #21: "The number of reminders depends on the user's preferences."
  // There is no system cap to fall back on, so absent a preference there is no
  // cap — inventing one drops reminders the user set up themselves. Quiet
  // hours still apply, from the defaults above, because 3am is 3am whether or
  // not anyone has saved a row.
  if (!policy) {
    return kind !== "dailyReview" &&
      isWithinQuietHours(
        nowLocalTime,
        DEFAULT_QUIET_HOURS_START,
        DEFAULT_QUIET_HOURS_END,
      )
      ? { allowed: false, reason: "quietHours" }
      : { allowed: true, reason: "ok" };
  }

  if (isPaused(now, policy.pausedUntil)) {
    return { allowed: false, reason: "paused" };
  }
  // Asked whether they want a break and heard nothing back. Continuing to
  // nudge would answer the question for them, in the least welcome direction.
  // This holds until they say something, anything: the reset is any inbound
  // message, not a particular reply, because someone who starts logging again
  // has answered more clearly than "no" would have.
  //
  // THE DAILY REVIEW IS EXEMPT, for the same reason it is exempt from quiet
  // hours below. SCOPING.md §23 is written about nudges — "the coach stops
  // nudging", "never sends a fifth unanswered nudge" — and the evening review
  // is §24, a separate thing the user asked for at an hour they chose
  // themselves. Suppressing it here was reading §23 wider than it is written.
  //
  // On 16 Sep 2026 eleven of the twenty-four people with reminder settings were
  // in this state, nine of them quiet for seven to eleven days, and every one
  // had named a check-in time. They were receiving nothing at all. An explicit
  // pause still silences everything, above, because that is a thing they chose;
  // going quiet is not the same as asking to be left alone.
  if (policy.awaitingBreakReply && kind !== "dailyReview") {
    return { allowed: false, reason: "awaitingReply" };
  }
  if (
    kind !== "dailyReview" &&
    isWithinQuietHours(nowLocalTime, policy.quietHoursStart, policy.quietHoursEnd)
  ) {
    return { allowed: false, reason: "quietHours" };
  }
  const sentToday = policy.sentLocalDate === today ? (policy.sentCount ?? 0) : 0;
  if (sentToday >= policy.maxPerDay) {
    return { allowed: false, reason: "dailyCap" };
  }
  // Quiet hours and the cap are checked first on purpose: the break offer is
  // still a message, and it must not be the one thing that gets to arrive at
  // 3am or past the daily limit.
  //
  // `awaitingBreakReply` rules it out entirely: they have already been asked,
  // and asking twice is worse than the nagging the offer exists to prevent.
  // This only became reachable when the daily review above stopped being
  // blocked — without it, somebody's evening check-in would be replaced by a
  // second copy of a question they have already ignored once.
  if (
    !policy.awaitingBreakReply &&
    (policy.unansweredNudges ?? 0) >= NUDGES_BEFORE_BREAK_OFFER
  ) {
    return { allowed: true, reason: "ok", offerBreak: true };
  }
  return { allowed: true, reason: "ok" };
}

// ---------------------------------------------------------------------------
// The floor under every calorie target.
//
// `_loss_target` in the gate has always refused to go below the body's resting
// burn, on the grounds that below what you burn asleep is not a deficit, it is
// under-eating. But that floor only guarded the number the *gate* computed. The
// model can call ted_set_target with any number at all, and that call lands
// here, where nothing checked it. Twice now it has written one that is too low:
//
//   * Gourav, 5 Sep 2026, asked for "1500 to 1600" and was told "*1,550* it
//     is" against a resting burn of 1,667.
//   * UD, 7 Sep 2026, was given 1,850 against a resting burn of 1,956, worked
//     backwards from a half-kilo-a-week pace he had asked about.
//
// Both were agreed in open conversation, after the gate's own target question
// had closed, so no gate was listening. Putting the floor in the mutation
// closes it for every caller and every route, which is the only version of
// this that stays fixed.

/**
 * Mifflin-St Jeor resting energy: what the body burns doing nothing.
 *
 * The same formula as `_resting_energy` in hermes/ted_safety_gates. Duplicated
 * rather than shared because the two run in different languages on different
 * machines; the tests pin them to the same numbers.
 */
export function restingEnergy(profile: {
  age: number;
  heightCm: number;
  weightKg: number;
  sex?: string | null;
}): number {
  // Unknown sex takes the female adjustment, which is 166 lower. That makes the
  // floor the most permissive of the two, so a missing answer can never push
  // somebody's target up on a guess. It only ever refuses what is clearly low.
  const sexAdjustment = profile.sex === "male" ? 5 : -161;
  // Rounded DOWN, not to nearest, and that is deliberate. Python's round() is
  // banker's rounding and JavaScript's Math.round is half-up, so they disagree
  // on an exact .5: Gourav's 1752.5 is 1752 in the gate and 1753 here. One
  // kcal sounds harmless until you notice which way it breaks — a floor above
  // the gate's would reject the gate's own computed target, so the safe number
  // Ted worked out would be refused when it tried to save. Math.floor is
  // always at or below Python's round, so this can never be the stricter of
  // the two.
  return Math.floor(
    10 * profile.weightKg + 6.25 * profile.heightCm - 5 * profile.age + sexAdjustment,
  );
}

export type CalorieFloor =
  | { known: false }
  | { known: true; floor: number; reason: "restingEnergy" };

/**
 * The lowest calorie target this person may be given, when it can be worked
 * out at all.
 *
 * Returns `known: false` rather than a guess when the profile is incomplete.
 * Refusing a target on a floor built from missing data would block real users
 * for no gain, and the setup flow is what fills those fields in.
 */
export function calorieFloorFor(profile: {
  age?: number | null;
  heightCm?: number | null;
  weightKg?: number | null;
  sex?: string | null;
}): CalorieFloor {
  const { age, heightCm, weightKg } = profile;
  if (
    typeof age !== "number" ||
    typeof heightCm !== "number" ||
    typeof weightKg !== "number" ||
    age <= 0 ||
    heightCm <= 0 ||
    weightKg <= 0
  ) {
    return { known: false };
  }
  return {
    known: true,
    floor: restingEnergy({ age, heightCm, weightKg, sex: profile.sex }),
    reason: "restingEnergy",
  };
}

// ---------------------------------------------------------------------------
// Is this person set up?
//
// The bug this replaces: `status` only ever became "active" when the model
// wrote `currentField: "complete"`, so "set up" meant "the model remembered to
// say so". On 6 Sep that was wrong in both directions at once. Seven users had
// a name, age, height, weight, goal, a calorie target and a check-in time on
// file and were still filed as mid-onboarding, because the flow that collected
// them was a gate flow that never sent the closing write. Three others were
// filed active with almost nothing: Pradosh had no age, height, weight or
// target, and Ted had been coaching him for three days anyway.
//
// Onboarding changed shape several times during build week — five counted
// questions, then six, then stretches of open conversation — so which flow a
// person happened to arrive through decided which record they ended up in.
// A flag cannot survive that. A function over the stored data can: it asks the
// same question of every row no matter what collected it, so a flow change
// cannot create another cohort, and a backfill is just this function run again.
//
// PRODUCT_BUILD_GUARDRAILS §5: "completion state ... should be calculated from
// persisted data", not reconstructed by the model.

/**
 * What Ted needs on file before it can do the job it promises.
 *
 * Deliberately short. Every entry is load-bearing for the daily loop: the
 * privacy notice is what makes storing any of the rest of it fair, the
 * profile four are what a calorie number is computed from, `goal` decides
 * which direction that number moves, `calorieTarget` is the number a meal is
 * logged against, and `checkInTime` is the only reason Ted ever speaks first.
 *
 * Everything else in `onboardingFields` — steps, water, workouts, custom
 * commitments, the weekly review, the morning commitment — is a preference.
 * Missing preferences make Ted less tailored. Missing entries here make Ted
 * unable to answer "how am I doing", which is the whole product.
 */
/**
 * What a stored health number is allowed to be.
 *
 * The job here is to catch a value that cannot describe a person, not to argue
 * with an unusual one. A hiker logging 30,000 steps, someone drinking four
 * litres, a 250kg powerlifter: all fine, all stored. What is refused is the
 * value that is not a measurement at all — a negative weight, a height of 4,
 * a calorie count with eight digits.
 *
 * Height and weight deliberately match the bounds already in the gate at
 * `ted_safety_gates/__init__.py` (`_PROFILE_RANGES`). Those bounds existed and
 * still let a height of 4cm sit on a profile for nine days, because they guard
 * one path — facts being promoted to profile columns — and every other way a
 * measurement reaches the row went unchecked. Repeating them here is the point:
 * this is the write itself, which every path has to go through.
 *
 * `age` is the exception and is far wider than the beta admits on purpose. The
 * beta is 18+, but that is enforced by `setupStateFor` returning
 * `blocked: "minor"`, which it can only do if the age was *stored*. Refusing to
 * write 17 would mean a minor's age never lands, so nothing could ever block
 * them and they would read as merely incomplete. The bound here is only
 * "could this be a human being".
 */
export const HEALTH_RANGES: Record<string, { min: number; max: number; unit: string }> = {
  age: { min: 5, max: 120, unit: "years" },
  heightCm: { min: 90, max: 250, unit: "cm" },
  weightKg: { min: 20, max: 400, unit: "kg" },
  calories: { min: 0, max: 20000, unit: "kcal" },
  proteinGrams: { min: 0, max: 2000, unit: "g" },
  carbohydrateGrams: { min: 0, max: 2000, unit: "g" },
  fatGrams: { min: 0, max: 2000, unit: "g" },
  fiberGrams: { min: 0, max: 2000, unit: "g" },
  steps: { min: 0, max: 200000, unit: "steps" },
  waterMl: { min: 0, max: 20000, unit: "ml" },
  workoutMinutes: { min: 0, max: 1440, unit: "minutes" },
  workoutsPerWeek: { min: 0, max: 50, unit: "per week" },
};

/**
 * Why this value cannot be stored in this field, or null if it can.
 *
 * Returns a sentence rather than a boolean so the caller can throw something
 * that says which field and which number. That message goes to the log, never
 * to the user: the gate turns a refused write into one plain line, and a
 * sentence naming somebody's weight is not for them to read back.
 *
 * A field with no range is not an error. Unlisted fields pass, so adding one to
 * a mutation without adding it here fails open rather than blocking a write
 * nobody meant to block.
 */
export function healthValueProblem(field: string, value: unknown): string | null {
  if (value === undefined || value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return `${field} must be a finite number, got ${String(value)}`;
  }
  const range = HEALTH_RANGES[field];
  if (!range) return null;
  if (value < range.min || value > range.max) {
    return (
      `${field} of ${value} is outside the range a person can have ` +
      `(${range.min} to ${range.max} ${range.unit})`
    );
  }
  return null;
}

/**
 * The first problem in a bag of fields, or null if every one of them is
 * storable. Field order is the caller's, so the message names whichever the
 * caller listed first rather than whichever happens to hash first.
 */
export function firstHealthValueProblem(
  fields: Record<string, unknown>,
): string | null {
  for (const [field, value] of Object.entries(fields)) {
    const problem = healthValueProblem(field, value);
    if (problem) return problem;
  }
  return null;
}

export const setupRequirements = [
  "privacyNotice",
  "name",
  "age",
  "height",
  "weight",
  "goal",
  "calorieTarget",
  "checkInTime",
] as const;

export type SetupRequirement = (typeof setupRequirements)[number];

/** Beta is adults only, and a calorie number is the thing that must not reach a minor. */
export const MINIMUM_AGE = 18;

/**
 * The stored rows this reads, named rather than passed as whole documents so
 * the function stays testable and callable from the reconcile script, which
 * holds the same fields as plain JSON rather than as Convex docs.
 */
export type SetupSnapshot = {
  privacyNoticeSentAt?: number | null;
  name?: string | null;
  age?: number | null;
  heightCm?: number | null;
  weightKg?: number | null;
  sex?: string | null;
  goal?: Goal | null;
  /** From `targets.calories`. */
  calories?: number | null;
  /** From `reminders.dailyReviewTime`. */
  dailyReviewTime?: string | null;
};

/**
 * Assemble a snapshot from the three rows it is spread across.
 *
 * Pure, and deliberately takes the rows rather than a database handle, so the
 * two callers that need it can read those rows however suits them: `ted.ts`
 * fetches one user's target and reminder by index, while the dashboard reads
 * every row once and looks them up in a map. Both then judge readiness by the
 * identical code, which is the whole point — a second opinion about what
 * "missing" means is the bug this shape exists to prevent.
 */
export function setupSnapshotFrom(
  user: {
    privacyNoticeSentAt?: number | null;
    name?: string | null;
    age?: number | null;
    heightCm?: number | null;
    weightKg?: number | null;
    sex?: string | null;
    goal?: Goal | null;
  },
  target: { calories?: number | null } | null | undefined,
  reminder: { dailyReviewTime?: string | null } | null | undefined,
): SetupSnapshot {
  return {
    privacyNoticeSentAt: user.privacyNoticeSentAt ?? null,
    name: user.name ?? null,
    age: user.age ?? null,
    heightCm: user.heightCm ?? null,
    weightKg: user.weightKg ?? null,
    sex: user.sex ?? null,
    goal: user.goal ?? null,
    calories: target?.calories ?? null,
    dailyReviewTime: reminder?.dailyReviewTime ?? null,
  };
}

export type SetupState = {
  missing: SetupRequirement[];
  /**
   * Set when the gap cannot be closed by asking again. A stated age under 18
   * is not an unanswered question, and re-asking it is the one response that
   * would be worse than doing nothing.
   */
  blocked: "minor" | null;
  ready: boolean;
};

function hasText(value: string | null | undefined): boolean {
  return typeof value === "string" && value.trim().length > 0;
}

function hasNumber(value: number | null | undefined): boolean {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

/**
 * Which requirements this person is still missing.
 *
 * Order follows `setupRequirements`, so the first entry is always the next
 * thing worth asking for and a caller can take `missing[0]` without sorting.
 */
export function setupStateFor(snapshot: SetupSnapshot): SetupState {
  const missing: SetupRequirement[] = [];

  if (!hasNumber(snapshot.privacyNoticeSentAt)) missing.push("privacyNotice");
  if (!hasText(snapshot.name)) missing.push("name");
  if (!hasNumber(snapshot.age)) missing.push("age");
  if (!hasNumber(snapshot.heightCm)) missing.push("height");
  if (!hasNumber(snapshot.weightKg)) missing.push("weight");
  if (!hasText(snapshot.goal)) missing.push("goal");
  if (!hasNumber(snapshot.calories)) missing.push("calorieTarget");
  if (!isLocalTimeKey(String(snapshot.dailyReviewTime ?? ""))) missing.push("checkInTime");

  // Checked after the list is built so a minor's record still reports what
  // else is absent. The block is what stops them, not the missing fields.
  const blocked =
    typeof snapshot.age === "number" && snapshot.age < MINIMUM_AGE ? "minor" : null;

  return { missing, blocked, ready: missing.length === 0 && blocked === null };
}

/**
 * What `onboarding.completedAt` should be after a readiness check.
 *
 * One home for a rule that used to live in one caller. `completedAt` was
 * written only inside `saveOnboarding`, while `users.status` is derived by
 * `refreshSetupStatus` from seven call sites, so anybody whose last missing
 * field was closed by a `setTarget` call went active and never got the column.
 * On 16 Sept two users were in exactly that state, and because two others were
 * wrong in the opposite direction the totals matched and every aggregate check
 * in the repo stayed green.
 *
 * Kept once earned, which is the older half of the rule and still right: a user
 * who finished setup and later had a field cleared is somebody with a gap to
 * close, not somebody who never started. So this only ever moves from unset to
 * set, never back.
 */
export function nextCompletedAt(
  current: number | undefined,
  ready: boolean,
  now: number,
): number | undefined {
  if (current !== undefined) return current;
  return ready ? now : undefined;
}

/** Shorthand for the one thing `users.status` should be derived from. */
export function isSetUp(snapshot: SetupSnapshot): boolean {
  return setupStateFor(snapshot).ready;
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
  "week",
  "target",
  "reminder",
  "onboarding",
  "report",
  "reports",
  "reminderGate",
  "replied",
  "setupAudit",
  "refreshSetup",
] as const;
