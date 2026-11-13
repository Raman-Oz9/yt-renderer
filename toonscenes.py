"""Settings (backgrounds) and props for the cartoon-explainer renderer. Flat colours, thick outlines."""
import math
import random

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

from toon import INK, WHITE, SS, smooth, stroke, blob, circle, ellipse, shade, mix, vgrad

SKY = (176, 214, 236)
GRASS = (110, 170, 80)
GRASS_D = (80, 140, 64)
SAND = (236, 214, 160)
DIRT = (120, 84, 56)
STONE = (170, 168, 160)
LEAF = (70, 140, 70)
LEAF_D = (46, 100, 52)
TRUNK = (150, 160, 120)
RED = (226, 68, 62)
YEL = (255, 206, 52)
ORG = (244, 150, 50)
BROWN = (160, 112, 70)

FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


def _font(sz):
    for p in [str(Path(__file__).with_name("fonts") / "Hand.ttf")] + FONTS:
        if Path(p).exists():
            return ImageFont.truetype(p, int(sz))
    return ImageFont.load_default()


def ow_for(H):
    return max(3.0, H * 0.0042)


# ----------------------------------------------------------------------------- small drawing helpers
def cloud(d, x, y, s, ow):
    pts = [(x - s * 1.0, y + s * 0.2), (x - s * 0.8, y - s * 0.2), (x - s * 0.4, y - s * 0.45), (x + s * 0.0, y - s * 0.3),
           (x + s * 0.4, y - s * 0.5), (x + s * 0.85, y - s * 0.2), (x + s * 1.0, y + s * 0.2), (x, y + s * 0.3)]
    blob(d, pts, WHITE, ow)


def fern(d, x, y, s, ow, rng, lean=0.0, col=LEAF):
    """Fern frond: curved stem with leaflet pairs. (x,y)=base, s=height px."""
    n = 11
    stem = []
    for i in range(n + 1):
        t = i / n
        stem.append((x + lean * s * t * t + math.sin(t * 2.2) * s * 0.05, y - s * t))
    stroke(d, smooth(stem, False, 4), max(2, ow * 0.9), INK)
    for i in range(1, n + 1):
        t = i / n
        px, py = stem[i]
        ln = s * 0.36 * (1 - t * 0.75)
        for sd in (-1, 1):
            tip = (px + sd * ln, py - ln * 0.35)
            base = (px, py)
            mid1 = (px + sd * ln * 0.55, py - ln * 0.42)
            mid2 = (px + sd * ln * 0.55, py + ln * 0.0)
            leaf = [base, mid1, tip, mid2]
            d.polygon(leaf, fill=shade(col, 1.0 + 0.15 * ((i + (sd > 0)) % 2)))
            stroke(d, leaf, max(2, ow * 0.7), INK, closed=True)


def fern_bush(d, x, y, s, ow, rng, col=LEAF, k=5):
    for i in range(k):
        a = (i - (k - 1) / 2) / max(1, k - 1)
        fern(d, x + a * s * 0.25, y, s * rng.uniform(0.7, 1.0), ow, rng, lean=a * 0.9, col=col)


def grass_tufts(d, W, y, H, ow, rng, n=14, col=GRASS_D):
    for _ in range(n):
        x = rng.uniform(0, W)
        yy = y + rng.uniform(H * 0.02, H * 0.12)
        h = H * rng.uniform(0.02, 0.04)
        for k in (-1, 0, 1):
            stroke(d, [(x, yy), (x + k * h * 0.5, yy - h)], max(2, ow * 0.7), shade(col, 0.7))


def patterned_trunk(d, x, y, w, h, ow, base=TRUNK, flare=1.4):
    """Palm/tree-fern trunk with diamond lattice. (x,y)=base centre, top at y-h."""
    pts = [(x - w * flare / 2, y), (x - w / 2, y - h * 0.35), (x - w * 0.46, y - h), (x + w * 0.46, y - h), (x + w / 2, y - h * 0.35),
           (x + w * flare / 2, y)]
    d.polygon(pts, fill=base)
    dk = shade(base, 0.72)
    rows = 14
    for r in range(rows):
        yy = y - h * r / rows
        ww = w * (0.5 + 0.45 * (1 - r / rows) ** 3)
        step = w * 0.28
        off = (r % 2) * step / 2
        xx = x - ww + off
        while xx < x + ww:
            dy = h / rows
            dia = [(xx, yy), (xx + step / 2, yy - dy / 2), (xx + step, yy), (xx + step / 2, yy + dy / 2)]
            d.polygon([(px, py) for px, py in dia], outline=dk)
            xx += step
    stroke(d, [pts[0], pts[1], pts[2]], ow, INK)
    stroke(d, [pts[5], pts[4], pts[3]], ow, INK)


def palm_top(d, x, y, s, ow, rng):
    for a in (-70, -35, 0, 35, 70, -100, 100):
        r = math.radians(a - 90)
        tipx, tipy = x + math.cos(r) * s, y + math.sin(r) * s * 0.7
        midx, midy = x + math.cos(r) * s * 0.55, y + math.sin(r) * s * 0.55 - s * 0.12
        leaf = [(x, y), (midx - 6 * SS, midy - s * 0.08), (tipx, tipy), (midx + 6 * SS, midy + s * 0.08)]
        blob(d, leaf, LEAF, ow * 0.8, steps=5)


