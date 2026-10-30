"""AI-illustrated scenes: one generated picture per sentence of the narration,
animated with a slow zoom/pan, so the visuals always show what is being said.

build_ai_segments(script, words, length, work, w, h, fps) -> list of mp4 paths
(or None if too few scenes could be generated; the caller then falls back to
stock footage).
"""
import base64
import json
import os
import random
import re
import subprocess
import urllib.parse
from pathlib import Path

import requests

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TEXT_MODELS = ["gemini-3.5-flash-lite", "gemini-2.5-flash"]
IMAGE_MODELS = ["gemini-2.5-flash-image", "gemini-2.0-flash-preview-image-generation"]
STYLE = ("cinematic documentary still, dramatic lighting, rich detail, "
         "photorealistic, vertical 9:16 composition, no text, no captions, no watermark")
MIN_SCENE, MAX_SCENE = 3.0, 7.5


def note(msg):
    print(f"::warning title=ai_scenes::{str(msg)[:300]}", flush=True)



def split_sentences(text):
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    return [p for p in parts if p.strip()]


def plan_scenes(script, words, length):
    """Group sentences into scenes of ~3-7.5s with start/end times."""
    sents = split_sentences(script)
    n_words = len(script.split())
    counts = [max(1, len(s.split())) for s in sents]
    # time span of each sentence, proportional mapping onto the word timings
    spans, cum = [], 0
    for c in counts:
        a, b = cum / n_words, (cum + c) / n_words
        cum += c
        if words:
            ia = min(len(words) - 1, int(round(a * len(words))))
            ib = min(len(words) - 1, max(ia, int(round(b * len(words))) - 1))
            t0, t1 = words[ia][1], words[ib][2]
        else:
            t0, t1 = a * length, b * length
        spans.append([t0, t1])
    # stitch: each scene runs from its start to the next scene's start
    for i in range(len(spans) - 1):
        spans[i][1] = spans[i + 1][0]
    spans[0][0] = 0.0
    spans[-1][1] = length + 0.4
    scenes = [{"text": s, "t0": a, "t1": b} for s, (a, b) in zip(sents, spans)]
    # merge too-short scenes into the next, split too-long ones in half
    merged = []
    for sc in scenes:
        if merged and (merged[-1]["t1"] - merged[-1]["t0"]) < MIN_SCENE:
            merged[-1]["text"] += " " + sc["text"]
            merged[-1]["t1"] = sc["t1"]
        else:
            merged.append(dict(sc))
    if len(merged) > 1 and (merged[-1]["t1"] - merged[-1]["t0"]) < MIN_SCENE:
        last = merged.pop()
        merged[-1]["text"] += " " + last["text"]
        merged[-1]["t1"] = last["t1"]
    out = []
    for sc in merged:
        d = sc["t1"] - sc["t0"]
        if d > MAX_SCENE:
            k = int(d // MAX_SCENE) + 1
            step = d / k
            words_ = sc["text"].split()
            per = max(1, len(words_) // k)
            for j in range(k):
                chunk = " ".join(words_[j * per:(j + 1) * per if j < k - 1 else None])
                out.append({"text": chunk or sc["text"],
                            "t0": sc["t0"] + j * step, "t1": sc["t0"] + (j + 1) * step})
        else:
            out.append(sc)
    return out


def write_prompts(scenes, title):
    """Ask Gemini for one vivid, literal image prompt per scene."""
    fallback = [f"{s['text']}, {STYLE}" for s in scenes]
    if not GEMINI_KEY:
        return fallback
    listing = "\n".join(f"{i + 1}. {s['text']}" for i, s in enumerate(scenes))
    ask = (
        f"You are the art director of a documentary Short titled \"{title}\".\n"
        "For each numbered narration line below write ONE image-generation prompt "
        "that literally shows what that line says (the subject, place, action), as a "
        "single concrete scene a camera could film. No text, no logos, no real "
        "people's faces by name. Keep the same visual look across all scenes. "
        "Max 40 words each. Return ONLY a JSON array of strings, one per line, "
        f"in order, exactly {len(scenes)} items.\n\n{listing}"
    )
    for model in TEXT_MODELS:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": GEMINI_KEY},
                json={"contents": [{"parts": [{"text": ask}]}],
                      "generationConfig": {"responseMimeType": "application/json"}},
                timeout=90)
            if r.status_code != 200:
                note(f"Prompt writer {model}: {r.status_code} {r.text[:150]}")
                continue
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            arr = json.loads(txt)
            if isinstance(arr, list) and len(arr) == len(scenes):
                note(f"Scene prompts written by {model}")
                return [f"{str(p).strip()}, {STYLE}" for p in arr]
        except Exception as exc:
            note(f"Prompt writer {model} failed: {exc}")
    return fallback


def gemini_image(prompt, dest):
    for model in IMAGE_MODELS:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": GEMINI_KEY},
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}},
                timeout=120)
            if r.status_code != 200:
                note(f"  {model}: {r.status_code} {re.sub(r'\s+', ' ', r.text)[60:300]}")
                continue
            for p in r.json()["candidates"][0]["content"]["parts"]:
                inl = p.get("inlineData") or p.get("inline_data")
                if inl:
                    Path(dest).write_bytes(base64.b64decode(inl["data"]))
                    return model
        except Exception as exc:
            note(f"  {model} failed: {exc}")
    return None


