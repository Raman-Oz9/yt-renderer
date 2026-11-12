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
STYLE = ("epic cinematic film still shot on IMAX, ultra detailed and razor sharp, vivid rich saturated colours, "
         "deep contrast with glowing highlights, volumetric light rays, dramatic scale and depth, "
         "main subject large and centered, photorealistic, vertical 9:16 composition, no text, no letters, no words, "
         "no signs, no logos, no captions, no watermark")
STICKMAN = os.environ.get("VISUAL_STYLE", "").strip().lower() == "stickman"
if STICKMAN:
    STYLE = ("hand-drawn minimalist explainer illustration on warm near-white paper with a very faint square grid, "
             "fine slightly irregular black pen outlines, a slender stick figure with a round head, long thin single-line "
             "limbs and small oval hands, colourful hand-drawn props with marker accents in warm yellow, red, green and "
             "navy blue, clean uncluttered composition with one clear subject, expressive, vertical 9:16, "
             "no text, no letters, no words, no numbers, no logos, no captions, no watermark")
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
    global MIN_SCENE, MAX_SCENE
    if length > 80:  # long video: fewer, slightly longer scenes to stay inside the daily image allowance
        MIN_SCENE, MAX_SCENE = 3.0, 5.5
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
    stick_ask = None
    if STICKMAN:
        stick_ask = (
            f"You are the art director of a hand-drawn stick-figure explainer Short titled \"{title}\".\n"
            f"The full script, for context: {' '.join(sc['text'] for sc in scenes)[:1800]}\n"
            "For each numbered narration line write ONE image-generation prompt for a hand-drawn illustration on paper "
            "that literally shows what the line says. A slender stick figure (round head, thin single-line limbs) acts "
            "out the line with its WHOLE BODY - strong readable emotion, leaning, reaching, pointing, recoiling - while "
            "interacting with the hand-drawn colourful objects, places or diagrams the line names (name the exact subject: "
            "a black hole as a black circle with an orange swirling disk, a cave diver with tank and fins, a volcano with "
            "lava, and so on). Use only the ONE stick figure per picture, with a different pose, expression and camera "
            "framing in every scene (wide view, close-up, from above, scale comparison); alternate scenes with the figure "
            "and scenes that show only the subject drawn large. Never write any words, letters, numbers or labels inside the "
            "picture. Stay inside the video's own subject and never switch to an unrelated place or object. Keep each scene "
            "to ONE clear focal subject and a simple composition. Max 40 words each. Return ONLY a JSON array of strings, "
            f"one per line, in order, exactly {len(scenes)} items.\n\n{listing}"
        )
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
        "subject that fits it. LITERAL AND SPECTACULAR: show the actual named thing, big and unmistakable - never a vague scatter of stars or dust and never an abstract metaphor (no trains, tunnels, roads, machines or objects standing in for an idea; if a line is a metaphor, show the real thing it is about). For space lines pick a different striking object each time: the Sun with violent solar flares, Jupiter with its storms, Saturn and its rings, Earth from orbit, the Moon, a black hole with a glowing orange accretion disk bending the light around it, a vivid spiral galaxy, a colourful glowing nebula, an exploding supernova, a neutron star, a comet, a lone spacecraft. Make colours vivid and the lighting dramatic. SUBJECT LOCK: every scene must stay inside the video's own subject and its world (a space video shows only space, planets, stars, galaxies, spacecraft or telescopes; an ocean video only the sea; and so on). NEVER show an unrelated place or object such as a warehouse, garage, truck, office, desk, laptop or generic room, and never a person staring at the camera. VARIETY AND DRAMA: make every scene look clearly different from the others and visually spectacular - alternate between a vast wide establishing view, an extreme close-up of one striking detail, a scale comparison, a dramatic angle from above or below, and an eye-catching colour contrast (deep blacks with glowing highlights). Never repeat the same composition twice in a row. PEOPLE RULE: ONLY when the narration line itself is clearly about a person or a human role (never just because a face might look engaging, and NEVER in videos about space, the ocean, nature, animals or physics unless the line names a person or role), SHOW A REAL-LOOKING PERSON, but in the way image generators draw best: EXACTLY ONE person (never a crowd or a group), a medium shot from the waist up or a wide shot, standing or sitting in a simple relaxed pose, face turned three-quarters or in profile with a calm natural expression, and HANDS OUT OF FRAME (hands in pockets, behind the back, or below the bottom edge of the picture). Dress them in plain simple clothing and give them no worn or held items at all (no stethoscope, headset, tools, phones, weapons, bags, glasses, jewellery). Write the prompt like a real photograph: 'candid documentary photograph of a [age] [role], natural skin texture, correct human anatomy and proportions, natural symmetrical face, shot on an 85mm lens'. Never depict a named real person (a politician, a leader, a celebrity): show a podium, a flag, a building or an empty table instead. Use a person in at most one scene in four, and in none when the video is not about people; otherwise show places, objects, maps, machines, ships, buildings or nature. Keep each scene to ONE clear subject and a simple composition. "
        "Max 40 words each. Return ONLY a JSON array of strings, one per line, "
        f"in order, exactly {len(scenes)} items.\n\n{listing}"
    )
    if stick_ask:
        ask = stick_ask
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
_ovh_last = [0.0]
_dead = set()   # providers that hit a hard limit this run - skip them for the rest
if os.environ.get("SKIP_CLOUDFLARE") == "1":   # test renders keep Cloudflare's daily allowance for real uploads
    _dead.add("cf")


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
    fails = 0
    for attempt in range(8):                      # patient: wait out the 2-per-minute limit
        if time.time() > _BUDGET_END[0]:
            return None
        gap = 32 - (time.time() - _ovh_last[0])   # stay under the anonymous rate limit
        if gap > 0:
            time.sleep(gap)
        try:
            _ovh_last[0] = time.time()
            r = requests.post(url, headers=hdr, json=body, timeout=150)
            _ovh_last[0] = time.time()
            if r.status_code == 200 and len(r.content) > 5000:
                Path(dest).write_bytes(r.content)
                return "ovh sdxl"
            if r.status_code in (401, 403):
                note(f"  ovh: {r.status_code} blocked")
                _dead.add("ovh")
                return None
            fails += 1
            note(f"  ovh: {r.status_code} retrying ({fails})")
            time.sleep(15 if r.status_code != 429 else 20)
        except Exception as exc:
            fails += 1
            note(f"  ovh failed: {exc}; retrying ({fails})")
            time.sleep(10)
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



