"""Stick-figure explainer renderer v2 (only used when VISUAL_STYLE=stickman).

Layouts adapt to the frame: vertical 9:16 (Shorts) or landscape 16:9 (long videos).
Every scene = tinted paper + big headline + a LARGE framed illustration card with a slow
camera push + a stick figure (drawn in code) acting beside / on the card + small effects
(burst lines, sparkles, question mark). Scenes are joined with varied transitions.
The cinematic renderer never imports this module.
"""
import math
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

import ai_scenes as A

INK = (20, 20, 24)
ACCENTS = [(226, 70, 56), (245, 184, 30), (38, 150, 96), (36, 98, 190), (150, 80, 190), (240, 120, 40)]
TINTS = [(253, 252, 247), (247, 252, 246), (244, 249, 254), (254, 248, 242), (250, 246, 253), (255, 251, 238)]
FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"]
TRANSITIONS = ["slideleft", "circleopen", "wipeleft", "slideup", "smoothleft", "radial", "zoomin"]
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


# ----------------------------------------------------------------------------- figure
def draw_figure(pose, mood, height_px, flip, phase, accent, fx, fxt):
    """RGBA figure whose total height is ~height_px. Returns (img, feet_y_in_img)."""
    scale = height_px / 388.0
    S = 2
    side = int(520 * scale)
    W = H = side * S
    u = scale * S
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lw = max(4, int(9 * u))
    bob = math.sin(phase * 2 * math.pi) * 5 * u
    hip = (W / 2, 300 * u + bob)
    lean = math.radians(pose["lean"])
    neck = (hip[0] + math.sin(lean) * 120 * u, hip[1] - math.cos(lean) * 120 * u)

    def limb(p, a1, a2, l1, l2):
        r1, r2 = math.radians(a1), math.radians(a2)
        m = (p[0] + math.sin(r1) * l1, p[1] + math.cos(r1) * l1)
        return m, (m[0] + math.sin(r2) * l2, m[1] + math.cos(r2) * l2)

    for a1, a2 in ((pose["ll1"], pose["ll2"]), (pose["rl1"], pose["rl2"])):
        m, e = limb(hip, a1, a2, 85 * u, 85 * u)
        d.line([hip, m, e], fill=INK, width=lw, joint="curve")
        d.ellipse([e[0] - lw * .6, e[1] - lw * .6, e[0] + lw * .6, e[1] + lw * .6], fill=INK)
    for a1, a2 in ((pose["la1"], pose["la2"]), (pose["ra1"], pose["ra2"])):
        sh = (neck[0], neck[1] + 14 * u)
        m, e = limb(sh, a1, a2, 70 * u, 70 * u)
        d.line([sh, m, e], fill=INK, width=lw, joint="curve")
        d.ellipse([e[0] - lw * .9, e[1] - lw * .9, e[0] + lw * .9, e[1] + lw * .9], fill=INK)
    d.line([hip, neck], fill=INK, width=lw)
    # accent scarf
    d.line([(neck[0] - 18 * u, neck[1] + 10 * u), (neck[0] + 18 * u, neck[1] + 10 * u)], fill=accent, width=int(lw * 1.7))
    hr = 46 * u
    hc = (neck[0] + math.sin(math.radians(pose["head"])) * 20 * u, neck[1] - hr - 6 * u)
    d.ellipse([hc[0] - hr, hc[1] - hr, hc[0] + hr, hc[1] + hr], fill=(255, 255, 255, 255), outline=INK, width=lw)
    ex, ey = hr * 0.38, hc[1] - hr * 0.12
    er = max(3, int(6 * u)) if mood != 2 else int(9 * u)
    for sx in (-1, 1):
        x = hc[0] + sx * ex
        if mood == 2:
            d.ellipse([x - er, ey - er, x + er, ey + er], outline=INK, width=max(2, int(3 * u)))
            d.ellipse([x - er * .35, ey - er * .35, x + er * .35, ey + er * .35], fill=INK)
        else:
            d.ellipse([x - er * .7, ey - er * .7, x + er * .7, ey + er * .7], fill=INK)
    my, mw, mlw = hc[1] + hr * 0.42, hr * 0.42, max(2, int(4 * u))
    if mood == 1:
        d.arc([hc[0] - mw, my - mw * .8, hc[0] + mw, my + mw * .6], 15, 165, fill=INK, width=mlw)
    elif mood == -1:
        d.arc([hc[0] - mw, my - mw * .2, hc[0] + mw, my + mw * 1.2], 195, 345, fill=INK, width=mlw)
    elif mood == 2:
        d.ellipse([hc[0] - mw * .45, my - mw * .5, hc[0] + mw * .45, my + mw * .6], outline=INK, width=mlw)
    else:
        d.line([hc[0] - mw * .6, my, hc[0] + mw * .6, my], fill=INK, width=mlw)
    if flip:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
        hc = (W - hc[0], hc[1])
    # effects drawn after the flip so text is never mirrored
    d = ImageDraw.Draw(img)
    if fx == "burst" and fxt < 1.6:
        k = _ease(fxt / 0.25) * (1 - _ease((fxt - 1.1) / 0.5))
        for ang in (-155, -125, -95, -65, -35):
            r0, r1 = hr * 1.25, hr * (1.25 + 0.55 * k)
            a = math.radians(ang)
            d.line([(hc[0] + math.cos(a) * r0, hc[1] + math.sin(a) * r0),
                    (hc[0] + math.cos(a) * r1, hc[1] + math.sin(a) * r1)], fill=accent, width=max(3, int(7 * u)))
    elif fx == "spark":
        for j, (ox, oy, sz) in enumerate(((-1.5, -0.9, 0.34), (1.55, -0.6, 0.26), (1.1, -1.5, 0.2))):
            s = hr * sz * (0.7 + 0.3 * math.sin(phase * 2 * math.pi + j * 2))
            cx, cy = hc[0] + ox * hr, hc[1] + oy * hr
            d.polygon([(cx, cy - s * 1.6), (cx + s * .4, cy - s * .4), (cx + s * 1.6, cy), (cx + s * .4, cy + s * .4),
                       (cx, cy + s * 1.6), (cx - s * .4, cy + s * .4), (cx - s * 1.6, cy), (cx - s * .4, cy - s * .4)],
                      fill=accent)
    elif fx == "q":
        f = _font(int(hr * 1.4))
        bounce = math.sin(phase * 2 * math.pi) * hr * 0.08
        d.text((hc[0] + hr * 0.9, hc[1] - hr * 2.0 + bounce), "?", font=f, fill=accent, stroke_width=max(2, int(3 * u)),
               stroke_fill=INK)
    img = img.resize((side, side), Image.LANCZOS)
    return img, int(470 * scale)


