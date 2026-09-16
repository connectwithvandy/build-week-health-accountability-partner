"use client";

import { ConvexProvider, ConvexReactClient } from "convex/react";
import type { ReactNode } from "react";

/**
 * The Convex client for anything rendered in the browser.
 *
 * This used to `throw` at module scope when `NEXT_PUBLIC_CONVEX_URL` was
 * absent, and `layout.tsx` wraps every App Router page in it, so one missing
 * variable took down `/privacy` — a static page with no Convex in it at all —
 * along with the `/metrics` setup panel whose entire job is to tell you which
 * variable is missing. The loudest possible failure, in the one place it could
 * do no good.
 *
 * It is also redundant. Every page that genuinely needs Convex checks for
 * itself and says so in words: `metrics/page.tsx` names the missing variable
 * and prints the commands that set it, and `convex/site.ts` refuses to read or
 * write without `TED_SITE_SECRET`. Nothing here was ever the thing that told
 * anybody, so removing the throw loses no warning that is not already given
 * better somewhere else.
 *
 * Note that nothing in `src/` currently uses a Convex React hook: `/metrics`
 * reads through `ConvexHttpClient` on the server and `/privacy` is static. This
 * provider is kept for the first client component that needs one, and it is
 * now inert rather than dangerous while it waits.
 */
const convexUrl = process.env.NEXT_PUBLIC_CONVEX_URL;

/**
 * Built once, at module scope, because that is what `ConvexReactClient`
 * expects: constructing one per render opens a fresh websocket on every
 * navigation. Null when there is no URL to build it from.
 */
const convex = convexUrl ? new ConvexReactClient(convexUrl) : null;

export function ConvexClientProvider({ children }: { children: ReactNode }) {
  // Without a client the children render exactly as they would have, which is
  // correct for every page that never asks Convex anything. A component that
  // does ask will throw on its own hook, at the point of use, naming itself —
  // which is a far more useful failure than the whole tree refusing to mount.
  if (!convex) return <>{children}</>;

  return <ConvexProvider client={convex}>{children}</ConvexProvider>;
}