_PERSON_RE = re.compile(r"\b(person|people|man|men|woman|women|soldier|soldiers|doctor|nurse|scientist|"
                        r"officer|pilot|crowd|figure|silhouette|worker|workers|child|boy|girl|portrait|face|"
                        r"sailor|diplomat|president|leader|team|staff|surgeon|patient|king|queen|baker|farmer)\b", re.I)
_NO_PEOPLE_RE = re.compile(r"\b(no|without)\s+(people|humans|faces|hands|persons|person|human)\b", re.I)


def has_person(prompt):
    if STICKMAN:
        return False
    return bool(_PERSON_RE.search(_NO_PEOPLE_RE.sub("", prompt)))


def no_people_prompt(scene_text):
    return (f"{scene_text[:160]}, shown with no people at all: only the place, objects, machines or "
            f"landscape, no humans, no faces, no hands, {STYLE}")


_PERSON_LADDER = [
    "one person seen from behind or over the shoulder, face not visible, hands out of frame, plain clothing",
    "wide cinematic shot with one small distant person far from the camera, no facial detail, hands not visible",
    "one person as a dark backlit silhouette against the scene, no facial detail, no hands visible",
]


def person_variant(scene_text, k):
    """Progressively safer ways to keep a human in the scene when the first picture was flawed."""
    how = _PERSON_LADDER[min(k, len(_PERSON_LADDER)) - 1]
    return (f"{scene_text[:150]}, candid documentary photograph, {how}, natural proportions, "
            f"correct anatomy, {STYLE}")


def gen_image(prompt, scene_text, dest):
    """People are only drawn by the best generator (Cloudflare); everywhere else a no-people version is used."""
    if has_person(prompt) and ("cf" in _dead or not (CF_ACCOUNT and CF_TOKEN)):
        # Cloudflare unavailable (tests, or its daily cap is spent): start from the safer human framing on OVH
        prompt = person_variant(scene_text, 1)
    src = make_image(prompt, dest)
    if not src and has_person(prompt):
        note("  people scene: best generator unavailable, using a no-people version")
        src = make_image(no_people_prompt(scene_text), dest)
    return src


