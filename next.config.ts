import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /**
   * The landing page is v6 from `design-experiments/`: one self-contained HTML
   * file with its own CSS and scroll-scrubbed chat threads. It is served as a
   * static file rather than retyped into JSX, so what ships is byte-for-byte
   * the design that was reviewed.
   *
   * `beforeFiles` runs ahead of the App Router, so this claims "/" even though
   * `src/app` no longer defines a page there. Everything else — /privacy,
   * /robots.txt, /api/* — is untouched and still Next.js.
   *
   * To go back to a React landing page: delete this rewrite and add
   * `src/app/page.tsx` (the previous one is in git, before this commit).
   */
  async rewrites() {
    return {
      beforeFiles: [{ source: "/", destination: "/landing-v6.html" }],
      afterFiles: [],
      fallback: [],
    };
  },
};

export default nextConfig;
