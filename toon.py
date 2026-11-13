"""Cartoon-explainer drawing kit (Ink-Explainer look): thick black outlines, flat colours, one recurring hero.

Used only by stickman.py. Pure PIL, supersampled, no network, no image generators.
"""
import math
import random

from PIL import Image, ImageDraw

INK = (20, 20, 24)
WHITE = (255, 255, 255)
SHIRT = (52, 143, 226)
SHIRT_D = (40, 118, 196)
JEANS = (74, 108, 160)
JEANS_D = (58, 88, 138)
SS = 2


# ----------------------------------------------------------------------------- primitives
def smooth(pts, closed=True, steps=8):
    """Catmull-Rom through pts."""
    n = len(pts)
    if n < 3:
        return list(pts)
    out = []
    rng = range(n) if closed else range(n - 1)
    for i in rng:
        p0 = pts[(i - 1) % n] if (closed or i > 0) else pts[0]
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        p3 = pts[(i + 2) % n] if (closed or i + 2 < n) else pts[-1]
        for s in range(steps):
            t = s / steps
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2 +
                                    (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3) for k in (0, 1)))
    if not closed:
        out.append(pts[-1])
    return out


def stroke(d, pts, w, col=INK, closed=False):
    pts = list(pts)
    if closed:
        pts = pts + [pts[0]]
    d.line(pts, fill=col, width=int(w), joint="curve")
    r = w / 2
    for x, y in (pts[0], pts[-1]) if not closed else pts[::3]:
        d.ellipse((x - r, y - r, x + r, y + r), fill=col)


def blob(d, pts, fill, ow, sm=True, steps=8, outline=INK):
    p = smooth(pts, True, steps) if sm else list(pts)
    d.polygon(p, fill=fill)
    if ow:
        stroke(d, p, ow, outline, closed=True)


def circle(d, c, r, fill, ow, outline=INK):
    x, y = c
    d.ellipse((x - r, y - r, x + r, y + r), fill=fill, outline=outline if ow else None, width=int(ow))


def ellipse(d, c, rx, ry, fill, ow, outline=INK):
    x, y = c
    d.ellipse((x - rx, y - ry, x + rx, y + ry), fill=fill, outline=outline if ow else None, width=int(ow))


def shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def vgrad(w, h, top, bot):
    col = Image.new("RGB", (1, h))
    px = col.load()
    for y in range(h):
        px[0, y] = mix(top, bot, y / max(1, h - 1))
    return col.resize((w, h))


# ----------------------------------------------------------------------------- hero
EXPR = {
    # eyes: dot / closed(^) / wide / half / angry ; brows: (left_tilt, right_tilt, lift) ; mouth: smile/open/o/flat/frown/smirk/wavy
    "happy":    dict(eyes="closed", brow=(0, 0, 0.0), mouth="open"),
    "neutral":  dict(eyes="dot", brow=(0, 0, 0.0), mouth="flat"),
    "shocked":  dict(eyes="wide", brow=(-10, 10, 0.35), mouth="o"),
    "scared":   dict(eyes="wide", brow=(-18, 18, 0.35), mouth="wavy"),
    "smug":     dict(eyes="half", brow=(0, 14, 0.0), mouth="smirk"),
    "angry":    dict(eyes="dot", brow=(22, -22, 0.0), mouth="frown"),
    "sad":      dict(eyes="dot", brow=(-16, 16, 0.1), mouth="frown"),
    "sleepy":   dict(eyes="half", brow=(0, 0, 0.0), mouth="smile"),
    "worried":  dict(eyes="dot", brow=(-14, 14, 0.2), mouth="wavy"),
    "excited":  dict(eyes="wide", brow=(-6, 6, 0.3), mouth="open"),
    "think":    dict(eyes="dot", brow=(0, -12, 0.15), mouth="flat"),
}

