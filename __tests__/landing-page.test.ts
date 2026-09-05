import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The landing page is a static file (`public/landing-v6.html`) served at "/" by
 * the rewrite in `next.config.ts`, so React tests cannot reach it. These
 * assertions are the only thing standing between a design edit and a page that
 * quietly drops a safety disclosure, stops linking to /privacy, or becomes
 * indexable while the beta is still private.
 */
const html = readFileSync(join(process.cwd(), "public/landing-v6.html"), "utf8");

const openingMessage = "Okay Ted, let's do this 💪";

/** The page is static, so it cannot read NEXT_PUBLIC_TED_WHATSAPP_NUMBER at
 *  runtime; the number is written into the markup, and this constant is what
 *  the markup is checked against.
 *
 *  The constant alone cannot catch the number drifting away from the env value
 *  the rest of the product uses — it would just be two copies of the same
 *  stale string — so where the env var is actually set (any machine with
 *  `.env.local`, which CI does not have) the two are compared as well. */
const whatsappNumber = "918660650986";

describe("the v6 landing page", () => {
  it("uses the same number as the rest of the product", () => {
    const fromEnv = process.env.NEXT_PUBLIC_TED_WHATSAPP_NUMBER;

    if (!fromEnv) {
      expect(whatsappNumber).toMatch(/^\d{12}$/);
      return;
    }

    expect(whatsappNumber).toBe(fromEnv);
  });

  it("keeps the private beta out of search", () => {
    expect(html).toContain('<meta name="robots" content="noindex, nofollow">');
  });

  it("renders at phone width instead of a zoomed-out desktop page", () => {
    expect(html).toContain('<meta name="viewport" content="width=device-width, initial-scale=1">');
  });

  it("explains Ted's core promise", () => {
    expect(html).toMatch(/remembers your meals, movement, water/i);
    expect(html).toMatch(/one useful thing you can still do today/i);
  });

  it("makes the health and privacy disclosures", () => {
    expect(html).toMatch(/not medical advice/i);
    expect(html).toMatch(/emergencies, diagnosis,? or treatment/i);
    expect(html).toMatch(/stores your profile, messages, plans, logs/i);
    expect(html).toMatch(/services that run it process this information/i);
    expect(html).toMatch(/delete my data/i);
    expect(html).toContain('href="/privacy"');
  });

  it("repeats the WhatsApp action with the agreed opening message", () => {
    const links = [...html.matchAll(/href="(https:\/\/wa\.me\/[^"]*)"/g)].map((m) => m[1]);
    expect(links.length).toBeGreaterThanOrEqual(2);

    for (const href of links) {
      expect(href).toContain(`wa.me/${whatsappNumber}`);
      expect(decodeURIComponent(href)).toContain(openingMessage);
      expect(decodeURIComponent(href)).toContain("💪");
    }
  });

  it("labels every WhatsApp button with where it sits, so the dashboard can tell them apart", () => {
    const anchors = [...html.matchAll(/<a[^>]*href="https:\/\/wa\.me\/[^"]*"[^>]*>/g)].map((m) => m[0]);
    expect(anchors.length).toBe(3);

    const placements = anchors.map((tag) => tag.match(/data-ted-cta="([^"]+)"/)?.[1]);
    expect(placements).toEqual(["nav", "hero", "close"]);
  });

  it("counts its own visitors and taps, which Vercel's free tier cannot", () => {
    expect(html).toContain("/api/site-event");
    expect(html).toContain("type:'page_view'");
    expect(html).toContain("type:'whatsapp_click'");
    // Vercel's script stays: it is the independent cross-check on the visitor number.
    expect(html).toContain('<script defer src="/_vercel/insights/script.js"></script>');
  });

  it("no longer calls itself an experiment", () => {
    expect(html).not.toMatch(/design experiment/i);
    expect(html).not.toMatch(/not the live site/i);
  });
});
