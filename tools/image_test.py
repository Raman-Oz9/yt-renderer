"""Compare free image sources on the same prompts. Saves results to image-test/."""
import base64, json, os, re, sys, time, threading
from pathlib import Path
import requests

OUT = Path("image-test"); OUT.mkdir(exist_ok=True)
STYLE = ("cinematic documentary still, main subject large and centered, dramatic lighting, "
         "highly detailed, sharp focus, photorealistic, no text, no letters, no watermark")
PROMPTS = {
    "scientist": "a scientist in a white coat looking into a microscope in a modern lab, " + STYLE,
    "ruins": "ancient stone ruins with tall columns under a stormy sky at dusk, " + STYLE,
    "ice": "a tiny translucent creature frozen inside a clear block of ice, macro shot, " + STYLE,
}
log = []
def say(m):
    print(m, flush=True); log.append(m)

HORDE = "https://aihorde.net/api/v2/"
HDR = {"apikey": os.environ.get("HORDE_API_KEY") or "0000000000",
       "Client-Agent": "yt-renderer:1.0:github.com/Raman-Oz9/yt-renderer", "Content-Type": "application/json"}

def pick_models():
    try:
        r = requests.get(HORDE + "status/models?type=image&min_count=1", timeout=60).json()
    except Exception as e:
        say(f"models query failed: {e}"); return []
    say(f"{len(r)} image models online")
    rows = sorted(r, key=lambda m: -m.get("count", 0))
    say("top by workers: " + ", ".join(f"{m['name']}({m.get('count')}w,q{m.get('queued',0):.0f})" for m in rows[:25]))
    want = []
    for key in ["flux", "juggernaut", "albedobase", "sdxl", "realvis", "dreamshaper xl", "stable diffusion xl"]:
        for m in rows:
            if key in m["name"].lower() and m["name"] not in want and m.get("count", 0) >= 2:
                want.append(m["name"]); break
    return want[:4]

def horde_one(model, pname, prompt):
    tag = re.sub(r"[^a-z0-9]+", "_", model.lower())
    body = {"prompt": prompt + " ### text, letters, watermark, blurry, deformed, low quality",
            "params": {"width": 576, "height": 1024, "steps": 25, "n": 1, "sampler_name": "k_euler_a"},
            "models": [model], "nsfw": False, "r2": True}
    try:
        r = requests.post(HORDE + "generate/async", headers=HDR, json=body, timeout=60)
        if r.status_code not in (200, 202):
            say(f"[{model}/{pname}] submit {r.status_code} {r.text[:120]}"); return
        rid = r.json()["id"]; t0 = time.time()
        while time.time() - t0 < 270:
            time.sleep(5)
            c = requests.get(HORDE + f"generate/check/{rid}", headers=HDR, timeout=30).json()
            if c.get("faulted"): say(f"[{model}/{pname}] faulted"); return
            if c.get("done"):
                g = requests.get(HORDE + f"generate/status/{rid}", headers=HDR, timeout=30).json()["generations"][0]
                img = requests.get(g["img"], timeout=60).content
                (OUT / f"horde_{tag}_{pname}.webp").write_bytes(img)
                say(f"[{model}/{pname}] ok {time.time()-t0:.0f}s {len(img)//1024}KB"); return
        requests.delete(HORDE + f"generate/status/{rid}", headers=HDR, timeout=15)
        say(f"[{model}/{pname}] timeout")
    except Exception as e:
        say(f"[{model}/{pname}] error {e}")

def ovh(pname, prompt, tag, extra):
    try:
        r = requests.post("https://stable-diffusion-xl.endpoints.kepler.ai.cloud.ovh.net/api/text2image",
                          headers={"Content-Type": "application/json", "accept": "application/octet-stream"},
                          json={"prompt": prompt, "negative_prompt": extra}, timeout=120)
        if r.status_code == 200:
            (OUT / f"ovh_{tag}_{pname}.png").write_bytes(r.content); say(f"[ovh {tag}/{pname}] ok")
        else:
            say(f"[ovh {tag}/{pname}] {r.status_code} {r.text[:100]}")
    except Exception as e:
        say(f"[ovh {tag}/{pname}] error {e}")

def cf(pname, prompt):
    a, t = os.environ.get("CLOUDFLARE_ACCOUNT_ID"), os.environ.get("CLOUDFLARE_API_TOKEN")
    if not (a and t): return
    r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{a}/ai/run/@cf/black-forest-labs/flux-1-schnell",
                      headers={"Authorization": f"Bearer {t}"}, json={"prompt": prompt, "steps": 8}, timeout=120)
    if r.status_code == 200 and r.json().get("result", {}).get("image"):
        (OUT / f"cloudflare_flux_{pname}.png").write_bytes(base64.b64decode(r.json()["result"]["image"])); say(f"[cf/{pname}] ok")
    else:
        say(f"[cf/{pname}] {r.status_code} {r.text[:80]}")

models = pick_models()
say(f"testing models: {models}")
threads = []
for m in models:
    for pn, pr in PROMPTS.items():
        th = threading.Thread(target=horde_one, args=(m, pn, pr)); th.start(); threads.append(th)
# OVH: baseline vs refined prompt, spaced for the 2/min limit
for pn, pr in list(PROMPTS.items())[:2]:
    ovh(pn, pr, "base", "text, watermark, blurry")
    time.sleep(31)
    ovh(pn, pr + ", 85mm lens, f/2.8, ultra sharp, intricate details, 8k", "refined",
        "text, letters, watermark, logo, blurry, soft, deformed, distorted, disfigured, extra limbs, low quality, oversaturated, cartoon")
    time.sleep(31)
for pn, pr in PROMPTS.items(): cf(pn, pr)
for th in threads: th.join()
(OUT / "log.txt").write_text("\n".join(log))
