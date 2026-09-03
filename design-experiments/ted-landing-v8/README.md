# Ted landing, v8

A copy of the shipped `public/landing-v6.html`, taken on 3 Sep 2026, with the
alignment audit, the motion rebuild and the design pass applied. Nothing here is
imported by `src/app`, it creates no route, and it cannot affect the live site.

Preview:

```bash
python3 -m http.server 4188 --directory design-experiments/ted-landing-v8
```

`index.html` is one self-contained file, already carrying the deployed head
(viewport, noindex, share tags, favicon). To ship it, copy it over
`public/landing-v6.html`; no head surgery is needed this time.

## What was broken in v6 and is fixed here

1. **`#nudge` never collapsed on mobile.** At 390px it split into 123px + 178px
   columns, so the headline broke one word per line and the phone squeezed to
   176px. The 980px rule collapses `.split`, but `.split.wide` is more specific
   and media queries add no specificity, so the two-column grid survived. This
   was live in production.
2. **The evening review could come to rest on a number that was not true.** The
   count-up unobserved its element immediately and had no visibility re-sync, so
   backgrounding the tab during the 900ms count froze it for good. Caught reading
   "0 of 1,400 cals", "96 of 1,400" and "33 of 1,400". Every clock on the page is
   now one rAF loop and every number is a pure function of scene time, so there
   is no state it can rest in that is not the real one.
3. **Three phone frames at three scales**, 372 / 704 / 386px, the widest of them
   landscape while wearing an iPhone status bar, and its right edge 116px past
   the margin every other section respects. One 372px frame now.
4. **Bubbles up to 593px wide.** Capped at 296px, which is what WhatsApp does.
5. **The recap stopped 64px short** of the page's right margin. It fills its
   column now.
6. **54px between the dark review band and the dark privacy card.** The privacy
   note is now the white bubble it always wanted to be, so the run reads dark,
   white, orange.
7. **Photo timestamps had no scrim**, only a text shadow, so "3:00 PM" sat white
   on white rice. Real gradient now.
8. **The photo bubble was clipped flat** by the third format tile. All three
   tiles clear their bubble by 8px.
9. **The day pill sat on top of messages.** It now steps aside when a chat, the
   recap or the privacy bubble is underneath it.

## What changed on purpose

- **The threads play themselves.** They used to be scrubbed by the scrollbar, so
  they froze mid-sentence the moment you stopped scrolling. Each thread is now a
  scene that plays when it arrives and rewinds once it has fully left, on the
  timing the conversation would really have: Ted's dots run for about as long as
  the line takes to type, your own replies appear in the composer a character at
  a time. Where the script names `pre` and `type` they are used as written.
- **Nothing on the page is a frozen screenshot any more.** The three format
  tiles play as a set (the text writes itself, the voice note plays with its
  timer running, the photo arrives the way a photo does) and the review lands a
  line at a time with the totals counting up last.
- **The nudge plays centre stage** instead of being a fourth text-left,
  chat-right section. That was the biggest tell of a generated layout.
- **The italic tic is down from six headlines to three**, kept only where the
  italic marks the actual turn in meaning. No words changed.
- `--paper-2` darkened so page, band and chat wallpaper are no longer three
  shades of the same beige.

## The day now only moves forwards

The reminder thread used to set a reminder at 9:12 PM and then fire it at 9:00
PM, twelve minutes before it was asked for, and it ran on to 11:04 PM while the
review that follows it on the page is stamped 10:45 PM. Every clock on the page
now moves one way: 3:00 the meal, 7:42 to 8:19 the walk, 8:31 the reminders set,
9:00 the dose it fires, 9:04 the travel pause, 10:45 the review.

## The ground

A pin emboss, white on white, at 60%. Each pinhead is drawn three times: a white
highlight, a shadow a hair the other way, and a faint dimple between them, which
is what makes it read as pressed paper rather than a printed dot. The light then
walks a slow circle every 30 seconds, so the relief keeps changing which way it
is pressed. Ink peaks at 2%.

It is a fixed pseudo element rather than a background on the body: a 24px grid
cannot be seen to scroll, and pinning it means one viewport repaints instead of
the whole 5,800px page. The pale band carries the same relief, so it reads as
the same sheet.

Rejected on the way: a tiled Ted-mark watermark, an aurora shader, poster shapes
in five arrangements, a scroll-driven sky that ran from afternoon to night, and a
Voronoi cell field. The useful correction was that orange, white and green is the
Indian flag, so every shape variant built from brand colours read as the same
basic thing no matter how the shapes were arranged.

## Off the beige

The ground is white. Ted's own mark is scattered across it on a 300px tile at
2% ink, carried on the body so it scrolls with the content and every band paints
over it, which keeps the page from reading as a blank canvas. The chat wallpaper
went cool rather than warm and stays a shade off white, because pure white
wallpaper would swallow the incoming white bubbles. The privacy note moved onto
a soft band for the same reason: a white bubble needs wallpaper behind it.

## Ted reads the photo correctly now

The hero reply said "paneer and kidney beans". The photograph is a burrito bowl:
pinto beans in a thin gravy, turmeric paneer, corn salsa, sautéed peppers, pico
de gallo and white rice. Rajma is darker and kidney shaped; these are pintos. The
alt text was worse, it described "a pot of greek yogurt" that is not in the frame
at all. Both are corrected, and the dosa alt now mentions its second chutney. The
photo section claims Ted "names what it sees before it counts anything", so this
is the one place on the page that cannot be approximately right.

## Copy rules applied

- **No dashes joining sentences** anywhere a visitor can read, including inside
  Ted's messages. Hyphens inside words (omega-3, 19-minute) stay.
- **The nudge thread no longer has Ted reading your step count by itself.** Ted
  cannot do that until the health-app connection exists, so the thread starts
  where it really starts, with you telling it the number, and Ted does the part
  it can actually do: the arithmetic, the one move, and moving the gym instead of
  deleting it. The section lede was corrected to match.

## Still open

- Not yet shipped. `public/landing-v6.html` is untouched and still live.
- Verified at 1512px and at 390px in a real Chrome, and against the twelve guard
  assertions in `__tests__/landing-page.test.ts`. Not yet checked at tablet
  widths, and not yet seen by anyone but the author.
