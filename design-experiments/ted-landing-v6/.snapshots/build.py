import base64, re, sys, pathlib
from urllib.parse import quote
import doodles

SC = pathlib.Path('/private/tmp/claude-503/-Users-vandana-agarwal/f0b66fa0-168d-482e-9b4e-08b690eb48d5/scratchpad')
tpl = (SC/'build/page.tpl.html').read_text(encoding='utf-8')

# ── the bubble mark. viewBox is cropped to the artwork (x 4→48, y 2→47) so the
#    svg box edge is the ink edge — that is what fixes the logo's optical gap.
def bubble(cls, style=''):
    return ('<svg class="bubble%s" viewBox="4 2 44 45"%s aria-hidden="true">'
      '<rect x="4" y="2" width="44" height="34" rx="10" fill="#ff7e3e"/>'
      '<path d="M13 34 L7 47 L24 35 Z" fill="#ff7e3e"/>'
      '<g fill="none" stroke="#111317" stroke-width="2.9" stroke-linecap="round">'
      '<path d="M15 16 Q19 9.5 23 16"/><path d="M29 16 Q33 9.5 37 16"/>'
      '<path d="M17 22 Q26 32 35 22"/></g></svg>') % (cls, style)

WM = '<span class="wm"><b>t</b><b>e</b><b>d</b></span>'
LOGO    = '<span class="ted-logo">%s%s</span>' % (bubble(''), WM)
LOGO_SM = '<span class="ted-logo sm">%s%s</span>' % (bubble(''), WM)

# ── WhatsApp chrome ─────────────────────────────────────────────────────────
# Our own doodle wallpaper in the spirit of WhatsApp's — health-shop icons
# rather than a copy of theirs — tiled at very low contrast behind the thread.
DOODLES = (
 'M30 18c6 8 10 13 10 19a10 10 0 0 1-20 0c0-6 4-11 10-19z'                     # drop
 ' M92 30h26M88 24v12M96 22v16M114 22v16M122 24v12'                            # dumbbell
 ' M180 24c-4-6-13-4-13 3 0 6 8 11 13 15 5-4 13-9 13-15 0-7-9-9-13-3z'         # heart
 ' M28 92h30c0 9-7 15-15 15s-15-6-15-15zM36 86c2-4 6-4 8 0M46 84c2-4 6-4 8 0'  # bowl
 ' M104 84h22v14a11 11 0 0 1-22 0zM126 88h6a5 5 0 0 1 0 10h-6'                 # cup
 ' M24 168c0-14 12-24 26-24 0 14-12 24-26 24zM24 168c8-6 14-11 20-19'          # leaf
 ' M112 152v9l6 4'                                                             # clock hands
 ' M46 210c-6-6-14-2-14 7s6 17 11 17c2 0 3-1 5-1s3 1 5 1c5 0 11-8 11-17s-8-13-14-7z'
 ' M46 210v-7c0-4 3-6 7-6'                                                     # apple
 ' M126 206c4 5 6 8 6 12a6 6 0 0 1-12 0c0-4 2-7 6-12z'                         # drop 2
 ' M176 214h20M190 208l6 6-6 6'                                                # arrow
 ' M183 92h.01M193 92h.01M182 100c4 4 8 4 12 0'                                # face
)
WAVE = [26,48,70,38,86,58,96,50,76,34,62,90,42,68,30,54,80,44,60,36,72,40,28,22]

def wallpaper(stroke, opacity):
    size, body = doodles.tile()
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">'
           '<g fill="none" color="%s" stroke="%s" stroke-width="1.5" stroke-linecap="round" '
           'stroke-linejoin="round" opacity="%s">%s</g></svg>'
           ) % (size, size, size, size, stroke, stroke, opacity, body)
    return 'data:image/svg+xml,' + quote(svg, safe="")

GRAIN = ('data:image/svg+xml,' + quote(
    '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">'
    '<filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="4" '
    'stitchTiles="stitch"/></filter>'
    '<rect width="200" height="200" filter="url(#n)"/></svg>', safe=""))

