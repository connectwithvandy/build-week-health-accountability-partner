# Ted landing — v6

A copy of `ted-landing-v5-editorial`, taken on 3 Sep 2026 and reworked against a
design critique run in a fresh context on screenshots alone (no code, no history).

**Frozen at iteration 2. Scored 6/10.** Work continues in `ted-landing-v7`.

Preview:

```bash
python3 -m http.server 4186 --directory design-experiments/ted-landing-v6
```

`ted-landing.html` is one self-contained file. `ted-landing.artifact.html` is identical,
kept for publishing. Nothing here is imported by `src/app`; it creates no route and cannot
affect the live site.

## What changed from v5

- The brush script went from five headlines to one. It is the hero's signature and nothing else.
- The tilted hard-shadow stickers ("real thread", "reads the photo") were removed. They
  annotated what the phone already showed.
- The evening review stopped being a native app card with a stats table. It is now one
  oversized incoming message. This also fixed a product contradiction: `hermes/SOUL.md`
  forbids tables, headers and dividers in a recap, so the old card contradicted Ted's voice.
- The dark act moved from 25% of the page to the emotional midpoint, so the second half is
  not flat white.
- The hero thread lost a five-line bubble and a four-line ingredient dump.
- Warm paper ground, so the WhatsApp green and the brand orange sit in one palette.
- Nav: six links at near-CTA weight down to three at regular weight.
- The ~34px strip of bare ground between the orange closer and the footer is gone.
- The 01/02/03 row got real display numerals; its decorative squiggle was deleted.

## What the second critique said is still wrong

Kept here because v7 starts from it.

1. Every section is the same shape — text left, chat right — four times. Nothing gets louder
   or quieter across 5,500px. Called the biggest tell of a generated layout.
2. The italic emphasis word now appears in seven headlines. Replacing the script with italics
   moved the tic rather than removing it.
3. Three different mockup scales, and the widest one is landscape while still wearing a phone
   status bar with bubbles wider than any phone renders.
4. Page, section, tile and chat wallpaper are all within a few percent of the same beige.
5. The dark review band and the dark privacy card sit almost back to back.
6. The hero phone outweighs the headline; the eyebrow floats ~45px off the H1.
