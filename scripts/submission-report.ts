/**
 * Build Week submission numbers, read from Convex and nothing else.
 *
 *     npm run submission:report
 *
 * READ-ONLY BY CONSTRUCTION. The only Convex command this file is allowed to
 * shell out to is `npx convex data`, which lists tables and reads documents.
 * There is no insert, no update, no delete, no migration, no `convex deploy`,
 * no `convex import`, no `convex run`. `assertReadOnly` below refuses to spawn
 * anything else, so a future edit that reaches for a writing subcommand fails
 * loudly instead of quietly touching production.
 *
 * Every number is printed with the table it came from and the exact filter that
 * produced it, on the same line, so each one can be defended.
 *
 * Table and field names are read from convex/schema.ts, not guessed. Where the
 * schema simply does not record something Build Week asks for (inbound message
 * count is the big one), this says so in place of the number rather than
 * substituting a proxy silently.
 */

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { homedir } from "node:os";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * Rows to ask for per table. Convex refuses to scan more than 16384 documents
 * in one query, so this sits just under that. If a table ever returns exactly
 * this many rows the output says so rather than quietly under-counting.
 */
const ROW_LIMIT = 16000;

/**
 * The URL to submit. `whatsapp-accountability-partner-ted.vercel.app` is the
 * project's auto-generated Vercel domain and serves the identical deployment,
 * but this is the one to put in front of judges.
 */
const PRODUCT_URL = "https://heyted.vercel.app/";
const REPO_URL =
  "https://github.com/connectwithvandy/build-week-health-accountability-partner";

const MANUAL_HEADING = "## Fill in manually before submitting";

/**
 * Written by `scripts/gateway-message-count.py`, which reads the gateway's own
 * store because Convex structurally cannot count inbound messages. This script
 * must never generate that section, only carry it through untouched, so a
 * Convex refresh does not silently drop the one number Convex cannot produce.
 */
const GATEWAY_HEADING = "## Inbound messages, from the gateway";

/**
 * The blank shape of the hand-written section, used only the first time or
 * after the section has been emptied. One row per post so each number sits
 * next to the post it came from, which is how the insight panels are read.
 */
const MANUAL_TEMPLATE = [
  "Numbers here come from each post's own insights panel and from analytics.",
  "Screenshot each panel as you go and keep the file names next to the row.",
  "",
  "| Post | Link | Impressions | Reactions | Screenshot |",
  "| --- | --- | ---: | ---: | --- |",
  "| LinkedIn |  |  |  |  |",
  "| Instagram |  |  |  |  |",
  "| X |  |  |  |  |",
  "",
  "- Unique site visitors this week: ",
  "- Analytics screenshot: ",
  "- Analytics read-only access link: ",
];

/**
 * Reads back whatever was typed into the hand-written section of an existing
 * SUBMISSION.md. Returns the blank template when the file is missing, when the
 * section is absent, or when every line still reads as empty, so a re-run mid
 * submission never costs numbers that are only written down here.
 */
function readManualSection(target: string): string[] {
  if (!existsSync(target)) return MANUAL_TEMPLATE;
  const lines = readFileSync(target, "utf8").split("\n");
  const start = lines.findIndex((l) => l.trim() === MANUAL_HEADING);
  if (start === -1) return MANUAL_TEMPLATE;
  let end = lines.findIndex((l, i) => i > start && l.startsWith("## "));
  if (end === -1) end = lines.length;
  const body = lines.slice(start + 1, end);
  while (body.length && body[0].trim() === "") body.shift();
  while (body.length && body[body.length - 1].trim() === "") body.pop();
  if (!body.length) return MANUAL_TEMPLATE;

  // A section still holding only labels, table scaffolding and blanks carries
  // no answers, so it is worth nothing and the template is the better start.
  const hasAnswer = body.some((line) => {
    const t = line.trim();
    if (t === "" || t.startsWith("|")) return false;
    const afterLabel = t.replace(/^[-*]\s*/, "");
    const colon = afterLabel.indexOf(":");
    return colon !== -1 && afterLabel.slice(colon + 1).trim() !== "";
  });
  const hasFilledCell = body.some((line) => {
    const t = line.trim();
    if (!t.startsWith("|") || /^\|[\s|:-]*\|$/.test(t)) return false;
    const cells = t.split("|").slice(1, -1).map((c) => c.trim());
    return cells.slice(1).some((c) => c !== "");
  });
  return hasAnswer || hasFilledCell ? body : MANUAL_TEMPLATE;
}

