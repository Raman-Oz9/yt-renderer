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
import time
import urllib.parse
from pathlib import Path

import requests

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()
CF_ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
CF_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
HF_MODELS = ["black-forest-labs/FLUX.1-schnell", "black-forest-labs/FLUX.1-dev"]
TEXT_MODELS = ["gemini-3.5-flash-lite", "gemini-2.5-flash"]
IMAGE_MODELS = ["gemini-2.5-flash-image", "gemini-2.0-flash-preview-image-generation"]
STYLE = ("cinematic documentary still, main subject large and centered in the middle of the frame "
         "with empty space left and right, dramatic lighting, rich detail, "
         "photorealistic, vertical 9:16 composition, no text, no letters, no words, "
         "no signs, no logos, no captions, no watermark")
MIN_SCENE, MAX_SCENE = 2.2, 4.6   # fast cuts keep still images feeling alive
OVERLAP = 0.7                      # slow cross-fade between scenes


_seen = set()


def note(msg):
    key = str(msg)[:28]
    if key in _seen and "image via" not in str(msg):
        return  # one annotation per distinct message type (GitHub caps them at 10)
    _seen.add(key)
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


def parse_json_list(txt):
    """Tolerant JSON-array parser (handles code fences / surrounding prose)."""
    txt = txt.strip()
    try:
        return json.loads(txt)
    except Exception:
        pass
    m = re.search(r"\[.*\]", txt, re.S)
    if not m:
        raise ValueError("no JSON array in reply")
    return json.loads(m.group(0))