# ----------------------------------------------------------------------------- props  (each: draw(d, cx, base_y, s, ow, rng))
def p_tree(d, x, y, s, ow, rng):
    h = s
    stroke(d, [(x, y), (x, y - h * 0.5)], h * 0.12 + ow * 2, INK)
    stroke(d, [(x, y), (x, y - h * 0.5)], h * 0.12, BROWN)
    blob(d, [(x - h * .38, y - h * .5), (x - h * .3, y - h * .8), (x, y - h * 1.0), (x + h * .32, y - h * .82), (x + h * .4, y - h * .52), (x, y - h * .42)], LEAF, ow)


def p_palm(d, x, y, s, ow, rng):
    patterned_trunk(d, x, y, s * 0.16, s * 0.9, ow)
    palm_top(d, x, y - s * 0.9, s * 0.5, ow, rng)


def p_pine(d, x, y, s, ow, rng):
    stroke(d, [(x, y), (x, y - s * 0.2)], s * 0.08, BROWN)
    for i, (w, t) in enumerate(((0.55, 0.15), (0.45, 0.4), (0.33, 0.65))):
        blob(d, [(x - s * w / 2, y - s * t), (x, y - s * (t + 0.38)), (x + s * w / 2, y - s * t)], (60, 130, 80), ow, sm=False)


def p_fern(d, x, y, s, ow, rng):
    fern_bush(d, x, y, s, ow, rng)


def p_rock(d, x, y, s, ow, rng):
    pts = [(x - s * .5, y), (x - s * .42, y - s * .45), (x - s * .1, y - s * .7), (x + s * .3, y - s * .6), (x + s * .5, y - s * .2), (x + s * .45, y)]
    blob(d, pts, STONE, ow, steps=4)
    stroke(d, [(x - s * .1, y - s * .7), (x - s * .05, y - s * .3), (x + s * .15, y - s * .05)], ow * 0.8, INK)


def p_boulder(d, x, y, s, ow, rng):
    p_rock(d, x, y, s, ow, rng)


def p_campfire(d, x, y, s, ow, rng):
    for i in range(7):
        a = math.pi * (i / 6)
        rx = x + math.cos(a) * s * 0.6
        ry = y - math.sin(a) * s * 0.12
        ellipse(d, (rx, ry), s * .13, s * .09, STONE, ow * 0.8)
    blob(d, [(x - s * .3, y - s * .05), (x - s * .25, y - s * .4), (x - s * .05, y - s * .55), (x - s * .05, y - s * .85), (x + s * .2, y - s * .45), (x + s * .3, y - s * .05)], ORG, ow)
    blob(d, [(x - s * .15, y - s * .05), (x - s * .1, y - s * .3), (x + s * .05, y - s * .4), (x + s * .15, y - s * .05)], YEL, ow * 0.6)


def p_house(d, x, y, s, ow, rng):
    w, h = s * 1.0, s * 0.6
    blob(d, [(x - w / 2, y), (x - w / 2, y - h), (x + w / 2, y - h), (x + w / 2, y)], (240, 226, 190), ow, sm=False)
    blob(d, [(x - w * .62, y - h), (x, y - h - s * 0.4), (x + w * .62, y - h)], RED, ow, sm=False)
    blob(d, [(x - w * .1, y), (x - w * .1, y - h * .55), (x + w * .1, y - h * .55), (x + w * .1, y)], BROWN, ow * 0.8, sm=False)
    blob(d, [(x + w * .22, y - h * .45), (x + w * .22, y - h * .75), (x + w * .4, y - h * .75), (x + w * .4, y - h * .45)], SKY, ow * 0.8, sm=False)


def p_castle(d, x, y, s, ow, rng):
    w, h = s * 1.2, s * 0.6
    blob(d, [(x - w / 2, y), (x - w / 2, y - h), (x + w / 2, y - h), (x + w / 2, y)], STONE, ow, sm=False)
    for sd in (-1, 1):
        tx = x + sd * w * 0.5
        blob(d, [(tx - s * .14, y), (tx - s * .14, y - h * 1.5), (tx + s * .14, y - h * 1.5), (tx + s * .14, y)], shade(STONE, 1.05), ow, sm=False)
        blob(d, [(tx - s * .19, y - h * 1.5), (tx, y - h * 1.5 - s * .3), (tx + s * .19, y - h * 1.5)], RED, ow, sm=False)
    blob(d, [(x - s * .12, y), (x - s * .12, y - h * .5), (x, y - h * .62), (x + s * .12, y - h * .5), (x + s * .12, y)], BROWN, ow, sm=False)
    for i in range(5):
        bx = x - w / 2 + i * w / 4.5 + w * 0.02
        d.rectangle((bx, y - h - s * .06, bx + s * .1, y - h), fill=STONE, outline=INK, width=int(ow * 0.7))


def p_tent(d, x, y, s, ow, rng):
    blob(d, [(x - s * .6, y), (x, y - s * .7), (x + s * .6, y)], ORG, ow, sm=False)
    blob(d, [(x - s * .12, y), (x, y - s * .34), (x + s * .12, y)], (90, 50, 30), ow * 0.8, sm=False)


def p_cactus(d, x, y, s, ow, rng):
    G = (92, 160, 90)
    blob(d, [(x - s * .1, y), (x - s * .1, y - s), (x + s * .1, y - s), (x + s * .1, y)], G, ow)
    for sd in (-1, 1):
        ax = x + sd * s * .22
        stroke(d, [(x + sd * s * .1, y - s * .3), (ax + sd * s * .1, y - s * .3), (ax + sd * s * .1, y - s * .62)], s * .13 + ow * 2, INK)
        stroke(d, [(x + sd * s * .1, y - s * .3), (ax + sd * s * .1, y - s * .3), (ax + sd * s * .1, y - s * .62)], s * .13, G)