POSES = {   # angles in degrees from straight-down, + = toward screen right.  a1 upper, a2 lower
    "stand":  dict(lean=0,  la=(-12, -8),   ra=(12, 8),    ll=(-6, -4),  rl=(6, 4),   head=0),
    "wide":   dict(lean=0,  la=(-78, -88),  ra=(78, 88),   ll=(-9, -6),  rl=(9, 6),   head=0),
    "point":  dict(lean=3,  la=(-12, -8),   ra=(80, 86),   ll=(-7, -4),  rl=(7, 4),   head=4),
    "pointl": dict(lean=-3, la=(-80, -86),  ra=(12, 8),    ll=(-7, -4),  rl=(7, 4),   head=-4),
    "scared": dict(lean=-8, la=(-140, -160), ra=(150, 168), ll=(-20, -8), rl=(14, 6), head=-5),
    "run":    dict(lean=14, la=(-55, -110), ra=(50, 100),  ll=(-36, -8), rl=(34, 70), head=5),
    "flee":   dict(lean=-14, la=(-45, -95), ra=(55, 100),  ll=(-34, -60), rl=(32, 8), head=-5),
    "cheer":  dict(lean=0,  la=(-150, -165), ra=(150, 165), ll=(-12, -6), rl=(12, 6),  head=0),
    "think":  dict(lean=2,  la=(-12, -8),   ra=(25, 150),  ll=(-6, -4),  rl=(6, 4),   head=6),
    "shrug":  dict(lean=0,  la=(-50, -110), ra=(50, 110),  ll=(-6, -4),  rl=(6, 4),   head=8),
    "hold":   dict(lean=2,  la=(-12, -8),   ra=(35, 140),  ll=(-6, -4),  rl=(6, 4),   head=3),
    "sit":    dict(lean=-6, la=(-14, -10),  ra=(40, 10),   ll=(74, 8),   rl=(86, 14), head=-2, sit=True),
    "hips":   dict(lean=0,  la=(-45, 20),   ra=(45, -20),  ll=(-6, -4),  rl=(6, 4),   head=0),
    "dead":   dict(lean=-4, la=(-30, -40),  ra=(30, 40),   ll=(-10, -5), rl=(10, 5),  head=18),
    "bow":    dict(lean=22, la=(-10, -6),   ra=(10, 6),    ll=(-6, -4),  rl=(6, 4),   head=10),
}


def _lerp_pose(a, b, t):
    out = {}
    for k in a:
        if k in ("la", "ra", "ll", "rl"):
            out[k] = (a[k][0] + (b[k][0] - a[k][0]) * t, a[k][1] + (b[k][1] - a[k][1]) * t)
        elif k == "sit":
            out[k] = a[k] if t < 0.5 else b.get(k, False)
        else:
            out[k] = a[k] + (b.get(k, 0) - a[k]) * t
    out.setdefault("sit", False)
    return out


def blend_pose(n1, n2, t):
    a, b = POSES[n1], POSES[n2]
    a = dict(a); b = dict(b)
    a.setdefault("sit", False); b.setdefault("sit", False)
    return _lerp_pose(a, b, t)


def _dir(a):
    r = math.radians(a)
    return math.sin(r), math.cos(r)


def _d(shirt, pants=JEANS, shoes=WHITE, hair=None, hat=None, acc=(), headc=WHITE, scale=1.0, legs="pants", sleeve=None):
    return dict(shirt=shirt, pants=pants, shoes=shoes, hair=hair, hat=hat, acc=tuple(acc), headc=headc, scale=scale, legs=legs,
                sleeve=sleeve or shirt)


