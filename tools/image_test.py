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

for size in ["1024x1536"]:
    for pn in ["scientist", "ruins", "ice"]:
        ovh_oai(pn, PROMPTS[pn], size); time.sleep(31)
(OUT / "log.txt").write_text("\n".join(log))
