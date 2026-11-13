"""Cartoon storytelling renderer v8 "toon" (only used when VISUAL_STYLE=stickman).

Ink-Explainer look: full-bleed flat-colour cartoon scenes with thick black outlines and one recurring hero
(round white head, blue tee, jeans, sneakers, expressive face). Every scene is composed from the narration line:
setting + up to 3 props + hero pose/expression + optional handwritten-style label. Pure PIL (toon.py / toonscenes.py).
Vertical 9:16 for Shorts, 16:9 for long videos. The cinematic renderer never imports this module.
"""
import math
import random
import re
import subprocess
from pathlib import Path

import numpy as np
import requests
try:
    import cv2
except Exception:   # PIL fallback (slower)
    cv2 = None
from PIL import Image, ImageDraw, ImageFilter

import ai_scenes as A
import toon as T
import toonscenes as S

TRANSITIONS = ["slideleft", "wipeleft", "circleopen", "smoothleft", "zoomin", "slideup", "fadewhite"]
CHUNK = 10
MODELS = ["gemini-3.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"]
MARGIN = 1.10      # world is 10% larger than the frame so the camera can push in
SS = T.SS


def _ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _back(t):
    t = max(0.0, min(1.0, t))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


# ----------------------------------------------------------------------------- layers
def prop_layer(name, size, ow, seed):
    """Draw one prop onto its own RGBA layer. Returns (img, anchor_x, anchor_y) with anchor = ground-centre of the prop."""
    s = size * SS
    Wd, Hd = int(s * 2.4), int(s * 1.5)
    im = Image.new("RGBA", (Wd, Hd), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    bx, by = Wd / 2, Hd * 0.9
    if name in ("army", "crowd"):
        kinds = ["soldier", "soldier", "knight", "soldier", "soldier", "roman"] if name == "army" else \
                ["peasant", "farmer", "girl", "kid", "woman", "oldman", "worker", "hero"]
        rng = random.Random(seed)
        hero_px = size / 6.4                      # one head-radius of a front-row person
        for ri, (sc_, n_) in enumerate(((0.80, 6), (0.72, 7), (0.65, 8))):
            px = hero_px * sc_ * SS
            for k in range(n_):
                who = kinds[(k + ri * 2) % len(kinds)]
                if name == "crowd" and who == "kid":
                    who = "peasant"
                himg, fy, hip = T.draw_hero("stand" if name == "army" else rng.choice(["stand", "wide", "cheer", "shrug"]),
                                            "neutral" if name == "army" else rng.choice(["happy", "neutral", "worried"]), px,
                                            design=who)
                cx = bx + (k - (n_ - 1) / 2) * px * 3.0
                cy = by - (2 - ri) * px * 1.15
                im.alpha_composite(himg, (int(cx - hip[0]), int(cy - fy)))
        box = im.getbbox() or (0, 0, 2, 2)
        im2 = im.crop(box)
        ax, ay = bx - box[0], by - box[1]
        im2 = im2.resize((max(1, im2.width // SS), max(1, im2.height // SS)), Image.LANCZOS)
        return im2, ax / SS, ay / SS
    S.PROPS[name](d, bx, by, s, ow * SS, random.Random(seed))
    box = im.getbbox() or (0, 0, 2, 2)
    im = im.crop(box)
    ax, ay = bx - box[0], by - box[1]
    im = im.resize((max(1, im.width // SS), max(1, im.height // SS)), Image.LANCZOS)
    return im, ax / SS, ay / SS


def label_layer(text, size):
    """Chapter-title plate: white bold text on a dark translucent rounded bar with a gold underline."""
    f = S._font(size * SS)
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    lines = text.upper().split("\n")
    wmax = max(probe.textlength(l, font=f) for l in lines)
    pad = int(size * SS * 0.55)
    lh = size * SS * 1.2
    Wd, Hd = int(wmax + pad * 2), int(lh * len(lines) + pad * 1.4)
    im = Image.new("RGBA", (Wd, Hd), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, Wd - 1, Hd - 1), radius=int(size * SS * 0.35), fill=(12, 14, 20, 176))
    for i, l in enumerate(lines):
        d.text((Wd / 2, pad * 0.7 + lh * (i + 0.5)), l, font=f, fill=(255, 255, 255), anchor="mm")
    d.rectangle((pad, Hd - int(size * SS * 0.16), Wd - pad, Hd - int(size * SS * 0.08)), fill=(255, 205, 40))
    return im.resize((Wd // SS, Hd // SS), Image.LANCZOS)


def effects_layer(kind, R, ow):
    """Small comic marks (speed lines, shock lines, sparkles) drawn around the head; returns RGBA."""
    s = int(R * 6 * SS)
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = s / 2
    w = max(3, ow * SS)
    if kind == "shock":
        for a in (-60, -35, -10, 190, 215, 240):
            r = math.radians(a)
            T.stroke(d, [(c + math.cos(r) * R * 1.7 * SS, c + math.sin(r) * R * 1.7 * SS),
                         (c + math.cos(r) * R * 2.3 * SS, c + math.sin(r) * R * 2.3 * SS)], w, T.INK)
    elif kind == "sweat":
        x, y = c + R * 1.5 * SS, c - R * 0.8 * SS
        T.blob(d, [(x, y - R * .5 * SS), (x + R * .22 * SS, y), (x, y + R * .25 * SS), (x - R * .22 * SS, y)], (150, 210, 250), w * 0.8)
    elif kind == "spark":
        for ang, rr in ((-40, 1.9), (-80, 2.1), (200, 1.9)):
            r = math.radians(ang)
            x, y = c + math.cos(r) * R * rr * SS, c + math.sin(r) * R * rr * SS
            q = R * 0.28 * SS
            T.blob(d, [(x, y - q), (x + q * .3, y - q * .3), (x + q, y), (x + q * .3, y + q * .3), (x, y + q), (x - q * .3, y + q * .3),
                       (x - q, y), (x - q * .3, y - q * .3)], (255, 214, 60), w * 0.6, sm=False)
    elif kind == "zzz":
        f = S._font(R * 0.9 * SS)
        for i, t in enumerate("zZ"):
            d.text((c + R * (1.6 + i * 0.7) * SS, c - R * (1.0 + i * 0.8) * SS), t, font=f, fill=T.WHITE, anchor="mm",
                   stroke_width=int(w), stroke_fill=T.INK)
    elif kind == "question":
        f = S._font(R * 1.3 * SS)
        d.text((c + R * 1.8 * SS, c - R * 1.2 * SS), "?", font=f, fill=(255, 206, 52), anchor="mm", stroke_width=int(w * 1.3), stroke_fill=T.INK)
    return im.resize((s // SS, s // SS), Image.LANCZOS)


def speed_layer(R, ow, side):
    """Trailing speed lines behind a running hero. side=+1 when hero moves right (lines on the left)."""
    Wd, Hd = int(R * 4.5 * SS), int(R * 5 * SS)
    im = Image.new("RGBA", (Wd, Hd), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i in range(4):
        y = Hd * (0.18 + 0.2 * i)
        x0 = Wd * (0.1 + 0.1 * (i % 2))
        T.stroke(d, [(x0, y), (x0 + Wd * 0.55, y)], max(3, ow * SS), T.INK)
    im = im.resize((Wd // SS, Hd // SS), Image.LANCZOS)
    return im if side > 0 else im.transpose(Image.FLIP_LEFT_RIGHT)


def comp(dst, im, x, y):
    """alpha-composite RGBA im onto RGBA dst at (x, y) with clipping."""
    x, y = int(x), int(y)
    sx0, sy0 = max(0, -x), max(0, -y)
    sx1, sy1 = min(im.width, dst.width - x), min(im.height, dst.height - y)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    piece = im.crop((sx0, sy0, sx1, sy1)) if (sx0, sy0, sx1, sy1) != (0, 0, im.width, im.height) else im
    dst.alpha_composite(piece, dest=(x + sx0, y + sy0))


def paste_c(dst, im, cx, cy, scale=1.0, alpha=1.0, sx=None, sy=None):
    sx = scale if sx is None else sx
    sy = scale if sy is None else sy
    if im is None or sx <= 0.02 or sy <= 0.02:
        return
    if abs(sx - 1.0) > 0.01 or abs(sy - 1.0) > 0.01:
        im = im.resize((max(1, int(im.width * sx)), max(1, int(im.height * sy))), Image.BILINEAR)
    if alpha < 0.99:
        a = im.getchannel("A").point(lambda v: int(v * alpha))
        im = im.copy()
        im.putalpha(a)
    comp(dst, im, cx - im.width / 2, cy - im.height / 2)


def shadow_layer(wpx):
    im = Image.new("RGBA", (int(wpx), max(4, int(wpx * 0.16))), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((0, 0, im.width - 1, im.height - 1), fill=(0, 0, 0, 70))
    return im


def spring(t, over=1.0):
    """0->1 with a small overshoot (slick settle)."""
    t = max(0.0, min(1.0, t))
    return 1 + (2.2 * over) * (t - 1) ** 3 + (1.2 * over) * (t - 1) ** 2


PAPER = {"day": (246, 242, 232), "sunset": (250, 232, 206), "night": (118, 128, 166)}
INKC = {"day": (22, 22, 28), "sunset": (24, 22, 28), "night": (30, 34, 56)}
ACC_WARM = (255, 200, 40)    # brand gold (same family as the gold caption word)
ACC_COOL = (64, 118, 214)


def minimal(im, tod="day", bg=False):
    """Minimal ink look: everything is ink / paper / greys, strong colours collapse into just two accents (gold, blue)."""
    mode = "RGB" if im.mode == "RGB" else "RGBA"
    arr = np.asarray(im).astype(np.float32)
    rgb = arr[..., :3]
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = (mx - mn) / (mx + 1e-6)
    L = (0.299 * R + 0.587 * G + 0.114 * B) / 255.0
    lvl = (L if bg else np.round(L * 4) / 4)[..., None]
    ink = np.array(INKC["day" if not bg else tod], np.float32)
    paper = np.array(PAPER["day" if not bg else tod], np.float32)
    base = ink + (paper - ink) * lvl
    acc = np.where((R >= B)[..., None], np.array(ACC_WARM, np.float32), np.array(ACC_COOL, np.float32))
    acc = acc * np.clip(0.62 + 0.5 * L, 0.6, 1.05)[..., None]
    mask = ((sat > (0.72 if bg else 0.42)) & (mx > 100))[..., None]
    out = np.where(mask, acc, base)
    if mode == "RGBA":
        out = np.concatenate([out, arr[..., 3:4]], -1)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), mode)


def tint(im, tod):
    return minimal(im, "day")


def grade_bg(bg, tod, mul, Hc, Hd, rng):
    img = minimal(bg, tod, bg=True)
    if tod == "sunset":
        a = np.asarray(img).astype(np.float32)
        h = a.shape[0]
        yy = np.linspace(0, 1, h)[:, None]
        glow = np.exp(-((yy - 0.46) / 0.2) ** 2)[..., None] * np.array([255, 170, 60], np.float32) * 0.22
        img = Image.fromarray(np.clip(a + glow, 0, 255).astype(np.uint8))
    return img


def build_lut(tod):
    return np.stack([np.arange(256, dtype=np.uint8)] * 3, -1).reshape(256, 1, 3)


def _old_lut(tod):
    x = np.arange(256, dtype=np.float32) / 255.0
    sm = x * x * (3 - 2 * x)
    base = x * 0.55 + sm * 0.45                       # gentle S-curve contrast
    r = base * 1.02 + 0.015 * x
    g = base
    b = base * 0.97 + 0.03 * (1 - x) * (1.0 if tod != "night" else 1.4)   # teal in the shadows, warm highlights
    lut = np.stack([r, g, b], axis=-1)
    return (np.clip(lut, 0, 1) * 255).astype(np.uint8).reshape(256, 1, 3)


def make_grain(w, h, n=5, amp=3):
    rng = np.random.default_rng(7)
    out = []
    for _ in range(n):
        nz = rng.integers(-amp, amp + 1, (h // 2, w // 2, 1)).astype(np.int16)
        nz = np.repeat(np.repeat(nz, 2, 0), 2, 1)[:h, :w]
        out.append((np.clip(nz, 0, 255).astype(np.uint8).repeat(3, 2), np.clip(-nz, 0, 255).astype(np.uint8).repeat(3, 2)))
    return out


def blend_layers(bg, fg, bbox, fbox, w, h):
    """Crop+scale the world background and the transparent foreground (different windows = parallax) and composite -> RGB array."""
    if cv2 is None:
        b = bg.convert("RGBA").resize((w, h), Image.BILINEAR, box=bbox)
        b.alpha_composite(fg.resize((w, h), Image.BILINEAR, box=fbox))
        return np.asarray(b.convert("RGB"))

    def warp(img, box, ch):
        arr = np.asarray(img)
        sx, sy = w / (box[2] - box[0]), h / (box[3] - box[1])
        M = np.array([[sx, 0, -box[0] * sx], [0, sy, -box[1] * sy]], np.float32)
        return cv2.warpAffine(arr, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    b = warp(bg, bbox, 3)
    f = warp(fg, fbox, 4)
    a = f[..., 3:4].astype(np.uint16)
    out = (b.astype(np.uint16) * (255 - a) + f[..., :3].astype(np.uint16) * a + 127) // 255
    return out.astype(np.uint8)


PARTICLES = {"snow": "snow", "desert": "dust", "ancient": "dust", "underwater": "bubbles", "night": "stars", "space": "stars",
             "forest": "pollen", "meadow": "pollen", "cave": "dust", "sea": "pollen"}


class Scene:
    def __init__(self, w, h, spec, idx, seed, words=None, span=4.0):
        self.w, self.h, self.idx = w, h, idx
        land = w >= h
        self.land = land
        self.Wd, self.Hd = int(w * MARGIN), int(h * MARGIN)
        self.Hc = int(self.Hd * (1.0 if land else 0.90))
        ow = S.ow_for(self.Hd)
        self.ow = ow
        rng = random.Random(seed * 131 + idx)
        self.rng = rng
        self.words = words or []
        # ---- background
        big = Image.new("RGB", (self.Wd * SS, self.Hc * SS), (255, 255, 255))
        d = ImageDraw.Draw(big)
        setting = spec.get("setting") if spec.get("setting") in S.SETTINGS else "meadow"
        self.setting = setting
        gy = S.SETTINGS[setting](d, self.Wd * SS, self.Hc * SS, ow * SS, rng) / SS
        self.gy = gy
        bg = big.resize((self.Wd, self.Hc), Image.LANCZOS)
        if self.Hc < self.Hd:
            full = Image.new("RGB", (self.Wd, self.Hd))
            full.paste(bg, (0, 0))
            strip = bg.crop((0, self.Hc - 3, self.Wd, self.Hc - 1)).resize((self.Wd, self.Hd - self.Hc + 1))
            full.paste(strip, (0, self.Hc - 1))
            dd = ImageDraw.Draw(full)
            base = strip.getpixel((5, 5))
            drk = S.shade(base, 0.78)
            for _ in range(26):
                x = rng.uniform(0, self.Wd)
                y = rng.uniform(self.Hc + self.Hd * 0.01, self.Hd * 0.985)
                r = rng.uniform(0.006, 0.014) * self.Hd
                if rng.random() < 0.5:
                    dd.ellipse((x - r * 1.6, y - r * .8, x + r * 1.6, y + r * .8), fill=drk)
                else:
                    for kx in (-1, 0, 1):
                        T.stroke(dd, [(x, y), (x + kx * r, y - r * 1.6)], max(3, ow * 0.9), drk)
            bg = full
        vg = np.ones((self.Hd, self.Wd), np.float32)
        yy_, xx_ = np.mgrid[0:self.Hd, 0:self.Wd]
        rr_ = np.sqrt(((xx_ - self.Wd / 2) / (self.Wd / 2)) ** 2 + ((yy_ - self.Hd / 2) / (self.Hd / 2)) ** 2)
        vg = 1.0 - 0.24 * np.clip(rr_ - 0.55, 0, 1) ** 1.5
        bg = Image.fromarray((np.asarray(bg, dtype=np.float32) * vg[..., None]).astype(np.uint8)).filter(ImageFilter.GaussianBlur(self.Hd * 0.0018))
        self.tod = spec.get("tod") if spec.get("tod") in ("day", "sunset", "night") else ("night" if setting in ("night", "space") else "day")
        self.mul = self.tod
        bg = grade_bg(bg, self.tod, self.mul, self.Hc, self.Hd, rng)
        self.bg = bg
        # ---- characters
        chars = spec.get("chars") or [dict(who="hero", pose=spec.get("pose", "stand"), pose2=spec.get("pose2", "stand"), expr=spec.get("expr", "neutral"))]
        chars = chars[:2]
        self.n = len(chars)
        side = 0 if spec.get("hero_side", "left") == "left" else 1
        self.side = side
        self.shot = spec.get("shot") if spec.get("shot") in ("wide", "medium", "close") else "medium"
        if self.n == 2 and self.shot == "close":
            self.shot = "medium"
        shot_k = {"wide": 0.62, "medium": 0.88, "close": 1.55 if land else 1.5}[self.shot]
        hero_h = (0.58 if land else 0.46) * self.Hc * (1.0 if self.n == 1 else 0.84) * shot_k
        hero_h = min(hero_h, self.Hc * 0.9)
        self.persp = setting in ("street", "city", "village", "field")
        self.feet_persp = None
        if self.persp:   # person height follows the street's own perspective so people and buildings share one scale
            vpy_, G_ = self.Hc * 0.46, self.Hc * 0.56
            z_ = {"wide": 2.3, "medium": 1.5, "close": 1.0}[self.shot]
            hero_h = 1.06 * G_ / z_ * (1.0 if self.n == 1 else 0.9)
            self.feet_persp = vpy_ + G_ / z_
        self.chars = []
        if self.n == 1:
            xs = [self.Wd * ((0.34 if side == 0 else 0.66) if land else (0.38 if side == 0 else 0.62))]
        else:
            xs = [self.Wd * (0.30 if land else 0.31), self.Wd * (0.70 if land else 0.69)]
        for k, c in enumerate(chars):
            who = c.get("who") if str(c.get("who", "")).split(":")[0] in T.DESIGNS else "hero"
            des = dict(T.design_for(who))
            if des["headc"] != T.WHITE:
                l_ = int(0.299 * des["headc"][0] + 0.587 * des["headc"][1] + 0.114 * des["headc"][2])
                des["headc"] = (l_, l_, l_)
            p1 = c.get("pose") if c.get("pose") in T.POSES else "stand"
            p2 = c.get("pose2") if c.get("pose2") in T.POSES else p1
            ex = c.get("expr") if c.get("expr") in T.EXPR else "neutral"
            R = hero_h / 6.4 * des["scale"]
            fl = (k == 1) if self.n == 2 else (side == 1)
            ch = dict(who=who, des=des, p1=p1, p2=p2, expr=ex, R=R, x=xs[k], flip=fl, cache={}, delay=0.12 * k, side=-1 if xs[k] < self.Wd / 2 else 1)
            fx = None
            if ex in ("shocked",):
                fx = effects_layer("shock", R, ow)
            elif ex in ("scared", "worried"):
                fx = effects_layer("sweat", R, ow)
            elif ex in ("happy", "excited"):
                fx = effects_layer("spark", R, ow)
            elif ex == "sleepy":
                fx = effects_layer("zzz", R, ow)
            elif ex == "think":
                fx = effects_layer("question", R, ow)
            ch["fx"] = minimal(fx) if fx is not None else None
            ch["speed"] = speed_layer(R, ow, -1 if fl else 1) if p1 in ("run", "flee") else None
            ch["shadow"] = shadow_layer(R * 3.2)
            self.chars.append(ch)
        self.feet = gy + self.Hc * 0.045
        if self.feet_persp is not None:
            self.feet = self.feet_persp
            gy = self.feet - self.Hc * 0.045
            self.gy = gy
        if self.shot == "close":
            self.feet = self.Hc * 0.10 + hero_h * 0.97
        self.hero_h = hero_h
        chars_R = max(c["R"] for c in self.chars)
        # ---- props: sized in hero-heights, placed only in free horizontal gaps so nothing overlaps or floats
        self.props = []
        names = [p for p in spec.get("props", []) if p in S.PROPS]
        ground = [p for p in names if p not in S.AIR][:1]
        air = [p for p in names if p in S.AIR][:1]
        if self.shot == "close":
            ground = []
        hh = self.hero_h
        lo_x, hi_x = self.Wd * 0.075, self.Wd * 0.925
        taken = sorted((c["x"] - chars_R * 3.4, c["x"] + chars_R * 3.4) for c in self.chars)
        gaps, cur = [], lo_x
        for a_, b_ in taken:
            if a_ > cur:
                gaps.append([cur, min(a_, hi_x)])
            cur = max(cur, b_)
        if cur < hi_x:
            gaps.append([cur, hi_x])
        pref = [self.Wd * (0.70 if side == 0 else 0.30) if self.n == 1 else self.Wd * 0.5, self.Wd * 0.5]
        for i, name in enumerate(ground):
            gaps = [g for g in gaps if g[1] - g[0] > self.Wd * 0.08]
            if not gaps:
                break
            sz = hh * S.SCALE.get(name, 1.0) * (1.0 if i == 0 else 0.8)
            big = name in ("castle", "tower", "windmill", "pyramid", "mountain", "volcano", "house", "palm", "dino", "pine", "tree", "hut")
            sz = min(sz, self.Hc * (0.85 if big else 0.5))
            im, ax, ay = prop_layer(name, sz, ow, seed + i)
            g = min(gaps, key=lambda g_: abs((g_[0] + g_[1]) / 2 - pref[i]))
            room = g[1] - g[0]
            if im.width > room:
                k2 = room / im.width
                im = im.resize((max(1, int(im.width * k2)), max(1, int(im.height * k2))), Image.LANCZOS)
                ax, ay = ax * k2, ay * k2
            cx = min(max(pref[i], g[0] + im.width / 2), g[1] - im.width / 2)
            # split the gap so the next prop cannot overlap
            l_, r_ = cx - im.width / 2 - self.Wd * 0.02, cx + im.width / 2 + self.Wd * 0.02
            gaps.remove(g)
            gaps += [[g[0], l_], [r_, g[1]]]
            y = gy + self.Hc * (0.05 if i == 0 else 0.015)
            self.props.append(dict(im=im, x=cx - ax + im.width / 2, y=y - ay + im.height / 2, behind=False, delay=0.10 + 0.2 * i, name=name,
                                   shadow=shadow_layer(im.width * 0.9), air=False, bx=cx, by=y))
        head_top = self.feet - hh * 1.02
        for i, name in enumerate(air):
            sz = min(max(hh * S.SCALE.get(name, 0.6), self.Hc * 0.12), self.Hc * 0.22)
            im, ax, ay = prop_layer(name, sz, ow, seed + 7 + i)
            ay_ = self.Hc * 0.2
            if ay_ + im.height * 0.8 > head_top - self.Hc * 0.02:
                continue
            ax_ = self.Wd * (0.70 if side == 0 else 0.30) if self.n == 1 else self.Wd * 0.5
            self.props.append(dict(im=im, x=ax_, y=ay_ + im.height * 0.35, behind=False, delay=0.3 + 0.2 * i, name=name, shadow=None, air=True, bx=ax_, by=ay_))
        for p in self.props:
            p["im"] = tint(p["im"], self.mul)
        self.fire = next((p for p in self.props if p["name"] == "campfire"), None)
        # ---- label
        self.label = None
        lab = (spec.get("label") or "").strip() if self.shot != "close" else ""
        if lab:
            lab = lab[:28]
            ws = lab.split()
            if len(ws) > 2 or len(lab) > 14:
                half = (len(ws) + 1) // 2
                lab = " ".join(ws[:half]) + "\n" + " ".join(ws[half:])
            self.label = label_layer(lab, self.Hc * (0.07 if land else 0.052))
        # ---- camera + particles
        kinds = ["push", "pull", "pan", "push", "pan2", "pull"]
        self.cam = "punch" if any(c["expr"] in ("shocked", "scared") for c in self.chars) else kinds[(idx + seed) % len(kinds)]
        self.pkind = PARTICLES.get(setting)
        self.parts = [(rng.random(), rng.random(), rng.uniform(0.4, 1.0), rng.uniform(0.5, 1.6)) for _ in range(28)]

    def hero(self, ch, blend, blink, mouth):
        key = (round(blend * 5), blink, mouth)
        if key not in ch["cache"]:
            pose = T.blend_pose(ch["p1"], ch["p2"], key[0] / 5)
            img, fy, hip = T.draw_hero(pose, ch["expr"], ch["R"], blinking=blink, flip=ch["flip"], mouth_open=key[2] / 2.0, design=ch["des"])
            bb = img.getbbox() or (0, 0, img.width, img.height)
            ch["cache"][key] = (tint(img.crop(bb), self.mul), fy - bb[1], (hip[0] - bb[0], hip[1] - bb[1]))
        return ch["cache"][key]

    def talking(self, t, k):
        if not self.words:
            return 0.0
        for a, b in self.words:
            if a <= t <= b:
                return abs(math.sin(t * 14 + k))
        return 0.0


def _bump(x):
    return math.exp(-x * x)


def render_scene(sc, span, dest, w, h, fps):
    frames = max(2, int(round(span * fps)))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
           "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(dest)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    Wd, Hd = sc.Wd, sc.Hd
    bgA = sc.bg
    lut = build_lut(sc.tod)
    grain = make_grain(w, h) if cv2 is not None else None
    try:
        for f in range(frames):
            t = f / fps
            k = _ease(f / max(1, frames - 1))
            fg = Image.new("RGBA", (Wd, Hd), (0, 0, 0, 0))
            # behind props
            for p in sc.props:
                if p["behind"]:
                    paste_c(fg, p["im"], p["x"], p["y"], max(0.05, _back((t - p["delay"]) / 0.4)))
            # characters
            speaker = 0 if sc.n == 1 else (0 if t < span * 0.5 else 1)
            for ci, ch in enumerate(sc.chars):
                tt = t - ch["delay"]
                R = ch["R"]
                tm = span * (0.5 if ci == 0 else 0.62)
                blend = spring((tt - tm) / 0.5) if ch["p2"] != ch["p1"] else 0.0
                blink = ((t + ci * 0.9) % 3.1) > 2.95
                mq = 0
                if ci == speaker:
                    m = sc.talking(t, ci)
                    mq = 0 if m < 0.2 else (1 if m < 0.6 else 2)
                himg, fy, hip = sc.hero(ch, blend, blink, mq)
                ent = max(0.0, min(1.0, tt / 0.55))
                off = (1 - spring(ent)) * Wd * 0.3 * ch["side"] * -1
                hop = -math.sin(math.pi * min(1.0, ent)) * R * 0.45 if ent < 1 else 0
                land_b = _bump((tt - 0.55) / 0.09) if tt > 0.3 else 0.0
                breathe = math.sin(t * 2.4 + ci) * 0.012
                sxs = 1 + 0.09 * land_b - breathe + (0.05 * math.sin(math.pi * ent) if ent < 1 else 0) * -1
                sys_ = 1 - 0.10 * land_b + breathe + (0.07 * math.sin(math.pi * ent) if ent < 1 else 0)
                sway = math.sin(t * 1.7 + ci * 1.3) * 1.1
                xf = ch["x"] + off
                yf = sc.feet + hop
                # shadow
                sh = ch["shadow"]
                shs = 1.0 - min(0.25, abs(hop) / (R * 3))
                paste_c(fg, sh, xf, sc.feet + sc.Hc * 0.004, 1.0, 0.9 * ent, sx=shs, sy=shs)
                if ch["speed"] is not None and tt > 0.1:
                    sx_ = xf - (1 if not ch["flip"] else -1) * R * 3.2
                    paste_c(fg, ch["speed"], sx_ + math.sin(t * 30) * R * 0.1, yf - R * 3.2, 1.0, 0.9)
                im2 = himg
                if abs(sxs - 1) > 0.004 or abs(sys_ - 1) > 0.004:
                    im2 = himg.resize((max(1, int(himg.width * sxs)), max(1, int(himg.height * sys_))), Image.BILINEAR)
                    fy2, hx2, hy2 = fy * sys_, hip[0] * sxs, hip[1] * sys_
                else:
                    fy2, hx2, hy2 = fy, hip[0], hip[1]
                comp(fg, im2, xf - hx2, yf - fy2)
                if ch["fx"] is not None and tt > 0.3:
                    paste_c(fg, ch["fx"], xf, yf - fy2 + hy2 - R * 2.95, max(0.1, _back((tt - 0.3) / 0.3)))
            # front props
            for p in sc.props:
                if not p["behind"]:
                    s_ = max(0.05, _back((t - p["delay"]) / 0.4))
                    yy = p["y"]
                    if p["air"]:
                        yy += math.sin(t * 2.6 + p["delay"] * 5) * sc.Hc * 0.008
                    if p["shadow"] is not None and s_ > 0.3:
                        paste_c(fg, p["shadow"], p["bx"], p["by"] + sc.Hc * 0.004, 1.0, 0.8)
                    sc_x = s_
                    sc_y = s_
                    if p is sc.fire:
                        sc_y *= 1 + 0.035 * math.sin(t * 17)
                        sc_x *= 1 - 0.02 * math.sin(t * 17)
                    paste_c(fg, p["im"], p["x"], yy, sx=sc_x, sy=sc_y)
            if sc.label is not None and t > 0.15:
                lp = _back((t - 0.15) / 0.35)
                lx = Wd * 0.075 + sc.label.width / 2 if sc.land else Wd / 2
                ly = Hd * (0.10 if sc.land else 0.08) + sc.label.height / 2
                paste_c(fg, sc.label, lx - (1 - min(1.0, lp)) * Wd * 0.05, ly, 1.0, min(1.0, max(0.0, lp)))
            # ---- camera (bg moves less than fg -> parallax)
            c0 = sc.chars[0]["x"] / Wd
            if sc.cam == "push":
                z, cx = 1.05 + 0.11 * k, 0.5 + (c0 - 0.5) * 0.3 * k
            elif sc.cam == "pull":
                z, cx = 1.16 - 0.11 * k, 0.5 + (c0 - 0.5) * 0.3 * (1 - k)
            elif sc.cam == "pan":
                z, cx = 1.13, 0.44 + 0.12 * k
            elif sc.cam == "pan2":
                z, cx = 1.13, 0.56 - 0.12 * k
            else:  # punch: fast zoom-in with a little shake
                z = 1.04 + 0.12 * _ease(t / 0.35) + 0.03 * k
                cx = 0.5 + (c0 - 0.5) * 0.25
            shake = 0.0
            if sc.cam == "punch" and t < 0.6:
                shake = math.sin(t * 60) * (1 - t / 0.6) * 0.004
            cy = 0.5 + shake

            def win(zz, cxx):
                ww, wh = Wd / zz, Hd / zz
                x0 = min(max(cxx * Wd - ww / 2, 0), Wd - ww)
                y0 = min(max(cy * Hd - wh / 2, 0), Hd - wh)
                return (x0, y0, x0 + ww, y0 + wh)
            zb = 1 + (z - 1) * 0.55
            frame = blend_layers(bgA, fg, win(zb, 0.5 + (cx - 0.5) * 0.5), win(z, cx), w, h)
            if sc.pkind or sc.fire is not None:
                frame = Image.fromarray(frame)
                dr = ImageDraw.Draw(frame)
                unit = h / 1000
                for (a, bb, sp, sz) in sc.parts:
                    if sc.pkind == "snow":
                        x, y, col, r = (a * w + math.sin(t * sp + bb * 9) * 30 * unit) % w, ((bb + t * 0.09 * sp) % 1) * h, (255, 255, 255), 5 * sz * unit
                    elif sc.pkind == "bubbles":
                        x, y, col, r = (a * w + math.sin(t * 2 * sp + bb * 7) * 22 * unit) % w, (1 - ((bb + t * 0.07 * sp) % 1)) * h, (210, 240, 252), 6 * sz * unit
                    elif sc.pkind == "stars":
                        x, y, col, r = a * w, bb * h * 0.7, (255, 250, 220), (2.5 + 2.5 * abs(math.sin(t * 2.5 * sp + a * 9))) * unit
                    elif sc.pkind == "dust":
                        x, y, col, r = (a * w + t * 40 * sp * unit) % w, (bb * 0.8 + 0.1) * h + math.sin(t * sp + a * 5) * 14 * unit, (255, 246, 224), 3.5 * sz * unit
                    elif sc.pkind == "pollen":
                        x, y, col, r = (a * w + t * 26 * sp * unit) % w, (bb * 0.7 + 0.05) * h + math.sin(t * 1.5 * sp + a * 7) * 18 * unit, (255, 248, 200), 3.2 * sz * unit
                    else:
                        continue
                    dr.ellipse((x - r, y - r, x + r, y + r), fill=col)
                if sc.fire is not None:
                    for (a, bb, sp, sz) in sc.parts[:10]:
                        life = (t * 0.5 * sp + bb) % 1
                        fx_ = (sc.fire["bx"] / Wd) * w + math.sin(life * 9 + a * 6) * 26 * unit - (w - w) 
                        fy_ = (sc.fire["by"] / Hd) * h - life * 260 * unit - 60 * unit
                        r = (5 - 4 * life) * sz * unit
                        dr.ellipse((fx_ - r, fy_ - r, fx_ + r, fy_ + r), fill=(255, int(190 - 80 * life), 60))
                frame = np.asarray(frame)
            if cv2 is not None:
                frame = cv2.LUT(np.ascontiguousarray(frame), lut)
                gp, gn = grain[f % len(grain)]
                frame = cv2.subtract(cv2.add(frame, gp), gn)
            proc.stdin.write(np.ascontiguousarray(frame).tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed for stickman scene")


# ----------------------------------------------------------------------------- planning
KW = [  # (regex, dict(setting?, props?, expr?, pose?))
    (r"\b(army|armies|military|troops?|regiment|infantry|invade\w*|invasion)\b", dict(props=["army"], expr="angry", pose="point", tod="sunset")),
    (r"\b(crowd|people|everyone|villagers?|citizens|population|town|mob|protest\w*)\b", dict(props=["crowd"])),
    (r"\b(farm|farmer|crops?|harvest|field|fields|wheat|barn)\b", dict(setting="field", props=["hay", "windmill"], tod="sunset")),
    (r"\b(village|medieval|middle ages|market|street|cobble\w*|old town)\b", dict(setting="street", props=["barrel", "wagon"])),
    (r"\b(chicken|chickens|hen|hens|rooster|egg|eggs)\b", dict(props=["chicken"])),
    (r"\b(horse|horses|cavalry|ride|riding)\b", dict(props=["horse"])),
    (r"\b(cow|cows|cattle|milk)\b", dict(props=["cow"])),
    (r"\b(sheep|wool|shepherd)\b", dict(props=["sheep"])),
    (r"\b(dog|dogs|puppy)\b", dict(props=["dog"])),
    (r"\b(barrel|barrels|wine|beer)\b", dict(props=["barrel"])),
    (r"\b(coin|coins|tax|taxes|salary|wage|wages|earn\w*|profit|trade|trading|sell|sold|buy|bought)\b", dict(props=["coin"])),
    (r"\b(cannon|artillery|gun|guns|weapon\w*|firearm\w*)\b", dict(props=["cannon"])),
    (r"\b(tank|tanks)\b", dict(props=["tank"])),
    (r"\b(plane|planes|airplane|bomber|aircraft)\b", dict(props=["plane"])),
    (r"\b(tower|fortress|wall|walls|siege)\b", dict(props=["tower"])),
    (r"\b(shield|armor|armour)\b", dict(props=["shield"])),
    (r"\b(spear|spears|lance)\b", dict(props=["spear"])),
    (r"\b(throne|crown|kingdom)\b", dict(props=["throne"])),
    (r"\b(school|teach\w*|class|lesson|board|math|numbers?)\b", dict(props=["blackboard"])),
    (r"\b(sunset|evening|dusk|golden)\b", dict(tod="sunset")),
    (r"\b(night|midnight|dark|moonlight)\b", dict(tod="night")),
    (r"\b(jungle|forest|rainforest|swamp|prehistoric|dinosaur|carboniferous|cretaceous|jurassic)\b", dict(setting="forest", props=["fern"])),
    (r"\b(desert|sahara|dune|egypt|pyramid|pharaoh)\b", dict(setting="desert", props=["pyramid", "cactus"])),
    (r"\b(ocean|sea|beach|island|shore|coast|cliff)\b", dict(setting="sea", props=["boat"])),
    (r"\b(underwater|shark|whale|fish|dive|diving)\b", dict(setting="underwater")),
    (r"\b(city|street|downtown|traffic|urban|skyscraper|building)\b", dict(setting="city", props=["car"])),
    (r"\b(house|home|room|bedroom|kitchen|indoors?|apartment)\b", dict(setting="room", props=["bed"])),
    (r"\b(space|planet|galaxy|astronaut|alien|mars|universe|moon|orbit)\b", dict(setting="space", props=["planet", "ufo"])),
    (r"\b(snow|ice|winter|freez\w*|arctic|glacier|cold)\b", dict(setting="snow", props=["pine"])),
    (r"\b(cave|underground|tunnel|dark)\b", dict(setting="cave")),
    (r"\b(ancient|rome|roman|empire|medieval|knight|castle|king|queen|kingdom|war|battle|soldier)\b", dict(setting="meadow", props=["castle", "sword"])),
    (r"\b(lab|laborator\w*|science|scientist|experiment|chemical|virus|research)\b", dict(setting="lab", props=["bulb"])),
    (r"\b(night|midnight|sleep|asleep|dream)\b", dict(setting="night", props=["moon"], expr="sleepy")),
    (r"\b(fire|burn\w*|flame|camp|campfire|warm)\b", dict(props=["campfire"])),
    (r"\b(volcano|lava|erupt\w*)\b", dict(props=["volcano"])),
    (r"\b(money|rich|wealth\w*|cash|dollar\w*|price|cost|pay|paid|billion\w*|million\w*|gold)\b", dict(props=["money"], expr="excited")),
    (r"\b(time|clock|hour\w*|minutes?|seconds?|years?|days?|forever|late|deadline)\b", dict(props=["clock"])),
    (r"\b(idea|think\w*|thought|imagine|wonder\w*|why|how|what if|mystery|secret)\b", dict(props=["question"], expr="think", pose="think")),
    (r"\b(danger\w*|deadly|kill\w*|die|dead|death|dying|poison\w*|bomb|explod\w*|explosion)\b", dict(props=["skull"], expr="scared", pose="scared")),
    (r"\b(run|runs|running|escape|flee|chase\w*|hunt\w*|attack\w*|monster|predator|creature)\b", dict(props=["monster"], expr="scared", pose="flee")),
    (r"\b(wolf|wolves|dog)\b", dict(props=["wolf"])),
    (r"\b(computer|internet|online|code|software|digital|hack\w*|screen|ai)\b", dict(props=["computer"])),
    (r"\b(phone|call|text|message|app|social)\b", dict(props=["phone"])),
    (r"\b(book|read|story|history|learn\w*|school|study|lesson)\b", dict(props=["book"])),
    (r"\b(win|won|winner|best|first|champion\w*|record|success\w*|victory)\b", dict(props=["trophy"], expr="happy", pose="cheer")),
    (r"\b(love|heart|friend\w*|family|happy|joy|fun|celebrate\w*)\b", dict(props=["heart"], expr="happy", pose="wide")),
    (r"\b(shock\w*|suddenly|unbelievable|crazy|insane|wow|incredible|impossible|never)\b", dict(props=["exclaim"], expr="shocked", pose="scared")),
    (r"\b(sad|cry\w*|lost|lose|loser|fail\w*|alone|lonely)\b", dict(expr="sad", pose="shrug")),
    (r"\b(angry|furious|hate|enemy|fight\w*)\b", dict(expr="angry", pose="hips")),
    (r"\b(food|eat|eating|hungry|dinner|lunch|meal|starv\w*)\b", dict(props=["food"])),
    (r"\b(treasure|chest|pirate|prize|reward)\b", dict(props=["chest"])),
    (r"\b(car|drive|driving|road|race|racing)\b", dict(props=["car"])),
    (r"\b(rocket|launch\w*|fly|flying|flight|plane)\b", dict(props=["rocket"])),
    (r"\b(map|where|country|north\w*|south\w*|east\w*|west\w*|england|america|africa|nigeria|europe|asia|world)\b", dict(setting="map", props=["pin"])),
]


CASTKW = [
    (r"\b(army|armies|soldiers?|military|troops?|regiment|infantry|war|invade\w*|invasion)\b", "soldier"),
    (r"\b(general|commander|marshal|dictator)\b", "general"),
    (r"\b(viking\w*|norse|raid\w*)\b", "viking"),
    (r"\b(roman|rome|gladiator|legion\w*|caesar)\b", "roman"),
    (r"\b(pharaoh|egypt\w*|pyramids?)\b", "pharaoh"),
    (r"\b(farmer|farm|harvest|crops?|field|fields|village\w*|peasants?|serf\w*|villagers?)\b", "peasant"),
    (r"\b(wizard|magic\w*|witch|sorcer\w*|spell)\b", "wizard"),
    (r"\b(police|cop|arrest\w*|crime|criminal|thief|prison)\b", "police"),
    (r"\b(chef|cook\w*|restaurant|kitchen)\b", "chef"),
    (r"\b(teacher|class|classroom|student|lesson|school)\b", "teacher"),
    (r"\b(ninja|samurai|assassin|spy)\b", "ninja"),
    (r"\b(alien|ufo|extraterrestrial)\b", "alien"),
    (r"\b(worker|workers|construction|factory|labou?r|build\w*|mine|miner\w*)\b", "worker"),
    (r"\b(queen|princess)\b", "queen"),
    (r"\b(king|queen|royal|throne|emperor|pharaoh|monarch)\b", "king"),
    (r"\b(knight|soldier|army|warrior|battle|guard)\b", "knight"),
    (r"\b(scientist|experiment|lab|laborator\w*|professor|research\w*|inventor|invent\w*)\b", "scientist"),
    (r"\b(astronaut|space|rocket|moon|mars|orbit)\b", "astronaut"),
    (r"\b(pirate|ship|treasure|sailor|captain)\b", "pirate"),
    (r"\b(caveman|cave|prehistoric|stone age|neanderthal)\b", "caveman"),
    (r"\b(explorer|expedition|jungle|safari|adventur\w*)\b", "explorer"),
    (r"\b(grandfather|grandpa|old man|elder|wise)\b", "oldman"),
    (r"\b(girl|she|her|mother|mom|woman|lady|daughter|sister)\b", "girl"),
    (r"\b(kid|child|children|boy|son|baby)\b", "kid"),
    (r"\b(boss|ceo|business|company|corporation|billionaire|banker|bank|tax\w*)\b", "boss"),
    (r"\b(robot|ai|machine|android|computer)\b", "robot"),
    (r"\b(doctor|hospital|virus|disease|medicine|patient|nurse|sick)\b", "doctor"),
    (r"\b(cowboy|wild west|sheriff|outlaw|ranch)\b", "cowboy"),
]


def keyword_chars(text, i, spec):
    low = text.lower()
    roles = []
    for rx, who in CASTKW:
        if re.search(rx, low) and who not in roles:
            roles.append(who)
    pose, expr = spec["pose"], spec["expr"]
    if not roles:
        return [dict(who="hero", pose=pose, pose2=spec["pose2"], expr=expr)]
    r1 = roles[0]
    if len(roles) >= 2 and i % 3 != 0:
        return [dict(who=roles[0], pose=pose, pose2=spec["pose2"], expr=expr),
                dict(who=roles[1], pose="stand" if pose != "stand" else "wide", pose2="shrug", expr="neutral")]
    if re.search(r"\b(you|your|we)\b", low):
        return [dict(who="hero", pose=pose, pose2=spec["pose2"], expr=expr), dict(who=r1, pose="point" if i % 2 else "stand", pose2="shrug", expr="smug")]
    return [dict(who=r1, pose=pose, pose2=spec["pose2"], expr=expr)]


def keyword_plan(text, i, prev):
    spec = dict(setting=prev.get("setting", "meadow") if prev else "meadow", props=[], expr="neutral", pose="stand", label="")
    props = []
    for rx, v in KW:
        if re.search(rx, text.lower()):
            if "setting" in v and not spec.get("_set"):
                spec["setting"] = v["setting"]
                spec["_set"] = True
            for p in v.get("props", []):
                if p not in props:
                    props.append(p)
            if "expr" in v and spec["expr"] == "neutral":
                spec["expr"] = v["expr"]
            if "pose" in v and spec["pose"] == "stand":
                spec["pose"] = v["pose"]
            if "tod" in v and "tod" not in spec:
                spec["tod"] = v["tod"]
    spec.pop("_set", None)
    spec["props"] = props[:3] or [S.PROP_NAMES[(i * 7) % len(S.PROP_NAMES)]]
    poses = list(T.POSES)
    if spec["pose"] == "stand":
        spec["pose"] = ["wide", "point", "stand", "think", "shrug", "hold", "hips"][i % 7]
    safe = ["stand", "wide", "point", "shrug", "hold", "hips", "think", "cheer", "pointl"]
    spec["pose2"] = safe[(i * 5 + 2) % len(safe)] if (i % 2 and spec["pose"] in safe) else spec["pose"]
    caps = re.findall(r"\b[A-Z][a-z]{3,}\b", text)
    spec["label"] = caps[0].upper() if caps and i % 2 == 0 else ""
    spec["hero_side"] = "left" if i % 2 == 0 else "right"
    spec["chars"] = keyword_chars(text, i, spec)
    spec["shot"] = ["medium", "medium", "close", "medium", "wide", "medium"][i % 6]
    if spec["shot"] == "close" and len(spec["chars"]) > 1:
        spec["shot"] = "medium"
    if "army" in spec["props"] or "crowd" in spec["props"]:
        spec["shot"] = "wide"
    return spec


def _prompt(title, lines, start, prev_setting):
    listing = "\n".join(f"{start + i + 1}. {t}" for i, t in enumerate(lines))
    cont = f"The previous scene took place in the '{prev_setting}' setting; keep it unless the location changes. " if prev_setting else ""
    return (
        f"You are the storyboard artist for a cartoon explainer video titled \"{title}\" in the style of The Ink Explainer: one recurring hero "
        "(round white head, blue t-shirt) acts out the story in colourful flat-colour scenes. For EACH numbered narration line, design the picture "
        "so a viewer who only sees the picture understands that exact line (show the thing being talked about literally, never a generic image). "
        + cont +
        "Return for each line an object with: "
        "\"scene\" (ONE sentence describing exactly what the picture shows for this line; write it first and make every other field follow from it), "
        f"\"setting\" (one of: {', '.join(S.SETTING_NAMES)}; keep the same setting for consecutive lines in the same place, change it when the location changes), "
        f"\"props\" (1-3 names that literally depict the line, most important first, from: {', '.join(S.PROP_NAMES)}), "
        "\"chars\" (1 or 2 characters in the scene; each {\"who\", \"pose\", \"pose2\", \"expr\"}; use a second character when two people interact, "
        "otherwise one; 'hero' is the everyman narrator and should appear in most scenes about 'you', but use the matching specialist when the story is about them "
        "(a king scene shows the king, a lab scene the scientist...) and keep each person looking the same throughout the video), "
        f"character names ('who') with looks: {'; '.join(k + '=' + v for k, v in T.CAST_INFO.items())}; "
        "any 'who' may add a skin tone like 'soldier:brown' (options: white, peach, tan, brown, dark) - vary skin tones across people for a diverse world; "
        "use props 'army' or 'crowd' (a whole group, wide shot) when the line is about many people; use settings street/village/field for medieval towns and farmland, city for modern cities; "
        f"poses (start/end body language) from: {', '.join(T.POSES)}; expr (face) from: {', '.join(T.EXPR)}, "
        "\"hero_side\" (left or right; alternate for variety), "
        "\"shot\" (camera framing: wide = small characters in a big world, use for places, crowds, armies and establishing; medium = normal; close = big face for emotion or a punchline; use medium most of the time, wide only for places/crowds/armies, close at most once in four lines and only for emotion), "
        "\"tod\" (time of day: day, sunset or night; keep it consistent within a story beat), "
        "and \"label\" (optional 1-3 word ALL-CAPS name or number worth showing on screen, e.g. a place, year or amount taken from the line; empty string if none). "
        "Match emotion to the line (fear when danger, smug when clever, shocked at surprises). "
        f"Return ONLY a JSON array of exactly {len(lines)} objects in order.\n\n{listing}")


def _clean(o, f):
    o = o if isinstance(o, dict) else {}
    props = [p for p in (o.get("props") or []) if p in S.PROPS][:3] or f["props"]
    p1 = o.get("pose") if o.get("pose") in T.POSES else f["pose"]
    p2 = o.get("pose2") if o.get("pose2") in T.POSES else p1
    chars = []
    for c in (o.get("chars") or [])[:2]:
        if isinstance(c, dict) and str(c.get("who", "")).split(":")[0] in T.DESIGNS:
            q1 = c.get("pose") if c.get("pose") in T.POSES else "stand"
            q2 = c.get("pose2") if c.get("pose2") in T.POSES else q1
            chars.append(dict(who=c["who"], pose=q1, pose2=q2, expr=c.get("expr") if c.get("expr") in T.EXPR else "neutral"))
    if not chars:
        chars = f["chars"]
    return dict(
        setting=o.get("setting") if o.get("setting") in S.SETTINGS else f["setting"], chars=chars,
        props=props, pose=p1, pose2=p2,
        expr=o.get("expr") if o.get("expr") in T.EXPR else f["expr"],
        hero_side="right" if str(o.get("hero_side", "")).lower().startswith("r") else "left",
        shot=o.get("shot") if o.get("shot") in ("wide", "medium", "close") else f.get("shot", "medium"),
        tod=o.get("tod") if o.get("tod") in ("day", "sunset", "night") else f.get("tod", "day"),
        label=re.sub(r"[^A-Z0-9 '$%&.,!?-]", "", str(o.get("label") or "").upper())[:24])


def plan_details(scenes, title, batch=24):
    """Per-line storyboard. LLM router (llm.py: Gemini -> Groq -> OpenRouter -> NVIDIA, whichever keys exist), planned in
    batches so small models cope with long videos; any batch no provider can plan falls back to the keyword planner."""
    import llm
    n = len(scenes)
    fb, prev = [], None
    for i, sc in enumerate(scenes):
        prev = keyword_plan(sc["text"], i, prev)
        fb.append(dict(prev))
    provs = llm.available()
    if not provs:
        A.note("Stickman planner: no LLM key, keyword fallback")
        return fb
    A.note(f"Stickman planner providers: {', '.join(provs)}")
    out = list(fb)
    prev_setting = None
    for st in range(0, n, batch):
        lines = [s["text"] for s in scenes[st:st + batch]]
        arr = llm.ask_list(_prompt(title, lines, st, prev_setting), len(lines))
        if arr is None:
            A.note(f"Stickman planner: batch {st // batch + 1} unplanned, keyword fallback")
            prev_setting = fb[min(n, st + len(lines)) - 1]["setting"]
            continue
        for k, o in enumerate(arr):
            out[st + k] = _clean(o, fb[st + k])
        prev_setting = out[st + len(lines) - 1]["setting"]
    for i_, o_ in enumerate(out[:4]):
        A.note(f"Stickman plan {i_ + 1}: {o_['setting']} | {','.join(o_['props'])} | {o_['pose']} | {o_['expr']} | {o_['label']}")
    return out


# ----------------------------------------------------------------------------- joining
def join_chunk(segs, spans, dest, k0):
    n = len(segs)
    if n == 1:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(segs[0]), "-c", "copy", str(dest)], check=True)
        return
    parts, cum, last = [], 0.0, "[0:v]"
    for k in range(n - 1):
        cum += spans[k]
        tr = TRANSITIONS[(k0 + k) % len(TRANSITIONS)]
        out = "[v]" if k == n - 2 else f"[x{k}]"
        parts.append(f"{last}[{k + 1}:v]xfade=transition={tr}:duration={A.OVERLAP}:offset={cum:.3f}{out}")
        last = out
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for sg in segs:
        cmd += ["-i", str(sg)]
    cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "20", "-pix_fmt", "yuv420p", str(dest)]
    subprocess.run(cmd, check=True)


# ----------------------------------------------------------------------------- main entry
def build(script, title, words, length, work, w, h, fps):
    land = w >= h
    A.MIN_SCENE, A.MAX_SCENE = (4.5, 8.0) if land else ((3.0, 5.5) if length > 80 else (2.4, 4.8))
    scenes = A.plan_scenes(script, words, length)
    A.note(f"Stickman scenes planned: {len(scenes)} ({'landscape' if land else 'vertical'})")
    det = plan_details(scenes, title)
    work = Path(work)
    segs, spans = [], []
    seed = sum(ord(c) for c in title) % 997
    for i, (sc, dt) in enumerate(zip(scenes, det)):
        sw = [(a_ - sc["t0"], b_ - sc["t0"]) for (_, a_, b_) in words if sc["t0"] - 0.05 <= a_ < sc["t1"]]
        scn = Scene(w, h, dt, i, seed, sw, sc["t1"] - sc["t0"])
        end_of_chunk = (i % CHUNK == CHUNK - 1) or i == len(scenes) - 1
        base = sc["t1"] - sc["t0"]
        span = base + (0 if end_of_chunk else A.OVERLAP)
        seg = work / f"stkseg_{i}.mp4"
        render_scene(scn, span, seg, w, h, fps)
        segs.append(seg)
        spans.append(base)
        if i % 5 == 0:
            A.note(f"Stickman scene {i + 1}/{len(scenes)} done")
    out = []
    for c in range(0, len(segs), CHUNK):
        part = work / f"stkjoin_{c // CHUNK}.mp4"
        try:
            join_chunk(segs[c:c + CHUNK], spans[c:c + CHUNK], part, c)
        except Exception as exc:
            A.note(f"Stickman join failed ({exc}); hard cuts for chunk")
            part = None
        if part:
            out.append(part)
        else:
            for k in range(c, min(c + CHUNK, len(segs))):
                o = work / f"stkcut_{k}.mp4"
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(segs[k]), "-t", f"{spans[k]:.3f}",
                                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(o)], check=True)
                out.append(o)
    return out