def write_prompts(scenes, title):
    """Ask Gemini for one vivid, literal image prompt per scene."""
    fallback = [f"{s['text']}, {STYLE}" for s in scenes]
    if not GEMINI_KEY:
        return fallback
    listing = "\n".join(f"{i + 1}. {s['text']}" for i, s in enumerate(scenes))
    ask = (
        f"You are the art director of a documentary Short titled \"{title}\".\n"
        f"The full script, for context: {' '.join(sc['text'] for sc in scenes)[:1800]}\n"
        "For each numbered narration line below write ONE image-generation prompt "
        "that literally shows what that line says (the subject, place, action), as a "
        "single concrete scene a camera could film. No text, no logos, no real "
        "people's faces by name. Keep the same visual look across all scenes. "
        "RELEVANCE RULE (most important): each image must literally and unmistakably show what "
        "its narration line says - name the exact subject (e.g. 'a bdelloid rotifer, a microscopic "
        "animal'), place or event, so a viewer could guess the line from the picture alone. If the "
        "line is abstract (a question, a reflection), show the most concrete visual of the video's own "
        "subject that fits it. If a line mentions a person or role (a scientist, a king, a diver), SHOW "
        "that person: EXACTLY ONE person (never a group, even if the line says several - show one), "
        "medium or wide shot, face in profile or turned partly away, and HANDS NOT VISIBLE: write "
        "phrases like 'waist-up portrait, arms down out of frame, hands hidden behind a desk' in the "
        "prompt so no fingers appear - image generators draw fingers wrongly. Never show someone "
        "operating equipment or holding objects. "
        "Keep each scene to ONE clear subject and a simple composition. "
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
            arr = parse_json_list(txt)
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


def hf_image(prompt, dest):
    """Hugging Face Inference Providers (auto-picks an available provider)."""
    try:
        from huggingface_hub import InferenceClient
        client = InferenceClient(provider="auto", api_key=HF_TOKEN)
    except Exception as exc:
        note(f"  hf client unavailable: {exc}")
        return None
    for model in HF_MODELS:
        try:
            img = client.text_to_image(prompt, model=model)
            img.save(str(dest), format="PNG")
            return "huggingface " + model.split("/")[-1]
        except Exception as exc:
            note(f"  hf {model}: {re.sub(r'[\\s]+', ' ', str(exc))[:220]}")
    return None


def cf_image(prompt, dest):
    """Cloudflare Workers AI (free daily allowance)."""
    base = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/ai/run/"
    hdr = {"Authorization": f"Bearer {CF_TOKEN}"}
    tries = [("@cf/black-forest-labs/flux-1-schnell", {"prompt": prompt[:2000], "steps": 6}),
             ("@cf/stabilityai/stable-diffusion-xl-base-1.0",
              {"prompt": prompt[:1000], "width": 768, "height": 1344, "num_steps": 20})]
    for model, body in tries:
        try:
            r = requests.post(base + model, headers=hdr, json=body, timeout=150)
            if r.status_code == 200:
                if r.headers.get("content-type", "").startswith("image"):
                    Path(dest).write_bytes(r.content)
                    return "cloudflare " + model.split("/")[-1]
                data = r.json().get("result", {})
                if data.get("image"):
                    Path(dest).write_bytes(base64.b64decode(data["image"]))
                    return "cloudflare " + model.split("/")[-1]
            if r.status_code == 429:
                _dead.add("cf")
                note("  cf: daily free allocation used up, skipping Cloudflare for this run")
                return None
            note(f"  cf {model}: {r.status_code} {re.sub(r'[\\s]+', ' ', r.text)[:200]}")
        except Exception as exc:
            note(f"  cf {model} failed: {exc}")
    return None


_horde_timeouts = []
_BUDGET_END = [float("inf")]   # wall-clock cutoff for picture generation
_dead = set()   # providers that hit a hard limit this run - skip them for the rest


def ovh_image(prompt, dest):
    """OVHcloud AI Endpoints, Stable Diffusion XL (free; anonymous = 2 req/min)."""
    url = "https://stable-diffusion-xl.endpoints.kepler.ai.cloud.ovh.net/api/text2image"
    hdr = {"Content-Type": "application/json", "accept": "application/octet-stream"}
    tok = os.environ.get("OVH_AI_TOKEN", "").strip()
    if tok:
        hdr["Authorization"] = f"Bearer {tok}"
    body = {"prompt": prompt[:1400] + ", 85mm lens, ultra sharp focus, intricate details",
            "negative_prompt": ("text, letters, watermark, logo, blurry, soft, deformed, distorted, "
                                "disfigured, extra limbs, low quality, oversaturated, cartoon")}
    for attempt in range(2):
        try:
            r = requests.post(url, headers=hdr, json=body, timeout=120)
            if r.status_code == 200 and len(r.content) > 5000:
                Path(dest).write_bytes(r.content)
                return "ovh sdxl"
            if r.status_code == 429:
                if attempt == 0:
                    time.sleep(35)   # anonymous limit is 2 requests per minute
                    continue
                _dead.add("ovh")     # still limited: stop wasting time on it
            note(f"  ovh: {r.status_code} {re.sub(r'[\\s]+', ' ', r.text)[:150]}")
            if r.status_code in (401, 403):
                _dead.add("ovh")
            break
        except Exception as exc:
            note(f"  ovh failed: {exc}")
            break
    return None


def horde_image(prompt, dest):
    """AI Horde (free, crowdsourced, queue based)."""
    base = "https://aihorde.net/api/v2/"
    hdr = {"apikey": os.environ.get("HORDE_API_KEY", "").strip() or "0000000000",
           "Client-Agent": "yt-renderer:1.0:github.com/Raman-Oz9/yt-renderer",
           "Content-Type": "application/json"}
    body = {"prompt": prompt[:900] + " ### text, letters, watermark, blurry, deformed",
            "params": {"width": 576, "height": 1024, "steps": 25, "n": 1},
            "nsfw": False, "censor_nsfw": True, "r2": True}
    try:
        r = requests.post(base + "generate/async", headers=hdr, json=body, timeout=60)
        if r.status_code not in (200, 202):
            note(f"  horde submit: {r.status_code} {re.sub(r'[\\s]+', ' ', r.text)[:150]}")
            return None
        rid = r.json()["id"]
        deadline = time.time() + 150
        while time.time() < deadline:
            time.sleep(4)
            c = requests.get(base + f"generate/check/{rid}", headers=hdr, timeout=30).json()
            if c.get("faulted"):
                note("  horde: job faulted")
                return None
            if c.get("done"):
                st = requests.get(base + f"generate/status/{rid}", headers=hdr, timeout=30).json()
                gens = st.get("generations") or []
                if not gens or gens[0].get("censored"):
                    return None
                img = requests.get(gens[0]["img"], timeout=60)
                if img.status_code == 200 and len(img.content) > 3000:
                    Path(dest).write_bytes(img.content)
                    return "ai horde"
                return None
        try:  # give up and free the queue slot
            requests.delete(base + f"generate/status/{rid}", headers=hdr, timeout=15)
        except Exception:
            pass
        note("  horde: timed out waiting in queue")
        _horde_timeouts.append(1)
        if len(_horde_timeouts) >= 2:
            _dead.add("horde")
    except Exception as exc:
        note(f"  horde failed: {exc}")
    return None


def make_image(prompt, dest):
    """Free providers in order; a provider that hits its daily cap is skipped
    for the rest of the run so we don't waste time on it."""
    if time.time() > _BUDGET_END[0]:
        return None
    for attempt in range(2):
        if CF_ACCOUNT and CF_TOKEN and "cf" not in _dead:
            used = cf_image(prompt, dest)
            if used:
                return used
        if "ovh" not in _dead:
            used = ovh_image(prompt, dest)
            if used:
                return used
        if "horde" not in _dead:
            used = horde_image(prompt, dest)
            if used:
                return used
        used = pollinations_image(prompt, dest)
        if used:
            return used
    return None


def check_image(img, scene_text):
    """Ask Gemini (vision) to spot typical AI-image mistakes. Returns (ok, problem)."""
    if not GEMINI_KEY:
        return True, ""
    try:
        small = Path(str(img) + ".chk.jpg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(img), "-vf", "scale=640:-2",
                        "-q:v", "4", str(small)], check=True)
        data = base64.b64encode(small.read_bytes()).decode()
        ask = ("You are a strict quality inspector for AI-generated images used in a documentary video. "
               f"The image should illustrate: '{scene_text[:200]}'. Look for CLEAR visible mistakes: wrong number "
               "of fingers (COUNT the fingers on every visible hand: anything other than five clean, natural fingers, "
               "or any blobby, fused, gloved-blob or blurry hand, is a mistake), malformed hands or faces, extra or missing limbs, eyes or objects pointing the wrong "
               "way, equipment merged with a body or used impossibly, duplicated or melted objects, garbled "
               "text or letters. "
               "ALSO reject it if it does not clearly and recognisably show the subject of the line. "
               "Minor softness is fine. "
               'Reply ONLY with JSON: {"ok": true or false, "problem": "short reason"}. '
               "Say ok=false only if a mistake is clearly visible.")
        for model in TEXT_MODELS:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": GEMINI_KEY},
                json={"contents": [{"parts": [{"text": ask},
                                              {"inlineData": {"mimeType": "image/jpeg", "data": data}}]}],
                      "generationConfig": {"responseMimeType": "application/json"}},
                timeout=60)
            if r.status_code != 200:
                continue
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            m = re.search(r"\{.*\}", txt, re.S)
            res = json.loads(m.group(0))
            return bool(res.get("ok", True)), str(res.get("problem", ""))[:120]
    except Exception as exc:
        note(f"  quality check skipped: {exc}")
    return True, ""


