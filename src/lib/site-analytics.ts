import { createHash } from "node:crypto";

/**
 * How the website counts a visitor without following one.
 *
 * There is no cookie and nothing is written to the visitor's device. The server
 * takes the IP address and browser string it already receives with the request,
 * mixes in a secret salt plus the current week, and keeps only the hash. The
 * hash cannot be reversed into an address, and because the week is part of what
 * is hashed, the same person visiting next week is a different hash. That is
 * deliberate: it is long enough to answer "how many different people came this
 * week" and too short to build a history of anyone.
 */

const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

/** The IST calendar day a moment falls in, as YYYY-MM-DD. Ted's reports are all
 *  read in IST, so the website's are too. */
export function istDayKey(timestamp: number) {
  return new Date(timestamp + IST_OFFSET_MS).toISOString().slice(0, 10);
}

/** The Monday that starts the IST week a moment falls in, as YYYY-MM-DD. This
 *  is the life of a visitor hash. */
export function istWeekKey(timestamp: number) {
  const shifted = new Date(timestamp + IST_OFFSET_MS);
  // getUTCDay on the shifted clock is the IST weekday. Sunday is 0; treat it as
  // the last day of the week that began the Monday before.
  const weekday = (shifted.getUTCDay() + 6) % 7;
  return new Date(shifted.getTime() - weekday * DAY_MS).toISOString().slice(0, 10);
}

/**
 * The fallback salt. Setting SITE_EVENT_SALT to a random secret is what makes a
 * hash impossible to guess your way back out of; without it someone who already
 * knew an IP address and browser string could confirm that pair visited. The
 * fallback keeps the dashboard working out of the box and is documented in
 * .env.example as the thing to replace.
 */
const FALLBACK_SALT = "ted-site-analytics-unsalted";

export function visitorHash(input: {
  ip: string;
  userAgent: string;
  weekKey: string;
  salt?: string;
}) {
  const salt = input.salt && input.salt.length > 0 ? input.salt : FALLBACK_SALT;
  return createHash("sha256")
    .update(`${salt}|${input.weekKey}|${input.ip}|${input.userAgent}`)
    .digest("hex")
    .slice(0, 32);
}

/** The three places a "Message Ted" button appears on the landing page. An
 *  unrecognised placement is dropped rather than stored, so the breakdown can
 *  only ever contain buttons that exist. */
export const PLACEMENTS = ["nav", "hero", "close"] as const;
export type Placement = (typeof PLACEMENTS)[number];

export function normalisePlacement(value: unknown): Placement | undefined {
  return PLACEMENTS.includes(value as Placement) ? (value as Placement) : undefined;
}

/** The visitor's address as the platform reports it. Vercel puts the real one
 *  first in x-forwarded-for; the rest of the list is proxies. */
export function clientIp(headers: Headers) {
  const forwarded = headers.get("x-forwarded-for");
  if (forwarded) {
    const first = forwarded.split(",")[0]?.trim();
    if (first) return first;
  }
  return headers.get("x-real-ip") ?? "unknown";
}

/**
 * Crawlers and preview fetchers are not visitors. This is the same idea as the
 * bot filter in any analytics product: a name-based check that catches the
 * honest ones and misses anything pretending to be a browser. It only ever
 * removes rows, so the visitor count is a floor, never inflated.
 */
const BOT_PATTERN =
  /bot\b|crawler|spider|slurp|curl\/|wget|python-requests|headless|lighthouse|pingdom|facebookexternalhit|twitterbot|linkedinbot|whatsapp\/\d|vercel-screenshot/i;

export function looksLikeABot(userAgent: string) {
  return userAgent.length === 0 || BOT_PATTERN.test(userAgent);
}
