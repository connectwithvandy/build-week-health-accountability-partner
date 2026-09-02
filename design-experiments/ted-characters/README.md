# Ted character experiment — 2×2

A standalone design experiment. It is **not** imported by `src/app`, creates no Next.js
route, and cannot change the live landing page. It sits beside `ted-recovery-led/` as a
sibling, not a replacement.

Preview it locally:

```bash
python3 -m http.server 4174 --directory design-experiments/ted-characters
```

Then open `http://localhost:4174`.

## What is being tested

One daily-review card, built four times. Copy, palette, layout, type and spacing are held
**identical** across all four. The character is the only variable, so any difference in how
the card feels is attributable to the character alone.

|            | Flat doodle              | Soft / volumetric              |
|------------|--------------------------|--------------------------------|
| Hedgehog   | hand-built SVG, ink line | hand-built SVG, gradient-shaded |
| Capybara   | hand-built SVG, ink line | hand-built SVG, gradient-shaded |

The right-hand column is **not** a generated 3D render. It is the same character geometry
filled with radial gradients plus a contact shadow, standing in for the matte-clay look. It
tests the real question — does volume make Ted warmer, or more toylike? — without needing an
image-generation key. Swap in real renders later if one becomes available.

## Why the card and not the landing page

Ted lives on WhatsApp, so almost none of the product surface is styleable. The daily review
card is the one rectangle we fully control, it is what `IDEA_SCOPE.md` names as "the personal
artifact a user would screenshot", and it arrives at the emotionally loaded moment. It is the
highest-value place to spend design effort.

## Palette

Base and accent taken from `tbh.studiovoila.com`:

| Token      | Value     | Role                              |
|------------|-----------|-----------------------------------|
| `--paper`  | `#f8f4f2` | page ground                       |
| `--card`   | `#fffdfc` | card ground                       |
| `--ink`    | `#211e1d` | text, progress fill               |
| `--muted`  | `#847e7c` | secondary text                    |
| `--line`   | `#e1d9d5` | rules, empty progress track       |
| `--accent` | `#ff8556` | the one action, rationed          |

`Fraunces` stands in for TBH's `Recoleta`, which is not free. Same job: a warm serif carrying
the friendliness so colour does not have to.

Constraint driving these choices: the card is rendered as a flat image inside WhatsApp, so it
sits against WhatsApp's own green and must survive both WhatsApp light and dark mode without
adapting. Warm neutrals sit calmly beside green; a cool grey or blue would not.

## Copy rules held constant

- No streak language, no red, no failure states. A missed commitment is stated as a number
  and nothing more.
- Exactly one forward action, and it must still be achievable tonight.
- Numbers come from what the user actually logged, never a generic motivational line.

## Status

All four cells are built and rendering. Nothing here is wired into the app.

On the missing key: there is no usable `OPENAI_API_KEY` anywhere reachable from this repo.
`.env.example` carries the name with an empty value, `.env.local` does not have it, and Vercel
holds only `NEXT_PUBLIC_TED_WHATSAPP_NUMBER` and `CONVEX_DEPLOY_KEY`. Ted's OpenAI usage is
configured in `hermes/machine/hermes-config.yaml`, so the key lives with Hermes on whatever
machine runs it — not here.

## Known rough edges

- The hedgehog's snout is long enough to read slightly anteater-ish at large sizes. Fine in the
  52px card avatar, worth shortening if the hedgehog wins.
- Neither character has been tested against a real WhatsApp dark-mode background yet.
- The card has only been viewed at desktop width. It has not been checked at phone width,
  which is where it will actually be seen.