/**
 * Reads back the gateway section verbatim, or returns nothing when the file
 * has none yet. Unlike the hand-written section there is no blank template to
 * fall back on: an absent section means `gateway-message-count.py` has not run,
 * and inventing a placeholder here would put an empty table where a real number
 * belongs.
 */
function readGatewaySection(target: string): string[] {
  if (!existsSync(target)) return [];
  const lines = readFileSync(target, "utf8").split("\n");
  const start = lines.findIndex((l) => l.trim() === GATEWAY_HEADING);
  if (start === -1) return [];
  let end = lines.findIndex((l, i) => i > start && l.startsWith("## "));
  if (end === -1) end = lines.length;
  const body = lines.slice(start + 1, end);
  while (body.length && body[0].trim() === "") body.shift();
  while (body.length && body[body.length - 1].trim() === "") body.pop();
  return body.length ? [GATEWAY_HEADING, "", ...body, ""] : [];
}

/** The only convex subcommand this script may ever run. */
const ALLOWED_CONVEX_SUBCOMMAND = "data";

function assertReadOnly(args: string[]): void {
  if (args[0] !== "convex" || args[1] !== ALLOWED_CONVEX_SUBCOMMAND) {
    throw new Error(
      `refusing to run \`npx ${args.join(" ")}\` — this script may only run ` +
        `\`npx convex ${ALLOWED_CONVEX_SUBCOMMAND}\`, which is read-only.`,
    );
  }
  const writing = ["deploy", "import", "run", "dev", "env", "dashboard", "export"];
  for (const arg of args) {
    if (writing.includes(arg) && arg !== ALLOWED_CONVEX_SUBCOMMAND) {
      throw new Error(`refusing to run \`npx ${args.join(" ")}\` — not read-only.`);
    }
  }
}

function convex(args: string[]): string {
  const full = ["convex", ...args];
  assertReadOnly(full);
  try {
    return execFileSync("npx", full, {
      cwd: REPO,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      maxBuffer: 256 * 1024 * 1024,
    });
  } catch (error) {
    // The raw failure is a wall of Convex client stack frames. Keep the first
    // line, which is the part that says what actually went wrong.
    const stderr = String((error as { stderr?: string }).stderr ?? "").trim();
    const first = stderr.split("\n").filter(Boolean).slice(0, 2).join(" ");
    throw new Error(`\`npx ${full.join(" ")}\` failed: ${first || String(error)}`);
  }
}

// ---------------------------------------------------------------------------
// Which deployment holds the real users
// ---------------------------------------------------------------------------

function readEnvFile(path: string): Record<string, string> {
  const out: Record<string, string> = {};
  if (!existsSync(path)) return out;
  for (const raw of readFileSync(path, "utf8").split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const key = line.slice(0, line.indexOf("=")).trim();
    let value = line.slice(line.indexOf("=") + 1).trim();
    if (value.startsWith('"') || value.startsWith("'")) {
      value = value.slice(1, value.indexOf(value[0], 1) === -1 ? undefined : value.indexOf(value[0], 1));
    }
    out[key] = value;
  }
  return out;
}

/** `https://hardy-scorpion-901.eu-west-1.convex.site` -> `hardy-scorpion-901` */
function deploymentFromUrl(url: string): string | null {
  const match = /https?:\/\/([a-z0-9-]+)\./.exec(url.trim());
  return match ? match[1] : null;
}

type Resolved = { name: string; source: string };

function resolveDeployment(): Resolved {
  const flag = process.argv.slice(2).find((a) => a.startsWith("--deployment="));
  if (flag) return { name: flag.split("=")[1], source: "--deployment= flag" };

  if (process.env.TED_CONVEX_DEPLOYMENT) {
    return { name: process.env.TED_CONVEX_DEPLOYMENT, source: "TED_CONVEX_DEPLOYMENT env var" };
  }

  // The live WhatsApp gateway writes to whatever TED_CONVEX_SITE_URL points at.
  // That is the deployment holding real users, and it is NOT necessarily the
  // one in .env.local, which is the local dev deployment.
  const hermesEnv = join(homedir(), ".hermes", ".env");
  const siteUrl = readEnvFile(hermesEnv).TED_CONVEX_SITE_URL;
  const fromHermes = siteUrl ? deploymentFromUrl(siteUrl) : null;
  if (fromHermes) {
    return { name: fromHermes, source: `TED_CONVEX_SITE_URL in ${hermesEnv} (the live gateway's backend)` };
  }

  const local = readEnvFile(join(REPO, ".env.local")).CONVEX_DEPLOYMENT;
  if (local) {
    const name = local.split("#")[0].trim().replace(/^(dev|prod):/, "");
    return { name, source: "CONVEX_DEPLOYMENT in .env.local" };
  }

  throw new Error(
    "could not work out which Convex deployment to read. Pass --deployment=<name>.",
  );
}