def p_cloud(d, x, y, s, ow, rng):
    cloud(d, x, y - s * .5, s * .5, ow)


def p_sun(d, x, y, s, ow, rng):
    cy = y - s * .5
    for i in range(12):
        a = i * math.pi / 6
        stroke(d, [(x + math.cos(a) * s * .38, cy + math.sin(a) * s * .38), (x + math.cos(a) * s * .55, cy + math.sin(a) * s * .55)], ow * 1.2, INK)
    circle(d, (x, cy), s * .3, YEL, ow)


def p_moon(d, x, y, s, ow, rng):
    cy = y - s * .5
    circle(d, (x, cy), s * .32, (250, 244, 210), ow)
    circle(d, (x + s * .14, cy - s * .08), s * .27, (22, 28, 60), 0, outline=None)


def p_crown(d, x, y, s, ow, rng):
    w, h = s * .8, s * .5
    blob(d, [(x - w / 2, y), (x - w / 2, y - h * .8), (x - w / 4, y - h * .4), (x, y - h), (x + w / 4, y - h * .4), (x + w / 2, y - h * .8), (x + w / 2, y)], YEL, ow, sm=False)
    for px in (-w / 2, 0, w / 2):
        circle(d, (x + px, y - h * (1 if px == 0 else .8)), s * .05, RED, ow * 0.7)


def p_chest(d, x, y, s, ow, rng):
    w, h = s * .9, s * .5
    blob(d, [(x - w / 2, y), (x - w / 2, y - h * .6), (x + w / 2, y - h * .6), (x + w / 2, y)], BROWN, ow, sm=False)
    blob(d, [(x - w / 2, y - h * .6), (x - w * .4, y - h), (x + w * .4, y - h), (x + w / 2, y - h * .6)], shade(BROWN, 1.15), ow, sm=False)
    d.rectangle((x - s * .05, y - h * .7, x + s * .05, y - h * .35), fill=YEL, outline=INK, width=int(ow * 0.8))


def p_sword(d, x, y, s, ow, rng):
    stroke(d, [(x, y), (x, y - s * .75)], s * .08 + ow * 2, INK)
    stroke(d, [(x, y - s * .02), (x, y - s * .73)], s * .08, (210, 216, 226))
    stroke(d, [(x - s * .16, y - s * .0), (x + s * .16, y - s * .0)], s * .05 + ow * 2, INK)
    stroke(d, [(x - s * .15, y), (x + s * .15, y)], s * .05, YEL)


def p_book(d, x, y, s, ow, rng):
    w, h = s * .8, s * .55
    blob(d, [(x - w / 2, y), (x - w / 2, y - h), (x, y - h * .85), (x + w / 2, y - h), (x + w / 2, y), (x, y - h * .12)], (250, 246, 232), ow, sm=False)
    stroke(d, [(x, y - h * .85), (x, y - h * .12)], ow, INK)
    for k in range(3):
        stroke(d, [(x - w * .4, y - h * (.7 - k * .17)), (x - w * .08, y - h * (.62 - k * .17))], ow * 0.6, (120, 120, 130))
        stroke(d, [(x + w * .08, y - h * (.62 - k * .17)), (x + w * .4, y - h * (.7 - k * .17))], ow * 0.6, (120, 120, 130))


def p_money(d, x, y, s, ow, rng):
    for i in range(4):
        ellipse(d, (x, y - s * .09 * i - s * .06), s * .3, s * .09, YEL, ow * 0.8)
    for i in range(3):
        ellipse(d, (x + s * .45, y - s * .09 * i - s * .06), s * .26, s * .08, YEL, ow * 0.8)
    f = _font(s * .3)
    d.text((x, y - s * .6), "$", font=f, fill=(40, 140, 60), anchor="mm", stroke_width=int(ow * 0.7), stroke_fill=INK)


def p_computer(d, x, y, s, ow, rng):
    w, h = s * .9, s * .6
    blob(d, [(x - w / 2, y - s * .12), (x - w / 2, y - s * .12 - h), (x + w / 2, y - s * .12 - h), (x + w / 2, y - s * .12)], (60, 66, 80), ow, sm=False)
    d.rectangle((x - w * .45, y - s * .12 - h * .92, x + w * .45, y - s * .12 - h * .08), fill=(130, 200, 240))
    blob(d, [(x - w * .6, y), (x - w * .5, y - s * .12), (x + w * .5, y - s * .12), (x + w * .6, y)], (200, 204, 212), ow, sm=False)


def p_phone(d, x, y, s, ow, rng):
    w, h = s * .38, s * .72
    blob(d, [(x - w / 2, y), (x - w / 2, y - h), (x + w / 2, y - h), (x + w / 2, y)], (50, 54, 66), ow)
    d.rectangle((x - w * .4, y - h * .9, x + w * .4, y - h * .12), fill=(150, 210, 240))


def p_clock(d, x, y, s, ow, rng):
    cy = y - s * .4
    circle(d, (x, cy), s * .36, WHITE, ow * 1.2)
    stroke(d, [(x, cy), (x, cy - s * .22)], ow * 1.2, INK)
    stroke(d, [(x, cy), (x + s * .15, cy + s * .05)], ow * 1.2, INK)
    for i in range(12):
        a = i * math.pi / 6
        stroke(d, [(x + math.cos(a) * s * .3, cy + math.sin(a) * s * .3), (x + math.cos(a) * s * .33, cy + math.sin(a) * s * .33)], ow * 0.8, INK)


