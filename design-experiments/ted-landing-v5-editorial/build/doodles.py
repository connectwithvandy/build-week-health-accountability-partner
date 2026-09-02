"""A dense doodle wallpaper in the spirit of WhatsApp's — our own drawings,
   health-and-food weighted, tiled behind every thread."""
import random

# each icon is drawn inside a 24x24 box, stroke only
ICONS = [
 "M12 21c-5-3.5-8-6.5-8-10a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 11c0 3.5-3 6.5-8 10z",      # heart
 "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z",                                # sparkle
 "M5 8h11v7a5.5 5.5 0 0 1-11 0zM16 10h2.5a2.5 2.5 0 0 1 0 5H16M7 5c.8-1.6 2-1.6 2.8 0M12 4c.8-1.6 2-1.6 2.8 0",  # cup
 "M3 8.5A2 2 0 0 1 5 6.5h2l1.2-2h7.6l1.2 2h2a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z M15.4 12.5a3.4 3.4 0 1 1-6.8 0 3.4 3.4 0 0 1 6.8 0",  # camera
 "M20 12a8 8 0 1 1-16 0 8 8 0 0 1 16 0M12 7v5.2l3.4 2",                                      # clock
 "M5 19c0-8 6-13 14-13 0 8-6 13-14 13zM5 19c5-4 8-7 11-11",                                  # leaf
 "M12 3c4 5 6.5 8 6.5 11a6.5 6.5 0 0 1-13 0C5.5 11 8 8 12 3z",                               # drop
 "M6 12h12M4 8v8M8 6v12M16 6v12M20 8v8",                                                     # dumbbell
 "M12 8c-3-2.4-7 0-7 4.6S8 21 10 21c.8 0 1.3-.4 2-.4s1.2.4 2 .4c2 0 5-3.8 5-8.4S15 5.6 12 8zM12 8V5c0-1.6 1.2-2.6 2.8-2.6",  # apple
 "M13 2L5 13h6l-1 9 8-11h-6z",                                                               # bolt
 "M18 14.5A8 8 0 0 1 9.5 6a8 8 0 1 0 8.5 8.5z",                                              # moon
 "M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4",  # sun
 "M4 10h16v10H4zM4 10V8h16v2M12 8v12M12 8c-1.5-3-6-3-6 0M12 8c1.5-3 6-3 6 0",                # gift
 "M10 3h4v3l1.6 2.4V21H8.4V8.4L10 6zM8.4 12h7.2",                                            # bottle
 "M4 20l1-4L16 5l3 3L8 19zM14 7l3 3",                                                        # pencil
 "M4 5h7v15H4zM13 5h7v15h-7zM11.5 5v15",                                                     # book
 "M20.5 12a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0M9 10h.01M15 10h.01M8.5 14c2 2.6 5 2.6 7 0", # smiley
 "M4 12h16c0 4.4-3.6 8-8 8s-8-3.6-8-8zM8 8c1-2 3-2 4 0M14 7c1-2 3-2 4 0",                    # bowl
 "M4 16c2-1 3-3 5-5 1.4-1.4 3 0 3 1.6 0 1.6 2 2.4 4 2.4h4v3H4z",                             # shoe
 "M9 18V6l10-2v12M9 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0M19 16a2 2 0 1 1-4 0 2 2 0 0 1 4 0",       # music
 "M12 3c3 4 6 6 6 10a6 6 0 0 1-12 0c0-2 1-3 2-4 0 2 1 3 2 3-1-3 0-6 2-9z",                   # flame
 "M3 7h18v11H3zM3 7l9 7 9-7",                                                                # envelope
 "M4 6c8 0 14 6 14 14C10 20 4 14 4 6zM7 8c4 1 7 4 8 8",                                      # melon
 "M18 9a6 6 0 1 1-12 0 6 6 0 0 1 12 0M12 15v3l-2 2h4l-2-2",                                  # balloon
 "M4 17c0-6 4-10 8-10s8 4 8 10zM4 17h16",                                                    # taco
 "M6 18C2 14 6 4 14 4c4 4 4 12-4 14zM9 15l6-6M10 11l2 2M12 9l2 2",                           # ball
 "M3 19l6-9 4 5 3-4 5 8z",                                                                   # mountain
 "M4 12l8-7 8 7v8H4zM10 20v-5h4v5",                                                          # house
 "M12 6v12M6 12h12",                                                                         # plus
 "M6 6l12 12M18 6L6 18",                                                                     # cross
 "M5 9h14v9a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2zM8 9V6a4 4 0 0 1 8 0v3M12 13v3",                   # lock
 "M4 18s2-8 8-8 8 8 8 8zM12 10V4M9 6l3-3 3 3",                                               # send-ish
]

def tile(size=420, seed=11):
    """Icons are laid on a jittered grid finer than the icons themselves, so the
       repeat is hard to read at the size the wallpaper is actually shown."""
    rnd = random.Random(seed)
    cell, out = 42, []
    n = size // cell
    order = list(range(n * n))
    rnd.shuffle(order)
    for k, slot in enumerate(order):
        gx, gy = (slot % n) * cell, (slot // n) * cell
        d = ICONS[(k * 7) % len(ICONS)]
        sc = rnd.uniform(.62, 1.15)
        rot = rnd.choice([0, -14, 12, -26, 20, -8, 32, -34])
        x = gx + rnd.uniform(-2, 16)
        y = gy + rnd.uniform(-2, 16)
        out.append('<g transform="translate(%.1f %.1f) rotate(%d 12 12) scale(%.2f)">'
                   '<path d="%s"/></g>' % (x, y, rot, sc, d))
    # the small dots and ticks that fill the gaps in the real pattern
    for _ in range(150):
        x, y = rnd.uniform(2, size - 2), rnd.uniform(2, size - 2)
        r = rnd.choice([1.3, 1.3, 1.8, 2.4])
        out.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="currentColor" stroke="none"/>' % (x, y, r))
    for _ in range(40):
        x, y = rnd.uniform(6, size - 6), rnd.uniform(6, size - 6)
        s = rnd.uniform(3, 5)
        out.append('<path d="M%.1f %.1fv%.1fM%.1f %.1fh%.1f"/>' % (x, y - s, s * 2, x - s, y, s * 2))
    return size, ''.join(out)
