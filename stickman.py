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
from PIL import Image, ImageDraw

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
    S.PROPS[name](d, bx, by, s, ow * SS, random.Random(seed))
    box = im.getbbox() or (0, 0, 2, 2)
    im = im.crop(box)
    ax, ay = bx - box[0], by - box[1]
    im = im.resize((max(1, im.width // SS), max(1, im.height // SS)), Image.LANCZOS)
    return im, ax / SS, ay / SS


def label_layer(text, size):
    f = S._font(size * SS)
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    lines = text.upper().split("\n")
    wmax = max(probe.textlength(l, font=f) for l in lines)
    pad = int(size * SS * 0.5)
    Wd, Hd = int(wmax + pad * 2), int(size * SS * 1.25 * len(lines) + pad)
    im = Image.new("RGBA", (Wd, Hd), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, l in enumerate(lines):
        d.text((Wd / 2, pad / 2 + size * SS * 1.25 * (i + 0.5)), l, font=f, fill=T.INK, anchor="mm",
               stroke_width=int(size * SS * 0.12), stroke_fill=T.WHITE)
        d.text((Wd / 2, pad / 2 + size * SS * 1.25 * (i + 0.5)), l, font=f, fill=T.INK, anchor="mm")
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


def paste_c(dst, im, cx, cy, scale=1.0, alpha=1.0):
    if scale <= 0.02 or im is None:
        return
    if abs(scale - 1.0) > 0.01:
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.BILINEAR)
    if alpha < 0.99:
        a = im.getchannel("A").point(lambda v: int(v * alpha))
        im = im.copy()
        im.putalpha(a)
    dst.paste(im, (int(cx - im.width / 2), int(cy - im.height / 2)), im)


# ----------------------------------------------------------------------------- scene
class Scene:
    def __init__(self, w, h, spec, idx, seed):
        self.w, self.h, self.idx = w, h, idx
        land = w >= h
        self.land = land
        self.Wd, self.Hd = int(w * MARGIN), int(h * MARGIN)
        self.Hc = int(self.Hd * (1.0 if land else 0.90))   # composition height (vertical keeps the caption zone free)
        ow = S.ow_for(self.Hd)
        self.ow = ow
        rng = random.Random(seed * 131 + idx)
        # ---- background
        big = Image.new("RGB", (self.Wd * SS, self.Hc * SS), (255, 255, 255))
        d = ImageDraw.Draw(big)
        setting = spec.get("setting") if spec.get("setting") in S.SETTINGS else "meadow"
        gy = S.SETTINGS[setting](d, self.Wd * SS, self.Hc * SS, ow * SS, rng) / SS
        self.gy = gy
        bg = big.resize((self.Wd, self.Hc), Image.LANCZOS)
        if self.Hc < self.Hd:   # extend the ground colour under the caption zone
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
        self.bg = bg.convert("RGBA")
        self.dark = setting in ("space", "night", "cave")
        # ---- hero placement
        side = 0 if spec.get("hero_side", "left") == "left" else 1
        self.side = side
        hero_h = (0.58 if land else 0.46) * self.Hc
        self.R = hero_h / 6.4
        self.hx = self.Wd * (0.30 if side == 0 else 0.70) if land else self.Wd * (0.36 if side == 0 else 0.64)
        self.feet = gy + self.Hc * 0.045
        # ---- props
        self.props = []   # (img, x, y_anchor, z_behind, pop_delay)
        ground = [p for p in spec.get("props", []) if p in S.PROPS and p not in S.AIR][:3]
        air = [p for p in spec.get("props", []) if p in S.PROPS and p in S.AIR][:2]
        opp = self.Wd * ((0.72 if side == 0 else 0.28) if land else (0.70 if side == 0 else 0.30))
        base_sz = min(self.Hc * (0.42 if land else 0.34), self.Wd * (0.42 if land else 0.62))
        slots = [(opp, 1.0, False), (self.Wd * (0.52 if side == 0 else 0.48), 0.55, True),
                 (self.Wd * (0.08 if side == 0 else 0.92), 0.5, True)]
        for i, name in enumerate(ground):
            x, k, behind = slots[i]
            sz = base_sz * k * (1.25 if name in ("castle", "house", "mountain", "volcano", "pyramid", "dino", "bug", "car", "boat") else 1.0)
            im, ax, ay = prop_layer(name, sz, ow, seed + i)
            y = gy + self.Hc * (0.06 if not behind else 0.0)
            self.props.append((im, x - ax + im.width / 2, y - ay + im.height / 2, behind, 0.10 + 0.22 * i))
        aslots = [(opp, self.Hc * 0.2), (self.Wd * (0.5 if side == 0 else 0.5), self.Hc * 0.12)]
        for i, name in enumerate(air):
            ax_, ay_ = aslots[i]
            sz = self.Hc * (0.2 if i == 0 else 0.15)
            im, ax, ay = prop_layer(name, sz, ow, seed + 7 + i)
            self.props.append((im, ax_, ay_ + im.height * 0.35, False, 0.3 + 0.2 * i))
        # ---- label
        self.label = None
        lab = (spec.get("label") or "").strip()
        if lab:
            lab = lab[:28]
            words = lab.split()
            if len(words) > 2 or len(lab) > 14:
                half = (len(words) + 1) // 2
                lab = " ".join(words[:half]) + "\n" + " ".join(words[half:])
            self.label = label_layer(lab, self.Hc * (0.07 if land else 0.052))
        # ---- hero + fx
        self.expr = spec.get("expr", "neutral")
        self.p1 = spec.get("pose", "stand")
        self.p2 = spec.get("pose2", self.p1)
        if self.p1 not in T.POSES:
            self.p1 = "stand"
        if self.p2 not in T.POSES:
            self.p2 = self.p1
        self.flip = side == 1
        self.fx = None
        if self.expr in ("shocked",):
            self.fx = effects_layer("shock", self.R, ow)
        elif self.expr in ("scared", "worried"):
            self.fx = effects_layer("sweat", self.R, ow)
        elif self.expr in ("happy", "excited"):
            self.fx = effects_layer("spark", self.R, ow)
        elif self.expr == "sleepy":
            self.fx = effects_layer("zzz", self.R, ow)
        elif self.expr == "think":
            self.fx = effects_layer("question", self.R, ow)
        self.speed = speed_layer(self.R, ow, -1 if side else 1) if self.p1 in ("run", "flee") else None
        self._hero_cache = {}

    def hero(self, blend, blink):
        key = (round(blend * 6), blink)
        if key not in self._hero_cache:
            pose = T.blend_pose(self.p1, self.p2, key[0] / 6)
            img, fy, hip = T.draw_hero(pose, self.expr, self.R, blinking=blink, flip=self.flip)
            self._hero_cache[key] = (img, fy, hip)
        return self._hero_cache[key]


def render_scene(sc, span, dest, w, h, fps, caption_clear=False):
    frames = max(2, int(round(span * fps)))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
           "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(dest)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    Wd, Hd = sc.Wd, sc.Hd
    pull = sc.idx % 2 == 1
    try:
        for f in range(frames):
            t = f / fps
            k = f / max(1, frames - 1)
            if pull:
                k = 1 - k
            world = sc.bg.copy()
            # behind props
            for im, x, y, behind, dl in sc.props:
                if behind:
                    paste_c(world, im, x, y, max(0.05, _back((t - dl) / 0.4)))
            # hero pose: switch from pose1 to pose2 half-way
            tm = span * 0.5
            blend = _ease((t - tm) / 0.45) if sc.p2 != sc.p1 else 0.0
            blink = (t % 3.1) > 2.95
            himg, fy, hip = sc.hero(blend, blink)
            enter = _ease(t / 0.4)
            slide = (1 - enter) * Wd * 0.25 * (-1 if sc.side == 0 else 1)
            bob = math.sin(t * 3.2) * sc.R * 0.03
            hx = sc.hx + slide
            fyw = sc.feet + bob
            x0 = int(hx - hip[0])
            y0 = int(fyw - fy)
            if sc.speed is not None:
                sx = hx - (1 if sc.side == 0 else -1) * sc.R * 3.2
                paste_c(world, sc.speed, sx, fyw - sc.R * 3.2, 1.0, 0.9)
            world.paste(himg, (x0, y0), himg)
            if sc.fx is not None and t > 0.25:
                lean_head = (hx, fyw - sc.R * 5.4)
                p = _back((t - 0.25) / 0.3)
                paste_c(world, sc.fx, hx, y0 + hip[1] - sc.R * 2.95, max(0.1, p))
            # front props
            for im, x, y, behind, dl in sc.props:
                if not behind:
                    paste_c(world, im, x, y, max(0.05, _back((t - dl) / 0.4)))
            if sc.label is not None and t > 0.15:
                paste_c(world, sc.label, Wd / 2, Hd * (0.10 if sc.land else 0.09) + sc.label.height / 2,
                        max(0.05, _back((t - 0.15) / 0.35)))
            # camera
            ww = Wd - (Wd - w) * _ease(k)
            wh = Hd - (Hd - h) * _ease(k)
            cx = Wd * (0.5 + (0.5 - sc.side) * 0.0)
            cy = Hd * 0.5 if sc.land else Hd * 0.5
            box = (cx - ww / 2, cy - wh / 2, cx + ww / 2, cy + wh / 2)
            frame = world.convert("RGB").resize((w, h), Image.BILINEAR, box=box)
            proc.stdin.write(np.asarray(frame).tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed for stickman scene")


# ----------------------------------------------------------------------------- planning
KW = [  # (regex, dict(setting?, props?, expr?, pose?))
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
        f"\"pose\" and \"pose2\" (hero body language at start and end of the line, from: {', '.join(T.POSES)}), "
        f"\"expr\" (hero face, from: {', '.join(T.EXPR)}), "
        "\"hero_side\" (left or right; alternate for variety), "
        "and \"label\" (optional 1-3 word ALL-CAPS name or number worth showing on screen, e.g. a place, year or amount taken from the line; empty string if none). "
        "Match emotion to the line (fear when danger, smug when clever, shocked at surprises). "
        f"Return ONLY a JSON array of exactly {len(lines)} objects in order.\n\n{listing}")


def _clean(o, f):
    o = o if isinstance(o, dict) else {}
    props = [p for p in (o.get("props") or []) if p in S.PROPS][:3] or f["props"]
    p1 = o.get("pose") if o.get("pose") in T.POSES else f["pose"]
    p2 = o.get("pose2") if o.get("pose2") in T.POSES else p1
    return dict(
        setting=o.get("setting") if o.get("setting") in S.SETTINGS else f["setting"],
        props=props, pose=p1, pose2=p2,
        expr=o.get("expr") if o.get("expr") in T.EXPR else f["expr"],
        hero_side="right" if str(o.get("hero_side", "")).lower().startswith("r") else "left",
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
        scn = Scene(w, h, dt, i, seed)
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