def p_rocket(d, x, y, s, ow, rng):
    blob(d, [(x - s * .14, y - s * .2), (x - s * .2, y - s * .5), (x, y - s * 1.0), (x + s * .2, y - s * .5), (x + s * .14, y - s * .2)], (240, 240, 245), ow)
    circle(d, (x, y - s * .55), s * .08, (120, 190, 240), ow * 0.8)
    blob(d, [(x - s * .14, y - s * .2), (x - s * .3, y - s * .1), (x - s * .14, y - s * .38)], RED, ow * 0.8, sm=False)
    blob(d, [(x + s * .14, y - s * .2), (x + s * .3, y - s * .1), (x + s * .14, y - s * .38)], RED, ow * 0.8, sm=False)
    blob(d, [(x - s * .1, y - s * .2), (x, y + s * .15), (x + s * .1, y - s * .2)], ORG, ow * 0.8)


def p_planet(d, x, y, s, ow, rng):
    cy = y - s * .5
    circle(d, (x, cy), s * .32, (230, 150, 90), ow)
    stroke(d, smooth([(x - s * .5, cy + s * .1), (x, cy + s * .22), (x + s * .5, cy - s * .1)], False, 8), ow * 1.2, INK)
    stroke(d, [(x - s * .2, cy - s * .1), (x + s * .1, cy - s * .18)], ow * 0.7, (190, 110, 60))


def p_ufo(d, x, y, s, ow, rng):
    cy = y - s * .5
    circle(d, (x, cy - s * .1), s * .2, (170, 230, 250), ow)
    ellipse(d, (x, cy), s * .5, s * .15, (180, 184, 196), ow)
    for k in (-1, 0, 1):
        circle(d, (x + k * s * .25, cy), s * .03, YEL, 0)


def p_monster(d, x, y, s, ow, rng):
    pts = [(x - s * .5, y), (x - s * .5, y - s * .5), (x - s * .25, y - s * .8), (x + s * .25, y - s * .8), (x + s * .5, y - s * .5), (x + s * .5, y)]
    blob(d, pts, (150, 90, 170), ow)
    for sd in (-1, 1):
        circle(d, (x + sd * s * .17, y - s * .55), s * .1, WHITE, ow * 0.8)
        circle(d, (x + sd * s * .17, y - s * .55), s * .04, INK, 0)
    blob(d, [(x - s * .22, y - s * .32), (x, y - s * .22), (x + s * .22, y - s * .32), (x + s * .15, y - s * .42), (x - s * .15, y - s * .42)], (60, 20, 40), ow * 0.8, sm=False)
    for k in (-2, -1, 0, 1, 2):
        stroke(d, [(x + k * s * .1, y - s * .42), (x + k * s * .1 + s * .03, y - s * .34)], ow * 0.8, WHITE)


def p_dino(d, x, y, s, ow, rng):
    G = (110, 170, 90)
    body = [(x - s * .5, y - s * .2), (x - s * .3, y - s * .5), (x + s * .1, y - s * .55), (x + s * .35, y - s * .45), (x + s * .38, y - s * .85),
            (x + s * .6, y - s * .88), (x + s * .62, y - s * .7), (x + s * .5, y - s * .6), (x + s * .35, y - s * .2), (x - s * .1, y - s * .2), (x - s * .9, y - s * .1)]
    blob(d, body, G, ow, steps=4)
    for lx in (-0.15, 0.2):
        stroke(d, [(x + s * lx, y - s * .25), (x + s * lx, y)], s * .12 + ow * 2, INK)
        stroke(d, [(x + s * lx, y - s * .25), (x + s * lx, y)], s * .12, G)
    circle(d, (x + s * .5, y - s * .8), s * .03, INK, 0)


def p_bug(d, x, y, s, ow, rng):
    """Long segmented creature (centipede)."""
    n = 11
    for i in range(n):
        cx = x - s * .5 + s * i / (n - 1)
        for sd in (-1, 1):
            stroke(d, [(cx, y - s * .12), (cx + sd * s * .03, y + s * .02)], max(2, ow * 0.8), INK)
        ellipse(d, (cx, y - s * .14), s * .065, s * .1, (112, 74, 60), ow * 0.8)
    circle(d, (x + s * .56, y - s * .14), s * .08, (150, 90, 70), ow * 0.8)


def p_boat(d, x, y, s, ow, rng):
    blob(d, [(x - s * .5, y - s * .25), (x - s * .35, y), (x + s * .35, y), (x + s * .5, y - s * .25)], BROWN, ow, sm=False)
    stroke(d, [(x, y - s * .25), (x, y - s * .95)], ow * 1.4, INK)
    blob(d, [(x + s * .03, y - s * .9), (x + s * .4, y - s * .35), (x + s * .03, y - s * .35)], WHITE, ow, sm=False)


def p_flag(d, x, y, s, ow, rng):
    stroke(d, [(x, y), (x, y - s)], ow * 1.4, INK)
    blob(d, [(x, y - s), (x + s * .45, y - s * .88), (x, y - s * .66)], RED, ow, sm=False)


def p_sign(d, x, y, s, ow, rng):
    stroke(d, [(x, y), (x, y - s * .6)], s * .06 + ow * 2, INK)
    stroke(d, [(x, y), (x, y - s * .6)], s * .06, BROWN)
    blob(d, [(x - s * .35, y - s * .45), (x - s * .35, y - s * .85), (x + s * .35, y - s * .85), (x + s * .35, y - s * .45)], (232, 200, 140), ow, sm=False)


