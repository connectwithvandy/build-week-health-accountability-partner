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
  tone: "visitors" | "clicks" | "starts";
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

export function Dashboard({ summary, source }: { summary: Summary; source: string }) {
  const { totals, thisWeek, daily, byPlacement, coverage } = summary;

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
              {totals.uniqueVisitors.toLocaleString()} people across every week on record
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
            <p className="metric-stage-note">
              {share(thisWeek.conversationsStarted, thisWeek.uniqueClickers)} of the people who
              tapped · {totals.conversationsStarted.toLocaleString()} all time
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
              </tr>
            </thead>
            <tbody>
              {[...daily].reverse().map((day) => (
                <tr key={day.dayKey}>
                  <th scope="row">{dayLabel(day.dayKey)}</th>
                  <td>{day.visitors}</td>
                  <td>{day.clicks}</td>
                  <td>{day.starts}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
              ? `, the oldest from ${IST_TIME.format(new Date(coverage.oldestEventAt))}`
              : ""}
. Read from the Convex deployment at <code>{source}</code> at{" "}
            {IST_TIME.format(new Date(summary.generatedAt))} IST — the same deployment the
            WhatsApp side writes to, so the conversations counted here are the conversations Ted
            actually had.
          </dd>
        </dl>
      </section>
    </>
  );
}