# ----------------------------------------------------------------------------- layout
def layout(w, h, side):
    """Rects: headline box, card box, figure (cx, floor_y, height), title font size."""
    if w >= h:   # landscape 16:9
        card_w = int(w * 0.64)
        cx0 = int(w * 0.03) if side == 0 else int(w * 0.97) - card_w
        card = (cx0, int(h * 0.235), cx0 + card_w, int(h * 0.80))
        fig_cx = int(w * 0.835) if side == 0 else int(w * 0.165)
        return dict(land=True, head=(int(w * 0.03), int(h * 0.03), int(w * 0.97), int(h * 0.21)), card=card,
                    fig=(fig_cx, int(h * 0.80), int(h * 0.50)), fs=int(h * 0.072), cardshift=0)
    card = (int(w * 0.045), int(h * 0.185), int(w * 0.955), int(h * 0.60))
    fig_cx = int(w * 0.20) if side == 0 else int(w * 0.80)
    return dict(land=False, head=(int(w * 0.05), int(h * 0.035), int(w * 0.95), int(h * 0.175)), card=card,
                fig=(fig_cx, int(h * 0.745), int(h * 0.205)), fs=int(w * 0.095), cardshift=0)


def paper(w, h, tint):
    img = Image.new("RGB", (w, h), tint)
    d = ImageDraw.Draw(img)
    g = tuple(max(0, c - 22) for c in tint)
    step = max(40, w // 24)
    for x in range(0, w, step):
        d.line([(x, 0), (x, h)], fill=g, width=2)
    for y in range(0, h, step):
        d.line([(0, y), (w, y)], fill=g, width=2)
    return img


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


def rounded_mask(size, r):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], r, fill=255)
    return m


def cover(im, size, extra=1.0):
    """Resize to cover `size` (times extra), centre-cropped."""
    tw, th = int(size[0] * extra), int(size[1] * extra)
    s = max(tw / im.width, th / im.height)
    im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)
    x, y = (im.width - tw) // 2, (im.height - th) // 2
    return im.crop((x, y, x + tw, y + th))