def p_skull(d, x, y, s, ow, rng):
    circle(d, (x, y - s * .5), s * .3, (246, 244, 236), ow)
    blob(d, [(x - s * .16, y - s * .24), (x - s * .16, y - s * .1), (x + s * .16, y - s * .1), (x + s * .16, y - s * .24)], (246, 244, 236), ow, sm=False)
    for sd in (-1, 1):
        circle(d, (x + sd * s * .12, y - s * .52), s * .07, INK, 0)


def p_bomb(d, x, y, s, ow, rng):
    circle(d, (x, y - s * .3), s * .3, (40, 42, 52), ow)
    stroke(d, smooth([(x + s * .15, y - s * .55), (x + s * .3, y - s * .75), (x + s * .4, y - s * .7)], False, 6), ow * 1.2, INK)
    circle(d, (x + s * .42, y - s * .72), s * .06, YEL, ow * 0.7)


def p_bulb(d, x, y, s, ow, rng):
    cy = y - s * .55
    circle(d, (x, cy), s * .28, (255, 238, 140), ow)
    d.rectangle((x - s * .1, cy + s * .26, x + s * .1, cy + s * .4), fill=(190, 194, 200), outline=INK, width=int(ow * 0.8))
    for i in range(7):
        a = math.radians(-160 + i * 22)
        stroke(d, [(x + math.cos(a) * s * .36, cy + math.sin(a) * s * .36), (x + math.cos(a) * s * .5, cy + math.sin(a) * s * .5)], ow, INK)


def p_car(d, x, y, s, ow, rng):
    blob(d, [(x - s * .6, y - s * .1), (x - s * .6, y - s * .3), (x - s * .25, y - s * .35), (x - s * .12, y - s * .58), (x + s * .25, y - s * .58),
             (x + s * .38, y - s * .35), (x + s * .6, y - s * .3), (x + s * .6, y - s * .1)], RED, ow, steps=4)
    for sd in (-1, 1):
        circle(d, (x + sd * s * .33, y - s * .08), s * .13, (40, 40, 46), ow)
        circle(d, (x + sd * s * .33, y - s * .08), s * .05, (190, 190, 196), 0)


def p_pyramid(d, x, y, s, ow, rng):
    blob(d, [(x - s * .6, y), (x, y - s * .75), (x + s * .6, y)], (226, 190, 110), ow, sm=False)
    blob(d, [(x, y - s * .75), (x + s * .6, y), (x + s * .1, y)], (200, 160, 86), ow, sm=False)


def p_mountain(d, x, y, s, ow, rng):
    blob(d, [(x - s * .7, y), (x - s * .1, y - s * .9), (x + s * .15, y - s * .6), (x + s * .35, y - s * .75), (x + s * .85, y)], (130, 136, 150), ow, sm=False)
    blob(d, [(x - s * .24, y - s * .62), (x - s * .1, y - s * .9), (x + s * .04, y - s * .66), (x - s * .05, y - s * .7), (x - s * .14, y - s * .6)], WHITE, ow * 0.8, sm=False)


def p_volcano(d, x, y, s, ow, rng):
    blob(d, [(x - s * .7, y), (x - s * .15, y - s * .7), (x + s * .15, y - s * .7), (x + s * .7, y)], (110, 84, 76), ow, sm=False)
    blob(d, [(x - s * .15, y - s * .7), (x - s * .05, y - s * .95), (x + s * .05, y - s * .78), (x + s * .15, y - s * .7)], ORG, ow * 0.8, sm=False)


def p_wolf(d, x, y, s, ow, rng):
    G = (130, 134, 146)
    blob(d, [(x - s * .5, y - s * .25), (x - s * .4, y - s * .5), (x + s * .2, y - s * .52), (x + s * .35, y - s * .7), (x + s * .5, y - s * .55),
             (x + s * .6, y - s * .5), (x + s * .45, y - s * .4), (x + s * .3, y - s * .25), (x + s * .2, y - s * .15), (x - s * .3, y - s * .15), (x - s * .7, y - s * .5)], G, ow, steps=4)
    for lx in (-0.3, 0.2):
        stroke(d, [(x + s * lx, y - s * .2), (x + s * lx, y)], s * .09 + ow * 2, INK)
        stroke(d, [(x + s * lx, y - s * .2), (x + s * lx, y)], s * .09, G)
    circle(d, (x + s * .42, y - s * .54), s * .025, INK, 0)


def p_pin(d, x, y, s, ow, rng):
    cy = y - s * .7
    blob(d, [(x, y), (x - s * .22, cy + s * .1), (x - s * .25, cy - s * .08), (x, cy - s * .3), (x + s * .25, cy - s * .08), (x + s * .22, cy + s * .1)], RED, ow)
    circle(d, (x, cy - s * .06), s * .09, WHITE, ow * 0.8)


def p_arrow(d, x, y, s, ow, rng):
    stroke(d, smooth([(x - s * .5, y - s * .2), (x - s * .1, y - s * .55), (x + s * .35, y - s * .5)], False, 8), s * .09 + ow * 2, INK)
    stroke(d, smooth([(x - s * .5, y - s * .2), (x - s * .1, y - s * .55), (x + s * .35, y - s * .5)], False, 8), s * .09, RED)
    blob(d, [(x + s * .32, y - s * .66), (x + s * .62, y - s * .48), (x + s * .3, y - s * .34)], RED, ow, sm=False)