def _dims(img):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height", "-of", "csv=p=0:s=x", str(img)]).decode().strip()
    iw, ih = out.split("x")[:2]
    return int(iw), int(ih)


def animate(img, dur, dest, idx, w, h, fps):
    """Gentle zoom / drift over the picture, exactly `dur` seconds.

    Square-ish pictures are shown whole (full width) over a blurred copy of
    themselves, so nothing important is cropped; tall pictures fill the frame."""
    frames = max(2, int(round(dur * fps)))
    iw, ih = _dims(img)
    portrait = True   # full-frame look (blurred-backdrop layout was rejected)
    zmax = 0.06       # gentle zoom so the picture is not blown up
    style = idx % 4
    zin = f"min(1.0+{zmax}*on/{frames},{1 + zmax})"
    zout = f"max({1 + zmax}-{zmax}*on/{frames},1.0)"
    if style == 0:
        zz, x, y = zin, "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif style == 1:
        zz, x, y = zout, "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif style == 2:
        zz, x, y = zin, f"(iw-iw/zoom)*on/{frames}", "ih/2-(ih/zoom/2)"
    else:
        zz, x, y = zin, "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*(1-on/{frames})"
    if portrait:
        vf = (f"scale={int(w * 1.5)}:{int(h * 1.5)}:force_original_aspect_ratio=increase:flags=lanczos,"
              f"crop={int(w * 1.5)}:{int(h * 1.5)},"
              f"zoompan=z='{zz}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps},"
              "unsharp=5:5:0.6:5:5:0.0,setsar=1,format=yuv420p")
        fc = None
    else:
        fh = int(round(w * ih / iw / 2)) * 2
        fc = (f"[0:v]split[a][b];"
              f"[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
              f"gblur=sigma=45,eq=brightness=-0.10:saturation=1.1[bg];"
              f"[b]scale=2*{w}:-2,zoompan=z='{zz}':x='{x}':y='{y}':d={frames}:s={w}x{fh}:fps={fps},"
              f"setsar=1[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={fps},format=yuv420p[v]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(img)]
    cmd += (["-vf", vf] if fc is None else ["-filter_complex", fc, "-map", "[v]"])
    cmd += ["-frames:v", str(frames), "-an", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "23", "-pix_fmt", "yuv420p", str(dest)]
    subprocess.run(cmd, check=True)


def join_with_fades(segs, spans, dest):
    """Cross-dissolve scenes together, then add light film grain + vignette."""
    n = len(segs)
    if n == 1:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(segs[0]),
                        "-vf", "noise=alls=7:allf=t,vignette=PI/6,format=yuv420p",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", str(dest)], check=True)
        return
    parts, cum, last = [], 0.0, "[0:v]"
    for k in range(n - 1):
        cum += spans[k]
        out = f"[x{k}]"
        parts.append(f"{last}[{k + 1}:v]xfade=transition=fade:"
                     f"duration={OVERLAP}:offset={cum:.3f}{out}")
        last = out
    parts.append(f"{last}noise=alls=7:allf=t,vignette=PI/6,format=yuv420p[v]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for sg in segs:
        cmd += ["-i", str(sg)]
    cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", str(dest)]
    subprocess.run(cmd, check=True)


def build_ai_segments(script, title, words, length, work, w, h, fps):
    note(f"keys present: cloudflare={bool(CF_ACCOUNT and CF_TOKEN)} hf={bool(HF_TOKEN)} gemini={bool(GEMINI_KEY)}")
    _BUDGET_END[0] = time.time() + 14 * 60
    scenes = plan_scenes(script, words, length)
    note(f"AI scenes planned: {len(scenes)}")
    prompts = write_prompts(scenes, title)
    segs, ok = [], 0
    last_img = None
    redo_left = [max(4, len(scenes))]   # cap on regenerations per video
    for i, (sc, pr) in enumerate(zip(scenes, prompts)):
        img = Path(work) / f"ai_{i}.img"
        src = make_image(pr, img)
        tries = 0
        while src and tries < 2 and redo_left[0] > 0 and time.time() < _BUDGET_END[0]:
            good, why = check_image(img, sc["text"])
            if good:
                break
            tries += 1
            redo_left[0] -= 1
            note(f"Scene {i + 1}: flagged ({why}); regenerating ({tries})")
            img2 = Path(work) / f"ai_{i}_r{tries}.img"
            extra = ", anatomically correct, clean simple composition, exactly matching: " + sc["text"][:120]
            src2 = make_image(pr + extra, img2)
            if not src2:
                break
            img, src = img2, src2
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
        span = sc["t1"] - sc["t0"]
        try:
            animate(img, span + (OVERLAP if i < len(scenes) - 1 else 0), seg, i, w, h, fps)
        except subprocess.CalledProcessError as exc:
            note(f"Animate failed scene {i + 1}: {exc}")
            return None
        segs.append(seg)
    if ok < max(2, int(len(scenes) * 0.6)):
        note(f"Only {ok}/{len(scenes)} images generated, falling back to stock footage")
        return None
    spans = [sc["t1"] - sc["t0"] for sc in scenes]
    joined = Path(work) / "ai_joined.mp4"
    try:
        join_with_fades(segs, spans, joined)
        return [joined]
    except Exception as exc:
        note(f"Crossfade join failed ({exc}); using hard cuts")
        cut = []
        for k, (sg, sp) in enumerate(zip(segs, spans)):
            out = Path(work) / f"aicut_{k}.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(sg), "-t", f"{sp:.3f}",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", str(out)],
                           check=True)
            cut.append(out)
        return cut
