/**
 * The weekly recap card, as a picture.
 *
 * Draft. Rendered by `scripts/recap/render.mjs` into a PNG that the gateway
 * can send with `hermes send "MEDIA:<path>"`.
 *
 * Every colour and both fonts are lifted from `public/landing-v6.html` so the
 * card and the site cannot drift apart. The chat bubbles are the site's own
 * device, and they are the reason this reads as "that WhatsApp thing" at a
 * glance rather than as a generic fitness graphic.
 *
 * NOTHING CLINICAL IS ON IT. No calories, no weight, no targets, no health
 * notes, and no name. The whole point is that somebody can forward it without
 * forwarding their health record, and a name on a shared card is the one field
 * that identifies the person who shared it.
 *
 * Zeros are dropped, the same rule `meal_breakdown` follows. On 16 Sep the two
 * people this was built for had zero workouts and zero steps between them, and
 * a card announcing "0 workouts" is not a recap, it is a reprimand.
 */

const INK = "#111317";
const PAPER = "#ffffff";
const MUTED = "#868d96";
const LINE = "#e3e7ec";
const ORANGE = "#ff7e3e";
const ME = "#cfe9b6";
const WA = "#eef1f5";

const div = (style, children) => ({
  type: "div",
  props: { style: { display: "flex", ...style }, children },
});

const text = (style, value) => ({
  type: "div",
  props: { style: { display: "flex", ...style }, children: String(value) },
});

function bubble(body, mine) {
  return div(
    { justifyContent: mine ? "flex-end" : "flex-start", marginBottom: 16 },
    [
      text(
        {
          maxWidth: 660,
          background: mine ? ME : WA,
          color: INK,
          padding: "20px 26px",
          borderRadius: 20,
          fontFamily: "Outfit",
          fontWeight: 400,
          fontSize: 31,
          lineHeight: 1.35,
        },
        body,
      ),
    ],
  );
}

/** One dot per day, filled where they logged something. */
function dayStrip(days) {
  return div({ gap: 18 }, days.map((day, index) => div(
    { flexDirection: "column", alignItems: "center", gap: 12 },
    [
      div({
        width: 62,
        height: 62,
        borderRadius: 31,
        background: day.logged ? ORANGE : PAPER,
        border: day.logged ? `2px solid ${ORANGE}` : `2px solid ${LINE}`,
      }, []),
      text(
        {
          fontFamily: "Outfit",
          fontWeight: 600,
          fontSize: 24,
          color: day.logged ? INK : MUTED,
        },
        day.letter,
      ),
    ],
  )));
}

function stat(value, label) {
  return div({ flexDirection: "column", alignItems: "flex-start", flex: 1 }, [
    text({ fontFamily: "Fraunces", fontSize: 92, color: INK, lineHeight: 1 }, value),
    text(
      { fontFamily: "Outfit", fontWeight: 600, fontSize: 27, color: MUTED, marginTop: 6 },
      label,
    ),
  ]);
}

export function recapCard({ days = [], daysLogged = 0, stats = [], line = "" }) {
  return div(
    {
      width: "100%",
      height: "100%",
      flexDirection: "column",
      background: PAPER,
      padding: "68px 68px 60px",
      justifyContent: "space-between",
    },
    [
      // wordmark
      div({ alignItems: "center", gap: 16 }, [
        div({ width: 54, height: 54, borderRadius: 27, background: ORANGE }, []),
        text({ fontFamily: "Outfit", fontWeight: 800, fontSize: 33, color: INK }, "Ted"),
      ]),

      // the headline and the week at a glance
      div({ flexDirection: "column", gap: 44 }, [
        div({ flexDirection: "column" }, [
          text({ fontFamily: "Fraunces", fontSize: 78, color: INK, lineHeight: 1.04 }, "your week,"),
          text(
            { fontFamily: "Fraunces", fontSize: 78, color: ORANGE, lineHeight: 1.04 },
            `${daysLogged} days in.`,
          ),
        ]),
        dayStrip(days),
      ]),

      // the chat, which is what makes it recognisably Ted
      div({ flexDirection: "column" }, [
        bubble(line, false),
        bubble("no app. just the chat.", true),
      ]),

      // the numbers, zeros already dropped by the caller
      div({ flexDirection: "column" }, [
        div({ height: 1, background: LINE, marginBottom: 36 }, []),
        div({}, stats.map((s) => stat(s.value, s.label))),
      ]),

      // footer
      div({ alignItems: "center", justifyContent: "space-between" }, [
        text({ fontFamily: "Outfit", fontWeight: 600, fontSize: 29, color: MUTED }, "heyted.vercel.app"),
        text(
          {
            background: INK,
            color: PAPER,
            padding: "20px 34px",
            borderRadius: 10,
            fontFamily: "Outfit",
            fontWeight: 800,
            fontSize: 29,
          },
          "try Ted on WhatsApp",
        ),
      ]),
    ],
  );
}
