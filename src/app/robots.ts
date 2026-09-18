import type { MetadataRoute } from "next";

/**
 * Open to search as of 18 Sep 2026, on heyted.in. Until then this sent
 * `Disallow: /`, because a waitlist of exactly the people Vandy had messaged
 * gained nothing from strangers finding a health product mid-beta.
 *
 * Two paths stay shut, and neither is about the beta.
 *
 * `/api/` is machines talking to machines. There is nothing there for a
 * reader and the beacon endpoint accepts writes, so it does not belong in
 * an index.
 *
 * `/metrics` is the numbers dashboard. It is already reached only with
 * `?key=`, returns 404 without one, and sets its own `noindex` in
 * `metrics/page.tsx`. This is the third lock on the same door: cheap, and it
 * keeps the URL out of the crawl entirely rather than relying on the page to
 * turn a crawler away once it is there.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: ["/api/", "/metrics"] }],
    // Points at sitemap.ts. A crawler that arrives without being told where to
    // look reads this file first, so naming the sitemap here is what saves it
    // guessing at the two pages the site actually has.
    sitemap: "https://heyted.in/sitemap.xml",
    host: "https://heyted.in",
  };
}
