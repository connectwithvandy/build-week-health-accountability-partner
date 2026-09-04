import type { Metadata } from "next";
import { Baloo_2, Fraunces, Outfit } from "next/font/google";
import "./globals.css";
import { Analytics } from "@vercel/analytics/next";

import { ConvexClientProvider } from "./ConvexClientProvider";

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
  // Private beta: the waitlist is exactly the people Vandy has messaged, so
  // being findable in search is a liability, not a win. robots.ts asks
  // crawlers not to fetch; this asks them not to index anything they fetched
  // anyway. The landing page carries its own copy of this, because it is a
  // static file that this metadata cannot reach. Remove all three together
  // when the beta opens.
  robots: { index: false, follow: false },
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
      </body>
    </html>
  );
}
