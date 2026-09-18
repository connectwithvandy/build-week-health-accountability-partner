import type { Metadata } from "next";
import { Baloo_2, Fraunces, Outfit } from "next/font/google";
import "./globals.css";
import { Analytics } from "@vercel/analytics/next";

import { ConvexClientProvider } from "./ConvexClientProvider";
import { SiteBeacon } from "./SiteBeacon";

/**
 * The same three faces the landing page uses. The landing page is a static file
 * that pulls them from Google's CDN; here they are self-hosted by next/font, so
 * /privacy has no third-party font request and no layout shift.
 */
const display = Fraunces({
  variable: "--font-display",
  subsets: ["latin"],
  style: ["normal", "italic"],
});

const body = Outfit({
  variable: "--font-body",
  subsets: ["latin"],
});

// the Ted wordmark only — the three letters in the logo, nothing else
const wordmark = Baloo_2({
  variable: "--font-wordmark",
  subsets: ["latin"],
  weight: ["800"],
});

export const metadata: Metadata = {
  title: "Ted. Your day, remembered",
  description:
    "Ted remembers your meals, movement, water, and commitments in WhatsApp. Then it gives you one useful thing you can still do today.",
  // No `robots` key here on purpose, since 18 Sep 2026. It used to carry
  // `{ index: false, follow: false }` for the private beta, which applied to
  // every App Router page at once. Leaving it off lets the default apply and
  // keeps the decision in one place, `robots.ts`.
  //
  // `/metrics` is the exception and sets its own `noindex` in
  // `metrics/page.tsx`, because a page that is reached with a key should say
  // so itself rather than inherit it from a layout somebody may later edit.
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${body.variable} ${wordmark.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <ConvexClientProvider>{children}</ConvexClientProvider>
        {/*
          Covers the App Router pages only — /privacy and anything added later.
          "/" is a static file served by the rewrite in next.config.ts and never
          passes through this layout, so it carries its own copy of the Vercel
          insights script instead. Move the landing page back into React and
          that script tag becomes redundant; until then both are needed.
        */}
        <Analytics />
        {/*
          Ted's own count, which sits beside Vercel's rather than replacing it.
          Vercel gives the visitor number and is the cross-check; this one also
          sees WhatsApp button taps, which Vercel charges for, and feeds the
          /metrics dashboard where they sit next to conversations started.
        */}
        <SiteBeacon />
      </body>
    </html>
  );
}