def p_grave(d, x, y, s, ow, rng):
    blob(d, [(x - s * .3, y), (x - s * .3, y - s * .5), (x - s * .15, y - s * .7), (x + s * .15, y - s * .7), (x + s * .3, y - s * .5), (x + s * .3, y)], STONE, ow)
    stroke(d, [(x, y - s * .58), (x, y - s * .32)], ow, INK)
    stroke(d, [(x - s * .1, y - s * .5), (x + s * .1, y - s * .5)], ow, INK)


def p_trophy(d, x, y, s, ow, rng):
    blob(d, [(x - s * .25, y - s * .9), (x - s * .2, y - s * .5), (x, y - s * .38), (x + s * .2, y - s * .5), (x + s * .25, y - s * .9)], YEL, ow)
    stroke(d, [(x, y - s * .38), (x, y - s * .15)], s * .06, YEL)
    blob(d, [(x - s * .22, y - s * .15), (x - s * .22, y), (x + s * .22, y), (x + s * .22, y - s * .15)], (190, 150, 40), ow, sm=False)


def p_heart(d, x, y, s, ow, rng):
    cy = y - s * .5
    pts = []
    for i in range(40):
        t = i / 40 * 2 * math.pi
        hx = 16 * math.sin(t) ** 3
        hy = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((x + hx * s * .026, cy - hy * s * .026))
    blob(d, pts, RED, ow, sm=False)


def p_question(d, x, y, s, ow, rng):
    f = _font(s)
    d.text((x, y - s * .5), "?", font=f, fill=YEL, anchor="mm", stroke_width=int(ow * 1.6), stroke_fill=INK)


def p_exclaim(d, x, y, s, ow, rng):
    f = _font(s)
    d.text((x, y - s * .5), "!", font=f, fill=RED, anchor="mm", stroke_width=int(ow * 1.6), stroke_fill=INK)


def p_bed(d, x, y, s, ow, rng):
    blob(d, [(x - s * .6, y - s * .1), (x - s * .6, y - s * .3), (x + s * .6, y - s * .3), (x + s * .6, y - s * .1)], (230, 120, 120), ow, sm=False)
    blob(d, [(x - s * .6, y), (x - s * .6, y - s * .5), (x - s * .5, y - s * .5), (x - s * .5, y)], BROWN, ow, sm=False)
    ellipse(d, (x - s * .38, y - s * .36), s * .17, s * .07, WHITE, ow * 0.8)


def p_food(d, x, y, s, ow, rng):
    ellipse(d, (x, y - s * .1), s * .4, s * .12, WHITE, ow)
    blob(d, [(x - s * .25, y - s * .15), (x - s * .15, y - s * .4), (x + s * .15, y - s * .4), (x + s * .25, y - s * .15)], (214, 150, 80), ow)


def p_gadget(d, x, y, s, ow, rng):
    blob(d, [(x - s * .25, y), (x - s * .25, y - s * .4), (x + s * .25, y - s * .4), (x + s * .25, y)], (110, 116, 124), ow)
    circle(d, (x, y - s * .2), s * .1, RED, ow * 0.8)


PROPS = {
    "tree": p_tree, "palm": p_palm, "pine": p_pine, "fern": p_fern, "rock": p_rock, "boulder": p_boulder, "campfire": p_campfire,
    "house": p_house, "castle": p_castle, "tent": p_tent, "cactus": p_cactus, "cloud": p_cloud, "sun": p_sun, "moon": p_moon,
    "crown": p_crown, "chest": p_chest, "sword": p_sword, "book": p_book, "money": p_money, "computer": p_computer, "phone": p_phone,
    "clock": p_clock, "rocket": p_rocket, "planet": p_planet, "ufo": p_ufo, "monster": p_monster, "dino": p_dino, "bug": p_bug,
    "boat": p_boat, "flag": p_flag, "sign": p_sign, "skull": p_skull, "bomb": p_bomb, "bulb": p_bulb, "car": p_car,
    "pyramid": p_pyramid, "mountain": p_mountain, "volcano": p_volcano, "wolf": p_wolf, "pin": p_pin, "arrow": p_arrow,
    "grave": p_grave, "trophy": p_trophy, "heart": p_heart, "question": p_question, "exclaim": p_exclaim, "bed": p_bed,
    "food": p_food, "gadget": p_gadget,
}
PROP_NAMES = list(PROPS)
# props that float in the air rather than stand on the ground
AIR = {"cloud", "sun", "moon", "planet", "ufo", "rocket", "question", "exclaim", "bulb", "heart", "clock", "arrow"}


# ----------------------------------------------------------------------------- settings
def _clouds(d, W, H, ow, rng, n=3, top=0.05, bot=0.3):
    for _ in range(n):
        cloud(d, rng.uniform(0.1, 0.9) * W, rng.uniform(top, bot) * H, H * rng.uniform(0.05, 0.09), ow)


def s_forest(d, W, H, ow, rng):
    d.rectangle((0, 0, W, H), fill=SKY)
    d.rectangle((0, 0, W, H), fill=vgrad(1, 1, SKY, SKY).getpixel((0, 0)))
    gy = H * 0.74
    for i in range(4):   # background trunks
        x = W * (0.08 + 0.3 * i) + rng.uniform(-0.03, 0.03) * W
        patterned_trunk(d, x, gy, W * 0.11, H * rng.uniform(0.55, 0.7), ow, base=(160, 172, 130))
        palm_top(d, x, gy - H * 0.65, H * 0.22, ow, rng)
    for i in range(3):   # horsetail plants
        x = W * (0.25 + 0.25 * i)
        stroke(d, [(x, gy), (x, gy - H * 0.3)], ow * 1.2, INK)
    d.rectangle((0, gy, W, H), fill=DIRT)
    stroke(d, [(0, gy), (W, gy)], ow, INK)
    for _ in range(3):
        ellipse(d, (rng.uniform(0.2, 0.8) * W, gy + H * rng.uniform(0.04, 0.12)), W * 0.09, H * 0.018, (66, 120, 90), ow * 0.8)
    for x in (0.02, 0.12, 0.95, 0.85):
        fern_bush(d, x * W, gy + H * 0.05, H * 0.2, ow, rng)
    return gy


