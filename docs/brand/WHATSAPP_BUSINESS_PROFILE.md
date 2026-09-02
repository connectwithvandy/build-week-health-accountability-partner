# Ted WhatsApp Business profile

Rewritten for the v6 landing page (`public/landing-v6.html`). The previous
version of this file was written for the aubergine-and-coral site that v6
replaces, and its images used that palette; they are gone from git history's
tip, recoverable from an earlier commit if that design ever comes back.

Everything here is set by hand in the WhatsApp Business app
(**Settings -> Business tools -> Business profile**). Nothing in this repo can
change it for you: Hermes bridges messages, it does not manage the account
profile.

Two directions per field. **A** is Ted's own voice from `hermes/SOUL.md` —
lowercase, warm, a little Hinglish. **B** is the landing page's register. Pick a
column and stay in it; mixing the two is what makes a profile read as
committee-written.

Counts are checked against WhatsApp's real limits — over them, the app truncates
silently, usually mid-sentence.

## Business name — 25 characters

| | Copy | Count |
|---|---|---|
| **A** | `Ted` | 3 |
| **B** | `Ted · your day remembered` | 25 |

A is the better answer. The name sits beside every message in a chat list, where
a tagline is noise, and "Ted" is what testers already call it.

## Category

**Health & wellness.** The old file said "Other", which tells a new tester
nothing. There is no "habit coach" category; this is the closest honest fit.

## About — 139 characters

**A** — 134 characters

```
tell me what you ate and did. i'll remember it and send one useful move before the day's gone. 18+ · a habit coach, not medical advice
```

**B** — 127 characters

```
Health accountability that lives in WhatsApp. Your day, remembered. Free during beta · 18+ · A habit coach, not medical advice.
```

Both carry 18+ and not-medical-advice, because About is the one piece of copy a
tester reads *before* they send anything.

## Business description — 512 characters

**A** — 507 characters

```
hi, i'm Ted. your meals are in one app, water is an alarm, steps are somewhere else, and the gym bag is a guilt object by the door. tell me what you ate and did — text, a voice note, or a photo of the plate — and i'll keep the whole thread in the chat you already open forty times a day.

one useful move while the day can still be turned around, and an honest close at night. no dashboard, no streak to protect.

18+. a habit coach, not medical advice, never for emergencies. say "delete my data" any time.
```

**B** — 511 characters

```
Ted is health accountability that lives in WhatsApp. Tell it what you ate and did — in text, a voice note, or a photo of the plate — and it remembers your meals, water, steps, workouts and your own commitments.

Then it sends one useful thing you can still do today, and an honest close at night. Nothing to download. It starts in your chat.

Free during private beta. Adults 18+. A habit coach, not medical advice, and not for emergencies, diagnosis or treatment. Message "delete my data" to remove everything.
```

## Greeting message — 200 characters

Auto-sent to a first-time messager. The landing page's button sends
`Okay Ted, let's do this 💪`, so this is literally the first thing a tester reads
back.

**A** — 157 characters

```
hey! i'm Ted 👋 tell me what you ate or did today — type it, send a voice note, or just photograph the plate. i'll remember it. first, what should i call you?
```

**B** — 177 characters

```
Hi, I'm Ted. I remember your meals, movement, water and commitments, then send one useful nudge a day. Text, voice note or a photo of the plate all work. What should I call you?
```

**Check before switching this on.** If Hermes already answers the first message,
WhatsApp's greeting fires alongside it and the tester gets two hellos.

## Away message — 200 characters

Worth setting: Hermes runs on a laptop, so Ted genuinely is offline sometimes,
and silence from a health coach reads as being ignored.

**A** — 92 characters

```
i'm quiet right now, but nothing's lost — send it anyway and i'll pick it up when i'm back 🤬
```

**B** — 89 characters

```
Ted is offline for a moment. Send your update anyway; it will be logged when Ted is back.
```

## Website

`https://heyted.vercel.app` — the share URL. The other hostname,
`whatsapp-accountability-partner-ted.vercel.app`, serves the same deployment.

## Address and email

Leave both empty. Ted has no premises, and a home address on a public business
profile is a bad trade. The email waits for a real monitored address — the same
reason the privacy page still has no contact address.

## Images

Rendered from the v6 design tokens. Sources are in `docs/brand/src/`; each is an
HTML file screenshotted by headless Chrome at the exact pixel size, so a copy
change is an edit and a re-render, not a redraw.

| File | Size | Where it goes |
|---|---|---|
| `public/brand/ted-profile-picture.png` | 1024x1024 | **Profile picture.** Orange ground, ink face. Cropped to a circle it still reads at 48px in a chat list. |
| `public/brand/ted-profile-picture-bubble.png` | 1024x1024 | Alternative: the site's exact logo mark on paper. Truer to the page, weaker as a thumbnail. |
| `public/brand/ted-business-cover.png` | 1125x750 | **Cover photo** for the Business profile. |
| `public/brand/ted-business-cover-orange.png` | 1125x750 | Alternative cover, orange ground. |
| `public/brand/ted-whatsapp-cover.png` | 1600x900 | Link preview when the site is shared. Wired into the page's `og:image`. |
| `public/brand/ted-whatsapp-cover-orange.png` | 1600x900 | Alternative link preview. |

They live under `public/` rather than here so the same file serves the link
preview and can be opened on a phone at `https://heyted.vercel.app/brand/<name>`
— which is how you get them onto the device that sets the profile.

### Re-rendering

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
  --virtual-time-budget=8000 --window-size=1600,900 \
  --screenshot=out.png "file://$PWD/docs/brand/src/cover-1600x900.html"
magick out.png -strip -colors 128 public/brand/ted-whatsapp-cover.png
```

Headless Chrome clamps its window to a 500px minimum width, so anything narrower
has to be rendered inside an iframe of the target width.
