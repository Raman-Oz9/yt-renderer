"""Procedural stick-figure scenes (only used when VISUAL_STYLE=stickman).

Each scene = warm paper with faint grid + a headline + an AI-drawn marker prop
(multiplied onto the paper) + a stick figure drawn in code that moves between
poses.  Frames are piped straight to ffmpeg; every scene mp4 is exactly its span.
The cinematic renderer never imports this module.
"""
import json
import math
import re
import subprocess
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

import ai_scenes as A

PAPER = (253, 252, 247)
GRID = (232, 232, 226)
INK = (20, 20, 24)
ACCENTS = [(214, 62, 52), (240, 180, 30), (40, 140, 90), (30, 60, 120)]
FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"]

# angles in degrees from straight-down, + = toward screen right
POSES = {
    "idle":     dict(lean=0,   head=0,   la1=-12, la2=-8,  ra1=12,  ra2=8,   ll1=-6, ll2=-6, rl1=6,  rl2=6),
    "point":    dict(lean=4,   head=6,   la1=-12, la2=-8,  ra1=75,  ra2=80,  ll1=-6, ll2=-6, rl1=6,  rl2=6),
    "surprise": dict(lean=-6,  head=-4,  la1=-140, la2=-160, ra1=140, ra2=160, ll1=-12, ll2=-12, rl1=12, rl2=12),
    "think":    dict(lean=3,   head=8,   la1=-12, la2=-8,  ra1=30,  ra2=150, ll1=-6, ll2=-6, rl1=6,  rl2=6),
    "wave":     dict(lean=0,   head=4,   la1=-12, la2=-8,  ra1=120, ra2=160, ll1=-6, ll2=-6, rl1=6,  rl2=6),
    "run":      dict(lean=14,  head=6,   la1=-55, la2=-110, ra1=50, ra2=100, ll1=-40, ll2=-10, rl1=35, rl2=70),
    "cheer":    dict(lean=-4,  head=-6,  la1=-150, la2=-165, ra1=150, ra2=165, ll1=-16, ll2=-16, rl1=16, rl2=16),
    "shrug":    dict(lean=0,   head=10,  la1=-55, la2=-110, ra1=55, ra2=110, ll1=-6, ll2=-6, rl1=6,  rl2=6),
    "fear":     dict(lean=-10, head=-6,  la1=-35, la2=-150, ra1=35, ra2=150, ll1=-10, ll2=-14, rl1=14, rl2=18),
}
POSE_KEYS = list(POSES)
MOODS = {"happy": 1, "neutral": 0, "shocked": 2, "sad": -1}


def _font(size):
    for f in FONTS:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def _ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _pose_mix(a, b, t):
    t = _ease(t)
    return {k: a[k] + (b[k] - a[k]) * t for k in a}


