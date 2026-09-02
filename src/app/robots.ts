import type { MetadataRoute } from "next";

/**
 * Ted is a private beta with a waitlist of exactly the people Vandy has
 * messaged. Until that changes, being findable in search is a liability rather
 * than a win: strangers arriving at a health product that stores meal logs and
 * body measurements is not what this is for yet.
 *
 * Paired with `robots: { index: false }` in layout.tsx — robots.txt asks
 * crawlers not to fetch, the meta tag asks them not to index anything they
 * fetched anyway. Remove both together when the beta opens.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", disallow: "/" }],
    host: "https://whatsapp-accountability-partner-ted.vercel.app",
  };
}