DESIGNS = {
    "hero":      _d(SHIRT),
    "girl":      _d((232, 92, 132), hair=("long", (120, 70, 40)), acc=("dress",), legs="bare", shoes=(232, 92, 132)),
    "scientist": _d((246, 246, 250), pants=(90, 96, 110), hair=("wild", (200, 200, 206)), acc=("glasses", "coat"), sleeve=(246, 246, 250)),
    "knight":    _d((170, 176, 188), pants=(120, 126, 140), shoes=(90, 94, 104), hat=("helmet", (170, 176, 188)), acc=("armor",), sleeve=(150, 156, 170)),
    "king":      _d((190, 40, 60), pants=(60, 40, 90), hat=("crown", (255, 206, 52)), acc=("beard", "cape", "ermine"), shoes=(90, 60, 40)),
    "caveman":   _d((176, 122, 70), pants=(150, 104, 60), hair=("messy", (50, 36, 30)), acc=("fur", "stubble"), legs="bare", shoes=(150, 104, 60)),
    "astronaut": _d((240, 242, 248), pants=(226, 228, 238), shoes=(150, 156, 170), hat=("dome", None), acc=("patch",), sleeve=(240, 242, 248)),
    "pirate":    _d((230, 230, 236), pants=(60, 56, 70), hat=("bandana", (200, 40, 40)), acc=("eyepatch", "stripes", "stubble"), shoes=(70, 50, 40)),
    "explorer":  _d((196, 160, 96), pants=(120, 100, 70), hat=("safari", (214, 186, 120)), acc=("vest",), shoes=(110, 76, 50)),
    "oldman":    _d((96, 150, 100), pants=(120, 110, 100), hair=("bald", None), acc=("glasses", "beard", "mustache"), shoes=(90, 70, 60)),
    "kid":       _d((250, 190, 50), pants=(70, 130, 90), hair=("spiky", (60, 40, 30)), scale=0.74),
    "boss":      _d((40, 42, 52), pants=(40, 42, 52), shoes=(20, 20, 24), hair=("short", (30, 30, 36)), acc=("tie",), sleeve=(40, 42, 52)),
    "robot":     _d((140, 150, 166), pants=(110, 118, 134), shoes=(90, 96, 110), headc=(176, 186, 200), acc=("antenna", "visor"), sleeve=(140, 150, 166)),
    "woman":     _d((120, 90, 190), pants=(60, 60, 80), hair=("bob", (40, 30, 30)), acc=(), shoes=(40, 40, 50)),
    "cowboy":    _d((200, 80, 60), pants=(70, 100, 150), hat=("cowboy", (150, 100, 60)), acc=("bandanna",), shoes=(110, 70, 40)),
    "doctor":    _d((240, 246, 250), pants=(70, 160, 170), hair=("short", (90, 60, 40)), acc=("coat", "mask"), sleeve=(240, 246, 250)),
}
CAST_NAMES = list(DESIGNS)
CAST_INFO = {
    "hero": "everyman narrator in a blue tee", "girl": "girl with ponytail in a pink dress", "scientist": "wild-haired scientist in a lab coat",
    "knight": "armoured knight", "king": "king with crown, beard and red cape", "caveman": "caveman in fur", "astronaut": "astronaut in a helmet",
    "pirate": "pirate with eyepatch", "explorer": "safari explorer", "oldman": "bald old man with beard and glasses", "kid": "small spiky-haired kid",
    "boss": "boss in a black suit and tie", "robot": "grey robot", "woman": "woman with a bob haircut", "cowboy": "cowboy with hat",
    "doctor": "doctor in a white coat", }