class SceneArt:
    """Static pieces of a scene prepared once: background, card art, card overlay."""

    def __init__(self, w, h, headline, art, accent, tint, side):
        self.w, self.h, self.side = w, h, side
        self.L = L = layout(w, h, side)
        x0, y0, x1, y1 = L["card"]
        self.cw, self.ch = x1 - x0, y1 - y0
        bg = paper(w, h, tint)
        d = ImageDraw.Draw(bg)
        hx0, hy0, hx1, hy1 = L["head"]
        fs = L["fs"]
        while True:   # shrink until the whole headline fits in two lines
            font = _font(fs)
            lines = wrap(headline, font, hx1 - hx0, d, 9)
            if len(lines) <= 2 or fs < L["fs"] * 0.6:
                break
            fs = int(fs * 0.92)
        lines = lines[:2]
        lh = int(fs * 1.12)
        yy = hy0 + max(0, ((hy1 - hy0) - lh * len(lines) - 26) // 2)
        for ln in lines:
            tw = d.textlength(ln, font=font)
            d.text((hx0 + ((hx1 - hx0) - tw) / 2, yy), ln, font=font, fill=INK)
            yy += lh
        d.rounded_rectangle([w * 0.5 - w * 0.17, yy + 4, w * 0.5 + w * 0.17, yy + 16], 6, fill=accent)
        # hard offset shadow in the accent colour, then ground squiggle for the figure
        off = max(10, int(w * 0.011))
        d.rounded_rectangle([x0 + off, y0 + off, x1 + off, y1 + off], 30, fill=accent)
        fcx, floor, fh = L["fig"]
        d.line([(fcx - fh * 0.42, floor + 8), (fcx + fh * 0.42, floor + 8)], fill=INK, width=max(4, int(fh * 0.014)))
        self.bg = bg
        self.mask = rounded_mask((self.cw, self.ch), 26)
        ov = Image.new("RGBA", (self.cw, self.ch), (0, 0, 0, 0))
        ImageDraw.Draw(ov).rounded_rectangle([0, 0, self.cw - 1, self.ch - 1], 26, outline=INK + (255,),
                                             width=max(8, int(w * 0.009)))
        self.ov = ov
        if art is None:
            flat = Image.new("RGB", (self.cw, self.ch), accent)
            fd = ImageDraw.Draw(flat)
            bf = _font(int(self.ch * 0.5))
            fd.text((self.cw / 2, self.ch / 2), "?", font=bf, fill=(255, 255, 255), anchor="mm")
            art = flat
        self.big = cover(art, (self.cw, self.ch), 1.22)

    def card_at(self, t, span, idx):
        """Card picture (RGBA-less RGB) with slow camera push + pan."""
        k = min(1.0, t / max(span, 0.5))
        z = 1.0 + 0.14 * (k if idx % 2 == 0 else 1 - k)
        bw, bh = self.big.size
        ww, wh = bw / z, bh / z
        pan = (k - 0.5) * (1 if idx % 3 else -1)
        cx = bw / 2 + pan * (bw - ww) * 0.45
        cy = bh / 2
        box = (cx - ww / 2, cy - wh / 2, cx + ww / 2, cy + wh / 2)
        art = self.big.resize((self.cw, self.ch), Image.BILINEAR, box=box)
        return art


def draw_progress(frame, w, h, frac, accent):
    d = ImageDraw.Draw(frame)
    d.rectangle([0, 0, int(w * frac), max(6, h // 160)], fill=accent)


# ----------------------------------------------------------------------------- scene render
def render_scene(sa, keys, mood, fx, accent, span, dest, w, h, fps, idx, prog0=None, prog1=None):
    frames = max(2, int(round(span * fps)))
    L = sa.L
    x0, y0, x1, y1 = L["card"]
    fcx, floor, fh = L["fig"]
    flip = sa.side == 1 if not L["land"] else sa.side == 0   # face the card
    cache = {}
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", str(dest)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for f in range(frames):
            t = f / fps
            # which pose keyframe is active
            ki = 0
            for j, (kt, _) in enumerate(keys):
                if t >= kt:
                    ki = j
            kt, kp = keys[ki]
            prev = keys[ki - 1][1] if ki > 0 else POSES["idle"]
            tm = t - kt
            pose = _mix(prev, kp, tm / 0.45)
            ph = round(((t / 1.6) % 1.0) * 12) / 12
            sway = math.sin(ph * 2 * math.pi) * 3
            pose = dict(pose)
            pose["la1"] += sway
            pose["ra1"] -= sway
            q = round(min(tm, 0.45) / 0.45 * 6)
            fxt = round(tm * 10) / 10 if tm < 1.7 else 9.0
            key = (ki, q, ph, mood, fx if fxt < 1.7 or fx in ("spark", "q") else None, fxt if fxt < 1.7 else 9.0)
            if key not in cache:
                cache[key] = draw_figure(pose, MOODS[mood], fh, flip, ph, accent,
                                         fx if (fxt < 1.7 or fx in ("spark", "q")) else None, fxt)
                if len(cache) > 400:
                    cache.pop(next(iter(cache)))
            fig, feet = cache[key]
            frame = sa.bg.copy()
            art = sa.card_at(t, span, idx)
            pop = _ease(t / 0.32)
            if pop < 1.0:
                tile = art.convert("RGBA")
                tile.paste(sa.ov, (0, 0), sa.ov)
                s = 0.82 + 0.18 * pop
                tw, th = int(sa.cw * s), int(sa.ch * s)
                tile = tile.resize((tw, th), Image.BILINEAR)
                m = sa.mask.resize((tw, th), Image.BILINEAR)
                frame.paste(tile.convert("RGB"), (x0 + (sa.cw - tw) // 2, y0 + (sa.ch - th) // 2), m)
            else:
                frame.paste(art, (x0, y0), sa.mask)
                frame.paste(sa.ov, (x0, y0), sa.ov)
            # figure drops in with a little hop
            hop = (1 - pop) * -fh * 0.12 if pop < 1.0 else 0
            frame.paste(fig, (int(fcx - fig.width / 2), int(floor - feet + hop)), fig)
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
    shape = "wide landscape composition" if land else "wide composition"
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
        accent, tint = ACCENTS[i % len(ACCENTS)], TINTS[i % len(TINTS)]
        side = i % 2
        sa = SceneArt(w, h, dt["headline"], arts[i], accent, tint, side)
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
