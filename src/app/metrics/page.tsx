import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ConvexHttpClient } from "convex/browser";

import { api } from "../../../convex/_generated/api";

import { Dashboard } from "./dashboard";
import type { Summary } from "./summary";

/**
 * One page for the three numbers that say whether the website is working:
 * how many different people arrived, how many tapped "Message Ted", and how
 * many of those became a first conversation in WhatsApp.
 *
 * Reached at /metrics?key=… — the key is METRICS_KEY in the Vercel project.
 * Without the right key the page does not exist, so the link can be handed to
 * a judge as read-only access without handing over the Vercel account.
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Numbers | Ted",
  robots: { index: false, follow: false },
};

/** The dashboard reads its own numbers with the same secret the beacon writes
 *  them with, so a missing key fails here rather than showing an empty page. */
async function loadSummary(convexUrl: string, secret: string): Promise<Summary> {
  return new ConvexHttpClient(convexUrl).query(api.site.summary, { secret });
}

function SetupNeeded({ problem }: { problem: string }) {
  return (
    <section className="metric-setup">
      <p className="eyebrow">Not collecting yet</p>
      <h1>The dashboard is live, the numbers are not.</h1>
      <p>{problem}</p>
      <ol>
        <li>
          Make one secret and give it to both sides:
          <code>npx convex env set TED_SITE_SECRET &quot;$(openssl rand -hex 24)&quot;</code>
          <code>vercel env add TED_SITE_SECRET</code>
        </li>
        <li>
          Salt the visitor hash so it cannot be guessed:
          <code>vercel env add SITE_EVENT_SALT</code>
        </li>
        <li>
          Push the schema and redeploy: <code>npx convex deploy</code> then <code>vercel deploy --prod</code>
        </li>
      </ol>
    </section>
  );
}

export default async function MetricsPage({
  searchParams,
}: {
  searchParams: Promise<{ key?: string }>;
}) {
  const expectedKey = process.env.METRICS_KEY;
  const { key } = await searchParams;

  // No key configured means no dashboard. An unprotected page of live numbers
  // is worse than no page, so this fails closed.
  if (!expectedKey || key !== expectedKey) notFound();

  const convexUrl = process.env.NEXT_PUBLIC_CONVEX_URL;
  const secret = process.env.TED_SITE_SECRET;

  let summary: Summary | null = null;
  let problem = "";

  if (!convexUrl || !secret) {
    problem = "NEXT_PUBLIC_CONVEX_URL or TED_SITE_SECRET is missing from this deployment.";
  } else {
    try {
      summary = await loadSummary(convexUrl, secret);
    } catch (error) {
      // A ConvexError arrives with its message in `data`; anything else is a
      // genuine failure and its own message is the most useful thing to show.
      const data = (error as { data?: unknown })?.data;
      problem =
        typeof data === "string"
          ? data
          : error instanceof Error
            ? error.message
            : "Convex did not answer.";
    }
  }

  return (
    <main className="metric-page">
      <header className="privacy-header page-shell">
        <Link className="brand" href="/" aria-label="Ted home">
          <span className="metric-wordmark">ted</span>
        </Link>
        <span className="privacy-back">The website, in numbers</span>
      </header>

      <div className="metric-body page-shell">
        {summary ? (
          <Dashboard summary={summary} source={new URL(convexUrl!).hostname} />
        ) : (
          <SetupNeeded problem={problem} />
        )}
      </div>
    </main>
  );
}