def icon(d, extra=''):
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"%s>%s</svg>') % (extra, d)

I_CHEV   = ('<svg class="chev" viewBox="0 0 10 18" fill="none" stroke="currentColor" stroke-width="2.2" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 1 1.5 9 9 17"/></svg>')
I_VIDEO  = icon('<path d="M15 8.5 21.5 5v14L15 15.5z"/><rect x="2.5" y="5" width="12.5" height="14" rx="2.6"/>')
I_PHONE  = icon('<path d="M21 16.9v2.7a1.8 1.8 0 0 1-2 1.8 17.8 17.8 0 0 1-7.7-2.8 17.5 17.5 0 0 1-5.4-5.4A17.8 17.8 0 0 1 3.1 5.5 1.8 1.8 0 0 1 4.9 3.5h2.7a1.8 1.8 0 0 1 1.8 1.6c.1.9.3 1.7.6 2.5a1.8 1.8 0 0 1-.4 1.9l-1.1 1.1a14.4 14.4 0 0 0 5.4 5.4l1.1-1.1a1.8 1.8 0 0 1 1.9-.4c.8.3 1.6.5 2.5.6a1.8 1.8 0 0 1 1.6 1.8z"/>')
I_PLUS   = icon('<path d="M12 5v14M5 12h14"/>')
I_STICK  = icon('<path d="M20.5 12a8.5 8.5 0 1 0-8.5 8.5c1.2 0 4.2-3 5.9-4.7 1.7-1.7 2.6-2.7 2.6-3.8z"/><path d="M12.5 20.4c0-2.6.7-4.5 2.1-5.8 1.4-1.3 3.3-2 5.8-2"/>')
I_CAM    = icon('<path d="M3 8a2 2 0 0 1 2-2h2.2l1.3-2h6.9l1.3 2H20a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><circle cx="12.5" cy="12.5" r="3.6"/>')
I_MIC    = icon('<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10.5a7 7 0 0 0 14 0M12 17.5V22"/>')

I_SIG = ('<svg viewBox="0 0 20 12" fill="currentColor" aria-hidden="true">'
         '<rect x="0" y="8" width="3" height="4" rx="1"/><rect x="4.6" y="5.5" width="3" height="6.5" rx="1"/>'
         '<rect x="9.2" y="3" width="3" height="9" rx="1"/><rect x="13.8" y="0" width="3" height="12" rx="1"/></svg>')
I_BATT= ('<svg viewBox="0 0 28 13" fill="none" aria-hidden="true">'
         '<rect x="0.6" y="0.6" width="23" height="11.8" rx="3.4" stroke="currentColor" stroke-opacity=".45"/>'
         '<rect x="2.2" y="2.2" width="17" height="8.6" rx="2.2" fill="currentColor"/>'
         '<path d="M25.4 4.4c1.4.4 1.4 3.8 0 4.2z" fill="currentColor" fill-opacity=".45"/></svg>')
I_DOWN= ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
         'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>')

IOSBAR = ('<div class="ios-bar"><b>9:41</b><span class="r">%s<b>5G</b>%s</span></div>') % (I_SIG, I_BATT)

def wabar(avatar):
    return (IOSBAR + '<div class="wa-bar">%s<b class="badge">12</b><span class="ava">%s</span>'
            '<div class="who"><b>Ted</b><span><i class="on"></i>'
            '<i class="wa-status">online</i></span></div>'
            '<span class="wa-acts">%s%s</span></div>') % (I_CHEV, avatar, I_VIDEO, I_PHONE)

WAINPUT = ('<div class="wa-input">%s<div class="field"><span class="txt">Message</span></div>'
           '<span class="acts">%s%s%s</span></div>') % (I_PLUS, I_STICK, I_CAM, I_MIC)

WA = "https://wa.me/918660650986?text=Okay%20Ted%2C%20let's%20do%20this%20%F0%9F%92%AA"

