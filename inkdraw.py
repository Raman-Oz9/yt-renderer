"""Procedural "ink" doodle drawing: bold black stick figure + icon props (reference style).

Used only by stickman.py. Everything is drawn in code, so it is fast, free and always on-style.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

INK = (18, 18, 22)
YELLOW = (255, 205, 40)
YEL_L = (255, 238, 170)
GREY = (200, 202, 208)
BLUE = (96, 168, 235)
RED = (232, 78, 70)
GREEN = (96, 190, 120)
WHITE = (255, 255, 255)
_FONT = str(Path(__file__).with_name("fonts") / "Anton.ttf")


def font(size):
    try:
        return ImageFont.truetype(_FONT, size)
    except Exception:
        return ImageFont.load_default()


def _ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------------------ figure
POSES = {
    "idle":     dict(lean=0,  head=0,  la1=-14,  la2=-8,   ra1=14,  ra2=8,   ll1=-8,  ll2=-8,  rl1=8,  rl2=8),
    "point":    dict(lean=4,  head=6,  la1=-14,  la2=-8,   ra1=78,  ra2=84,  ll1=-8,  ll2=-8,  rl1=8,  rl2=8),
    "surprise": dict(lean=-6, head=-4, la1=-140, la2=-160, ra1=140, ra2=160, ll1=-14, ll2=-14, rl1=14, rl2=14),
    "think":    dict(lean=3,  head=8,  la1=-14,  la2=-8,   ra1=30,  ra2=150, ll1=-8,  ll2=-8,  rl1=8,  rl2=8),
    "wave":     dict(lean=0,  head=4,  la1=-14,  la2=-8,   ra1=120, ra2=160, ll1=-8,  ll2=-8,  rl1=8,  rl2=8),
    "run":      dict(lean=16, head=6,  la1=-60,  la2=-115, ra1=55,  ra2=105, ll1=-42, ll2=-8,  rl1=38, rl2=75),
    "cheer":    dict(lean=-4, head=-6, la1=-150, la2=-165, ra1=150, ra2=165, ll1=-18, ll2=-18, rl1=18, rl2=18),
    "shrug":    dict(lean=0,  head=10, la1=-58,  la2=-112, ra1=58,  ra2=112, ll1=-8,  ll2=-8,  rl1=8,  rl2=8),
    "fear":     dict(lean=-10, head=-6, la1=-38, la2=-150, ra1=38,  ra2=150, ll1=-12, ll2=-16, rl1=16, rl2=20),
}
POSE_KEYS = list(POSES)
MOODS = {"happy": 1, "neutral": 0, "shocked": 2, "sad": -1}
FX_FOR_POSE = {"surprise": "burst", "fear": "burst", "cheer": "spark", "think": "q", "wave": "spark", "run": "burst"}


def mix(a, b, t):
    t = _ease(t)
    return {k: a[k] + (b[k] - a[k]) * t for k in a}


def draw_figure(pose, mood, height_px, flip, phase, fx, fxt):
    """Bold solid-black stickman (thick limbs, round white head, small face). Returns (RGBA, feet_y)."""
    scale = height_px / 400.0
    S = 2
    side = int(540 * scale)
    W = H = side * S
    u = scale * S
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bob = math.sin(phase * 2 * math.pi) * 5 * u
    hip = (W / 2, 305 * u + bob)
    lean = math.radians(pose["lean"])
    neck = (hip[0] + math.sin(lean) * 98 * u, hip[1] - math.cos(lean) * 98 * u)

    def limb(p, a1, a2, l1, l2):
        r1, r2 = math.radians(a1), math.radians(a2)
        m = (p[0] + math.sin(r1) * l1, p[1] + math.cos(r1) * l1)
        return m, (m[0] + math.sin(r2) * l2, m[1] + math.cos(r2) * l2)

    def bold(pts, width):
        d.line(pts, fill=INK, width=int(width), joint="curve")
        for p in pts:
            d.ellipse([p[0] - width / 2, p[1] - width / 2, p[0] + width / 2, p[1] + width / 2], fill=INK)

    # legs + shoes
    for a1, a2 in ((pose["ll1"], pose["ll2"]), (pose["rl1"], pose["rl2"])):
        m, e = limb(hip, a1, a2, 68 * u, 68 * u)
        bold([hip, m, e], 31 * u)
        d.ellipse([e[0] - 14 * u, e[1] - 14 * u, e[0] + 40 * u, e[1] + 16 * u], fill=INK)
    # torso: solid, a bit wider at the shoulders
    d.polygon([(neck[0] - 25 * u, neck[1] + 6 * u), (neck[0] + 25 * u, neck[1] + 6 * u),
               (hip[0] + 19 * u, hip[1] + 6 * u), (hip[0] - 19 * u, hip[1] + 6 * u)], fill=INK)
    d.ellipse([neck[0] - 25 * u, neck[1] - 14 * u, neck[0] + 25 * u, neck[1] + 26 * u], fill=INK)
    d.ellipse([hip[0] - 19 * u, hip[1] - 12 * u, hip[0] + 19 * u, hip[1] + 18 * u], fill=INK)
    # arms + fists
    for a1, a2 in ((pose["la1"], pose["la2"]), (pose["ra1"], pose["ra2"])):
        sh = (neck[0], neck[1] + 14 * u)
        m, e = limb(sh, a1, a2, 58 * u, 54 * u)
        bold([sh, m, e], 27 * u)
        d.ellipse([e[0] - 19 * u, e[1] - 19 * u, e[0] + 19 * u, e[1] + 19 * u], fill=INK)
    # head
    hr = 62 * u
    hc = (neck[0] + math.sin(math.radians(pose["head"])) * 20 * u, neck[1] - hr - 2 * u)
    d.ellipse([hc[0] - hr, hc[1] - hr, hc[0] + hr, hc[1] + hr], fill=WHITE, outline=INK, width=int(9 * u))
    ex, ey = hr * 0.40, hc[1] - hr * 0.08
    er = 6 * u
    for sx in (-1, 1):
        x = hc[0] + sx * ex
        r_ = er * (1.5 if mood == 2 else 1.0)
        d.ellipse([x - r_, ey - r_, x + r_, ey + r_], fill=INK)
        by = ey - hr * (0.42 if mood == 2 else 0.32)
        bw_ = hr * 0.30
        if mood == -1:
            d.line([(x - bw_, by + 6 * u * sx), (x + bw_, by - 6 * u * sx)], fill=INK, width=int(4 * u))
        elif mood == 1:
            d.arc([x - bw_, by - bw_ * 0.6, x + bw_, by + bw_ * 0.6], 200, 340, fill=INK, width=int(4 * u))
        elif mood == 2:
            d.arc([x - bw_, by - bw_ * 0.2, x + bw_, by + bw_], 200, 340, fill=INK, width=int(4 * u))
    my, mw, mlw = hc[1] + hr * 0.46, hr * 0.46, int(5 * u)
    if mood == 1:
        d.arc([hc[0] - mw, my - mw * .9, hc[0] + mw, my + mw * .7], 15, 165, fill=INK, width=mlw)
    elif mood == -1:
        d.arc([hc[0] - mw, my - mw * .1, hc[0] + mw, my + mw * 1.2], 195, 345, fill=INK, width=mlw)
    elif mood == 2:
        d.ellipse([hc[0] - mw * .42, my - mw * .5, hc[0] + mw * .42, my + mw * .6], fill=INK)
    else:
        d.line([hc[0] - mw * .55, my, hc[0] + mw * .55, my], fill=INK, width=mlw)
    if flip:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
        hc = (W - hc[0], hc[1])
    d = ImageDraw.Draw(img)
    if fx == "burst" and fxt < 1.6:
        k = _ease(fxt / 0.25) * (1 - _ease((fxt - 1.1) / 0.5))
        for ang in (-160, -130, -100, -70, -40, -10):
            r0, r1 = hr * 1.45, hr * (1.45 + 0.6 * k)
            a = math.radians(ang)
            d.line([(hc[0] + math.cos(a) * r0, hc[1] + math.sin(a) * r0),
                    (hc[0] + math.cos(a) * r1, hc[1] + math.sin(a) * r1)], fill=INK, width=max(3, int(6 * u)))
    elif fx == "spark":
        for j, (ox, oy, sz) in enumerate(((-1.8, -1.0, 0.34), (1.8, -0.7, 0.26), (1.2, -1.8, 0.2))):
            s_ = hr * sz * (0.7 + 0.3 * math.sin(phase * 2 * math.pi + j * 2))
            cx, cy = hc[0] + ox * hr, hc[1] + oy * hr
            d.polygon([(cx, cy - s_ * 1.6), (cx + s_ * .4, cy - s_ * .4), (cx + s_ * 1.6, cy), (cx + s_ * .4, cy + s_ * .4),
                       (cx, cy + s_ * 1.6), (cx - s_ * .4, cy + s_ * .4), (cx - s_ * 1.6, cy), (cx - s_ * .4, cy - s_ * .4)],
                      fill=YELLOW, outline=INK, width=max(2, int(3 * u)))
    elif fx == "q":
        f = font(int(hr * 1.6))
        bounce = math.sin(phase * 2 * math.pi) * hr * 0.08
        d.text((hc[0] + hr * 1.0, hc[1] - hr * 2.4 + bounce), "?", font=f, fill=YELLOW, stroke_width=max(3, int(4 * u)),
               stroke_fill=INK)
    img = img.resize((side, side), Image.LANCZOS)
    return img, int(452 * scale)


# ------------------------------------------------------------------------------ icons
def _ow(u):
    return max(3, int(3.4 * u))


def _bulb(d, u):
    ow = _ow(u)
    for k in range(7):
        a = math.radians(-160 + k * 23.3)
        d.line([(50 * u + math.cos(a) * 34 * u, 40 * u + math.sin(a) * 34 * u),
                (50 * u + math.cos(a) * 44 * u, 40 * u + math.sin(a) * 44 * u)], fill=INK, width=ow)
    d.polygon([(40 * u, 60 * u), (60 * u, 60 * u), (57 * u, 74 * u), (43 * u, 74 * u)], fill=GREY, outline=INK, width=ow)
    d.rounded_rectangle([42 * u, 74 * u, 58 * u, 83 * u], int(3 * u), fill=GREY, outline=INK, width=ow)
    d.ellipse([26 * u, 16 * u, 74 * u, 64 * u], fill=YELLOW, outline=INK, width=ow)
    d.line([(44 * u, 60 * u), (44 * u, 46 * u), (50 * u, 38 * u), (56 * u, 46 * u), (56 * u, 60 * u)], fill=INK, width=int(2.4 * u))


def _star(d, u):
    pts = []
    for k in range(10):
        r = 44 * u if k % 2 == 0 else 19 * u
        a = math.radians(-90 + k * 36)
        pts.append((50 * u + math.cos(a) * r, 54 * u + math.sin(a) * r))
    d.polygon(pts, fill=YELLOW, outline=INK, width=_ow(u))


def _text_icon(ch):
    def f(d, u):
        ft = font(int(104 * u))
        d.text((50 * u, 54 * u), ch, font=ft, fill=YELLOW, anchor="mm", stroke_width=int(5 * u), stroke_fill=INK)
    return f


def _clock(d, u):
    ow = _ow(u)
    d.ellipse([22 * u, 6 * u, 40 * u, 24 * u], fill=YELLOW, outline=INK, width=ow)
    d.ellipse([60 * u, 6 * u, 78 * u, 24 * u], fill=YELLOW, outline=INK, width=ow)
    d.ellipse([12 * u, 14 * u, 88 * u, 90 * u], fill=(255, 247, 214), outline=INK, width=int(4.5 * u))
    for k in range(12):
        a = math.radians(k * 30)
        d.line([(50 * u + math.sin(a) * 31 * u, 52 * u - math.cos(a) * 31 * u),
                (50 * u + math.sin(a) * 36 * u, 52 * u - math.cos(a) * 36 * u)], fill=INK, width=int(2.4 * u))
    d.line([(50 * u, 52 * u), (50 * u, 30 * u)], fill=INK, width=int(4 * u))
    d.line([(50 * u, 52 * u), (66 * u, 60 * u)], fill=INK, width=int(4 * u))
    d.ellipse([46 * u, 48 * u, 54 * u, 56 * u], fill=INK)


def _magnifier(d, u):
    ow = _ow(u)
    d.line([(64 * u, 64 * u), (90 * u, 90 * u)], fill=INK, width=int(11 * u))
    d.ellipse([10 * u, 10 * u, 72 * u, 72 * u], fill=(214, 238, 255), outline=INK, width=int(5 * u))
    d.arc([20 * u, 20 * u, 62 * u, 62 * u], 200, 260, fill=WHITE, width=int(4 * u))


def _megaphone(d, u):
    ow = _ow(u)
    d.polygon([(26 * u, 38 * u), (70 * u, 16 * u), (70 * u, 84 * u), (26 * u, 62 * u)], fill=YELLOW, outline=INK, width=ow)
    d.rounded_rectangle([10 * u, 36 * u, 30 * u, 64 * u], int(5 * u), fill=GREY, outline=INK, width=ow)
    d.ellipse([62 * u, 14 * u, 80 * u, 86 * u], fill=(255, 226, 120), outline=INK, width=ow)
    d.rounded_rectangle([30 * u, 62 * u, 44 * u, 84 * u], int(4 * u), fill=INK)
    for k, a in enumerate((-22, 0, 22)):
        r = math.radians(a)
        d.line([(86 * u + math.cos(r) * 2 * u, 50 * u + math.sin(r) * 2 * u),
                (86 * u + math.cos(r) * 11 * u, 50 * u + math.sin(r) * 18 * u)], fill=INK, width=ow)


def _book(d, u):
    ow = _ow(u)
    d.polygon([(4 * u, 30 * u), (50 * u, 42 * u), (96 * u, 30 * u), (96 * u, 86 * u), (50 * u, 94 * u), (4 * u, 86 * u)],
              fill=YELLOW, outline=INK, width=ow)
    d.polygon([(10 * u, 26 * u), (49 * u, 38 * u), (49 * u, 84 * u), (10 * u, 74 * u)], fill=WHITE, outline=INK, width=ow)
    d.polygon([(90 * u, 26 * u), (51 * u, 38 * u), (51 * u, 84 * u), (90 * u, 74 * u)], fill=WHITE, outline=INK, width=ow)
    for k in range(4):
        y = 44 + k * 8
        d.line([(16 * u, (y - 8) * u), (43 * u, (y - 2) * u)], fill=GREY, width=int(2.4 * u))
        d.line([(84 * u, (y - 8) * u), (57 * u, (y - 2) * u)], fill=GREY, width=int(2.4 * u))


def _money(d, u):
    ow = _ow(u)
    d.ellipse([10 * u, 10 * u, 90 * u, 90 * u], fill=YELLOW, outline=INK, width=int(4.5 * u))
    d.ellipse([22 * u, 22 * u, 78 * u, 78 * u], outline=INK, width=int(2.4 * u))
    d.text((50 * u, 52 * u), "$", font=font(int(70 * u)), fill=INK, anchor="mm")


def _heart(d, u):
    pts = []
    for k in range(0, 360, 6):
        t = math.radians(k)
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append((50 * u + x * 2.7 * u, 46 * u + y * 2.7 * u))
    d.polygon(pts, fill=RED, outline=INK, width=_ow(u))
    d.arc([30 * u, 28 * u, 46 * u, 44 * u], 200, 260, fill=WHITE, width=int(3 * u))


def _check(d, u):
    d.line([(14 * u, 54 * u), (38 * u, 78 * u), (88 * u, 22 * u)], fill=INK, width=int(18 * u), joint="curve")
    d.line([(14 * u, 54 * u), (38 * u, 78 * u), (88 * u, 22 * u)], fill=GREEN, width=int(10 * u), joint="curve")


def _cross(d, u):
    d.line([(20 * u, 20 * u), (80 * u, 80 * u)], fill=INK, width=int(18 * u))
    d.line([(80 * u, 20 * u), (20 * u, 80 * u)], fill=INK, width=int(18 * u))
    d.line([(20 * u, 20 * u), (80 * u, 80 * u)], fill=RED, width=int(10 * u))
    d.line([(80 * u, 20 * u), (20 * u, 80 * u)], fill=RED, width=int(10 * u))


def _wave(d, u):
    ow = _ow(u)
    for j, (yb, col) in enumerate(((52, (140, 195, 245)), (68, BLUE))):
        pts = [(4 * u, 92 * u)]
        for x in range(4, 97, 3):
            pts.append((x * u, (yb + math.sin((x / 96 * 2 + j * 0.4) * math.pi * 2) * 7) * u))
        pts.append((96 * u, 92 * u))
        d.polygon(pts, fill=col, outline=INK, width=ow)
    d.arc([20 * u, 22 * u, 60 * u, 62 * u], 180, 330, fill=INK, width=ow)


def _drop(d, u):
    d.polygon([(50 * u, 6 * u), (74 * u, 48 * u), (78 * u, 62 * u), (72 * u, 76 * u), (60 * u, 88 * u), (40 * u, 88 * u),
               (28 * u, 76 * u), (22 * u, 62 * u), (26 * u, 48 * u)], fill=BLUE, outline=INK, width=_ow(u))
    d.arc([34 * u, 52 * u, 50 * u, 74 * u], 120, 200, fill=WHITE, width=int(3.4 * u))


def _fire(d, u):
    ow = _ow(u)
    d.polygon([(50 * u, 4 * u), (66 * u, 30 * u), (84 * u, 52 * u), (80 * u, 76 * u), (62 * u, 92 * u), (38 * u, 92 * u),
               (20 * u, 76 * u), (16 * u, 54 * u), (30 * u, 40 * u), (34 * u, 22 * u), (44 * u, 32 * u)],
              fill=RED, outline=INK, width=ow)
    d.polygon([(50 * u, 40 * u), (64 * u, 62 * u), (60 * u, 82 * u), (50 * u, 90 * u), (40 * u, 82 * u), (36 * u, 62 * u)],
              fill=YELLOW, outline=INK, width=int(2.6 * u))


def _sun(d, u):
    ow = _ow(u)
    for k in range(12):
        a = math.radians(k * 30)
        d.line([(50 * u + math.cos(a) * 34 * u, 50 * u + math.sin(a) * 34 * u),
                (50 * u + math.cos(a) * 46 * u, 50 * u + math.sin(a) * 46 * u)], fill=INK, width=int(4 * u))
    d.ellipse([22 * u, 22 * u, 78 * u, 78 * u], fill=YELLOW, outline=INK, width=int(4.5 * u))


def _cloud(d, u):
    ow = int(4 * u)
    cs = [(30, 58, 20), (50, 46, 26), (72, 58, 20), (50, 64, 22)]
    for cx, cy, r in cs:
        d.ellipse([(cx - r) * u - ow, (cy - r) * u - ow, (cx + r) * u + ow, (cy + r) * u + ow], fill=INK)
    for cx, cy, r in cs:
        d.ellipse([(cx - r) * u, (cy - r) * u, (cx + r) * u, (cy + r) * u], fill=WHITE)


def _mountain(d, u):
    ow = _ow(u)
    d.polygon([(46 * u, 86 * u), (74 * u, 38 * u), (98 * u, 86 * u)], fill=(120, 126, 146), outline=INK, width=ow)
    d.polygon([(2 * u, 86 * u), (36 * u, 20 * u), (70 * u, 86 * u)], fill=(156, 162, 180), outline=INK, width=ow)
    d.polygon([(28 * u, 36 * u), (36 * u, 20 * u), (44 * u, 36 * u), (38 * u, 33 * u), (34 * u, 38 * u)], fill=WHITE, outline=INK, width=int(2.4 * u))


def _tree(d, u):
    ow = _ow(u)
    d.rounded_rectangle([44 * u, 56 * u, 58 * u, 92 * u], int(3 * u), fill=(150, 106, 64), outline=INK, width=ow)
    for cx, cy, r in ((50, 30, 24), (30, 48, 18), (70, 48, 18)):
        d.ellipse([(cx - r) * u, (cy - r) * u, (cx + r) * u, (cy + r) * u], fill=GREEN, outline=INK, width=ow)


def _fish(d, u):
    ow = _ow(u)
    d.polygon([(70 * u, 50 * u), (96 * u, 28 * u), (92 * u, 50 * u), (96 * u, 72 * u)], fill=BLUE, outline=INK, width=ow)
    d.polygon([(40 * u, 28 * u), (54 * u, 14 * u), (58 * u, 32 * u)], fill=BLUE, outline=INK, width=ow)
    d.ellipse([6 * u, 28 * u, 78 * u, 72 * u], fill=(140, 195, 245), outline=INK, width=ow)
    d.ellipse([18 * u, 40 * u, 28 * u, 50 * u], fill=INK)
    d.arc([42 * u, 36 * u, 64 * u, 66 * u], 100, 260, fill=INK, width=int(2.4 * u))


def _warning(d, u):
    d.polygon([(50 * u, 6 * u), (96 * u, 86 * u), (4 * u, 86 * u)], fill=YELLOW, outline=INK, width=int(4.5 * u))
    d.text((50 * u, 62 * u), "!", font=font(int(58 * u)), fill=INK, anchor="mm")


def _lock(d, u):
    ow = _ow(u)
    d.arc([26 * u, 6 * u, 74 * u, 66 * u], 180, 360, fill=INK, width=int(9 * u))
    d.line([(28 * u, 36 * u), (28 * u, 50 * u)], fill=INK, width=int(9 * u))
    d.line([(72 * u, 36 * u), (72 * u, 50 * u)], fill=INK, width=int(9 * u))
    d.rounded_rectangle([16 * u, 44 * u, 84 * u, 92 * u], int(8 * u), fill=YELLOW, outline=INK, width=ow)
    d.ellipse([44 * u, 58 * u, 56 * u, 70 * u], fill=INK)
    d.rectangle([48 * u, 66 * u, 52 * u, 80 * u], fill=INK)


def _rocket(d, u):
    ow = _ow(u)
    d.polygon([(38 * u, 76 * u), (50 * u, 98 * u), (62 * u, 76 * u)], fill=YELLOW, outline=INK, width=ow)
    d.polygon([(30 * u, 50 * u), (10 * u, 82 * u), (36 * u, 74 * u)], fill=RED, outline=INK, width=ow)
    d.polygon([(70 * u, 50 * u), (90 * u, 82 * u), (64 * u, 74 * u)], fill=RED, outline=INK, width=ow)
    d.polygon([(50 * u, 2 * u), (68 * u, 30 * u), (66 * u, 80 * u), (34 * u, 80 * u), (32 * u, 30 * u)], fill=WHITE, outline=INK, width=ow)
    d.ellipse([40 * u, 34 * u, 60 * u, 54 * u], fill=(214, 238, 255), outline=INK, width=ow)


def _trophy(d, u):
    ow = _ow(u)
    d.arc([6 * u, 12 * u, 36 * u, 50 * u], 90, 270, fill=INK, width=int(6 * u))
    d.arc([64 * u, 12 * u, 94 * u, 50 * u], 270, 450, fill=INK, width=int(6 * u))
    d.polygon([(22 * u, 10 * u), (78 * u, 10 * u), (72 * u, 50 * u), (60 * u, 64 * u), (40 * u, 64 * u), (28 * u, 50 * u)],
              fill=YELLOW, outline=INK, width=ow)
    d.rectangle([45 * u, 62 * u, 55 * u, 78 * u], fill=YELLOW, outline=INK, width=ow)
    d.rounded_rectangle([30 * u, 78 * u, 70 * u, 92 * u], int(3 * u), fill=YELLOW, outline=INK, width=ow)


def _globe(d, u):
    ow = _ow(u)
    d.ellipse([8 * u, 8 * u, 92 * u, 92 * u], fill=(150, 205, 250), outline=INK, width=int(4.5 * u))
    d.polygon([(26 * u, 30 * u), (44 * u, 24 * u), (50 * u, 40 * u), (36 * u, 54 * u), (24 * u, 46 * u)], fill=GREEN, outline=INK, width=int(2.4 * u))
    d.polygon([(58 * u, 52 * u), (78 * u, 46 * u), (80 * u, 66 * u), (66 * u, 78 * u), (56 * u, 68 * u)], fill=GREEN, outline=INK, width=int(2.4 * u))
    d.arc([8 * u, 8 * u, 92 * u, 92 * u], 60, 120, fill=WHITE, width=int(3 * u))


def _chart(d, u):
    ow = _ow(u)
    d.line([(8 * u, 8 * u), (8 * u, 90 * u), (94 * u, 90 * u)], fill=INK, width=int(5 * u))
    for k, hgt in enumerate((26, 44, 64)):
        x = 20 + k * 24
        d.rectangle([x * u, (88 - hgt) * u, (x + 17) * u, 88 * u], fill=YELLOW, outline=INK, width=ow)
    d.line([(14 * u, 56 * u), (44 * u, 38 * u), (62 * u, 46 * u), (90 * u, 14 * u)], fill=RED, width=int(5 * u), joint="curve")
    d.polygon([(94 * u, 8 * u), (78 * u, 14 * u), (90 * u, 28 * u)], fill=RED)


def _gear(d, u):
    ow = _ow(u)
    pts = []
    for k in range(24):
        a = math.radians(k * 15)
        r = 44 * u if (k // 1) % 3 != 2 else 36 * u
        r = 44 * u if k % 3 == 0 or k % 3 == 1 else 34 * u
        pts.append((50 * u + math.cos(a) * r, 50 * u + math.sin(a) * r))
    d.polygon(pts, fill=GREY, outline=INK, width=ow)
    d.ellipse([32 * u, 32 * u, 68 * u, 68 * u], fill=WHITE, outline=INK, width=ow)


def _house(d, u):
    ow = _ow(u)
    d.rectangle([16 * u, 44 * u, 84 * u, 90 * u], fill=WHITE, outline=INK, width=ow)
    d.polygon([(6 * u, 48 * u), (50 * u, 8 * u), (94 * u, 48 * u)], fill=RED, outline=INK, width=ow)
    d.rectangle([42 * u, 62 * u, 58 * u, 90 * u], fill=YELLOW, outline=INK, width=ow)
    d.rectangle([22 * u, 54 * u, 36 * u, 68 * u], fill=(214, 238, 255), outline=INK, width=int(2.4 * u))


def _flask(d, u):
    ow = _ow(u)
    d.polygon([(40 * u, 8 * u), (60 * u, 8 * u), (60 * u, 38 * u), (90 * u, 86 * u), (10 * u, 86 * u), (40 * u, 38 * u)],
              fill=(235, 246, 255), outline=INK, width=ow)
    d.polygon([(30 * u, 58 * u), (70 * u, 58 * u), (90 * u, 86 * u), (10 * u, 86 * u)], fill=GREEN, outline=INK, width=ow)
    d.rectangle([36 * u, 4 * u, 64 * u, 12 * u], fill=GREY, outline=INK, width=int(2.6 * u))
    for cx, cy, r in ((44, 70, 4), (58, 76, 3), (52, 64, 3)):
        d.ellipse([(cx - r) * u, (cy - r) * u, (cx + r) * u, (cy + r) * u], fill=WHITE, outline=INK, width=int(1.8 * u))


def _bubble(d, u):
    ow = _ow(u)
    d.polygon([(26 * u, 70 * u), (22 * u, 94 * u), (50 * u, 74 * u)], fill=WHITE, outline=INK, width=ow)
    d.rounded_rectangle([6 * u, 10 * u, 94 * u, 76 * u], int(20 * u), fill=WHITE, outline=INK, width=ow)
    d.polygon([(27 * u, 66 * u), (24 * u, 84 * u), (46 * u, 70 * u)], fill=WHITE)
    for cx in (30, 50, 70):
        d.ellipse([(cx - 6) * u, 36 * u, (cx + 6) * u, 48 * u], fill=INK)


def _skull(d, u):
    ow = _ow(u)
    d.ellipse([16 * u, 8 * u, 84 * u, 70 * u], fill=WHITE, outline=INK, width=ow)
    d.rounded_rectangle([30 * u, 56 * u, 70 * u, 90 * u], int(6 * u), fill=WHITE, outline=INK, width=ow)
    d.ellipse([28 * u, 32 * u, 46 * u, 52 * u], fill=INK)
    d.ellipse([54 * u, 32 * u, 72 * u, 52 * u], fill=INK)
    d.polygon([(50 * u, 52 * u), (45 * u, 62 * u), (55 * u, 62 * u)], fill=INK)
    for x in (40, 50, 60):
        d.line([(x * u, 72 * u), (x * u, 88 * u)], fill=INK, width=int(2.6 * u))


def _eye(d, u):
    ow = _ow(u)
    d.polygon([(4 * u, 50 * u), (24 * u, 28 * u), (50 * u, 20 * u), (76 * u, 28 * u), (96 * u, 50 * u), (76 * u, 72 * u),
               (50 * u, 80 * u), (24 * u, 72 * u)], fill=WHITE, outline=INK, width=ow)
    d.ellipse([32 * u, 26 * u, 68 * u, 74 * u], fill=BLUE, outline=INK, width=ow)
    d.ellipse([42 * u, 38 * u, 58 * u, 62 * u], fill=INK)
    d.ellipse([46 * u, 40 * u, 52 * u, 46 * u], fill=WHITE)


def _key(d, u):
    ow = _ow(u)
    d.line([(46 * u, 50 * u), (92 * u, 50 * u)], fill=INK, width=int(13 * u))
    d.line([(46 * u, 50 * u), (92 * u, 50 * u)], fill=YELLOW, width=int(7 * u))
    d.rectangle([74 * u, 50 * u, 82 * u, 68 * u], fill=YELLOW, outline=INK, width=int(3 * u))
    d.rectangle([86 * u, 50 * u, 94 * u, 64 * u], fill=YELLOW, outline=INK, width=int(3 * u))
    d.ellipse([6 * u, 28 * u, 56 * u, 72 * u], fill=YELLOW, outline=INK, width=int(4.5 * u))
    d.ellipse([20 * u, 42 * u, 36 * u, 58 * u], fill=WHITE, outline=INK, width=ow)


ICONS = {
    "bulb": _bulb, "star": _star, "question": _text_icon("?"), "exclamation": _text_icon("!"), "clock": _clock,
    "magnifier": _magnifier, "megaphone": _megaphone, "book": _book, "money": _money, "heart": _heart,
    "check": _check, "cross": _cross, "wave": _wave, "drop": _drop, "fire": _fire, "sun": _sun, "cloud": _cloud,
    "mountain": _mountain, "tree": _tree, "fish": _fish, "warning": _warning, "lock": _lock, "rocket": _rocket,
    "trophy": _trophy, "globe": _globe, "chart": _chart, "gear": _gear, "house": _house, "flask": _flask,
    "bubble": _bubble, "skull": _skull, "eye": _eye, "key": _key,
}
ICON_NAMES = list(ICONS)

KEYWORDS = [
    ("wave", "ocean sea water lake river wave flood tide underwater swim shore beach pool"),
    ("flask", "salt chemical chemistry science lab experiment mineral acid liquid brine"),
    ("fish", "fish crab mussel animal creature species shark whale marine"),
    ("fire", "fire burn hot heat lava volcano flame explosion explode"),
    ("money", "money rich cost price dollar pay cash gold wealth billion million"),
    ("clock", "time year years day days hour hours century ancient old minutes seconds history long"),
    ("bulb", "idea think brain smart discover discovered scientist scientists know learn genius invented"),
    ("skull", "deadly kill killed poison paralysed paralyzed death die dies dead toxic lethal"),
    ("warning", "danger dangerous risk warning careful threat"),
    ("globe", "world earth planet global country countries across nation"),
    ("heart", "love heart friend family care emotion"),
    ("chart", "grow growth increase more percent times higher rise bigger faster record"),
    ("magnifier", "find found search explore look looked inspect investigate study studied detail"),
    ("megaphone", "call called name named announce said tell told shout claim"),
    ("book", "book story read write written tale history chapter"),
    ("lock", "secret hidden lock locked safe private mystery trapped"),
    ("rocket", "space rocket launch speed fast quickly instantly sudden"),
    ("trophy", "win won best champion first greatest ever prize"),
    ("sun", "sun summer light bright day shine warm"),
    ("mountain", "mountain hill rock cliff peak stone edge shoreline"),
    ("tree", "tree forest plant nature wild jungle grow green"),
    ("house", "house home build building city room shelter"),
    ("gear", "machine work engine system process mechanism technology"),
    ("eye", "see saw watch watched seen visible notice eyes"),
    ("question", "why how mystery unknown strange question wonder weird"),
    ("exclamation", "wow amazing shock shocking incredible surprising unbelievable insane crazy"),
    ("drop", "drop rain wet liquid"),
    ("key", "key unlock open answer solution"),
    ("star", "star special famous fame legend remarkable"),
    ("bubble", "talk speak conversation say"),
    ("cloud", "cloud sky weather storm air wind cold"),
]
MOOD_WORDS = {
    "shocked": "shock deadly paralysed paralyzed danger kill never impossible insane crazy suddenly imagine",
    "happy": "love win best amazing great fun happy enjoy beautiful perfect",
    "sad": "lost lose death die alone sad fail failed disaster tragic",
}
POSE_WORDS = {
    "surprise": "shock suddenly amazing incredible wow",
    "fear": "danger deadly kill paralysed paralyzed trapped death scary",
    "run": "run fast speed quickly escape hurry rush race",
    "think": "why how think mystery wonder idea strange unknown",
    "point": "look this here called name found see",
    "cheer": "win best champion first great success",
    "shrug": "maybe perhaps unknown nobody seems",
}


def guess_from_text(text, idx):
    """Deterministic fallback when the planner is unavailable: icons / pose / mood from keywords."""
    ws = set(w.strip(".,!?;:'\"()").lower() for w in text.split())
    icons = []
    for name, kws in KEYWORDS:
        if ws & set(kws.split()):
            icons.append(name)
        if len(icons) >= 2:
            break
    for name in ("bulb", "star", "question", "magnifier", "exclamation"):
        if len(icons) >= 2:
            break
        n2 = (ICON_NAMES.index(name) + idx) % len(ICON_NAMES)
        pick = ("bulb", "star", "question", "magnifier", "exclamation")[idx % 5]
        if pick not in icons:
            icons.append(pick)
    pose = next((p for p, kws in POSE_WORDS.items() if ws & set(kws.split())), POSE_KEYS[idx % 8])
    mood = next((m for m, kws in MOOD_WORDS.items() if ws & set(kws.split())), "neutral")
    return icons[:2], pose, mood


def render_icon(name, px):
    """RGBA icon, px x px, drawn 2x then reduced."""
    S = 2
    big = Image.new("RGBA", (px * S, px * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    ICONS.get(name, _star)(d, px * S / 100.0)
    return big.resize((px, px), Image.LANCZOS)


def speed_lines(w, h, side, n=5):
    """Grey speed lines trailing behind the figure (drawn once as RGBA)."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for k in range(n):
        y = h * (0.2 + 0.6 * k / max(1, n - 1))
        ln = w * (0.55 + 0.35 * ((k * 7) % 5) / 5)
        x0 = 0 if side == 0 else w - ln
        d.line([(x0, y), (x0 + ln, y)], fill=(150, 152, 160, 255), width=max(3, int(h * 0.012)))
    return img


def sparkle(px, color=YELLOW):
    img = Image.new("RGBA", (px * 2, px * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = px
    r1, r2 = px * 0.92, px * 0.22
    pts = []
    for k in range(8):
        r = r1 if k % 2 == 0 else r2
        a = math.radians(-90 + k * 45)
        pts.append((c + math.cos(a) * r, c + math.sin(a) * r))
    d.polygon(pts, fill=color, outline=INK, width=max(2, px // 14))
    return img.resize((px, px), Image.LANCZOS)
