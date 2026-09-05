"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

/**
 * The App Router half of the website's own counting. The landing page is a
 * static file with its own copy of this in a plain <script>; this covers
 * /privacy and anything added to src/app later, so the two halves of the site
 * are counted the same way.
 *
 * The dashboard at /metrics deliberately does not count itself — reading your
 * own numbers should not move them.
 */
export function SiteBeacon() {
  const pathname = usePathname();

  useEffect(() => {
    if (pathname.startsWith("/metrics")) return;

    const payload = JSON.stringify({
      type: "page_view",
      path: pathname,
      referrer: document.referrer,
    });
    const body = new Blob([payload], { type: "application/json" });

    if (navigator.sendBeacon?.("/api/site-event", body)) return;
    fetch("/api/site-event", { method: "POST", body, keepalive: true }).catch(() => {});
  }, [pathname]);

  return null;
}