def s_meadow(d, W, H, ow, rng):
    d.rectangle((0, 0, W, H), fill=SKY)
    _clouds(d, W, H, ow, rng)
    gy = H * 0.72
    blob(d, [(0, gy - H * .05), (W * .25, gy - H * .12), (W * .55, gy - H * .06), (W, gy - H * .14), (W, gy), (0, gy)], (130, 188, 100), ow)
    d.rectangle((0, gy, W, H), fill=GRASS)
    stroke(d, [(0, gy), (W, gy)], ow, INK)
    grass_tufts(d, W, gy, H, ow, rng)
    return gy


def s_desert(d, W, H, ow, rng):
    d.rectangle((0, 0, W, H), fill=(246, 214, 160))
    p_sun(d, W * 0.8, H * 0.28, H * 0.22, ow, rng)
    gy = H * 0.72
    blob(d, [(0, gy - H * .08), (W * .3, gy - H * .16), (W * .7, gy - H * .08), (W, gy - H * .15), (W, gy), (0, gy)], (228, 184, 110), ow)
    d.rectangle((0, gy, W, H), fill=(238, 200, 128))
    stroke(d, [(0, gy), (W, gy)], ow, INK)
    for _ in range(5):
        x = rng.uniform(0, W)
        stroke(d, smooth([(x, gy + H * .08), (x + W * .05, gy + H * .075), (x + W * .1, gy + H * .085)], False, 5), ow * 0.8, (200, 150, 80))
    return gy


def s_sea(d, W, H, ow, rng):
    d.rectangle((0, 0, W, H), fill=SKY)
    _clouds(d, W, H, ow, rng)
    hy = H * 0.5
    d.rectangle((0, hy, W, H * 0.8), fill=(110, 150, 190))
    stroke(d, [(0, hy), (W, hy)], ow, INK)
    for _ in range(4):
        x, y = rng.uniform(0.1, 0.9) * W, rng.uniform(0.55, 0.75) * H
        stroke(d, smooth([(x - W * .04, y), (x - W * .02, y - H * .012), (x, y), (x + W * .02, y - H * .012), (x + W * .04, y)], False, 5), ow * 0.9, WHITE)
    gy = H * 0.78
    d.rectangle((0, gy, W, H), fill=SAND)
    stroke(d, [(0, gy), (W, gy)], ow, INK)
    return gy


def s_city(d, W, H, ow, rng):
    d.rectangle((0, 0, W, H), fill=(190, 218, 236))
    gy = H * 0.78
    x = -W * 0.02
    cols = [(150, 160, 178), (190, 150, 130), (130, 150, 170), (214, 190, 150), (160, 176, 150)]
    i = 0
    while x < W:
        bw = W * rng.uniform(0.14, 0.22)
        bh = H * rng.uniform(0.35, 0.62)
        c = cols[i % len(cols)]
        d.rectangle((x, gy - bh, x + bw, gy), fill=c)
        stroke(d, [(x, gy), (x, gy - bh), (x + bw, gy - bh), (x + bw, gy)], ow, INK)
        for wy in range(int(gy - bh + H * 0.04), int(gy - H * 0.06), int(H * 0.07)):
            for wx in range(int(x + bw * 0.15), int(x + bw * 0.8), int(bw * 0.3)):
                d.rectangle((wx, wy, wx + bw * 0.14, wy + H * 0.04), fill=(240, 232, 170), outline=INK, width=int(ow * 0.6))
        x += bw
        i += 1
    d.rectangle((0, gy, W, H), fill=(96, 100, 110))
    stroke(d, [(0, gy), (W, gy)], ow, INK)
    for k in range(6):
        d.rectangle((W * (k / 6 + 0.03), H * 0.9, W * (k / 6 + 0.09), H * 0.915), fill=(240, 240, 200))
    return gy + H * 0.02


def s_room(d, W, H, ow, rng):
    d.rectangle((0, 0, W, H), fill=(240, 222, 190))
    gy = H * 0.78
    d.rectangle((0, gy, W, H), fill=(190, 140, 96))
    stroke(d, [(0, gy), (W, gy)], ow, INK)
    for k in range(1, 6):
        stroke(d, [(W * k / 6, gy), (W * (k / 6 - 0.5) * 1.3 + W * 0.5 if False else W * k / 6, H)], ow * 0.6, shade((190, 140, 96), 0.75))
    wx, wy = W * 0.62, H * 0.18
    d.rectangle((wx, wy, wx + W * 0.28, wy + H * 0.3), fill=SKY, outline=INK, width=int(ow))
    stroke(d, [(wx + W * 0.14, wy), (wx + W * 0.14, wy + H * 0.3)], ow, INK)
    stroke(d, [(wx, wy + H * 0.15), (wx + W * 0.28, wy + H * 0.15)], ow, INK)
    return gy


