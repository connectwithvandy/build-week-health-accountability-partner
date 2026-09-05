import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Dashboard } from "@/app/metrics/dashboard";
import type { Summary } from "@/app/metrics/summary";

/**
 * The dashboard is the whole point of the analytics: numbers nobody reads are
 * the same as no numbers. These render it the way a reader meets it and check
 * the arithmetic on the page rather than in the query.
 */

const DAYS = [
  "2026-08-23", "2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27",
  "2026-08-28", "2026-08-29", "2026-08-30", "2026-08-31", "2026-09-01",
  "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05",
];

function summary(overrides: Partial<Summary> = {}): Summary {
  return {
    generatedAt: Date.UTC(2026, 8, 5, 6, 0),
    today: "2026-09-05",
    windowDays: 14,
    totals: {
      uniqueVisitors: 412,
      pageViews: 631,
      whatsappClicks: 96,
      uniqueClickers: 71,
      conversationsStarted: 25,
    },
    thisWeek: {
      uniqueVisitors: 180,
      pageViews: 240,
      whatsappClicks: 45,
      uniqueClickers: 36,
      conversationsStarted: 9,
    },
    byPlacement: [
      { placement: "hero", clicks: 60, uniqueClickers: 44 },
      { placement: "close", clicks: 24, uniqueClickers: 19 },
      { placement: "nav", clicks: 12, uniqueClickers: 8 },
    ],
    daily: DAYS.map((dayKey, index) => ({
      dayKey,
      visitors: [4, 9, 12, 7, 15, 22, 18, 31, 27, 40, 36, 52, 44, 61][index],
      clicks: [0, 1, 2, 1, 3, 5, 4, 7, 6, 9, 8, 12, 10, 14][index],
      starts: [0, 0, 1, 0, 1, 2, 1, 3, 2, 4, 3, 5, 2, 4][index],
    })),
    coverage: {
      eventsScanned: 1204,
      truncated: false,
      oldestEventAt: Date.UTC(2026, 7, 23, 4, 0),
      newestEventAt: Date.UTC(2026, 8, 5, 5, 30),
    },
    ...overrides,
  };
}

describe("the /metrics dashboard", () => {
  it("leads with the number the week is judged on", () => {
    render(<Dashboard summary={summary()} source="hardy-scorpion-901.convex.cloud" />);

    const lede = screen.getByLabelText("This week, stage by stage");
    expect(within(lede).getByText("180")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: "different people opened the site" }),
    ).toBeInTheDocument();
    // the same number is never printed twice on the page
    expect(screen.getAllByText("180")).toHaveLength(1);
  });

  it("shows the drop from visiting to tapping to talking", () => {
    render(<Dashboard summary={summary()} source="hardy-scorpion-901.convex.cloud" />);

    const lede = screen.getByLabelText("This week, stage by stage");
    // 36 of 180 tapped, and 9 of those 36 became a first conversation.
    expect(within(lede).getByText(/20% of the people who came/)).toBeInTheDocument();
    // Conversations are never shown as a share of the taps: nothing links a tap
    // to the message that follows, and people reach Ted without the site at all.
    expect(within(lede).getByText(/not a share of the taps/)).toBeInTheDocument();
    expect(within(lede).queryByText(/% of the people who tapped/)).not.toBeInTheDocument();
  });

  it("says nothing rather than 0% when a stage had nobody in it", () => {
    const empty = summary({
      thisWeek: {
        uniqueVisitors: 0,
        pageViews: 0,
        whatsappClicks: 0,
        uniqueClickers: 0,
        conversationsStarted: 0,
      },
    });
    render(<Dashboard summary={empty} source="hardy-scorpion-901.convex.cloud" />);

    const lede = screen.getByLabelText("This week, stage by stage");
    expect(within(lede).getByText(/— of the people who came/)).toBeInTheDocument();
    expect(within(lede).queryByText(/0% of the people who came/)).not.toBeInTheDocument();
  });

  it("puts every charted value in a table, because the charts alone are not readable by everyone", () => {
    render(<Dashboard summary={summary()} source="hardy-scorpion-901.convex.cloud" />);

    // 14 days + 3 buttons + two header rows.
    expect(screen.getAllByRole("row")).toHaveLength(14 + 3 + 2);
    expect(screen.getByRole("row", { name: "5 Sept 61 14 4" })).toBeInTheDocument();
  });

  it("names the buttons the way a person would, not the way the code does", () => {
    render(<Dashboard summary={summary()} source="hardy-scorpion-901.convex.cloud" />);

    expect(screen.getByRole("rowheader", { name: "First screen" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "Top bar" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "Bottom of the page" })).toBeInTheDocument();
  });

  it("says where the numbers came from, so they can be argued with", () => {
    render(<Dashboard summary={summary()} source="hardy-scorpion-901.convex.cloud" />);

    expect(screen.getByText(/hardy-scorpion-901.convex.cloud/)).toBeInTheDocument();
    expect(screen.getByText(/1,204 site events read/)).toBeInTheDocument();
  });

  it("admits when the read hit its ceiling instead of showing a short count as a total", () => {
    const capped = summary({
      coverage: { eventsScanned: 16000, truncated: true, oldestEventAt: null, newestEventAt: null },
    });
    render(<Dashboard summary={capped} source="hardy-scorpion-901.convex.cloud" />);

    expect(screen.getByText(/older events are not counted/)).toBeInTheDocument();
  });
});
