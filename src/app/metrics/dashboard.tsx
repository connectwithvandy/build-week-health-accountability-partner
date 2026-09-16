import type { Summary } from "./summary";

/**
 * The dashboard itself: everything below the key check in `page.tsx`. It is a
 * pure function of one summary object, so `__tests__/metrics-dashboard.test.tsx`
 * can render it against sample numbers and check what a reader would actually
 * see — no Convex deployment in the loop.
 */

const DAY_LABEL = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});

const IST_TIME = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Asia/Kolkata",
});

function dayLabel(dayKey: string) {
  return DAY_LABEL.format(new Date(`${dayKey}T00:00:00Z`));
}

/** A share of a previous stage, or a dash when the stage was empty — never a
 *  division by zero dressed up as 0%. */
function share(part: number, whole: number) {
  if (whole <= 0) return "—";
  return `${Math.round((part / whole) * 100)}%`;
}

/** A 14-day column chart. One series, so no legend: the heading names it. The
 *  tallest column carries the only direct label; every value is in the table
 *  underneath, which is also the accessible reading of this data. */
export function DailyChart({
  title,
  note,
  series,
  tone,
}: {
  title: string;
  note: string;
  series: { dayKey: string; value: number }[];
  tone: "visitors" | "clicks" | "starts" | "activated";
}) {
  const peak = Math.max(...series.map((point) => point.value), 0);
  const peakIndex = series.findIndex((point) => point.value === peak && peak > 0);

  return (
    <figure className={`metric-chart metric-chart-${tone}`}>
      <figcaption>
        <h3>{title}</h3>
        <p>{note}</p>
      </figcaption>

      <div className="metric-plot" aria-hidden="true">
        {series.map((point, index) => (
          <div className="metric-col" key={point.dayKey}>
            <span className="metric-tip">
              {dayLabel(point.dayKey)}: {point.value}
            </span>
            {index === peakIndex ? <span className="metric-peak">{peak}</span> : null}
            <span
              className="metric-bar"
              style={{ height: peak > 0 ? `${Math.max((point.value / peak) * 100, point.value > 0 ? 4 : 0)}%` : "0%" }}
            />
          </div>
        ))}
      </div>

      <div className="metric-axis" aria-hidden="true">
        <span>{dayLabel(series[0].dayKey)}</span>
        <span>{dayLabel(series[series.length - 1].dayKey)}</span>
      </div>
    </figure>
  );
}

/** What each setup requirement is, said the way Ted asks for it. An unknown
 *  key falls through to itself rather than being hidden, so a requirement added
 *  to `setupRequirements` shows up here badly named instead of not at all. */
const REQUIREMENT_LABELS: Record<string, string> = {
  privacyNotice: "The privacy notice going out",
  name: "What to call them",
  age: "Their age",
  height: "Their height",
  weight: "Their weight",
  goal: "The one thing they want to change",
  calorieTarget: "A calorie target",
  checkInTime: "What time to check in, and their city",
};