def s_space(d, W, H, ow, rng):
    d.rectangle((0, 0, W, H), fill=(18, 20, 52))
    for _ in range(70):
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        r = rng.uniform(1.5, 4.5) * SS
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 250, 220))
    p_planet(d, W * 0.2, H * 0.3, H * 0.3, ow, rng)
    gy = H * 0.84
    blob(d, [(0, gy), (W * .3, gy - H * .03), (W * .6, gy + H * .0), (W, gy - H * .02), (W, H), (0, H)], (150, 150, 168), ow)
    for _ in range(4):
        ellipse(d, (rng.uniform(0.1, 0.9) * W, gy + H * rng.uniform(0.04, 0.1)), W * 0.05, H * 0.014, (120, 120, 140), ow * 0.8)
    return gy


def s_snow(d, W, H, ow, rng):
    d.rectangle((0, 0, W, H), fill=(206, 226, 240))
    p_mountain(d, W * 0.25, H * 0.74, H * 0.7, ow, rng)
    p_mountain(d, W * 0.78, H * 0.74, H * 0.55, ow, rng)
    gy = H * 0.74
    d.rectangle((0, gy, W, H), fill=(246, 250, 252))
    stroke(d, [(0, gy), (W, gy)], ow, INK)
    for _ in range(18):
        x, y = rng.uniform(0, W), rng.uniform(0, H * 0.7)
        r = rng.uniform(2.5, 5) * SS
        d.ellipse((x - r, y - r, x + r, y + r), fill=WHITE)
    return gy


def s_cave(d, W, H, ow, rng):
    d.rectangle((0, 0, W, H), fill=(60, 52, 60))
    gy = H * 0.78
    blob(d, [(0, 0), (W, 0), (W, H * .12), (W * .8, H * .22), (W * .6, H * .1), (W * .4, H * .26), (W * .2, H * .12), (0, H * .2)], (40, 34, 42), ow, sm=False)
    d.rectangle((0, gy, W, H), fill=(92, 80, 84))
    stroke(d, [(0, gy), (W, gy)], ow, INK)
    return gy


def s_ancient(d, W, H, ow, rng):
    d.rectangle((0, 0, W, H), fill=(240, 212, 160))
    p_sun(d, W * 0.2, H * 0.3, H * 0.2, ow, rng)
    gy = H * 0.74
    p_pyramid(d, W * 0.72, gy, H * 0.5, ow, rng)
    d.rectangle((0, gy, W, H), fill=(226, 192, 124))
    stroke(d, [(0, gy), (W, gy)], ow, INK)
    return gy


def s_lab(d, W, H, ow, rng):
    d.rectangle((0, 0, W, H), fill=(222, 236, 246))
    gy = H * 0.78
    d.rectangle((0, gy, W, H), fill=(180, 196, 212))
    stroke(d, [(0, gy), (W, gy)], ow, INK)
    for k in range(3):
        x = W * (0.12 + 0.3 * k)
        d.rectangle((x, H * 0.22, x + W * 0.2, H * 0.4), fill=(150, 200, 230), outline=INK, width=int(ow))
    return gy


def s_night(d, W, H, ow, rng):
    d.rectangle((0, 0, W, H), fill=(28, 36, 78))
    for _ in range(40):
        x, y = rng.uniform(0, W), rng.uniform(0, H * 0.6)
        r = rng.uniform(1.5, 3.5) * SS
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 250, 220))
    p_moon(d, W * 0.78, H * 0.3, H * 0.22, ow, rng)
    gy = H * 0.76
    d.rectangle((0, gy, W, H), fill=(40, 72, 70))
    stroke(d, [(0, gy), (W, gy)], ow, INK)
    return gy


def s_under(d, W, H, ow, rng):
    d.rectangle((0, 0, W, H), fill=(80, 170, 210))
    for _ in range(10):
        x, y = rng.uniform(0, W), rng.uniform(0, H * 0.8)
        circle(d, (x, y), rng.uniform(5, 14) * SS, (190, 232, 246), ow * 0.6)
    gy = H * 0.84
    d.rectangle((0, gy, W, H), fill=(226, 204, 150))
    stroke(d, [(0, gy), (W, gy)], ow, INK)
    return gy


def s_plain(d, W, H, ow, rng, col=(255, 250, 232)):
    d.rectangle((0, 0, W, H), fill=col)
    gy = H * 0.8
    ellipse(d, (W / 2, gy + H * 0.01), W * 0.4, H * 0.02, shade(col, 0.9), 0)
    return gy


def s_map(d, W, H, ow, rng):
    d.rectangle((0, 0, W, H), fill=(255, 255, 255))
    for (cx, cy, rx, ry, col) in ((0.34, 0.45, 0.28, 0.2, (96, 214, 52)), (0.72, 0.5, 0.2, 0.26, (244, 156, 30)), (0.55, 0.78, 0.18, 0.1, (80, 190, 240))):
        pts = []
        for i in range(14):
            a = i / 14 * 2 * math.pi
            k = rng.uniform(0.75, 1.15)
            pts.append((W * cx + math.cos(a) * W * rx * k, H * cy + math.sin(a) * H * ry * k))
        blob(d, pts, col, ow * 1.1, steps=5)
    return H * 0.85


SETTINGS = {
    "forest": s_forest, "meadow": s_meadow, "desert": s_desert, "sea": s_sea, "city": s_city, "room": s_room, "space": s_space,
    "snow": s_snow, "cave": s_cave, "ancient": s_ancient, "lab": s_lab, "night": s_night, "underwater": s_under, "plain": s_plain, "map": s_map,
}
SETTING_NAMES = list(SETTINGS)
