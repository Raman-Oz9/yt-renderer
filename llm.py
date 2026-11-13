"""Small multi-provider LLM router for structured (JSON) planning calls. Used only by stickman.py.

Ideas borrowed from free-claude-code: ordered provider fallback, per-provider retries with Retry-After backoff,
circuit-breaker for dead providers, free-tier providers only used when their key exists, everything env-overridable.
No key for a provider => it is silently skipped. Nothing here ever spends money by itself (free-tier models only).
"""
import json
import os
import time

import requests

import ai_scenes as A

# name -> (kind, url, env key, default model env, default model)
PROVIDERS = {
    "gemini": ("gemini", "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", "GEMINI_API_KEY",
               "LLM_GEMINI_MODELS", "gemini-3.5-flash-lite,gemini-2.5-flash,gemini-2.5-flash-lite"),
    "groq": ("openai", "https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY",
             "LLM_GROQ_MODELS", "llama-3.3-70b-versatile,openai/gpt-oss-120b"),
    "openrouter": ("openai", "https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY",
                   "LLM_OPENROUTER_MODELS", "meta-llama/llama-3.3-70b-instruct:free,deepseek/deepseek-chat-v3.1:free"),
    "nvidia": ("openai", "https://integrate.api.nvidia.com/v1/chat/completions", "NVIDIA_API_KEY",
               "LLM_NVIDIA_MODELS", "meta/llama-3.3-70b-instruct"),
}
ORDER = [p.strip() for p in os.environ.get("LLM_ORDER", "gemini,groq,openrouter,nvidia").split(",") if p.strip()]
_dead = set()        # (provider, model) that returned a permanent error this run
_cool = {}           # provider -> unix time before which we do not call it (rate limited)


def available():
    return [p for p in ORDER if p in PROVIDERS and os.environ.get(PROVIDERS[p][2], "").strip()]


def _call(provider, model, prompt, timeout=120):
    kind, url, env, _, _ = PROVIDERS[provider]
    key = os.environ[env].strip()
    if kind == "gemini":
        r = requests.post(url.format(model=model), headers={"x-goog-api-key": key},
                          json={"contents": [{"parts": [{"text": prompt}]}],
                                "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 16384}},
                          timeout=timeout)
        if r.status_code != 200:
            return r.status_code, None, r.headers.get("retry-after")
        return 200, r.json()["candidates"][0]["content"]["parts"][0]["text"], None
    r = requests.post(url, headers={"Authorization": f"Bearer {key}"},
                      json={"model": model, "temperature": 0.4, "max_tokens": 8192,
                            "messages": [{"role": "system", "content": "You are a precise storyboard planner. Reply with JSON only."},
                                         {"role": "user", "content": prompt}]},
                      timeout=timeout)
    if r.status_code != 200:
        return r.status_code, None, r.headers.get("retry-after")
    return 200, r.json()["choices"][0]["message"]["content"], None


def ask_list(prompt, n, tries=2):
    """Return a JSON list of exactly n items from the first provider that manages it, else None."""
    for prov in available():
        models = [m.strip() for m in os.environ.get(PROVIDERS[prov][3], PROVIDERS[prov][4]).split(",") if m.strip()]
        for model in models:
            if (prov, model) in _dead:
                continue
            for attempt in range(tries):
                wait = _cool.get(prov, 0) - time.time()
                if wait > 0:
                    time.sleep(min(wait, 30))
                try:
                    code, text, retry = _call(prov, model, prompt)
                except Exception as exc:
                    A.note(f"LLM {prov}/{model} error: {exc}")
                    time.sleep(2 * (attempt + 1))
                    continue
                if code in (401, 403, 404):
                    A.note(f"LLM {prov}/{model}: {code} (skipping for this run)")
                    _dead.add((prov, model))
                    break
                if code in (429, 500, 502, 503, 504):
                    try:
                        w = float(retry) if retry else 4 * (attempt + 1)
                    except ValueError:
                        w = 6.0
                    A.note(f"LLM {prov}/{model}: {code}, retry in {min(w, 20):.0f}s")
                    _cool[prov] = time.time() + min(w, 20)
                    continue
                if code != 200 or not text:
                    continue
                try:
                    arr = A.parse_json_list(text)
                except Exception:
                    arr = None
                if isinstance(arr, list) and len(arr) >= n:
                    A.note(f"LLM planner: {prov}/{model} ok")
                    return arr[:n]
                A.note(f"LLM {prov}/{model}: bad shape ({len(arr) if isinstance(arr, list) else 'n/a'} of {n})")
    return None
