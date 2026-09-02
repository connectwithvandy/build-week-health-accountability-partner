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

// Ted lives in WhatsApp, so a WhatsApp share is the main way anyone arrives.
// Without these tags that share renders as a bare blue link with no title, no
// description and no image — the worst possible first impression for the one
// channel the product actually lives in.
const siteUrl = "https://whatsapp-accountability-partner-ted.vercel.app";
const shareDescription =
  "Tell Ted what you ate and what got done in WhatsApp. It keeps track, " +
  "nudges you once when it matters, and gives you an honest recap at night.";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: "Ted — your health day, remembered",
  description: shareDescription,
  applicationName: "Ted",
  openGraph: {
    type: "website",
    url: siteUrl,
    siteName: "Ted",
    title: "Ted — your health day, remembered",
    description: shareDescription,
    images: [
      {
        url: "/ted-whatsapp-cover.png",
        width: 1600,
        height: 900,
        alt: "Ted, a health accountability partner that lives in WhatsApp",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Ted — your health day, remembered",
    description: shareDescription,
    images: ["/ted-whatsapp-cover.png"],
  },
  alternates: { canonical: siteUrl },
  // Private beta: keep it out of search results until it is meant to be found.
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
