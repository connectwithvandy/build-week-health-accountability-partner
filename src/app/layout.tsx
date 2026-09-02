import type { Metadata } from "next";
import { IBM_Plex_Mono, Manrope, Space_Grotesk } from "next/font/google";
import "./globals.css";
import { ConvexClientProvider } from "./ConvexClientProvider";

const display = Space_Grotesk({
  variable: "--font-display",
  subsets: ["latin"],
});

const body = Manrope({
  variable: "--font-body",
  subsets: ["latin"],
});

const utility = IBM_Plex_Mono({
  variable: "--font-utility",
  weight: ["500", "700"],
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Ted. Your day, remembered",
  description:
    "Ted remembers your meals, movement, water, and commitments in WhatsApp. Then it gives you one useful thing you can still do today.",
  // Private beta: the waitlist is exactly the people Vandy has messaged, so
  // being findable in search is a liability, not a win. robots.ts asks
  // crawlers not to fetch; this asks them not to index anything they fetched
  // anyway. Remove both together when the beta opens.
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${body.variable} ${utility.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <ConvexClientProvider>{children}</ConvexClientProvider>
      </body>
    </html>
  );
}