def pollinations_image(prompt, dest):
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:900]) +
           f"?width=1080&height=1920&nologo=true&model=flux&seed={random.randint(1, 10**6)}")
    try:
        r = requests.get(url, timeout=150)
        if r.status_code == 200 and len(r.content) > 5000 and r.headers.get(
                "content-type", "").startswith("image"):
            Path(dest).write_bytes(r.content)
            return "pollinations"
        note(f"  pollinations: {r.status_code} {len(r.content)}B")
    except Exception as exc:
        note(f"  pollinations failed: {exc}")
    return None


def make_image(prompt, dest):
    for attempt in range(2):
        used = (GEMINI_KEY and gemini_image(prompt, dest)) or pollinations_image(prompt, dest)
        if used:
            return used
    return None


def animate(img, dur, dest, idx, w, h, fps):
    """Slow zoom / pan over the picture (Ken Burns), exactly `dur` seconds."""
    frames = max(2, int(round(dur * fps)))
    style = idx % 4
    z = "min(1.0+0.18*on/{f},1.18)".format(f=frames)
    zout = "max(1.18-0.18*on/{f},1.0)".format(f=frames)
    if style == 0:   # push in, centre
        zz, x, y = z, "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif style == 1:  # pull out
        zz, x, y = zout, "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif style == 2:  # push in drifting right
        zz, x, y = z, f"(iw-iw/zoom)*on/{frames}", "ih/2-(ih/zoom/2)"
    else:             # push in drifting up
        zz, x, y = z, "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*(1-on/{frames})"
    vf = (f"scale=2*{w}:2*{h}:force_original_aspect_ratio=increase,crop=2*{w}:2*{h},"
          f"zoompan=z='{zz}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps},"
          "setsar=1,format=yuv420p")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(img), "-vf", vf,
                    "-frames:v", str(frames), "-an", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "23", "-pix_fmt", "yuv420p", str(dest)], check=True)


def build_ai_segments(script, title, words, length, work, w, h, fps):
    scenes = plan_scenes(script, words, length)
    note(f"AI scenes planned: {len(scenes)}")
    prompts = write_prompts(scenes, title)
    segs, ok = [], 0
    last_img = None
    for i, (sc, pr) in enumerate(zip(scenes, prompts)):
        img = Path(work) / f"ai_{i}.img"
        src = make_image(pr, img)
        if src:
            ok += 1
            last_img = img
            note(f"Scene {i + 1}/{len(scenes)} image via {src}")
        elif last_img:
            img = last_img  # reuse previous picture rather than break the timeline
            note(f"Scene {i + 1}: image failed, reusing previous")
        else:
            note(f"Scene {i + 1}: image failed")
            return None
        seg = Path(work) / f"aiseg_{i}.mp4"
        try:
            animate(img, sc["t1"] - sc["t0"], seg, i, w, h, fps)
        except subprocess.CalledProcessError as exc:
            note(f"Animate failed scene {i + 1}: {exc}")
            return None
        segs.append(seg)
    if ok < max(2, int(len(scenes) * 0.6)):
        note(f"Only {ok}/{len(scenes)} images generated, falling back to stock footage")
        return None
    return segs