def draw_figure(pose, mood, scale, flip, phase):
    """Return an RGBA stick figure image (supersampled, then reduced)."""
    S = 2
    H = int(520 * scale) * S
    W = int(520 * scale) * S
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = scale * S
    lw = max(3, int(9 * u))
    bob = math.sin(phase * 2 * math.pi) * 5 * u
    cx = W / 2
    hip = (cx, 300 * u + bob)
    lean = math.radians(pose["lean"])
    torso = 120 * u
    neck = (hip[0] + math.sin(lean) * torso, hip[1] - math.cos(lean) * torso)

    def limb(p, a1, a2, l1, l2):
        r1, r2 = math.radians(a1), math.radians(a2)
        m = (p[0] + math.sin(r1) * l1, p[1] + math.cos(r1) * l1)
        e = (m[0] + math.sin(r2) * l2, m[1] + math.cos(r2) * l2)
        return m, e

    # legs
    for a1, a2 in ((pose["ll1"], pose["ll2"]), (pose["rl1"], pose["rl2"])):
        m, e = limb(hip, a1, a2, 85 * u, 85 * u)
        d.line([hip, m, e], fill=INK, width=lw, joint="curve")
        d.ellipse([e[0] - lw * .6, e[1] - lw * .6, e[0] + lw * .6, e[1] + lw * .6], fill=INK)
    # arms
    for a1, a2 in ((pose["la1"], pose["la2"]), (pose["ra1"], pose["ra2"])):
        sh = (neck[0], neck[1] + 14 * u)
        m, e = limb(sh, a1, a2, 70 * u, 70 * u)
        d.line([sh, m, e], fill=INK, width=lw, joint="curve")
        d.ellipse([e[0] - lw * .9, e[1] - lw * .9, e[0] + lw * .9, e[1] + lw * .9], fill=INK)
    d.line([hip, neck], fill=INK, width=lw)
    # head
    hr = 46 * u
    hc = (neck[0] + math.sin(math.radians(pose["head"])) * 20 * u, neck[1] - hr - 6 * u)
    d.ellipse([hc[0] - hr, hc[1] - hr, hc[0] + hr, hc[1] + hr], fill=(255, 255, 255, 255), outline=INK, width=lw)
    ex = hr * 0.38
    ey = hc[1] - hr * 0.12
    er = max(3, int(6 * u)) if mood != 2 else int(9 * u)
    for sx in (-1, 1):
        x = hc[0] + sx * ex
        if mood == 2:
            d.ellipse([x - er, ey - er, x + er, ey + er], outline=INK, width=max(2, int(3 * u)))
        else:
            d.ellipse([x - er * .7, ey - er * .7, x + er * .7, ey + er * .7], fill=INK)
    my = hc[1] + hr * 0.42
    mw = hr * 0.42
    if mood == 1:
        d.arc([hc[0] - mw, my - mw * .8, hc[0] + mw, my + mw * .6], 15, 165, fill=INK, width=max(2, int(4 * u)))
    elif mood == -1:
        d.arc([hc[0] - mw, my - mw * .2, hc[0] + mw, my + mw * 1.2], 195, 345, fill=INK, width=max(2, int(4 * u)))
    elif mood == 2:
        d.ellipse([hc[0] - mw * .45, my - mw * .5, hc[0] + mw * .45, my + mw * .6], outline=INK, width=max(2, int(4 * u)))
    else:
        d.line([hc[0] - mw * .6, my, hc[0] + mw * .6, my], fill=INK, width=max(2, int(4 * u)))
    img = img.resize((W // S, H // S), Image.LANCZOS)
    if flip:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    return img


def paper(w, h):
    img = Image.new("RGB", (w, h), PAPER)
    d = ImageDraw.Draw(img)
    step = max(40, w // 20)
    for x in range(0, w, step):
        d.line([(x, 0), (x, h)], fill=GRID, width=2)
    for y in range(0, h, step):
        d.line([(0, y), (w, y)], fill=GRID, width=2)
    return img


def wrap_headline(text, font, maxw, draw):
    lines, cur = [], ""
    for wd in text.split():
        t = (cur + " " + wd).strip()
        if draw.textlength(t, font=font) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines[:3]


def plan_details(scenes, title):
    """Gemini: per scene a headline, a prop to doodle, a pose and a mood. Deterministic fallback."""
    n = len(scenes)
    fb = []
    for i, sc in enumerate(scenes):
        words = re.findall(r"[A-Za-z0-9'-]+", sc["text"])
        fb.append({"headline": " ".join(words[:4]).upper(),
                   "prop": f"{title}, {' '.join(words[:8])}",
                   "pose": POSE_KEYS[i % len(POSE_KEYS)], "mood": "neutral"})
    if not A.GEMINI_KEY:
        return fb
    listing = "\n".join(f"{i + 1}. {s['text']}" for i, s in enumerate(scenes))
    ask = (f"Plan a stick-figure explainer Short titled \"{title}\". For each numbered narration line return an object with: "
           "\"headline\" (2-4 word ALL-CAPS key phrase from the line, no punctuation), "
           "\"prop\" (one concrete drawable object or diagram the line is about, max 14 words, e.g. 'a volcano with orange lava'), "
           f"\"pose\" (one of {', '.join(POSE_KEYS)}) and \"mood\" (one of happy, neutral, shocked, sad). "
           "Vary the poses; match emotion to the line. "
           f"Return ONLY a JSON array of exactly {n} objects in order.\n\n{listing}")
    for model in A.TEXT_MODELS:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": A.GEMINI_KEY},
                json={"contents": [{"parts": [{"text": ask}]}],
                      "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 4096}},
                timeout=90)
            if r.status_code != 200:
                A.note(f"Stickman planner {model}: {r.status_code}")
                continue
            arr = A.parse_json_list(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            if isinstance(arr, list) and len(arr) == n:
                out = []
                for o, f in zip(arr, fb):
                    o = o if isinstance(o, dict) else {}
                    pose = o.get("pose") if o.get("pose") in POSES else f["pose"]
                    mood = o.get("mood") if o.get("mood") in MOODS else "neutral"
                    out.append({"headline": str(o.get("headline") or f["headline"]).upper()[:40],
                                "prop": str(o.get("prop") or f["prop"])[:160], "pose": pose, "mood": mood})
                return out
        except Exception as exc:
            A.note(f"Stickman planner {model} failed: {exc}")
    return fb


PROP_STYLE = ("simple hand-drawn marker doodle on a plain pure white background, thick black pen outline, flat colour fill "
              "in red, yellow, green or blue, one single object, centred, lots of empty white space around it, "
              "no text, no letters, no numbers, no people, no stick figure, no shadow")


def get_prop(desc, dest):
    src = A.make_image(f"{desc}, {PROP_STYLE}", dest)
    if not src:
        return None
    try:
        im = Image.open(dest).convert("RGB")
        return im
    except Exception:
        return None


def multiply_prop(base, prop, box):
    """Place prop (white bg) into box on the paper using multiply so white vanishes."""
    bw, bh = box[2] - box[0], box[3] - box[1]
    p = prop.copy()
    p.thumbnail((bw, bh), Image.LANCZOS)
    # lift near-white to pure white so the paper shows through cleanly
    arr = np.asarray(p).astype(np.float32)
    arr = np.clip((arr - 40) * (255.0 / 190.0), 0, 255)
    p = Image.fromarray(arr.astype(np.uint8))
    x = box[0] + (bw - p.width) // 2
    y = box[1] + (bh - p.height) // 2
    region = base.crop((x, y, x + p.width, y + p.height))
    mul = Image.fromarray((np.asarray(region).astype(np.float32) * np.asarray(p).astype(np.float32) / 255.0).astype(np.uint8))
    base.paste(mul, (x, y))
    return (x, y, p.width, p.height)


def make_bg(w, h, headline, prop, accent):
    bg = paper(w, h)
    d = ImageDraw.Draw(bg)
    fs = int(w * 0.105)
    font = _font(fs)
    lines = wrap_headline(headline, font, w * 0.86, d)
    y = int(h * 0.07)
    for ln in lines:
        tw = d.textlength(ln, font=font)
        d.text(((w - tw) / 2, y), ln, font=font, fill=INK)
        y += int(fs * 1.15)
    d.rectangle([w * 0.18, y + 8, w * 0.82, y + 18], fill=accent)
    top = y + 50
    if prop is not None:
        multiply_prop(bg, prop, (int(w * 0.08), top, int(w * 0.92), int(h * 0.56)))
    else:
        d.ellipse([w * .3, top + 60, w * .7, top + 60 + w * .4], outline=accent, width=14)
    return bg


def render_scene(bg, pose_a, pose_b, mood, span, dest, w, h, fps, side):
    frames = max(2, int(round(span * fps)))
    scale = w / 1080 * 1.0
    fig_w = int(520 * scale)
    base_y = int(h * 0.375)
    x0 = int(w * (0.04 if side == 0 else 0.96 - fig_w / w))
    x_mid = int(w * 0.5 - fig_w / 2)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "21", "-pix_fmt", "yuv420p", str(dest)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    big = 1.6
    try:
        for f in range(frames):
            t = f / fps
            pop = _ease(t / 0.35)
            frame = bg.copy()
            pose = _pose_mix(pose_a, pose_b, t / 0.45)
            # slow drift of the figure toward the middle, flipped to face the prop
            flip = side == 1
            fig = draw_figure(pose, MOODS[mood], big * scale * (0.9 + 0.1 * pop), flip, t / 1.6)
            shift = (-1 if side == 0 else 1) * w * 0.12 * (1 - min(1.0, t / max(span, 0.1)) * 0.5)
            xx = int(w / 2 - fig.width / 2 + shift)
            yy = base_y
            frame.paste(fig, (xx, yy), fig)
            proc.stdin.write(np.asarray(frame).tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed for stickman scene")


def build(script, title, words, length, work, w, h, fps):
    A._BUDGET_END[0] = A.time.time() + 34 * 60
    scenes = A.plan_scenes(script, words, length)
    A.note(f"Stickman scenes planned: {len(scenes)}")
    det = plan_details(scenes, title)
    segs, spans = [], []
    prev = POSES["idle"]
    for i, (sc, dt) in enumerate(zip(scenes, det)):
        accent = ACCENTS[i % len(ACCENTS)]
        prop = get_prop(dt["prop"], Path(work) / f"stk_prop_{i}.img")
        bg = make_bg(w, h, dt["headline"], prop, accent)
        span = sc["t1"] - sc["t0"] + (A.OVERLAP if i < len(scenes) - 1 else 0)
        seg = Path(work) / f"stkseg_{i}.mp4"
        target = POSES[dt["pose"]]
        render_scene(bg, prev, target, dt["mood"], span, seg, w, h, fps, i % 2)
        prev = target
        segs.append(seg)
        spans.append(sc["t1"] - sc["t0"])
        A.note(f"Stickman scene {i + 1}/{len(scenes)} done (prop={'ai' if prop else 'none'})")
    joined = Path(work) / "stk_joined.mp4"
    try:
        # plain cross-dissolve, no film grain/vignette for the flat paper look
        n = len(segs)
        if n == 1:
            return [segs[0]]
        parts, cum, last = [], 0.0, "[0:v]"
        for k in range(n - 1):
            cum += spans[k]
            parts.append(f"{last}[{k + 1}:v]xfade=transition=fade:duration={A.OVERLAP}:offset={cum:.3f}[x{k}]")
            last = f"[x{k}]"
        parts[-1] = parts[-1].rsplit("[x", 1)[0] + "[v]"
        cmd = ["ffmpeg", "-y", "-loglevel", "error"]
        for sg in segs:
            cmd += ["-i", str(sg)]
        cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-an", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", str(joined)]
        subprocess.run(cmd, check=True)
        return [joined]
    except Exception as exc:
        A.note(f"Stickman join failed ({exc}); hard cuts")
        out = []
        for k, (sg, sp) in enumerate(zip(segs, spans)):
            o = Path(work) / f"stkcut_{k}.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(sg), "-t", f"{sp:.3f}",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", str(o)], check=True)
            out.append(o)
        return out
