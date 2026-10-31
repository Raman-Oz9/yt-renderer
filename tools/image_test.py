"""Round 2: native portrait SDXL on OVHcloud + sequential AI Horde tests."""
import base64, os, re, time
from pathlib import Path
import requests

OUT = Path("image-test"); OUT.mkdir(exist_ok=True)
STYLE = ("cinematic documentary still, main subject large and centered, dramatic lighting, "
         "highly detailed, sharp focus, photorealistic, 85mm lens, intricate details")
NEG = ("text, letters, watermark, logo, blurry, soft, deformed, distorted, disfigured, extra limbs, "
       "low quality, oversaturated, cartoon")
PROMPTS = {
    "scientist": "a scientist in a white coat looking into a microscope in a modern lab, " + STYLE,
    "ruins": "ancient stone ruins with tall columns under a stormy sky at dusk, " + STYLE,
    "ice": "a tiny translucent creature frozen inside a clear block of ice, macro shot, " + STYLE,
}
log = []
def say(m): print(m, flush=True); log.append(m)

def ovh_oai(pname, prompt, size):
    try:
        r = requests.post("https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/images/generations",
                          headers={"Content-Type": "application/json"},
                          json={"model": "stabilityai/stable-diffusion-xl-base-1.0",
                                "prompt": prompt, "size": size}, timeout=150)
        if r.status_code == 200:
            b = r.json()["data"][0]["b64_json"]
            (OUT / f"ovh_{size}_{pname}.png").write_bytes(base64.b64decode(b)); say(f"[ovh {size}/{pname}] ok")
        else:
            say(f"[ovh {size}/{pname}] {r.status_code} {r.text[:160]}")
    except Exception as e:
        say(f"[ovh {size}/{pname}] error {e}")

for size in ["768x1344", "832x1216"]:
    for pn in ["scientist", "ruins"]:
        ovh_oai(pn, PROMPTS[pn], size); time.sleep(31)

HORDE = "https://aihorde.net/api/v2/"
HDR = {"apikey": "0000000000", "Client-Agent": "yt-renderer:1.0:github.com/Raman-Oz9/yt-renderer",
       "Content-Type": "application/json"}
def horde(model, pname, prompt, w, h, steps):
    tag = re.sub(r"[^a-z0-9]+", "_", model.lower())
    body = {"prompt": prompt + " ### " + NEG, "params": {"width": w, "height": h, "steps": steps, "n": 1},
            "models": [model], "nsfw": False, "r2": True}
    try:
        r = requests.post(HORDE + "generate/async", headers=HDR, json=body, timeout=60)
        if r.status_code not in (200, 202):
            say(f"[{model} {w}x{h}/{pname}] submit {r.status_code} {r.text[:260]}"); return
        rid = r.json()["id"]; t0 = time.time()
        while time.time() - t0 < 200:
            time.sleep(5)
            c = requests.get(HORDE + f"generate/check/{rid}", headers=HDR, timeout=30).json()
            if c.get("faulted"): say(f"[{model}/{pname}] faulted"); return
            if c.get("done"):
                g = requests.get(HORDE + f"generate/status/{rid}", headers=HDR, timeout=30).json()["generations"][0]
                (OUT / f"horde_{tag}_{pname}.webp").write_bytes(requests.get(g["img"], timeout=60).content)
                say(f"[{model}/{pname}] ok {time.time()-t0:.0f}s"); return
        requests.delete(HORDE + f"generate/status/{rid}", headers=HDR, timeout=15)
        say(f"[{model}/{pname}] timeout")
    except Exception as e:
        say(f"[{model}/{pname}] error {e}")

for model, w, h, steps in [("Flux.1-Schnell fp8 (Compact)", 512, 768, 6), ("Juggernaut XL", 512, 768, 20)]:
    horde(model, "scientist", PROMPTS["scientist"], w, h, steps); time.sleep(3)
(OUT / "log.txt").write_text("\n".join(log))
