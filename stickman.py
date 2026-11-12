"""Stick-figure storytelling renderer v5 "ink" (only used when VISUAL_STYLE=stickman).

Every scene is a bold black-ink stickman (drawn in code: thick limbs, round white head) acting next to big doodle
props (inkdraw.py icon library) on clean white / pale yellow, with a lively camera move.
Headline with a yellow highlighter swipe, original gold-word captions on top (burned by render.py).
Vertical 9:16 for Shorts, 16:9 for long videos. The cinematic renderer never imports this module.
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
import inkdraw as K

INK = (18, 18, 22)
YELLOW = (255, 205, 40)
WHITE = (255, 255, 255)
BGS = [(255, 255, 255), (255, 255, 255), (255, 246, 204), (255, 255, 255), (255, 255, 255), (255, 240, 180)]
FONTS = [str(Path(__file__).with_name("fonts") / "Anton.ttf"),
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
TRANSITIONS = ["slideleft", "wipeleft", "circleopen", "smoothleft", "zoomin", "slideup", "fadewhite"]
CHUNK = 10   # scenes per xfade chain (keeps ffmpeg light on long videos)

def _font(size):
    for f in FONTS:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def _ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _back(t):
    t = max(0.0, min(1.0, t))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


# ----------------------------------------------------------------------------- layout
def layout(w, h):
    if w >= h:   # landscape: stage is nearly the whole frame, headline top-centre
        return dict(land=True, head=(int(w * 0.10), int(h * 0.03), int(w * 0.90), int(h * 0.165)), maxlines=1,
                    box=(0, int(h * 0.19), w, int(h * 0.90)), fs=int(h * 0.10))
    return dict(land=False, head=(int(w * 0.05), int(h * 0.04), int(w * 0.95), int(h * 0.145)), maxlines=2,
                box=(0, int(h * 0.14), w, int(h * 0.76)), fs=int(h * 0.07))


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


def headline_image(text, box, fs0, maxlines):
    """Anton caps in ink with a yellow highlighter swipe behind the longest word."""
    bw, bh = box[2] - box[0], box[3] - box[1]
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    text = text.upper()
    fs = fs0
    while True:
        font = _font(fs)
        lines = wrap(text, font, bw - fs * 0.3, probe, 12)
        lh = int(fs * 1.16)
        if (len(lines) <= maxlines and lh * len(lines) <= bh) or fs < fs0 * 0.4:
            break
        fs = int(fs * 0.92)
    lines = lines[:maxlines]
    key = max(text.split(), key=len) if text.split() else ""
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y0 = max(0, (bh - lh * len(lines)) // 2)
    pos = []
    y = y0
    for ln in lines:
        x = (bw - d.textlength(ln, font=font)) / 2
        for wd in ln.split():
            pos.append((wd, x, y))
            x += d.textlength(wd + " ", font=font)
        y += lh
    for wd, x, y in pos:
        if wd == key:
            tw = d.textlength(wd, font=font)
            d.rounded_rectangle([x - fs * 0.10, y + fs * 0.30, x + tw + fs * 0.10, y + fs * 0.98], int(fs * 0.12), fill=YELLOW)
    for wd, x, y in pos:
        d.text((x, y), wd, font=font, fill=INK)
    return img


class SceneArt:
    """One scene = stage with: soft blob, big main prop, small second prop, stickman hero, ground line, decorations."""

    def __init__(self, w, h, headline, icons, tint, idx, side):
        self.w, self.h, self.idx, self.side = w, h, idx, side
        self.L = L = layout(w, h)
        bx0, by0, bx1, by1 = L["box"]
        self.bw, self.bh = bx1 - bx0, by1 - by0
        bw, bh = self.bw, self.bh
        self.tint = tint
        hb = L["head"]
        self.head = headline_image(headline, hb, L["fs"], L["maxlines"])
        self.head_pos = (hb[0], hb[1])
        land = L["land"]
        # stage geometry -----------------------------------------------------------------
        self.fh = int(bh * (0.80 if land else 0.60))                         # figure height
        self.floor = int(bh * (0.95 if land else 0.93))
        self.fig_cx = int(bw * ((0.25 if side == 0 else 0.75) if land else (0.30 if side == 0 else 0.70)))
        opp = 1 - side
        main_px = int(bh * 0.60) if land else int(bw * 0.50)
        self.main = K.render_icon(icons[0], main_px)
        self.main_c = (int(bw * ((0.72 if opp == 1 else 0.28) if land else (0.70 if opp == 1 else 0.30))),
                       int(bh * (0.42 if land else 0.27)))
        self.second = None
        if len(icons) > 1:
            sp = int(bh * 0.30) if land else int(bw * 0.24)
            self.second = K.render_icon(icons[1], sp)
            self.second_c = (int(self.fig_cx + (0.02 * bw if side else -0.02 * bw)), int(bh * (0.15 if land else 0.12)))
            if land:
                self.second_c = (int(bw * (0.46 if side == 0 else 0.54)), int(bh * 0.17))
        # pale blob behind the action
        blob = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        r = int(min(bw, bh) * (0.46 if land else 0.44))
        bd = ImageDraw.Draw(blob)
        bcol = (255, 244, 196, 255) if tint == (255, 255, 255) else (255, 252, 236, 255)
        cx, cy = int(bw * 0.5), int(bh * 0.52)
        bd.ellipse([cx - int(r * (1.25 if land else 1.0)), cy - r, cx + int(r * (1.25 if land else 1.0)), cy + r], fill=bcol)
        self.blob = blob
        # ground line + shadow
        ground = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        gd = ImageDraw.Draw(ground)
        gw = int(self.fh * 0.62)
        gd.ellipse([self.fig_cx - gw, self.floor - int(self.fh * 0.03), self.fig_cx + gw, self.floor + int(self.fh * 0.05)], fill=(205, 205, 210, 255))
        gd.line([(self.fig_cx - gw * 1.1, self.floor + int(self.fh * 0.03)), (self.fig_cx + gw * 1.1, self.floor + int(self.fh * 0.03))],
                fill=INK + (255,), width=max(4, int(self.fh * 0.014)))
        self.ground = ground
        back = Image.new("RGB", (bw, bh), tint)
        back.paste(blob, (0, 0), blob)
        back.paste(ground, (0, 0), ground)
        self.back = back
        self.lines = K.speed_lines(int(bw * 0.30), int(self.fh * 0.5), side)
        self.sp = K.sparkle(max(24, int(bw * 0.05)))
        self.sp2 = K.sparkle(max(16, int(bw * 0.032)))
        self.rot_cache = {}

    def rotated(self, key, img, ang):
        k = (key, round(ang))
        if k not in self.rot_cache:
            self.rot_cache[k] = img.rotate(round(ang), Image.BICUBIC, expand=True)
            if len(self.rot_cache) > 300:
                self.rot_cache.pop(next(iter(self.rot_cache)))
        return self.rot_cache[k]


def draw_progress(frame, w, h, frac):
    ImageDraw.Draw(frame).rectangle([0, 0, int(w * frac), max(6, h // 160)], fill=YELLOW)


def paste_center(stage, img, cx, cy, scale=1.0):
    if scale != 1.0:
        img = img.resize((max(2, int(img.width * scale)), max(2, int(img.height * scale))), Image.BILINEAR)
    stage.paste(img, (int(cx - img.width / 2), int(cy - img.height / 2)), img)


# ----------------------------------------------------------------------------- scene render
def render_scene(sa, keys, mood, fx, span, dest, w, h, fps, prog0=None, prog1=None):
    frames = max(2, int(round(span * fps)))
    L = sa.L
    bx0, by0, bx1, by1 = L["box"]
    bw, bh = sa.bw, sa.bh
    flip = (sa.side == 1)       # face toward the middle of the frame
    cache = {}
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", str(dest)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    off_x = (-1 if sa.fig_cx < bw / 2 else 1) * bw * 0.6
    base = Image.new("RGB", (w, h), sa.tint)
    try:
        for f in range(frames):
            t = f / fps
            ki = 0
            for j, (kt, _) in enumerate(keys):
                if t >= kt:
                    ki = j
            kt, kp = keys[ki]
            prev = keys[ki - 1][1] if ki > 0 else K.POSES["idle"]
            tm = t - kt
            pose = dict(K.mix(prev, kp, tm / 0.40))
            ph = round(((t / 1.5) % 1.0) * 12) / 12
            sway = math.sin(ph * 2 * math.pi) * 4
            pose["la1"] += sway
            pose["ra1"] -= sway
            q = round(min(tm, 0.40) / 0.40 * 6)
            fx_on = fx if (fx in ("spark", "q") or tm < 1.7) else None
            fxt = round(tm * 10) / 10 if tm < 1.7 else 9.0
            key = (ki, q, ph, mood, fx_on, fxt)
            if key not in cache:
                cache[key] = K.draw_figure(pose, K.MOODS[mood], sa.fh, flip, ph, fx_on, fxt)
                if len(cache) > 400:
                    cache.pop(next(iter(cache)))
            fig, feet = cache[key]
            stage = sa.back.copy()
            # speed lines trail behind the figure while it enters / runs
            if t < 0.55 or keys[ki][1] is K.POSES["run"]:
                lx = 0 if sa.side == 0 else bw - sa.lines.width
                stage.paste(sa.lines, (lx, int(sa.floor - sa.fh * 0.8)), sa.lines)
            # props: pop with overshoot, then a slow wiggle
            p1 = _back((t - 0.10) / 0.45)
            wig = round(math.sin(t * 2.0) * 4)
            m = sa.rotated(("m", sa.idx), sa.main, wig)
            paste_center(stage, m, sa.main_c[0], sa.main_c[1] + math.sin(t * 2.4) * bh * 0.008, max(0.05, p1))
            if sa.second is not None:
                p2 = _back((t - 0.40) / 0.45)
                s2 = sa.rotated(("s", sa.idx), sa.second, -wig)
                paste_center(stage, s2, sa.second_c[0], sa.second_c[1], max(0.05, p2))
            # sparkles around the main prop
            pulse = 0.75 + 0.25 * math.sin(t * 5)
            if t > 0.5:
                mx, my = sa.main_c
                off = sa.main.width * 0.55
                paste_center(stage, sa.sp, mx + off, my - off * 0.6, pulse)
                paste_center(stage, sa.sp2, mx - off * 0.9, my + off * 0.5, 1.6 - pulse)
            # figure slides in from the edge and settles
            slide = (1 - _ease(t / 0.38)) * off_x
            stage.paste(fig, (int(sa.fig_cx - fig.width / 2 + slide), int(sa.floor - feet)), fig)
            # camera push on the whole stage
            k = min(1.0, t / max(span, 0.5))
            z = 1.0 + 0.07 * (k if sa.idx % 2 == 0 else 1 - k)
            ww, wh = bw / z, bh / z
            cx = bw / 2 + (k - 0.5) * (bw - ww) * (0.6 if sa.idx % 3 == 0 else 0.0)
            stage = stage.resize((bw, bh), Image.BILINEAR, box=(cx - ww / 2, (bh - wh) / 2 + (bh - wh) * 0.1,
                                                                 cx + ww / 2, (bh - wh) / 2 + wh + (bh - wh) * 0.1))
            frame = base.copy()
            frame.paste(stage, (bx0, by0))
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
            if prog0 is not None:
                draw_progress(frame, w, h, prog0 + (prog1 - prog0) * (f / frames))
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
        icons, pose, mood = K.guess_from_text(sc["text"], i)
        words = re.findall(r"[A-Za-z0-9'-]+", sc["text"])
        fb.append({"headline": " ".join(words[:4]).upper(), "icons": icons, "pose": pose,
                   "pose2": K.POSE_KEYS[(K.POSE_KEYS.index(pose) + 3) % len(K.POSE_KEYS)], "mood": mood})
    if not A.GEMINI_KEY:
        return fb
    listing = "\n".join(f"{i + 1}. {s['text']}" for i, s in enumerate(scenes))
    ask = (f"Plan a stick-figure storytelling video titled \"{title}\". The same stick-figure hero appears in every scene next to big "
           "doodle icons. For each numbered narration line return an object with: "
           "\"headline\" (2-4 word ALL-CAPS hook phrase taken from the line, no punctuation), "
           f"\"icons\" (1 or 2 names from this list that best show the idea, most important first: {', '.join(K.ICON_NAMES)}), "
           f"\"pose\" and \"pose2\" (each one of: {', '.join(K.POSE_KEYS)}), "
           "and \"mood\" (happy, neutral, shocked or sad). Match emotion and action to the line and vary everything between scenes. "
           f"Return ONLY a JSON array of exactly {n} objects in order.\n\n{listing}")
    import time as _t
    for attempt in range(3):
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
                        ic = [x for x in (o.get("icons") or []) if x in K.ICONS][:2] or f["icons"]
                        p1 = o.get("pose") if o.get("pose") in K.POSES else f["pose"]
                        p2 = o.get("pose2") if o.get("pose2") in K.POSES else f["pose2"]
                        mood = o.get("mood") if o.get("mood") in K.MOODS else f["mood"]
                        out.append({"headline": str(o.get("headline") or f["headline"]).upper()[:44], "icons": ic,
                                    "pose": p1, "pose2": p2, "mood": mood})
                    return out
            except Exception as exc:
                A.note(f"Stickman planner {model} failed: {exc}")
        _t.sleep(4)
    A.note("Stickman planner unavailable: using keyword fallback")
    return fb


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
    total = scenes[-1]["t1"]
    for i, (sc, dt) in enumerate(zip(scenes, det)):
        sa = SceneArt(w, h, dt["headline"], dt["icons"], BGS[i % len(BGS)], i, i % 2)
        end_of_chunk = (i % CHUNK == CHUNK - 1) or i == len(scenes) - 1
        base = sc["t1"] - sc["t0"]
        span = base + (0 if end_of_chunk else A.OVERLAP)
        keys = [(0.0, K.POSES[dt["pose"]])]
        if base > 4.6:
            keys.append((base * 0.5, K.POSES[dt["pose2"]]))
        fx = K.FX_FOR_POSE.get(dt["pose"]) or ("spark" if dt["mood"] == "happy" else None)
        seg = work / f"stkseg_{i}.mp4"
        render_scene(sa, keys, dt["mood"], fx, span, seg, w, h, fps,
                     (sc["t0"] / total) if land else None, (sc["t1"] / total) if land else None)
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
