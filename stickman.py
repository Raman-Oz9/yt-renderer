"""Stick-figure storytelling renderer v4 (only used when VISUAL_STYLE=stickman).

Full-bleed illustration fills the whole frame (vertical 9:16 for Shorts, 16:9 for long videos) with a
lively camera move; a stick-figure presenter with hair, glasses and a blazer acts on top of it; bold
headline on a soft gradient. Scenes are joined with varied transitions. The cinematic renderer never
imports this module.
"""
import math
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import ai_scenes as A

INK = (18, 18, 22)
YELLOW = (255, 210, 63)
WHITE = (255, 255, 255)
HAIR = (58, 36, 26)
BLAZER = (36, 56, 104)
PANTS = (50, 58, 84)
SHOE = (28, 28, 34)
TIE = (214, 60, 56)
ACCENTS = [YELLOW, (255, 120, 96), YELLOW, (110, 220, 255)]   # effect / keyword colours
FONTS = [str(Path(__file__).with_name("fonts") / "Anton.ttf"),
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
TRANSITIONS = ["slideleft", "wipeleft", "circleopen", "smoothleft", "zoomin", "slideup", "fadewhite"]
CHUNK = 10   # scenes per xfade chain (keeps ffmpeg light on long videos)

# angles in degrees from straight-down, + = toward screen right
POSES = {
    "idle":     dict(lean=0,  head=0,  la1=-12,  la2=-8,   ra1=12,  ra2=8,   ll1=-6,  ll2=-6,  rl1=6,  rl2=6),
    "point":    dict(lean=4,  head=6,  la1=-12,  la2=-8,   ra1=75,  ra2=80,  ll1=-6,  ll2=-6,  rl1=6,  rl2=6),
    "surprise": dict(lean=-6, head=-4, la1=-140, la2=-160, ra1=140, ra2=160, ll1=-12, ll2=-12, rl1=12, rl2=12),
    "think":    dict(lean=3,  head=8,  la1=-12,  la2=-8,   ra1=30,  ra2=150, ll1=-6,  ll2=-6,  rl1=6,  rl2=6),
    "wave":     dict(lean=0,  head=4,  la1=-12,  la2=-8,   ra1=120, ra2=160, ll1=-6,  ll2=-6,  rl1=6,  rl2=6),
    "run":      dict(lean=14, head=6,  la1=-55,  la2=-110, ra1=50,  ra2=100, ll1=-40, ll2=-10, rl1=35, rl2=70),
    "cheer":    dict(lean=-4, head=-6, la1=-150, la2=-165, ra1=150, ra2=165, ll1=-16, ll2=-16, rl1=16, rl2=16),
    "shrug":    dict(lean=0,  head=10, la1=-55,  la2=-110, ra1=55,  ra2=110, ll1=-6,  ll2=-6,  rl1=6,  rl2=6),
    "fear":     dict(lean=-10, head=-6, la1=-35, la2=-150, ra1=35,  ra2=150, ll1=-10, ll2=-14, rl1=14, rl2=18),
}
POSE_KEYS = list(POSES)
MOODS = {"happy": 1, "neutral": 0, "shocked": 2, "sad": -1}
FX_FOR_POSE = {"surprise": "burst", "fear": "burst", "cheer": "spark", "think": "q", "wave": "spark", "run": "burst"}

CARD_STYLE = ("vibrant hand-drawn marker illustration, bold black ink outlines, flat saturated colours in red, yellow, "
              "green and blue, simple clean scene with a clear coloured background, comic explainer style, ONE main subject "
              "shown large and unmistakable, wide composition, no text, no letters, no numbers, no people, no stick figures")


def _font(size):
    for f in FONTS:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def _ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _mix(a, b, t):
    t = _ease(t)
    return {k: a[k] + (b[k] - a[k]) * t for k in a}


# ----------------------------------------------------------------------------- the presenter
def draw_figure(pose, mood, height_px, flip, phase, accent, fx, fxt):
    """RGBA stick-figure presenter (hair, glasses, blazer, tie, trousers, shoes) ~height_px tall.
    Returns (img, feet_y_in_img)."""
    scale = height_px / 388.0
    S = 2
    side = int(520 * scale)
    W = H = side * S
    u = scale * S
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lw = max(4, int(9 * u))
    ol = max(2, int(3.2 * u))                     # outline thickness for filled clothing
    bob = math.sin(phase * 2 * math.pi) * 5 * u
    hip = (W / 2, 300 * u + bob)
    lean = math.radians(pose["lean"])
    neck = (hip[0] + math.sin(lean) * 120 * u, hip[1] - math.cos(lean) * 120 * u)

    def limb(p, a1, a2, l1, l2):
        r1, r2 = math.radians(a1), math.radians(a2)
        m = (p[0] + math.sin(r1) * l1, p[1] + math.cos(r1) * l1)
        return m, (m[0] + math.sin(r2) * l2, m[1] + math.cos(r2) * l2)

    def thick(pts, width, fill):
        """Clothing-coloured limb with an ink outline."""
        d.line(pts, fill=INK, width=width + 2 * ol, joint="curve")
        for p in pts:
            d.ellipse([p[0] - width / 2 - ol, p[1] - width / 2 - ol, p[0] + width / 2 + ol, p[1] + width / 2 + ol], fill=INK)
        d.line(pts, fill=fill, width=width, joint="curve")
        for p in pts:
            d.ellipse([p[0] - width / 2, p[1] - width / 2, p[0] + width / 2, p[1] + width / 2], fill=fill)

    # legs (trousers) + shoes
    for a1, a2 in ((pose["ll1"], pose["ll2"]), (pose["rl1"], pose["rl2"])):
        m, e = limb(hip, a1, a2, 85 * u, 85 * u)
        thick([hip, m, e], int(lw * 1.5), PANTS)
        d.ellipse([e[0] - lw * 0.9, e[1] - lw * 0.5, e[0] + lw * 1.9, e[1] + lw * 0.9], fill=SHOE, outline=INK, width=ol)
    # torso: blazer, white shirt V and tie
    sl = (neck[0] - 30 * u, neck[1] + 12 * u)
    sr = (neck[0] + 30 * u, neck[1] + 12 * u)
    hl = (hip[0] - 21 * u, hip[1] + 4 * u)
    hr_ = (hip[0] + 21 * u, hip[1] + 4 * u)
    d.polygon([sl, sr, hr_, hl], fill=BLAZER, outline=INK, width=ol)
    d.polygon([(neck[0] - 13 * u, neck[1] + 12 * u), (neck[0] + 13 * u, neck[1] + 12 * u),
               (neck[0] + 2 * u * 0, neck[1] + 62 * u)], fill=WHITE)
    cx0, cy0 = neck[0], neck[1] + 20 * u
    d.polygon([(cx0 - 6 * u, cy0), (cx0 + 6 * u, cy0), (cx0 + 9 * u, cy0 + 36 * u), (cx0, cy0 + 48 * u),
               (cx0 - 9 * u, cy0 + 36 * u)], fill=TIE, outline=INK, width=max(1, ol // 2))
    # arms (blazer sleeves) + hands
    for a1, a2 in ((pose["la1"], pose["la2"]), (pose["ra1"], pose["ra2"])):
        sh = (neck[0] + (-26 * u if a1 < 0 or (a1 == 0) else 26 * u), neck[1] + 18 * u)
        m, e = limb(sh, a1, a2, 68 * u, 62 * u)
        thick([sh, m, e], int(lw * 1.45), BLAZER)
        r = lw * 1.05
        d.ellipse([e[0] - r, e[1] - r, e[0] + r, e[1] + r], fill=WHITE, outline=INK, width=ol)
    # head
    hr = 46 * u
    hc = (neck[0] + math.sin(math.radians(pose["head"])) * 20 * u, neck[1] - hr - 6 * u)
    d.line([neck, (hc[0], hc[1] + hr * 0.9)], fill=INK, width=lw)
    # hair (behind the face outline): quiff + side
    d.pieslice([hc[0] - hr * 1.04, hc[1] - hr * 1.04, hc[0] + hr * 1.04, hc[1] + hr * 1.04], 188, 352, fill=HAIR, outline=INK, width=ol)
    d.polygon([(hc[0] - hr * 0.95, hc[1] - hr * 0.35), (hc[0] - hr * 0.5, hc[1] - hr * 1.2), (hc[0] + hr * 0.3, hc[1] - hr * 1.38), (hc[0] + hr * 1.05, hc[1] - hr * 0.95), (hc[0] + hr * 0.9, hc[1] - hr * 0.45), (hc[0] + hr * 0.1, hc[1] - hr * 0.8)], fill=HAIR, outline=INK, width=ol)
    d.pieslice([hc[0] - hr * 1.04, hc[1] - hr * 1.04, hc[0] + hr * 1.04, hc[1] + hr * 1.04], 190, 350, fill=HAIR)
    # face (lower part) over the hair: white chord so the hairline reads
    d.ellipse([hc[0] - hr, hc[1] - hr * 0.62, hc[0] + hr, hc[1] + hr], fill=WHITE)
    d.arc([hc[0] - hr, hc[1] - hr, hc[0] + hr, hc[1] + hr], 0, 360, fill=INK, width=lw)
    # glasses
    ex, ey = hr * 0.40, hc[1] - hr * 0.05
    gr = hr * 0.30
    for sx in (-1, 1):
        x = hc[0] + sx * ex
        d.ellipse([x - gr, ey - gr, x + gr, ey + gr], fill=WHITE, outline=INK, width=max(2, int(3.4 * u)))
    d.line([hc[0] - ex + gr, ey, hc[0] + ex - gr, ey], fill=INK, width=max(2, int(3 * u)))
    # eyes + brows by mood
    er = max(3, int(5.5 * u))
    for sx in (-1, 1):
        x = hc[0] + sx * ex
        if mood == 2:
            d.ellipse([x - er * 1.2, ey - er * 1.2, x + er * 1.2, ey + er * 1.2], fill=INK)
        else:
            d.ellipse([x - er, ey - er, x + er, ey + er], fill=INK)
        by = ey - gr - 6 * u - (9 * u if mood == 2 else 0)
        tilt = {1: -2, 0: 0, 2: -5, -1: 7}[mood] * u * sx * -1 if mood == -1 else {1: 0, 0: 0, 2: -3, -1: 0}[mood] * u
        if mood == -1:
            d.line([(x - gr * 0.9, by + 5 * u * sx), (x + gr * 0.9, by - 5 * u * sx)], fill=INK, width=max(2, int(4 * u)))
        else:
            d.line([(x - gr * 0.9, by + tilt), (x + gr * 0.9, by + tilt - (3 * u if mood == 1 else 0))], fill=INK,
                   width=max(2, int(4 * u)))
    my, mw, mlw = hc[1] + hr * 0.52, hr * 0.42, max(2, int(4 * u))
    if mood == 1:
        d.arc([hc[0] - mw, my - mw * .8, hc[0] + mw, my + mw * .6], 15, 165, fill=INK, width=mlw)
    elif mood == -1:
        d.arc([hc[0] - mw, my - mw * .2, hc[0] + mw, my + mw * 1.2], 195, 345, fill=INK, width=mlw)
    elif mood == 2:
        d.ellipse([hc[0] - mw * .42, my - mw * .45, hc[0] + mw * .42, my + mw * .6], fill=(120, 30, 40), outline=INK, width=mlw)
    else:
        d.line([hc[0] - mw * .55, my, hc[0] + mw * .55, my], fill=INK, width=mlw)
    if flip:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
        hc = (W - hc[0], hc[1])
    d = ImageDraw.Draw(img)
    # effects drawn after the flip so text is never mirrored
    if fx == "burst" and fxt < 1.6:
        k = _ease(fxt / 0.25) * (1 - _ease((fxt - 1.1) / 0.5))
        for ang in (-155, -125, -95, -65, -35):
            r0, r1 = hr * 1.5, hr * (1.5 + 0.6 * k)
            a = math.radians(ang)
            d.line([(hc[0] + math.cos(a) * r0, hc[1] + math.sin(a) * r0),
                    (hc[0] + math.cos(a) * r1, hc[1] + math.sin(a) * r1)], fill=accent, width=max(3, int(7 * u)))
    elif fx == "spark":
        for j, (ox, oy, sz) in enumerate(((-1.7, -1.0, 0.34), (1.75, -0.7, 0.26), (1.2, -1.7, 0.2))):
            s_ = hr * sz * (0.7 + 0.3 * math.sin(phase * 2 * math.pi + j * 2))
            cx, cy = hc[0] + ox * hr, hc[1] + oy * hr
            d.polygon([(cx, cy - s_ * 1.6), (cx + s_ * .4, cy - s_ * .4), (cx + s_ * 1.6, cy), (cx + s_ * .4, cy + s_ * .4),
                       (cx, cy + s_ * 1.6), (cx - s_ * .4, cy + s_ * .4), (cx - s_ * 1.6, cy), (cx - s_ * .4, cy - s_ * .4)],
                      fill=accent)
    elif fx == "q":
        f = _font(int(hr * 1.5))
        bounce = math.sin(phase * 2 * math.pi) * hr * 0.08
        d.text((hc[0] + hr * 1.0, hc[1] - hr * 2.3 + bounce), "?", font=f, fill=accent, stroke_width=max(2, int(3 * u)),
               stroke_fill=INK)
    img = img.resize((side, side), Image.LANCZOS)
    # white sticker outline so the presenter pops off any picture
    r = max(4, int(height_px * 0.02))
    halo = img.split()[3].filter(ImageFilter.MaxFilter(2 * r + 1)).filter(ImageFilter.GaussianBlur(1.2))
    out = Image.new("RGBA", img.size, (255, 255, 255, 0))
    out.putalpha(halo)
    out.paste((255, 255, 255, 255), (0, 0), halo)
    out.alpha_composite(img)
    return out, int(470 * scale)


# ----------------------------------------------------------------------------- full-bleed stage
def layout(w, h, side):
    if w >= h:   # landscape 16:9
        return dict(land=True, head=(int(w * 0.06), int(h * 0.05), int(w * 0.94), int(h * 0.22)), maxlines=2,
                    fig=(int(w * 0.14) if side == 0 else int(w * 0.86), int(h * 0.915), int(h * 0.55)), fs=int(h * 0.105))
    return dict(land=False, head=(int(w * 0.05), int(h * 0.045), int(w * 0.95), int(h * 0.20)), maxlines=2,
                fig=(int(w * 0.19) if side == 0 else int(w * 0.81), int(h * 0.71), int(h * 0.27)), fs=int(h * 0.072))


def gradients(w, h):
    """Soft dark fades at top (headline) and bottom (captions) so text always reads on any picture."""
    ys = np.arange(h, dtype=np.float32) / h
    top = np.clip(1 - ys / 0.30, 0, 1) ** 1.6 * 0.62
    bot = np.clip((ys - 0.55) / 0.45, 0, 1) ** 1.4 * 0.70
    a = np.clip(top + bot, 0, 0.85)
    arr = np.zeros((h, w, 4), np.uint8)
    arr[:, :, 3] = (a[:, None] * 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def wrap(text, font, maxw, d, maxlines=2):
    lines, cur = [], ""
    for wd in text.split():
        t = (cur + " " + wd).strip()
        if d.textlength(t, font=font) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines[:maxlines]


def cover(im, size, extra=1.0):
    tw, th = int(size[0] * extra), int(size[1] * extra)
    s = max(tw / im.width, th / im.height)
    im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)
    x, y = (im.width - tw) // 2, (im.height - th) // 2
    return im.crop((x, y, x + tw, y + th))


def headline_image(text, box, fs0, maxlines, accent):
    """Anton caps with a thick ink stroke; the longest word in the accent colour."""
    bw, bh = box[2] - box[0], box[3] - box[1]
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    text = text.upper()
    fs = fs0
    while True:
        font = _font(fs)
        lines = wrap(text, font, bw - fs * 0.3, probe, 12)
        lh = int(fs * 1.14)
        if (len(lines) <= maxlines and lh * len(lines) <= bh) or fs < fs0 * 0.45:
            break
        fs = int(fs * 0.92)
    lines = lines[:maxlines]
    key = max(text.split(), key=len) if text.split() else ""
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    sw = max(3, int(fs * 0.07))
    y = max(0, (bh - lh * len(lines)) // 2)
    for ln in lines:
        x = (bw - d.textlength(ln, font=font)) / 2
        for wd in ln.split():
            d.text((x, y), wd, font=font, fill=accent if wd == key else WHITE, stroke_width=sw, stroke_fill=INK)
            x += d.textlength(wd + " ", font=font)
        y += lh
    return img


class SceneArt:
    def __init__(self, w, h, headline, art, accent, side):
        self.w, self.h, self.side = w, h, side
        self.L = L = layout(w, h, side)
        self.grad = gradients(w, h)
        hb = L["head"]
        self.head = headline_image(headline, hb, L["fs"], L["maxlines"], accent)
        self.head_pos = (hb[0], hb[1])
        if art is None:
            art = Image.new("RGB", (512, 512), (40, 60, 110))
            ImageDraw.Draw(art).text((256, 256), "?", font=_font(300), fill=accent, anchor="mm")
        self.big = cover(art, (w, h), 1.30)

    def frame_at(self, t, span, idx):
        """Full-frame picture with a lively camera move (varies per scene; scene 1 starts with a punch-in reveal)."""
        k = min(1.0, t / max(span, 0.5))
        bw, bh = self.big.size
        mode = idx % 5
        if idx == 0:
            z, px, py = 1.30 - 0.30 * _ease(k * 1.4), 0.0, 0.0
        elif mode == 0:
            z, px, py = 1.0 + 0.22 * k, 0.0, 0.0
        elif mode == 1:
            z, px, py = 1.22 - 0.22 * k, 0.0, 0.0
        elif mode == 2:
            z, px, py = 1.16, (k - 0.5) * 1.0, 0.0
        elif mode == 3:
            z, px, py = 1.16, (0.5 - k) * 1.0, 0.0
        else:
            z, px, py = 1.0 + 0.18 * k, (k - 0.5) * 0.7, (0.5 - k) * 0.7
        ww, wh = bw / z / 1.0, bh / z / 1.0
        ww, wh = ww * (1 / 1.0), wh * (1 / 1.0)
        # keep the visible window the size of the output frame (big is 1.3x) at z=1.3 -> 1x
        ww, wh = self.w * 1.30 / z, self.h * 1.30 / z
        ww, wh = min(ww, bw), min(wh, bh)
        cx = bw / 2 + px * (bw - ww)
        cy = bh / 2 + py * (bh - wh)
        box = (cx - ww / 2, cy - wh / 2, cx + ww / 2, cy + wh / 2)
        return self.big.resize((self.w, self.h), Image.BILINEAR, box=box)


def draw_progress(frame, w, h, frac, accent):
    d = ImageDraw.Draw(frame)
    d.rectangle([0, 0, int(w * frac), max(6, h // 160)], fill=accent)


# ----------------------------------------------------------------------------- scene render
def render_scene(sa, keys, mood, fx, accent, span, dest, w, h, fps, idx, prog0=None, prog1=None):
    frames = max(2, int(round(span * fps)))
    L = sa.L
    fcx, floor, fh = L["fig"]
    flip = (sa.side == 1) if not L["land"] else (sa.side == 0)   # face into the picture
    cache = {}
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", str(dest)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    off_x = (-1 if (fcx < w / 2) else 1) * w * 0.35
    try:
        for f in range(frames):
            t = f / fps
            ki = 0
            for j, (kt, _) in enumerate(keys):
                if t >= kt:
                    ki = j
            kt, kp = keys[ki]
            prev = keys[ki - 1][1] if ki > 0 else POSES["idle"]
            tm = t - kt
            pose = dict(_mix(prev, kp, tm / 0.45))
            ph = round(((t / 1.6) % 1.0) * 12) / 12
            sway = math.sin(ph * 2 * math.pi) * 3
            pose["la1"] += sway
            pose["ra1"] -= sway
            q = round(min(tm, 0.45) / 0.45 * 6)
            fx_on = fx if (fx in ("spark", "q") or tm < 1.7) else None
            fxt = round(tm * 10) / 10 if tm < 1.7 else 9.0
            key = (ki, q, ph, mood, fx_on, fxt)
            if key not in cache:
                cache[key] = draw_figure(pose, MOODS[mood], fh, flip, ph, accent, fx_on, fxt)
                if len(cache) > 400:
                    cache.pop(next(iter(cache)))
            fig, feet = cache[key]
            frame = sa.frame_at(t, span, idx)
            frame.paste(sa.grad, (0, 0), sa.grad)
            # headline: quick scale-slam
            hp = _ease(t / 0.22)
            hd = sa.head
            if hp < 1.0:
                s = 1.3 - 0.3 * hp
                hd = hd.resize((max(1, int(hd.width * s)), max(1, int(hd.height * s))), Image.BILINEAR)
                px = sa.head_pos[0] + (sa.head.width - hd.width) // 2
                py = sa.head_pos[1] + (sa.head.height - hd.height) // 2
                frame.paste(hd, (px, py), hd)
            else:
                frame.paste(hd, sa.head_pos, hd)
            # presenter slides in from the edge and settles
            slide = (1 - _ease(t / 0.4)) * off_x
            frame.paste(fig, (int(fcx - fig.width / 2 + slide), int(floor - feet)), fig)
            if t < 0.14:   # tiny white flash on every cut for punch
                frame = Image.blend(frame, Image.new("RGB", (w, h), WHITE), 0.30 * (1 - t / 0.14))
            if prog0 is not None:
                draw_progress(frame, w, h, prog0 + (prog1 - prog0) * (f / frames), accent)
            proc.stdin.write(np.asarray(frame).tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed for stickman scene")


# ----------------------------------------------------------------------------- planning
def plan_details(scenes, title):
    n = len(scenes)
    fb = []
    for i, sc in enumerate(scenes):
        words = re.findall(r"[A-Za-z0-9'-]+", sc["text"])
        fb.append({"headline": " ".join(words[:4]).upper(),
                   "scene": f"{title}, {' '.join(words[:10])}",
                   "pose": POSE_KEYS[i % len(POSE_KEYS)], "pose2": POSE_KEYS[(i + 3) % len(POSE_KEYS)],
                   "mood": "neutral"})
    if not A.GEMINI_KEY:
        return fb
    listing = "\n".join(f"{i + 1}. {s['text']}" for i, s in enumerate(scenes))
    ask = (f"Plan a stick-figure explainer video titled \"{title}\". For each numbered narration line return an object with: "
           "\"headline\" (2-4 word ALL-CAPS key phrase from the line, no punctuation), "
           "\"scene\" (a vivid, concrete illustration of what the line is about, max 28 words: name the exact subject, "
           "e.g. 'a huge erupting volcano with orange lava rivers under a red sky'; a different striking subject every time), "
           f"\"pose\" and \"pose2\" (each one of {', '.join(POSE_KEYS)}; pose2 is a second pose for later in the scene), "
           "and \"mood\" (one of happy, neutral, shocked, sad). Vary poses; match emotion to the line. "
           f"Return ONLY a JSON array of exactly {n} objects in order.\n\n{listing}")
    for model in A.TEXT_MODELS:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": A.GEMINI_KEY},
                json={"contents": [{"parts": [{"text": ask}]}],
                      "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 16384}},
                timeout=120)
            if r.status_code != 200:
                A.note(f"Stickman planner {model}: {r.status_code}")
                continue
            arr = A.parse_json_list(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            if isinstance(arr, list) and len(arr) == n:
                out = []
                for o, f in zip(arr, fb):
                    o = o if isinstance(o, dict) else {}
                    p1 = o.get("pose") if o.get("pose") in POSES else f["pose"]
                    p2 = o.get("pose2") if o.get("pose2") in POSES else f["pose2"]
                    mood = o.get("mood") if o.get("mood") in MOODS else "neutral"
                    out.append({"headline": str(o.get("headline") or f["headline"]).upper()[:44],
                                "scene": str(o.get("scene") or f["scene"])[:220], "pose": p1, "pose2": p2, "mood": mood})
                return out
        except Exception as exc:
            A.note(f"Stickman planner {model} failed: {exc}")
    return fb


def get_art(desc, dest, land):
    shape = "wide landscape composition filling the whole frame" if land else "tall vertical composition filling the whole frame"
    src = A.make_image(f"{desc}, {CARD_STYLE.replace('wide composition', shape)}", dest)
    if not src:
        return None
    try:
        return Image.open(dest).convert("RGB")
    except Exception:
        return None


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
    A._BUDGET_END[0] = A.time.time() + (80 if land else 34) * 60
    A.MIN_SCENE, A.MAX_SCENE = (4.5, 8.0) if land else ((3.0, 5.5) if length > 80 else (2.4, 4.8))
    scenes = A.plan_scenes(script, words, length)
    A.note(f"Stickman scenes planned: {len(scenes)} ({'landscape' if land else 'vertical'})")
    det = plan_details(scenes, title)
    work = Path(work)

    def job(i):
        return get_art(det[i]["scene"], work / f"stk_art_{i}.img", land)

    with ThreadPoolExecutor(max_workers=3) as ex:
        arts = list(ex.map(job, range(len(scenes))))
    ok = sum(1 for a in arts if a is not None)
    A.note(f"Stickman art: {ok}/{len(scenes)} generated")
    if ok == 0:
        return None
    last = None
    for i, a in enumerate(arts):
        if a is None and last is not None:
            arts[i] = last.transpose(Image.FLIP_LEFT_RIGHT)   # reuse (mirrored) rather than a blank card
        elif a is not None:
            last = a

    segs, spans = [], []
    total = scenes[-1]["t1"]
    for i, (sc, dt) in enumerate(zip(scenes, det)):
        accent = ACCENTS[i % len(ACCENTS)]
        side = i % 2
        sa = SceneArt(w, h, dt["headline"], arts[i], accent, side)
        end_of_chunk = (i % CHUNK == CHUNK - 1) or i == len(scenes) - 1
        base = sc["t1"] - sc["t0"]
        span = base + (0 if end_of_chunk else A.OVERLAP)
        keys = [(0.0, POSES[dt["pose"]])]
        if base > 5.2:
            keys.append((base * 0.5, POSES[dt["pose2"]]))
        fx = FX_FOR_POSE.get(dt["pose"]) or ("spark" if dt["mood"] == "happy" else None)
        seg = work / f"stkseg_{i}.mp4"
        render_scene(sa, keys, dt["mood"], fx, accent, span, seg, w, h, fps, i,
                     (sc["t0"] / total) if land else None, (sc["t1"] / total) if land else None)
        segs.append(seg)
        spans.append(base)
        if i % 5 == 0:
            A.note(f"Stickman scene {i + 1}/{len(scenes)} done")
    # chain-join in chunks; chunk boundaries are hard cuts (concat copy in render.py)
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