// ---------------------------------------------------------------------------
// Reading
// ---------------------------------------------------------------------------

/**
 * A row exactly as Convex hands it back. Deliberately untyped: the point of
 * this script is to count what the tables actually contain, so a mismatch
 * between a hand-written type here and the real row should show up as a
 * surprising number, not be hidden by a cast. `convex/schema.ts` is the
 * contract; this is just JSON.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Doc = Record<string, any>;

function listTables(deployment: string): string[] {
  return convex(["data", "--deployment", deployment])
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith("_") && /^[A-Za-z][A-Za-z0-9_]*$/.test(l));
}

function readTable(deployment: string, table: string): Doc[] {
  const out = convex([
    "data",
    table,
    "--deployment",
    deployment,
    "--limit",
    String(ROW_LIMIT),
    "--format",
    "jsonl",
  ]);
  return out
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => JSON.parse(l) as Doc);
}

// ---------------------------------------------------------------------------
// Report rows
// ---------------------------------------------------------------------------

type Row = {
  metric: string;
  value: string;
  table: string;
  filter: string;
};

const rows: Row[] = [];
const notes: string[] = [];

function add(metric: string, value: number | string, table: string, filter: string): void {
  rows.push({ metric, value: String(value), table, filter });
}

function istStamp(ms: number): string {
  return new Date(ms + IST_OFFSET_MS).toISOString().replace("T", " ").slice(0, 19) + " IST";
}

function main(): void {
  const deployment = resolveDeployment();
  const now = Date.now();
  const since24h = now - DAY_MS;
  const since7d = now - 7 * DAY_MS;

  const tables = listTables(deployment.name);
  const data: Record<string, Doc[]> = {};
  for (const t of tables) data[t] = readTable(deployment.name, t);

  for (const t of tables) {
    if (data[t].length >= ROW_LIMIT) {
      notes.push(
        `\`${t}\` returned ${data[t].length} rows, which is the read limit — the count may be truncated.`,
      );
    }
  }

  // What span these lifetime totals actually cover. Every count below is
  // unfiltered by date, so the honest framing is "everything production has
  // ever held" — and that is only as far back as its oldest row, which is not
  // the same day the repo started.
  const allCreationTimes = tables
    .flatMap((t) => data[t].map((d) => Number(d._creationTime)))
    .filter((n) => Number.isFinite(n));
  const earliestRow = allCreationTimes.length ? Math.min(...allCreationTimes) : null;
  const latestRow = allCreationTimes.length ? Math.max(...allCreationTimes) : null;

  const users = data.users ?? [];
  const onboarding = data.onboarding ?? [];
  const dailyEntries = data.dailyEntries ?? [];
  const userFacts = data.userFacts ?? [];
  const reportedReplies = data.reportedReplies ?? [];

  // --- coverage -----------------------------------------------------------
  add(
    "Data coverage (every total below is lifetime, no date filter)",
    earliestRow === null
      ? "no rows"
      : `${istStamp(earliestRow)} → ${istStamp(latestRow as number)}`,
    tables.join(" + "),
    "oldest and newest _creationTime across every table in the deployment — " +
      "totals cannot reach further back than this",
  );

  // --- users -------------------------------------------------------------
  add("Total user records created", users.length, "users", "no filter — every row in the table");

  const completed = onboarding.filter((o) => typeof o.completedAt === "number");
  add(
    "Users onboarded (finished onboarding)",
    completed.length,
    "onboarding",
    "completedAt !== undefined",
  );

  const active = users.filter((u) => u.status === "active");
  add(
    "Users onboarded (cross-check on the user row)",
    active.length,
    "users",
    'status === "active"',
  );

  const stillOnboarding = users.filter((u) => u.status === "onboarding");
  add(
    "Users part-way through onboarding",
    stillOnboarding.length,
    "users",
    'status === "onboarding"',
  );

  // --- activity in a window ----------------------------------------------
  // The schema has no messages table: inbound WhatsApp turns are not stored as
  // rows anywhere in Convex. The honest stand-in for "sent at least one
  // message" is "left a trace in a window", built from every per-user
  // timestamp the schema actually has.
  const ACTIVITY_FILTER =
    "distinct userId still present in `users`, with any of: dailyEntries.occurredAt | " +
    "dailyEntries.createdAt | dailyEntries.updatedAt | userFacts.updatedAt | " +
    "onboarding.updatedAt | users.updatedAt | reportedReplies.reportedAt";

  // Rows can outlive the user they point at — a deleted account leaves its
  // dailyEntries and reportedReplies behind. Counting those userIds would put
  // "active users" above "total users", which is indefensible, so the set is
  // intersected with the users table.
  const liveUserIds = new Set(users.map((u) => String(u._id)));

  function activeUsersSince(cutoff: number): Set<string> {
    const seen = new Set<string>();
    for (const e of dailyEntries) {
      if (
        Math.max(e.occurredAt ?? 0, e.createdAt ?? 0, e.updatedAt ?? 0) >= cutoff &&
        typeof e.userId === "string"
      ) {
        seen.add(e.userId);
      }
    }
    for (const f of userFacts) {
      if ((f.updatedAt ?? 0) >= cutoff && typeof f.userId === "string") seen.add(f.userId);
    }
    for (const o of onboarding) {
      if ((o.updatedAt ?? 0) >= cutoff && typeof o.userId === "string") seen.add(o.userId);
    }
    for (const r of reportedReplies) {
      if ((r.reportedAt ?? 0) >= cutoff && typeof r.userId === "string") seen.add(r.userId);
    }
    for (const u of users) {
      if ((u.updatedAt ?? 0) >= cutoff && typeof u._id === "string") seen.add(u._id);
    }
    for (const id of [...seen]) {
      if (!liveUserIds.has(id)) seen.delete(id);
    }
    return seen;
  }

  add(
    "Users active in the last 24 hours",
    activeUsersSince(since24h).size,
    "dailyEntries + userFacts + onboarding + users + reportedReplies",
    `${ACTIVITY_FILTER} >= ${since24h} (${istStamp(since24h)})`,
  );

  add(
    "Users active in the last 7 days",
    activeUsersSince(since7d).size,
    "dailyEntries + userFacts + onboarding + users + reportedReplies",
    `${ACTIVITY_FILTER} >= ${since7d} (${istStamp(since7d)})`,
  );

  // --- inbound messages ---------------------------------------------------
  // dailyEntries.externalMessageId is the only message identifier in the whole
  // schema. Report how many rows actually carry one, so the gap is visible
  // rather than papered over.
  const withMessageId = dailyEntries.filter(
    (e) => typeof e.externalMessageId === "string" && e.externalMessageId.length > 0,
  );
  const distinctMessageIds = new Set(withMessageId.map((e) => e.externalMessageId));

  if (distinctMessageIds.size > 0) {
    add(
      "Total inbound messages",
      distinctMessageIds.size,
      "dailyEntries",
      "distinct externalMessageId where externalMessageId !== ''",
    );
  } else {
    add(
      "Total inbound messages",
      "NOT STORED",
      "dailyEntries",
      "distinct externalMessageId where externalMessageId !== '' → 0 rows carry one; " +
        "the schema has no messages table, so inbound turns are not counted anywhere in Convex",
    );
    notes.push(
      "**Inbound messages cannot be counted from Convex.** `convex/schema.ts` has no messages " +
        "table, and `dailyEntries.externalMessageId` is written empty on every row " +
        `(0 of ${dailyEntries.length}). Use the line below as the defensible floor, or pull the ` +
        "real number from the WhatsApp gateway logs.",
    );
  }

  add(
    "Inbound messages — defensible floor",
    dailyEntries.length,
    "dailyEntries",
    "no filter — every row is one thing a user sent that Ted logged; " +
      "excludes chat that produced no log, so this is a lower bound",
  );

  // --- meals and food items ----------------------------------------------
  const meals = dailyEntries.filter((e) => e.entryType === "meal");
  add("Meals logged", meals.length, "dailyEntries", 'entryType === "meal"');

  const foodItems = meals.reduce(
    (sum, e) => sum + (Array.isArray(e.meal?.items) ? e.meal.items.length : 0),
    0,
  );
  add(
    "Individual food items logged",
    foodItems,
    "dailyEntries",
    'sum of meal.items.length where entryType === "meal"',
  );

  add(
    "All logged entries (meal + water + steps + workout + commitment)",
    dailyEntries.length,
    "dailyEntries",
    "no filter — every row in the table",
  );

  // --- voice notes --------------------------------------------------------
  const voice = dailyEntries.filter((e) => e.source === "voice");
  add("Voice notes received (that produced a log)", voice.length, "dailyEntries", 'source === "voice"');

  const photo = dailyEntries.filter((e) => e.source === "photo");
  add("Photos received (that produced a log)", photo.length, "dailyEntries", 'source === "photo"');

  // --- optional tables ----------------------------------------------------
  const waitlistTable = tables.find((t) => /waitlist|wait_list|waiting/i.test(t));
  if (waitlistTable) {
    add("Waitlist entries", data[waitlistTable].length, waitlistTable, "no filter — every row in the table");
  } else {
    add(
      "Waitlist entries",
      "NO SUCH TABLE",
      "—",
      `no table matching /waitlist|wait_list|waiting/i exists in ${deployment.name}`,
    );
  }

  const payTable = tables.find((t) => /pay|subscription|billing|invoice|checkout|order/i.test(t));
  if (payTable) {
    add("Payment / paid-user records", data[payTable].length, payTable, "no filter — every row in the table");
  } else {
    add(
      "Payment / paid-user records",
      "NO SUCH TABLE",
      "—",
      `no table matching /pay|subscription|billing|invoice|checkout|order/i exists in ${deployment.name}`,
    );
  }

  // --- supporting ---------------------------------------------------------
  add("Memory facts stored about users", userFacts.length, "userFacts", "no filter — every row in the table");
  add("Replies users reported as wrong", reportedReplies.length, "reportedReplies", "no filter — every row in the table");

  // --- print --------------------------------------------------------------
  const stamp = istStamp(now);
  const width = Math.max(...rows.map((r) => r.metric.length));
  const valueWidth = Math.max(...rows.map((r) => r.value.length));

  console.log("");
  console.log(`Build Week submission numbers — ${stamp}`);
  console.log(`Convex deployment: ${deployment.name}`);
  console.log(`Chosen from:       ${deployment.source}`);
  console.log(`Tables present:    ${tables.join(", ")}`);
  console.log(`Mode:              READ-ONLY (npx convex data only)`);
  console.log("");

  for (const r of rows) {
    console.log(
      `${r.metric.padEnd(width)}  ${r.value.padStart(valueWidth)}   [table: ${r.table}]  [filter: ${r.filter}]`,
    );
  }

  if (notes.length) {
    console.log("");
    console.log("Caveats:");
    for (const n of notes) console.log(`  - ${n.replace(/\*\*/g, "")}`);
  }

  // --- write SUBMISSION.md ------------------------------------------------
  const md: string[] = [];
  md.push(`# Build Week submission — generated ${stamp}`);
  md.push("");
  md.push(
    `Read from Convex deployment \`${deployment.name}\` (${deployment.source}) with read-only ` +
      `\`npx convex data\` queries. No writes, no migrations.`,
  );
  md.push("");
  md.push("## Numbers");
  md.push("");
  md.push("| Metric | Number | Source table | Exact filter |");
  md.push("| --- | ---: | --- | --- |");
  // A raw `|` ends the cell and a raw backtick ends the code span, and filter
  // strings contain both. Escaping here keeps the filter readable as one cell.
  const cell = (text: string) => text.replace(/`/g, "'").replace(/\|/g, "\\|");
  for (const r of rows) {
    md.push(
      `| ${cell(r.metric)} | ${cell(r.value)} | \`${cell(r.table)}\` | \`${cell(r.filter)}\` |`,
    );
  }
  md.push("");
  if (notes.length) {
    md.push("### Caveats");
    md.push("");
    for (const n of notes) md.push(`- ${n}`);
    md.push("");
  }
  // Everything below is typed in by hand from places Convex cannot see: post
  // insight panels, the analytics dashboard. A re-run must never wipe it, so
  // the hand-written section of the existing SUBMISSION.md wins over the
  // blank template whenever it already has something in it.
  const target = join(REPO, "SUBMISSION.md");
  md.push(...readGatewaySection(target));
  md.push(MANUAL_HEADING);
  md.push("");
  md.push(...readManualSection(target));
  md.push("");
  md.push("## Checklist");
  md.push("");
  md.push(`- [ ] Live product URL — ${PRODUCT_URL}`);
  md.push(`- [ ] Public GitHub repo URL — ${REPO_URL}`);
  md.push("- [ ] Metrics — the table above, plus the manual numbers filled in");
  md.push("");

  writeFileSync(target, md.join("\n"), "utf8");
  console.log("");
  console.log(`Wrote ${target}`);
  console.log("");
}

main();