def make_image(prompt, dest):
    """Free providers in order; a provider that hits its daily cap is skipped
    for the rest of the run so we don't waste time on it."""
    if time.time() > _BUDGET_END[0]:
        return None
    person = has_person(prompt)
    for attempt in range(2):
        if CF_ACCOUNT and CF_TOKEN and "cf" not in _dead:
            used = cf_image(prompt, dest)
            if used:
                return used
        if person:
            # people only come from the two better generators: Cloudflare, then OVH (never Horde/Pollinations)
            if "ovh" not in _dead:
                used = ovh_image(prompt, dest)
                if used:
                    return used
            continue
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
    if not GEMINI_KEY or STICKMAN:
        return True, ""
    try:
        small = Path(str(img) + ".chk.jpg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(img), "-vf", "scale=640:-2",
                        "-q:v", "4", str(small)], check=True)
        data = base64.b64encode(small.read_bytes()).decode()
        ask = ("You are a strict quality inspector for AI-generated images used in a documentary video. "
               f"The image should illustrate: '{scene_text[:200]}'. Look for CLEAR visible mistakes: wrong number "
               "of fingers (COUNT the fingers on every visible hand: anything other than five clean, natural fingers, "
               "or any blobby, fused, gloved-blob or blurry hand, is a mistake), more than one person in the picture, waxy or plastic-looking skin, blurry or distorted faces, malformed hands or faces, extra or missing limbs, eyes or objects pointing the wrong "
               "way, equipment merged with a body or used impossibly, duplicated or melted objects, garbled "
               "text or letters. "
               "If any person is visible, check them like a portrait retoucher: face symmetrical and natural, "
               "eyes and mouth correctly placed, normal body proportions, neck and limbs joined correctly, "
               "clothing and anything worn (a stethoscope, headset, bag) sitting correctly on the body - anything "
               "odd, uncanny, melted or misplaced on a person is a mistake. "
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
    zmax = 0.11       # a clearly visible push-in / drift so stills feel alive
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
    _BUDGET_END[0] = time.time() + 34 * 60
    scenes = plan_scenes(script, words, length)
    note(f"AI scenes planned: {len(scenes)}")
    prompts = write_prompts(scenes, title)
    # a person is drawn only when that scene's own narration is about a person or role; otherwise force a no-people picture
    prompts = [no_people_prompt(f"{title}. {sc['text']}") if (has_person(pr) and not has_person(sc['text'])) else pr
               for sc, pr in zip(scenes, prompts)]
    segs, ok = [], 0
    last_img = None
    redo_left = [max(8, int(len(scenes) * 1.3))]   # cap on regenerations per video
    for i, (sc, pr) in enumerate(zip(scenes, prompts)):
        img = Path(work) / f"ai_{i}.img"
        src = gen_image(pr, sc["text"], img)
        tries = 0
        flagged = False
        while src and tries < (3 if has_person(pr) else 2) and redo_left[0] > 0 and time.time() < _BUDGET_END[0]:
            good, why = check_image(img, sc["text"])
            if good:
                break
            flagged = True
            tries += 1
            redo_left[0] -= 1
            note(f"Scene {i + 1}: flagged ({why}); regenerating ({tries})")
            img2 = Path(work) / f"ai_{i}_r{tries}.img"
            if has_person(pr):
                # keep the human, but show them in a way generators draw reliably
                retry_pr = person_variant(sc["text"], tries)
            else:
                retry_pr = pr + ", anatomically correct, clean simple composition, exactly matching: " + sc["text"][:120]
            src2 = gen_image(retry_pr, sc["text"], img2)
            if not src2:
                break
            img, src = img2, src2
        if src and flagged and time.time() < _BUDGET_END[0]:
            good, why = check_image(img, sc["text"])
            if not good:      # still wrong after retries: use a version with no people at all
                note(f"Scene {i + 1}: still flagged ({why}); using a no-people version")
                img3 = Path(work) / f"ai_{i}_safe.img"
                safe = (f"{sc['text'][:160]}, shown with no people at all: only the place, objects, machines "
                        f"or landscape, no humans, no faces, no hands, {STYLE}")
                src3 = make_image(safe, img3)
                if src3:
                    img, src = img3, src3
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