def draw_hero(pose, expr, px, blinking=False, flip=False, mouth_open=0.0, design=None):
    """Returns (RGBA image, feet_y, hip_xy).  px = pixels per head-radius (final scale)."""
    D = design if isinstance(design, dict) else DESIGNS.get(design or "hero", DESIGNS["hero"])
    acc = D["acc"]
    s = px * SS
    ow = max(3.0, 0.075 * s)
    W, H = int(s * 12), int(s * 10.2)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    hip = (W / 2, s * 4.9)
    if isinstance(pose, str):
        pose = blend_pose(pose, pose, 0)
    lean = pose.get("lean", 0)
    sit = pose.get("sit", False)

    def U(x, y):   # upper-body local (head radius units, hip at 0,0) -> px with lean about the hip
        a = math.radians(lean)
        xr = x * math.cos(a) + y * math.sin(a)
        yr = -x * math.sin(a) + y * math.cos(a)
        return hip[0] + xr * s, hip[1] + yr * s

    # ---- legs (from hip) ----
    def leg(side, a1, a2):
        hx = side * 0.38
        hp = (hip[0] + hx * s, hip[1] - 0.05 * s)
        t1 = 1.15 * s
        t2 = 1.12 * s
        d1 = _dir(a1)
        k = (hp[0] + d1[0] * t1, hp[1] + d1[1] * t1)
        d2 = _dir(a2)
        f = (k[0] + d2[0] * t2, k[1] + d2[1] * t2)
        return hp, k, f
    legs = [leg(-1, *pose["ll"]), leg(1, *pose["rl"])]
    feet_y = 0
    for hp, k, f in legs:
        # jeans tube
        if D["legs"] == "bare":
            stroke(d, [hp, k, f], 0.16 * s, INK)
        else:
            for col, w in ((INK, 0.62 * s), (D["pants"], 0.62 * s - 2 * ow)):
                stroke(d, [hp, k, f], w, col)
        # shoe
        ang = 1 if (f[0] - k[0]) >= -0.1 else -1
        sx = f[0] + ang * 0.28 * s
        sy = f[1] + 0.12 * s
        ellipse(d, (sx, sy), 0.52 * s, 0.24 * s, D["shoes"], ow)
        d.line([(sx - 0.45 * s, sy + 0.12 * s), (sx + 0.45 * s, sy + 0.12 * s)], fill=INK, width=int(ow * 0.8))
        feet_y = max(feet_y, sy + 0.24 * s)

    # ---- back arm (viewer's left) first ----
    def arm(side, a1, a2):
        sh = U(side * 0.68, 0.0 - 1.62)  # shoulder is above hip
        d1, d2 = _dir(a1), _dir(a2)
        # rotate directions with lean
        la = math.radians(lean)

        def rot(v):
            return v[0] * math.cos(la) + v[1] * math.sin(la), -v[0] * math.sin(la) + v[1] * math.cos(la)
        d1, d2 = rot(d1), rot(d2)
        L1, L2 = 1.25 * s, 1.15 * s
        el = (sh[0] + d1[0] * L1, sh[1] + d1[1] * L1)
        hd = (el[0] + d2[0] * L2, el[1] + d2[1] * L2)
        return sh, el, hd, d1, d2

    # torso & head positions
    top = U(0, -1.75)
    bot = (hip[0], hip[1] + 0.12 * s)

    arms = [arm(-1, *pose["la"]), arm(1, *pose["ra"])]

    def draw_arm(A, side):
        sh, el, hd, d1, d2 = A
        # sleeve
        sl_end = (sh[0] + d1[0] * 0.55 * s, sh[1] + d1[1] * 0.55 * s)
        stroke(d, [el if False else sh, el, hd], 0.15 * s + ow, INK)
        for col, w in ((INK, 0.66 * s), (D["sleeve"], 0.66 * s - 2 * ow)):
            stroke(d, [sh, sl_end], w, col)
        # thin arm line over the sleeve end
        stroke(d, [sl_end, el, hd], 0.16 * s, INK)
        # mitten hand
        hr = 0.34 * s
        hdir = d2
        hc = (hd[0] + hdir[0] * 0.2 * s, hd[1] + hdir[1] * 0.2 * s)
        ellipse(d, hc, hr * 0.85, hr * 1.05, WHITE, ow * 0.85)
        th = (hc[0] + (-side) * hr * 0.9, hc[1] - hr * 0.1)
        ellipse(d, th, hr * 0.38, hr * 0.5, WHITE, ow * 0.7)

    draw_arm(arms[0], -1)

    # ---- torso ----
    if "cape" in acc:
        blob(d, [U(-0.7, -1.7), U(0.7, -1.7), U(1.15, 1.9), U(0.0, 2.15), U(-1.15, 1.9)], (150, 24, 44), ow, steps=5)
    p = [U(-0.62, -1.72), U(0.62, -1.72), U(0.68, -0.1), U(0.0, 0.12), U(-0.68, -0.1)]
    if "dress" in acc:
        blob(d, [U(-0.62, -1.72), U(0.62, -1.72), U(0.7, -0.2), U(1.12, 0.95), U(0.0, 1.12), U(-1.12, 0.95), U(-0.7, -0.2)], D["shirt"], ow, steps=5)
    else:
        blob(d, p, D["shirt"], ow, steps=6)
    stroke(d, [U(-0.3, -0.5), U(-0.15, -0.2)], ow * 0.6, shade(D["shirt"], 0.82))
    if "coat" in acc:
        stroke(d, [U(0, -1.72), U(0.0, 0.1)], ow * 0.8, INK)
        blob(d, [U(-0.2, -1.72), U(0.0, -1.1), U(0.2, -1.72)], (120, 190, 230) if "mask" not in acc else (120, 190, 230), ow * 0.7, sm=False)
    if "armor" in acc:
        for yy in (-1.2, -0.7, -0.2):
            stroke(d, [U(-0.62, yy), U(0.62, yy)], ow * 0.7, shade(D["shirt"], 0.7))
        circle(d, U(0, -0.9), 0.17 * s / s * s, (220, 40, 50), ow * 0.7) if False else None
    if "tie" in acc:
        blob(d, [U(-0.1, -1.72), U(0.1, -1.72), U(0.16, -0.6), U(0, -0.35), U(-0.16, -0.6)], (210, 40, 50), ow * 0.7, sm=False)
    if "fur" in acc:
        for xx in (-0.5, -0.25, 0, 0.25, 0.5):
            stroke(d, [U(xx, 0.0), U(xx + 0.08, 0.22)], ow * 0.9, INK)
    if "stripes" in acc:
        for yy in (-1.4, -0.9, -0.4):
            stroke(d, [U(-0.64, yy), U(0.64, yy)], ow * 1.1, (50, 70, 140))
    if "ermine" in acc:
        stroke(d, [U(-0.4, -1.72), U(0.0, -1.2), U(0.4, -1.72)], ow * 2.2, WHITE)
    if "vest" in acc:
        stroke(d, [U(-0.3, -1.72), U(-0.35, -0.1)], ow * 1.2, (130, 100, 60))
        stroke(d, [U(0.3, -1.72), U(0.35, -0.1)], ow * 1.2, (130, 100, 60))
    if "patch" in acc:
        circle(d, U(0.3, -1.2), 0.17 * s, (60, 110, 220), ow * 0.6)
    # jeans waist (belt area) small
    # ---- front arm ----
    draw_arm(arms[1], 1)

    # ---- neck + head ----
    hc = U(0, -2.95)
    th = math.radians(pose.get("head", 0))
    hx, hy = hc
    R = s * 1.2
    hair = D["hair"]
    if hair and hair[0] == "long":
        blob(d, [(hx - R * 1.05, hy - R * 0.2), (hx - R * 1.1, hy + R * 1.2), (hx + R * 1.1, hy + R * 1.2), (hx + R * 1.05, hy - R * 0.2)], hair[1], ow)
    if hair and hair[0] == "ponytail":
        blob(d, [(hx + R * .9, hy - R * .3), (hx + R * 1.7, hy + R * .1), (hx + R * 1.5, hy + R * 1.1), (hx + R * 1.0, hy + R * .3)], hair[1], ow)
    if "antenna" in acc:
        stroke(d, [(hx, hy - R), (hx, hy - R * 1.5)], ow, INK)
        circle(d, (hx, hy - R * 1.55), R * 0.12, (230, 60, 60), ow * 0.8)
    circle(d, (hx, hy), R, D["headc"], ow * 1.15)
    # face
    fx = hx + math.sin(th) * R * 0.15
    fy = hy + R * 0.12

    def fp(x, y):
        a = th
        return fx + (x * math.cos(a) - y * math.sin(a)) * R, fy + (x * math.sin(a) + y * math.cos(a)) * R
    e = EXPR.get(expr, EXPR["neutral"])
    ex = 0.34
    eyes = "closed" if blinking and e["eyes"] in ("dot", "wide") else e["eyes"]
    lt, rt, lift = e["brow"]
    for sd, tilt in ((-1, lt), (1, rt)):
        c = fp(sd * ex, -0.18)
        if eyes == "closed":
            a, b, cc = fp(sd * ex - 0.14, -0.14), fp(sd * ex, -0.28), fp(sd * ex + 0.14, -0.14)
            stroke(d, smooth([a, b, cc], False, 6), ow * 0.8, INK)
        elif eyes == "wide":
            ellipse(d, c, 0.12 * R, 0.15 * R, WHITE, ow * 0.55)
            circle(d, (c[0], c[1] + 0.01 * R), 0.055 * R, INK, 0)
        elif eyes == "half":
            ellipse(d, c, 0.12 * R, 0.10 * R, WHITE, ow * 0.55)
            circle(d, (c[0], c[1] + 0.03 * R), 0.06 * R, INK, 0)
            stroke(d, [fp(sd * ex - 0.16, -0.22), fp(sd * ex + 0.16, -0.22)], ow * 0.8, INK)
        else:
            ellipse(d, c, 0.075 * R, 0.10 * R, INK, 0)
        # brow
        if eyes != "closed" or lift:
            bc = fp(sd * ex, -0.42 - lift * 0.2)
            ang = math.radians(tilt * sd)
            dx, dy = math.cos(ang) * 0.13 * R, math.sin(ang) * 0.13 * R
            if eyes not in ("closed",):
                stroke(d, [(bc[0] - dx, bc[1] + dy * sd * -1), (bc[0] + dx, bc[1] - dy * sd * -1)], ow * 0.9, INK)
    # face extras behind mouth
    if "beard" in acc:
        blob(d, [fp(-0.85, 0.2), fp(-0.7, 0.9), fp(0, 1.25), fp(0.7, 0.9), fp(0.85, 0.2), fp(0.5, 0.45), fp(0, 0.5), fp(-0.5, 0.45)],
             WHITE if (D["hat"] and D["hat"][0] == "crown") or D["hair"] == ("bald", None) else (90, 60, 40), ow, steps=5)
    # mouth
    m = e["mouth"]
    mo = mouth_open
    if mo > 0.25 and m in ("flat", "smile", "smirk", "frown"):
        m = "talk"
    mc = (0, 0.32)
    if m == "open":
        pts = [fp(-0.30, 0.22), fp(0.30, 0.22), fp(0.22, 0.42 + 0.1 * mo), fp(0, 0.55 + 0.12 * mo), fp(-0.22, 0.42 + 0.1 * mo)]
        blob(d, pts, (110, 30, 40), ow * 0.7, steps=6)
        d.polygon([fp(-0.26, 0.23), fp(0.26, 0.23), fp(0.24, 0.29), fp(-0.24, 0.29)], fill=WHITE)
    elif m == "o":
        ellipse(d, fp(0, 0.38), 0.11 * R, 0.15 * R, (110, 30, 40), ow * 0.6)
    elif m == "talk":
        ellipse(d, fp(0, 0.38), (0.11 + 0.08 * mo) * R, (0.06 + 0.12 * mo) * R, (110, 30, 40), ow * 0.6)
    elif m == "smile":
        stroke(d, smooth([fp(-0.26, 0.28), fp(0, 0.42), fp(0.26, 0.28)], False, 6), ow * 0.75, INK)
    elif m == "smirk":
        stroke(d, smooth([fp(-0.2, 0.34), fp(0.08, 0.40), fp(0.32, 0.22)], False, 6), ow * 0.75, INK)
    elif m == "frown":
        stroke(d, smooth([fp(-0.22, 0.45), fp(0, 0.32), fp(0.22, 0.45)], False, 6), ow * 0.75, INK)
    elif m == "wavy":
        stroke(d, smooth([fp(-0.28, 0.40), fp(-0.14, 0.30), fp(0, 0.42), fp(0.14, 0.30), fp(0.28, 0.40)], False, 6), ow * 0.75, INK)
    else:
        stroke(d, [fp(-0.2, 0.38), fp(0.2, 0.38)], ow * 0.75, INK)

    # ---- head extras (drawn over the face) ----
    if "mustache" in acc:
        blob(d, [fp(-0.4, 0.2), fp(0, 0.12), fp(0.4, 0.2), fp(0.3, 0.3), fp(0, 0.24), fp(-0.3, 0.3)], WHITE if D["hair"] == ("bald", None) else INK, ow * 0.6)
    if "stubble" in acc:
        for xx in (-0.4, -0.2, 0.2, 0.4):
            for yy in (0.55, 0.7):
                circle(d, fp(xx, yy), 0.03 * R, INK, 0)
    if "glasses" in acc:
        for sd in (-1, 1):
            circle(d, fp(sd * 0.34, -0.18), 0.27 * R, (255, 255, 255), ow * 0.8)
        stroke(d, [fp(-0.07, -0.18), fp(0.07, -0.18)], ow * 0.8, INK)
    if "eyepatch" in acc:
        ellipse(d, fp(0.34, -0.18), 0.22 * R, 0.2 * R, INK, 0)
        stroke(d, [fp(-0.9, -0.5), fp(0.34, -0.18), fp(0.95, -0.55)], ow * 0.7, INK)
    if "visor" in acc:
        blob(d, [fp(-0.8, -0.38), fp(0.8, -0.38), fp(0.8, 0.0), fp(-0.8, 0.0)], (110, 220, 240), ow * 0.8)
        for sd in (-1, 1):
            circle(d, fp(sd * 0.34, -0.19), 0.09 * R, INK, 0)
    if "mask" in acc:
        blob(d, [fp(-0.6, 0.18), fp(0.6, 0.18), fp(0.5, 0.75), fp(-0.5, 0.75)], (170, 220, 236), ow * 0.7, sm=False)
    if "bandanna" in acc:
        stroke(d, [(hx - R * 0.6, hy + R * 1.0), (hx, hy + R * 1.25), (hx + R * 0.6, hy + R * 1.0)], ow * 3, (220, 50, 50))
    if hair and hair[0] in ("short", "spiky", "wild", "messy", "bob", "long", "ponytail"):
        st, col = hair
        a0, a1 = 200, 340
        arc = [(hx + math.cos(math.radians(a)) * R * 1.03, hy + math.sin(math.radians(a)) * R * 1.03) for a in range(a0, a1 + 1, 10)]
        if st == "spiky":
            pts = []
            for i, a in enumerate(range(195, 346, 15)):
                rr = 1.4 if i % 2 == 0 else 1.05
                pts.append((hx + math.cos(math.radians(a)) * R * rr, hy + math.sin(math.radians(a)) * R * rr))
            pts += [(hx + R * 0.8, hy - R * 0.55), (hx, hy - R * 0.72), (hx - R * 0.8, hy - R * 0.55)]
            blob(d, pts, col, ow, sm=False)
        elif st == "wild":
            pts = []
            for i, a in enumerate(range(170, 371, 20)):
                rr = 1.5 if i % 2 == 0 else 1.1
                pts.append((hx + math.cos(math.radians(a)) * R * rr, hy + math.sin(math.radians(a)) * R * rr))
            pts += [(hx + R * 0.9, hy - R * 0.2), (hx, hy - R * 0.6), (hx - R * 0.9, hy - R * 0.2)]
            blob(d, pts, col, ow, sm=False)
        elif st == "messy":
            pts = [(hx + math.cos(math.radians(a)) * R * (1.25 if i % 2 else 1.05), hy + math.sin(math.radians(a)) * R * (1.25 if i % 2 else 1.05))
                   for i, a in enumerate(range(190, 351, 12))]
            pts += [(hx + R * 0.7, hy - R * 0.5), (hx, hy - R * 0.62), (hx - R * 0.7, hy - R * 0.5)]
            blob(d, pts, col, ow, sm=False)
        else:
            low = 0.1 if st in ("bob", "long") else -0.45
            pts = arc + [(hx + R * 0.95, hy + R * low), (hx + R * 0.5, hy - R * 0.55), (hx, hy - R * 0.42), (hx - R * 0.55, hy - R * 0.6), (hx - R * 0.95, hy + R * low)]
            blob(d, pts, col, ow, steps=4)
    hat = D["hat"]
    if hat:
        kind, col = hat
        if kind == "crown":
            blob(d, [(hx - R * .6, hy - R * .85), (hx - R * .62, hy - R * 1.5), (hx - R * .3, hy - R * 1.2), (hx, hy - R * 1.6), (hx + R * .3, hy - R * 1.2),
                     (hx + R * .62, hy - R * 1.5), (hx + R * .6, hy - R * .85)], col, ow, sm=False)
        elif kind == "helmet":
            pts = [(hx + math.cos(math.radians(a)) * R * 1.08, hy + math.sin(math.radians(a)) * R * 1.08) for a in range(180, 361, 10)]
            blob(d, pts + [(hx + R * 1.08, hy + R * 0.15), (hx - R * 1.08, hy + R * 0.15)], col, ow, steps=3)
            stroke(d, [(hx - R * 0.8, hy - R * 0.1), (hx + R * 0.8, hy - R * 0.1)], ow * 1.2, INK)
            blob(d, [(hx - R * .12, hy - R * 1.08), (hx, hy - R * 1.7), (hx + R * .12, hy - R * 1.08)], (220, 40, 50), ow * 0.7, sm=False)
        elif kind == "dome":
            circle(d, (hx, hy), R * 1.12, (190, 225, 245), ow * 1.2) if False else None
            ring = [(hx + math.cos(math.radians(a)) * R * 1.16, hy + math.sin(math.radians(a)) * R * 1.16) for a in range(0, 360, 8)]
            stroke(d, ring, ow * 1.3, (190, 196, 208), closed=True)
            stroke(d, ring, ow * 0.5, INK, closed=True)
            stroke(d, [(hx - R * 0.6, hy - R * 0.8), (hx - R * 0.2, hy - R * 1.0)], ow * 1.2, (255, 255, 255))
        elif kind == "bandana":
            stroke(d, [(hx - R * 1.0, hy - R * 0.35), (hx, hy - R * 0.62), (hx + R * 1.0, hy - R * 0.35)], ow * 3.4, col)
            blob(d, [(hx + R * .95, hy - R * .38), (hx + R * 1.5, hy - R * .1), (hx + R * 1.25, hy - R * .55)], col, ow * 0.7, sm=False)
        elif kind in ("cowboy", "safari"):
            ellipse(d, (hx, hy - R * 0.72), R * 1.45, R * 0.28, col, ow)
            blob(d, [(hx - R * .62, hy - R * .72), (hx - R * .55, hy - R * 1.4), (hx + R * .55, hy - R * 1.4), (hx + R * .62, hy - R * .72)], col, ow, steps=4)
    out = img.resize((W // SS, H // SS), Image.LANCZOS)
    bbox_feet = feet_y / SS
    if flip:
        out = out.transpose(Image.FLIP_LEFT_RIGHT)
    return out, bbox_feet, (hip[0] / SS, hip[1] / SS)
