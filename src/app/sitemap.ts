import type { MetadataRoute } from "next";

/**
 * Two pages, because two is all the public site has. The landing page is a
 * static file served at "/" by the rewrite in next.config.ts, and /privacy is
 * the only App Router page a visitor can reach.
 *
 * /metrics is deliberately absent. It needs `?key=`, returns 404 without one,
 * sets its own noindex, and robots.ts shuts it. A sitemap entry would be the
 * one place that advertised the URL back.
 *
 * `lastModified` is written by hand rather than computed. `new Date()` would
 * be the obvious shortcut and it lies: every deployment would claim both pages
 * had just changed, including deployments that touched neither, and a crawler
 * that is told everything is always new learns to ignore the field. File mtime
 * is no better, because a fresh checkout on a build machine stamps every file
 * with the time of the checkout. So: when you change one of these pages, move
 * its date. When you change something else, leave them alone.
 */
const LAST_MODIFIED = {
  landing: "2026-09-18",
  privacy: "2026-09-18",
} as const;

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: "https://heyted.in/",
      lastModified: LAST_MODIFIED.landing,
      changeFrequency: "monthly",
      priority: 1,
    },
    {
      url: "https://heyted.in/privacy",
      lastModified: LAST_MODIFIED.privacy,
      changeFrequency: "yearly",
      priority: 0.5,
    },
  ];
}