export function Dashboard({ summary, source }: { summary: Summary; source: string }) {
  const { totals, thisWeek, daily, byPlacement, setupBlockers, coverage } = summary;

  return (
    <>
      {/* One number leads, and the two that follow are read as what happened to
          it: the same week, narrowing. Stating the visitor count again in its
          own hero band above this strip would be the same number twice. */}
      <section className="metric-lede" aria-label="This week, stage by stage">
        <p className="eyebrow">This week, to {dayLabel(summary.today)}</p>

        <div className="metric-stages">
          <div className="metric-stage metric-stage-visitors">
            <p className="metric-hero-figure">{thisWeek.uniqueVisitors.toLocaleString()}</p>
            <h1 className="metric-stage-label">different people opened the site</h1>
            <p className="metric-stage-note">
              {thisWeek.pageViews.toLocaleString()} page views ·{" "}
              {totals.visitorWeeks.toLocaleString()} across every week on record, counted once per
              person per week, so somebody who came back appears in each week they came
            </p>
          </div>

          <div className="metric-stage metric-stage-clicks">
            <p className="metric-stage-value">{thisWeek.uniqueClickers.toLocaleString()}</p>
            <p className="metric-stage-label">tapped &ldquo;Message Ted&rdquo;</p>
            <p className="metric-stage-note">
              {share(thisWeek.uniqueClickers, thisWeek.uniqueVisitors)} of the people who came ·{" "}
              {thisWeek.whatsappClicks.toLocaleString()} taps in total
            </p>
          </div>

          <div className="metric-stage metric-stage-starts">
            <p className="metric-stage-value">{thisWeek.conversationsStarted.toLocaleString()}</p>
            <p className="metric-stage-label">started talking to Ted</p>
            {/* Deliberately not a percentage of the taps to its left. Nothing
                links a tap to the WhatsApp message that may follow it, and
                people reach Ted from Instagram or a forwarded number without
                ever opening the site — so a share here would be a made-up
                conversion rate, and on any day the site is quiet it prints
                numbers like 2700%. */}
            <p className="metric-stage-note">
              {totals.conversationsStarted.toLocaleString()} all time · people also reach Ted
              without opening the site, so this is not a share of the taps
            </p>
          </div>

          {/* The stage the other three exist for. Starting a conversation is
              one message. This is the first point where Ted actually did its
              job, and unlike the stage to its left it is a fair share, because
              both numbers come from the same rows and describe the same people. */}
          <div className="metric-stage metric-stage-activated">
            <p className="metric-stage-value">{thisWeek.activated.toLocaleString()}</p>
            <p className="metric-stage-label">finished setup and logged something</p>
            <p className="metric-stage-note">
              {share(thisWeek.activated, thisWeek.conversationsStarted)} of the people who started ·{" "}
              {totals.activated.toLocaleString()} all time ·{" "}
              {totals.returnedASecondDay.toLocaleString()} came back and logged on a second day
            </p>
          </div>
        </div>
      </section>

      <section className="metric-charts">
        <DailyChart
          title="People who opened the site"
          note="Counted once per person per day"
          tone="visitors"
          series={daily.map((day) => ({ dayKey: day.dayKey, value: day.visitors }))}
        />
        <DailyChart
          title="Taps on &ldquo;Message Ted&rdquo;"
          note="Every tap, including repeats"
          tone="clicks"
          series={daily.map((day) => ({ dayKey: day.dayKey, value: day.clicks }))}
        />
        <DailyChart
          title="First conversations with Ted"
          note="One per new WhatsApp number"
          tone="starts"
          series={daily.map((day) => ({ dayKey: day.dayKey, value: day.starts }))}
        />
        <DailyChart
          title="People who activated"
          note="Setup finished and at least one thing logged"
          tone="activated"
          series={daily.map((day) => ({ dayKey: day.dayKey, value: day.activations }))}
        />
      </section>

      <section className="metric-table-wrap">
        <h2>The last {summary.windowDays} days</h2>
        <div className="metric-scroll">
          <table className="metric-table">
            <thead>
              <tr>
                <th scope="col">Day (IST)</th>
                <th scope="col">Visitors</th>
                <th scope="col">Taps</th>
                <th scope="col">Conversations started</th>
                <th scope="col">Activated</th>
              </tr>
            </thead>
            <tbody>
              {[...daily].reverse().map((day) => (
                <tr key={day.dayKey}>
                  <th scope="row">{dayLabel(day.dayKey)}</th>
                  <td>{day.visitors}</td>
                  <td>{day.clicks}</td>
                  <td>{day.starts}</td>
                  <td>{day.activations}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Not a vanity number. Every row here is a person who started talking to
          Ted and stopped somewhere, and the top row is the question costing the
          most people. This is the one panel on the page that says what to fix
          rather than how things went. */}
      <section className="metric-table-wrap" aria-labelledby="setup-blockers">
        <h2 id="setup-blockers">What setup is still waiting on</h2>
        {setupBlockers.length === 0 ? (
          <p className="metric-empty">Nobody is part-way through setup.</p>
        ) : (
          <>
            <p className="metric-note">
              {totals.loggedWithoutFinishingSetup.toLocaleString()} of these people are logging
              meals, water or workouts anyway, so Ted is useful to them while still counting them
              unfinished.
            </p>
            <div className="metric-scroll">
              <table className="metric-table">
                <thead>
                  <tr>
                    <th scope="col">Still missing</th>
                    <th scope="col">People held up by it</th>
                  </tr>
                </thead>
                <tbody>
                  {setupBlockers.map((row) => (
                    <tr key={row.requirement}>
                      <th scope="row">
                        {REQUIREMENT_LABELS[row.requirement] ?? row.requirement}
                      </th>
                      <td>{row.people}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      <section className="metric-table-wrap">
        <h2>Which button they tapped</h2>
        {byPlacement.length === 0 ? (
          <p className="metric-empty">No taps recorded yet.</p>
        ) : (
          <div className="metric-scroll">
            <table className="metric-table">
              <thead>
                <tr>
                  <th scope="col">Button</th>
                  <th scope="col">Taps</th>
                  <th scope="col">Different people</th>
                </tr>
              </thead>
              <tbody>
                {byPlacement.map((row) => (
                  <tr key={row.placement}>
                    <th scope="row">
                      {row.placement === "nav"
                        ? "Top bar"
                        : row.placement === "hero"
                          ? "First screen"
                          : row.placement === "close"
                            ? "Bottom of the page"
                            : row.placement}
                    </th>
                    <td>{row.clicks}</td>
                    <td>{row.uniqueClickers}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="metric-method">
        <h2>Where each number comes from</h2>
        <dl>
          <dt>Visitors and taps</dt>
          <dd>
            The site&rsquo;s own beacon, stored in Convex as <code>siteEvents</code>. A person is
            counted by a one-way hash of the address and browser their request already carries,
            salted with the week. No cookie, nothing stored on their device, and the hash cannot be
            turned back into an address. Because the salt changes weekly, someone who visits in two
            different weeks counts once in each — so the all-time figure is a ceiling, and the
            weekly one is the number to trust.
          </dd>
          <dt>First conversations</dt>
          <dd>
            Rows in the Convex <code>users</code> table, one per WhatsApp number, dated the first
            time Ted recorded anything for that person. Someone who messages and never gets that
            far is not counted, so this is a floor.
          </dd>
          <dt>The cross-check</dt>
          <dd>
            Vercel Web Analytics counts visitors independently on the same pages. Its number and the
            one above are measured differently and will not match exactly; if they are far apart,
            one of them is wrong. Vercel cannot see button taps (a paid feature) or anything that
            happens inside WhatsApp, which is why this page exists.
          </dd>
          <dt>Coverage</dt>
          <dd>
            {coverage.eventsScanned.toLocaleString()} site events read
            {coverage.truncated ? " (the read limit was hit, so older events are not counted)" : ""}
            {coverage.oldestEventAt
              ? `, the oldest from ${IST_TIME.format(new Date(coverage.oldestEventAt))}. `
              : ". "}
            {coverage.usersScanned.toLocaleString()} people and{" "}
            {coverage.entriesScanned.toLocaleString()} logged entries behind the activation
            figures
            {coverage.entriesTruncated
              ? ", and that read hit its limit too, so every activation number above is a floor rather than a count. "
              : ". "}
            Read from the Convex deployment at <code>{source}</code> at{" "}
            {IST_TIME.format(new Date(summary.generatedAt))} IST — the same deployment the
            WhatsApp side writes to, so the conversations counted here are the conversations Ted
            actually had.
          </dd>
        </dl>
      </section>
    </>
  );
}

