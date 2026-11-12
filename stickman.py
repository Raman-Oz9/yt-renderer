"""Stick-figure storytelling renderer v5 "ink" (only used when VISUAL_STYLE=stickman).

Every scene is an AI-drawn bold black-ink stickman doodle (thick marker limbs, round white head, a few
props, yellow accent, speed lines) on clean white / pale yellow, shown BIG with a lively camera move.
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
from PIL import Image, ImageChops, ImageDraw, ImageFont

import ai_scenes as A

INK = (18, 18, 22)
YELLOW = (255, 205, 40)
WHITE = (255, 255, 255)
BGS = [(255, 255, 255), (255, 255, 255), (255, 246, 204), (255, 255, 255), (255, 255, 255), (255, 240, 180)]
FONTS = [str(Path(__file__).with_name("fonts") / "Anton.ttf"),
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
TRANSITIONS = ["slideleft", "wipeleft", "circleopen", "smoothleft", "zoomin", "slideup", "fadewhite"]
CHUNK = 10   # scenes per xfade chain (keeps ffmpeg light on long videos)

ART_STYLE = ("hand-drawn doodle cartoon in the style of a bold black ink stick figure comic: ONE simple stick figure character "
             "with a round white head, tiny dot eyes and a small smile, thick solid black marker arms, legs and body, "
             "expressive exaggerated pose acting out the scene, a few simple props drawn with clean black outlines, "
             "a small touch of bright yellow as the only colour accent, light grey speed lines and small spark lines, "
             "sketchy ground shadow line, clean pure white background, lots of empty white space around, centred, "
             "no text, no letters, no numbers, no watermark")


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
    if w >= h:   # landscape: headline column on the left, picture big on the right
        return dict(land=True, head=(int(w * 0.04), int(h * 0.12), int(w * 0.31), int(h * 0.62)), maxlines=5,
                    box=(int(w * 0.30), int(h * 0.03), int(w * 0.99), int(h * 0.90)), fs=int(h * 0.12))
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
    for wd, x, y in pos:   # highlighter first
        if wd == key:
            tw = d.textlength(wd, font=font)
            d.rounded_rectangle([x - fs * 0.12, y + fs * 0.34, x + tw + fs * 0.12, y + fs * 0.98], int(fs * 0.12), fill=YELLOW)
    for wd, x, y in pos:
        d.text((x, y), wd, font=font, fill=INK)
    return img


def feather(size, edge=0.06):
    """White at the borders, black inside: used with 'lighter' so picture edges melt into the page."""
    w, h = size
    fx = np.minimum(np.arange(w), w - 1 - np.arange(w)) / max(1.0, edge * w)
    fy = np.minimum(np.arange(h), h - 1 - np.arange(h)) / max(1.0, edge * h)
    m = np.clip(np.minimum(fy[:, None], fx[None, :]), 0, 1)
    return Image.fromarray(((1 - m) * 255).astype(np.uint8)).convert("RGB")


class SceneArt:
    def __init__(self, w, h, headline, art, tint, idx):
        self.w, self.h, self.idx = w, h, idx
        self.L = L = layout(w, h)
        bx0, by0, bx1, by1 = L["box"]
        self.bw, self.bh = bx1 - bx0, by1 - by0
        self.bg = Image.new("RGB", (w, h), tint)
        hb = L["head"]
        self.head = headline_image(headline, hb, L["fs"], L["maxlines"])
        self.head_pos = (hb[0], hb[1])
        if art is None:
            art = Image.new("RGB", (768, 768), WHITE)
            ImageDraw.Draw(art).text((384, 384), "?", font=_font(420), fill=INK, anchor="mm")
        arr = np.asarray(art.convert("RGB")).astype(np.float32)
        arr = np.clip(arr * (255.0 / 236.0), 0, 255)          # lift near-white to pure white
        art = Image.fromarray(arr.astype(np.uint8))
        a = max(art.size)
        self.art = art.resize((a * 2, a * 2), Image.LANCZOS) if a < 1500 else art
        self.edge = feather((self.bw, self.bh))
        # how big the picture sits: art side = box height * 1.32 (subject fills the frame)
        self.scale = (self.bh * 1.38) / self.art.height

    def picture_at(self, t, span):
        k = min(1.0, t / max(span, 0.5))
        i = self.idx
        mode = i % 4
        if mode == 0:
            z, px, py = 1.0 + 0.16 * k, 0.0, 0.0
        elif mode == 1:
            z, px, py = 1.16 - 0.16 * k, 0.0, 0.0
        elif mode == 2:
            z, px, py = 1.08 + 0.06 * k, (k - 0.5) * 0.5, 0.0
        else:
            z, px, py = 1.08 + 0.06 * k, (0.5 - k) * 0.5, 0.0
        ww, wh = self.bw / self.scale / z, self.bh / self.scale / z
        aw, ah = self.art.size
        ww, wh = min(ww, aw), min(wh, ah)
        cx = aw / 2 + px * (aw - ww) * 0.5
        cy = ah / 2 + py * (ah - wh)
        box = (cx - ww / 2, cy - wh / 2, cx + ww / 2, cy + wh / 2)
        pic = self.art.resize((self.bw, self.bh), Image.BILINEAR, box=box)
        return ImageChops.lighter(pic, self.edge)


def draw_progress(frame, w, h, frac):
    ImageDraw.Draw(frame).rectangle([0, 0, int(w * frac), max(6, h // 160)], fill=YELLOW)


# ----------------------------------------------------------------------------- scene render
def render_scene(sa, span, dest, w, h, fps, prog0=None, prog1=None):
    frames = max(2, int(round(span * fps)))
    L = sa.L
    bx0, by0, bx1, by1 = L["box"]
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", str(dest)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for f in range(frames):
            t = f / fps
            frame = sa.bg.copy()
            pic = sa.picture_at(t, span)
            pop = _back(t / 0.40)
            region = frame.crop((bx0, by0, bx1, by1))
            if abs(pop - 1.0) > 0.002:   # picture pops in with a small overshoot
                s = 0.80 + 0.20 * pop
                tw, th = max(2, int(sa.bw * s)), max(2, int(sa.bh * s))
                pic = pic.resize((tw, th), Image.BILINEAR)
                tile = Image.new("RGB", (sa.bw, sa.bh), sa.bg.getpixel((0, 0)))
                tile.paste(ImageChops.multiply(tile.crop(((sa.bw - tw) // 2, (sa.bh - th) // 2,
                                                          (sa.bw - tw) // 2 + tw, (sa.bh - th) // 2 + th)), pic),
                           ((sa.bw - tw) // 2, (sa.bh - th) // 2))
                out = tile
            else:
                out = ImageChops.multiply(region, pic)
            frame.paste(out, (bx0, by0))
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
        words = re.findall(r"[A-Za-z0-9'-]+", sc["text"])
        fb.append({"headline": " ".join(words[:4]).upper(),
                   "scene": f"the stick figure reacting to this: {' '.join(words[:14])}"})
    if not A.GEMINI_KEY:
        return fb
    listing = "\n".join(f"{i + 1}. {s['text']}" for i, s in enumerate(scenes))
    ask = (f"Plan a stick-figure storytelling video titled \"{title}\". The same simple stick figure narrator-hero appears in every "
           "scene. For each numbered narration line return an object with: "
           "\"headline\" (2-4 word ALL-CAPS key phrase from the line, no punctuation), "
           "\"scene\" (what the stick figure is DOING in this moment plus 1-3 concrete props that show the idea, max 30 words, "
           "e.g. 'the stick figure peering into a glowing glass jar of salt crystals, a giant salt shaker beside him'; "
           "emotion and action must match the line; every scene a different striking action and different props; "
           "no text or numbers in the picture). "
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
                    out.append({"headline": str(o.get("headline") or f["headline"]).upper()[:44],
                                "scene": str(o.get("scene") or f["scene"])[:240]})
                return out
        except Exception as exc:
            A.note(f"Stickman planner {model} failed: {exc}")
    return fb


def get_art(desc, dest, land):
    src = A.make_image(f"{desc}. {ART_STYLE}", dest)
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
            arts[i] = last.transpose(Image.FLIP_LEFT_RIGHT)   # reuse (mirrored) rather than a blank page
        elif a is not None:
            last = a

    segs, spans = [], []
    total = scenes[-1]["t1"]
    for i, (sc, dt) in enumerate(zip(scenes, det)):
        sa = SceneArt(w, h, dt["headline"], arts[i], BGS[i % len(BGS)], i)
        end_of_chunk = (i % CHUNK == CHUNK - 1) or i == len(scenes) - 1
        base = sc["t1"] - sc["t0"]
        span = base + (0 if end_of_chunk else A.OVERLAP)
        seg = work / f"stkseg_{i}.mp4"
        render_scene(sa, span, seg, w, h, fps, (sc["t0"] / total) if land else None, (sc["t1"] / total) if land else None)
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
