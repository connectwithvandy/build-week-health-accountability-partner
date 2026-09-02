import Link from "next/link";

/**
 * The stock Next.js 404 is a black-and-white system page with no way back —
 * a dead end on a site whose only other route is the privacy page.
 *
 * Styled inline on purpose. It reads the site's own colour variables from
 * globals.css so it stays in the site's language, but it defines no classes of
 * its own and depends on no layout class, so it cannot break while the landing
 * page is being reworked — and it still renders sensibly if a variable is
 * renamed, because every one has a literal fallback.
 */
export default function NotFound() {
  return (
    <main
      style={{
        minHeight: "70vh",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        gap: "1.25rem",
        padding: "4rem 1.5rem",
        maxWidth: "38rem",
        margin: "0 auto",
        color: "var(--black, #1e1c1b)",
      }}
    >
      <p
        style={{
          fontFamily: "var(--font-utility), ui-monospace, monospace",
          fontSize: "0.8rem",
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--grey, #847e7c)",
          margin: 0,
        }}
      >
        404
      </p>

      <h1
        style={{
          fontFamily: "var(--font-display), system-ui, sans-serif",
          fontSize: "clamp(2rem, 6vw, 3rem)",
          lineHeight: 1.05,
          margin: 0,
        }}
      >
        That page isn&rsquo;t here.
        <br />
        <span style={{ color: "var(--orange, #fd7e40)" }}>Ted still is.</span>
      </h1>

      <p style={{ margin: 0, lineHeight: 1.6, color: "var(--grey, #847e7c)" }}>
        Nothing you logged is affected — this is just a link that doesn&rsquo;t go
        anywhere.
      </p>

      {/* 44px minimum so these are real tap targets on a phone, which is where
          almost everyone will hit this. */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
        <Link
          href="/"
          style={{
            display: "inline-flex",
            alignItems: "center",
            minHeight: "44px",
            padding: "0 1.25rem",
            borderRadius: "999px",
            background: "var(--black, #1e1c1b)",
            color: "var(--cream, #f8f4f2)",
            textDecoration: "none",
            fontWeight: 600,
          }}
        >
          Back to Ted
        </Link>
        <Link
          href="/privacy"
          style={{
            display: "inline-flex",
            alignItems: "center",
            minHeight: "44px",
            padding: "0 1.25rem",
            borderRadius: "999px",
            border: "1px solid var(--line, #e1d9d5)",
            color: "var(--black, #1e1c1b)",
            textDecoration: "none",
            fontWeight: 600,
          }}
        >
          Privacy
        </Link>
      </div>
    </main>
  );
}
