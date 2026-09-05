import { describe, expect, it } from "vitest";

import {
  clientIp,
  istDayKey,
  istWeekKey,
  looksLikeABot,
  normalisePlacement,
  visitorHash,
} from "@/lib/site-analytics";

/**
 * The website's visitor counting. These assertions are what stands between the
 * dashboard and two quiet failures: a hash that follows someone for longer than
 * it claims to, and a day boundary drawn in UTC while every other Ted number is
 * read in IST.
 */

/** 2026-09-05 02:00 IST — before UTC midnight has even happened, and the case a
 *  UTC day key gets wrong. */
const EARLY_IST_MORNING = Date.UTC(2026, 8, 4, 20, 30);

describe("IST day and week keys", () => {
  it("puts the small hours of an IST morning in that IST day, not the UTC one", () => {
    expect(new Date(EARLY_IST_MORNING).toISOString().slice(0, 10)).toBe("2026-09-04");
    expect(istDayKey(EARLY_IST_MORNING)).toBe("2026-09-05");
  });

  it("starts the week on Monday", () => {
    // 2026-09-05 IST is a Saturday; the Monday before it is 2026-08-31.
    expect(istWeekKey(EARLY_IST_MORNING)).toBe("2026-08-31");
  });

  it("keeps Sunday in the week that began the Monday before it", () => {
    const sunday = Date.UTC(2026, 8, 6, 12, 0); // 2026-09-06 17:30 IST, a Sunday
    expect(istWeekKey(sunday)).toBe("2026-08-31");
  });

  it("moves to a new week on Monday", () => {
    const monday = Date.UTC(2026, 8, 7, 12, 0); // 2026-09-07 IST, a Monday
    expect(istWeekKey(monday)).toBe("2026-09-07");
  });
});

describe("the visitor hash", () => {
  const visitor = { ip: "203.0.113.42", userAgent: "Mozilla/5.0 (iPhone)", salt: "s3cret" };

  it("counts the same person once within a week", () => {
    const monday = visitorHash({ ...visitor, weekKey: "2026-08-31" });
    const friday = visitorHash({ ...visitor, weekKey: "2026-08-31" });
    expect(friday).toBe(monday);
  });

  it("forgets them the following week", () => {
    expect(visitorHash({ ...visitor, weekKey: "2026-09-07" })).not.toBe(
      visitorHash({ ...visitor, weekKey: "2026-08-31" }),
    );
  });

  it("tells two visitors apart", () => {
    expect(visitorHash({ ...visitor, ip: "198.51.100.7", weekKey: "2026-08-31" })).not.toBe(
      visitorHash({ ...visitor, weekKey: "2026-08-31" }),
    );
  });

  it("carries nothing readable out of the address or the browser string", () => {
    const hash = visitorHash({ ...visitor, weekKey: "2026-08-31" });
    expect(hash).toMatch(/^[0-9a-f]{32}$/);
    expect(hash).not.toContain("203.0.113");
    expect(hash).not.toMatch(/iphone/i);
  });

  it("changes with the salt, so an unsalted deployment is not the same as a salted one", () => {
    expect(visitorHash({ ...visitor, salt: undefined, weekKey: "2026-08-31" })).not.toBe(
      visitorHash({ ...visitor, weekKey: "2026-08-31" }),
    );
  });
});

describe("what counts as a visitor", () => {
  it("keeps real browsers", () => {
    expect(
      looksLikeABot(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
      ),
    ).toBe(false);
    expect(
      looksLikeABot(
        "Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36",
      ),
    ).toBe(false);
  });

  it("drops crawlers and link-preview fetchers", () => {
    for (const agent of [
      "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
      "WhatsApp/2.23.20.79 A",
      "facebookexternalhit/1.1",
      "curl/8.7.1",
      "",
    ]) {
      expect(looksLikeABot(agent), agent).toBe(true);
    }
  });
});

describe("the request details", () => {
  it("reads the visitor's own address from the front of x-forwarded-for", () => {
    const headers = new Headers({ "x-forwarded-for": "203.0.113.42, 70.41.3.18, 150.172.238.178" });
    expect(clientIp(headers)).toBe("203.0.113.42");
  });

  it("says so rather than guessing when there is no address", () => {
    expect(clientIp(new Headers())).toBe("unknown");
  });

  it("only accepts buttons that exist on the page", () => {
    expect(normalisePlacement("hero")).toBe("hero");
    expect(normalisePlacement("footer")).toBeUndefined();
    expect(normalisePlacement(42)).toBeUndefined();
  });
});