def b64(name):
    return 'data:image/jpeg;base64,' + base64.b64encode((SC/name).read_bytes()).decode()

MEALSRC  = b64('meal_q.jpg')    # the paneer + rajma plate, in the hero thread
MEALSRC2 = b64('meal2_q.jpg')   # a dosa, so the photo never repeats on the page

# ── grounds. one token block restyles the whole page. ────────────────────────
GROUNDS = {
 # No cream anywhere. Cool white ground, near-black bands, orange as the only
 # colour on the page. The grain keeps the white from going sterile.
 'white': """  --paper:#ffffff; --paper-2:#f3f5f7; --white:#ffffff; --line:#e3e6ea;
  --ink:#111317; --ink-2:#494f57; --muted:#868d96; --hair:rgba(17,19,23,.09);
  --stamp:#8a9199; --wa-bar2:#eef1f4; --glow:rgba(255,126,62,.09);
  --deep:#111317; --deep-fg:#f4f6f8; --deep-fg-2:rgba(244,246,248,.72); --deep-line:rgba(244,246,248,.16);
  --panel:#111317; --panel-fg:#f4f6f8; --panel-fg-2:rgba(244,246,248,.72); --panel-fg-3:rgba(244,246,248,.42);
  --wa:#e8ecf0; --me:#d3f0bd; --me-fg:#111317; --shadow:rgba(17,19,23,.13);""",

 # same, one step off pure white so large areas do not glare
 'slate': """  --paper:#f2f4f6; --paper-2:#e8ebef; --white:#ffffff; --line:#dde1e6;
  --ink:#111317; --ink-2:#494f57; --muted:#848b94; --hair:rgba(17,19,23,.09);
  --stamp:#8a9199; --wa-bar2:#e9edf1; --glow:rgba(255,126,62,.10);
  --deep:#111317; --deep-fg:#f4f6f8; --deep-fg-2:rgba(244,246,248,.72); --deep-line:rgba(244,246,248,.16);
  --panel:#111317; --panel-fg:#f4f6f8; --panel-fg-2:rgba(244,246,248,.72); --panel-fg-3:rgba(244,246,248,.42);
  --wa:#e2e7ec; --me:#d3f0bd; --me-fg:#111317; --shadow:rgba(17,19,23,.12);""",
}


WALL = {'white':('#2b3138','.05'), 'slate':('#2b3138','.055')}

def build(pal):
    s = tpl.replace('__GROUND__', GROUNDS[pal])
    s = s.replace('__WAPATTERN__', wallpaper(*WALL[pal]))
    s = s.replace('__WABAR__', wabar(bubble('', ' style="width:24px;height:25px;margin-top:2px"')))
    s = s.replace('__WAINPUT__', WAINPUT)
    s = s.replace('__GRAIN__', GRAIN)
    s = s.replace('__JUMP__', '<span class="jump">%s</span>' % I_DOWN)
    # a plausible voice-note waveform: 34 bars, the played part highlighted
    bars = ''.join('<i class="%s" style="height:%d%%"></i>' % ('on' if k < 9 else '', h)
                   for k, h in enumerate(WAVE))
    s = s.replace('__WAVE__', bars)
    s = s.replace('__MICSM__', I_MIC)
    s = s.replace('__PHOTOSM__',
        '<span class="photo"><img src="%s" alt="A dosa with sambar, coconut chutney and potato masala" '
        'width="760" height="760"></span>' % MEALSRC2)
    s = s.replace('__BUBBLE26__', bubble('', ' style="width:23px;height:24px"'))
    s = s.replace('__LOGO_SM__', LOGO_SM).replace('__LOGO__', LOGO)
    s = s.replace('__WA__', WA)
    s = s.replace('__MEALSRC__', MEALSRC)
    assert '__' not in s.replace('_next',''), [t for t in re.findall(r'__\w+__', s)]
    return s

for name in GROUNDS:
    out = SC/'build'/('preview-%s.html' % name)
    out.write_text(build(name), encoding='utf-8')
    print(name, len(out.read_bytes()), 'bytes')
