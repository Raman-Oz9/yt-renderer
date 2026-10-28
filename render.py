#!/usr/bin/env python3
"""Faceless Short renderer.

Natural voice (Gemini TTS, falls back to edge-tts) + word-highlight captions
+ per-beat Pexels stock clips + optional background music + FFmpeg.
Writes output/video.mp4 (1080x1920).

Environment:
  SCRIPT          narration script (required)
  SEARCH_QUERY    one or more stock-video search phrases, "|"-separated,
                   one per scene beat, in the order they should appear
                   (required)
  TITLE           YouTube title - optional, but strongly recommended: a
                   few anchor keywords are pulled from it and baked into
                   every stock-footage search, so a vague beat phrase
                   still lands on-subject instead of on whatever ranks
                   top for its own (possibly meaningless) words.
  PEXELS_API_KEY  required
  GEMINI_API_KEY  optional - used for TTS voice and falls back to edge-tts
  GEMINI_VOICE    optional - defaults to "Charon" (calm male voice)
"""
import asyncio
import base64
import os
import random
import re
import subprocess
import sys
import time
import wave
from pathlib import Path

import requests

SCRIPT = os.environ["SCRIPT"].strip()
QUERIES = [q.strip() for q in os.environ.get("SEARCH_QUERY", "").split("|") if q.strip()] or ["nature"]
TITLE = os.environ.get("TITLE", "").strip()
PEXELS_KEY = os.environ["PEXELS_API_KEY"]
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "").strip()  # optional - second free stock source
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

GEMINI_TTS_MODEL = "gemini-3.1-flash-tts-preview"
GEMINI_VOICE = os.environ.get("GEMINI_VOICE", "Orus")  # deep, firm male narrator voice
EDGE_VOICES = ["en-US-GuyNeural", "en-US-AndrewMultilingualNeural"]  # fallback, male first
PITCH_FACTOR = 0.92      # <1 lowers pitch further on top of the voice itself, duration preserved

MAX_SECONDS = 170       # extended Shorts allow up to 3 min; stay comfortably under that
SEGMENT_SECONDS = 8      # max length taken from each stock clip
MAX_SEGMENTS = 30        # safety cap on number of clips stitched together
W, H, FPS = 1080, 1920, 30
VIDEO_CRF = 22
VIDEO_MAXRATE_KBPS = 6000
AUDIO_KBPS = 128
CAPTION_FONT_SIZE = 54
CAPTION_MARGIN_V = 430   # distance from the bottom edge
MUSIC_DIR = Path(".")    # music tracks live in the repo root alongside this script
MUSIC_VOLUME = 0.20      # back down from 0.30
MUSIC_START_OFFSET = 20  # skip the first 20s of the track (skip past quiet intros)

WORK = Path("work")
OUT = Path("output")
WORK.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

# Cross-video repeat avoidance: a running log of stock-clip URLs used in
# recent renders, committed back to the repo by the workflow after each run.
# Without this, two different videos pull from the exact same Pexels/Pixabay
# catalogs with the same relevance ranking for common beats ("space stars",
# "ocean waves", etc.), so the single top-ranked clip for a popular phrase
# kept winning over and over across unrelated videos.
USED_LOG_PATH = Path("used_clips_log.txt")
MAX_PERSISTED_LINKS = 600  # roughly the last ~25-30 videos' worth of clips


def load_persisted_links():
    if USED_LOG_PATH.exists():
        return [l.strip() for l in USED_LOG_PATH.read_text().splitlines() if l.strip()]
    return []


PERSISTED_LINKS = load_persisted_links()


def save_used_links(new_links):
    """Append this video's clips to the log and trim to the cap."""
    combined = PERSISTED_LINKS + new_links
    trimmed = combined[-MAX_PERSISTED_LINKS:]
    USED_LOG_PATH.write_text("\n".join(trimmed) + "\n")


def run(cmd):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


def audio_duration(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ])
    return float(out)


# ---------------------------------------------------------------- voice ----

def gemini_tts(dest):
    """Natural-sounding voice from Gemini TTS. Saves a 24 kHz mono WAV."""
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_TTS_MODEL}:generateContent")
    prompt = ("Say in a deep, strong, masculine documentary-narrator voice, "
              "confident and authoritative, at a natural pace with clear "
              f"pauses between ideas: {SCRIPT}")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {
                "prebuiltVoiceConfig": {"voiceName": GEMINI_VOICE}}},
        },
    }
    last = None
    for attempt in range(3):
        resp = requests.post(url, headers={"x-goog-api-key": GEMINI_KEY},
                             json=body, timeout=180)
        if resp.status_code == 200:
            parts = resp.json()["candidates"][0]["content"]["parts"]
            data = next(p["inlineData"]["data"] for p in parts if "inlineData" in p)
            with wave.open(str(dest), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(base64.b64decode(data))
            return
        last = f"{resp.status_code} {resp.text[:200]}"
        print(f"Gemini TTS attempt {attempt + 1} failed: {last}", flush=True)
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Gemini TTS failed: {last}")


async def edge_tts_voice(dest):
    """Fallback voice. Returns word timings when the service provides them."""
    import edge_tts
    for voice in EDGE_VOICES:
        try:
            try:
                comm = edge_tts.Communicate(SCRIPT, voice, boundary="WordBoundary")
            except TypeError:  # older edge-tts without the boundary option
                comm = edge_tts.Communicate(SCRIPT, voice)
            words = []
            with open(dest, "wb") as fh:
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        fh.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        start = chunk["offset"] / 1e7
                        words.append((chunk["text"], start,
                                      start + chunk["duration"] / 1e7))
            if Path(dest).stat().st_size > 1000:
                print(f"Voice OK: edge-tts {voice}")
                return words
        except Exception as exc:
            print(f"edge-tts voice {voice} failed: {exc}")
    sys.exit("Text-to-speech failed with every voice")


def trim_silence(src, dest):
    """Cut silence from the start and end so captions line up."""
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", src, "-af",
        ("silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
         "silenceremove=start_periods=1:start_threshold=-50dB,areverse"),
        dest,
    ])
    return dest if audio_duration(dest) > 1.0 else src


def deepen_voice(src, dest, factor=PITCH_FACTOR):
    """Lowers the voice pitch slightly for a deeper tone, compensating speed
    back so the duration (and caption timings) stay the same."""
    try:
        sr = int(subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate", "-of", "default=nw=1:nk=1", str(src),
        ]).strip())
    except Exception:
        sr = 24000
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", src,
        "-filter:a", f"asetrate={int(sr * factor)},aresample={sr},atempo={1 / factor:.4f}",
        dest,
    ])
    return dest


def make_voice():
    """Returns (audio_path, word_timings_or_None)."""
    if GEMINI_KEY:
        try:
            raw = WORK / "voice_raw.wav"
            gemini_tts(raw)
            print(f"Voice OK: Gemini TTS ({GEMINI_VOICE})")
            return trim_silence(raw, WORK / "voice.wav"), None
        except Exception as exc:
            print(f"Gemini TTS unavailable, falling back to edge-tts: {exc}")
    raw = WORK / "voice_raw.mp3"
    words = asyncio.run(edge_tts_voice(raw))
    if words:  # real timings only valid for the untrimmed audio
        return raw, words
    return trim_silence(raw, WORK / "voice.wav"), None


# ------------------------------------------------------------- captions ----

def clean_word(word):
    return re.sub(r"[{}\\\"“”.,;:…]", "", word).strip().upper()


def estimate_words(text, duration):
    """Spread the words over the audio, weighting by length and punctuation."""
    tokens = [t for t in text.split() if clean_word(t)]
    weights = []
    for t in tokens:
        w = len(clean_word(t)) + 1.5
        if re.search(r"[.!?…]$", t):
            w += 4
        elif re.search(r"[,;:—-]$", t):
            w += 2
        weights.append(w)
    total = sum(weights)
    words, at = [], 0.0
    for t, w in zip(tokens, weights):
        span = duration * w / total
        words.append((t, at, at + span))
        at += span
    return words


def ass_time(seconds):
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    return f"{h}:{m:02d}:{seconds % 60:05.2f}"


def chunk_words(words):
    """Group into short on-screen phrases: up to 3 words / ~15 characters."""
    chunks, cur = [], []
    for w in words:
        cand = cur + [w]
        text = " ".join(clean_word(x[0]) for x in cand)
        if cur and (len(cand) > 3 or len(text) > 15):
            chunks.append(cur)
            cur = [w]
        else:
            cur = cand
        if re.search(r"[.!?,;:]$", w[0]):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def build_ass(words, path):
    words = [w for w in words if clean_word(w[0])]
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Cap,DejaVu Sans,{CAPTION_FONT_SIZE},&H00FFFFFF,&H00FFFFFF,"
        f"&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,1,2,40,40,"
        f"{CAPTION_MARGIN_V},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    lines, idx = [], 0
    for chunk in chunk_words(words):
        for j, (tok, start, end) in enumerate(chunk):
            nxt = words[idx + 1] if idx + 1 < len(words) else None
            stop = nxt[1] if nxt and nxt[1] - end < 0.5 else end
            stop = max(stop, start + 0.08)
            parts = []
            for k, (t2, _, _) in enumerate(chunk):
                if k == j:
                    parts.append("{\\c&H0000D7FF&}" + clean_word(t2) + "{\\c&H00FFFFFF&}")
                else:
                    parts.append(clean_word(t2))
            lines.append(
                f"Dialogue: 0,{ass_time(start)},{ass_time(stop)},Cap,,0,0,0,,"
                + " ".join(parts))
            idx += 1
    Path(path).write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return len(words)


# ---------------------------------------------------------------- video ----

def search_pexels(query):
    # Pull the deepest single-call pool Pexels allows (80/page is its max)
    # instead of gambling on one of two shallow 40-result pages - that
    # doubled the real pool size we actually see per render, on top of the
    # cross-video exclusion log below, which is what was causing the same
    # one or two top-ranked clips to keep winning for common search phrases
    # across unrelated videos.
    resp = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": PEXELS_KEY},
        params={"query": query, "per_page": 80, "page": 1, "orientation": "portrait"},
        timeout=30,
    )
    resp.raise_for_status()
    videos = resp.json().get("videos", [])
    if not videos:
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": PEXELS_KEY},
            params={"query": query, "per_page": 80, "page": 2, "orientation": "portrait"},
            timeout=30,
        )
        resp.raise_for_status()
        videos = resp.json().get("videos", [])

    clips = []
    for video in videos:
        files = [
            f for f in video.get("video_files", [])
            if f.get("file_type") == "video/mp4"
            and f.get("height", 0) >= f.get("width", 0)
        ]
        if not files:
            continue
        files.sort(key=lambda f: abs(f["height"] - H))
        # Pexels doesn't expose tags via the API, but the video's page URL is
        # a descriptive slug (e.g. ".../video/aerial-view-city-traffic-123/")
        # that's a real signal of what's actually in the clip - use it to
        # judge relevance against the search query.
        clips.append({
            "source": "pexels",
            "link": files[0]["link"],
            "duration": video.get("duration", SEGMENT_SECONDS),
            "keywords": extract_keywords(video.get("url", "")),
        })
    return clips


def search_pixabay(query):
    """Second, independent free stock-footage source - pairs with Pexels so
    two videos searching a similar phrase draw from two separate catalogs
    instead of fighting over the same pool."""
    if not PIXABAY_KEY:
        return []
    resp = requests.get(
        "https://pixabay.com/api/videos/",
        params={"key": PIXABAY_KEY, "q": query, "per_page": 100, "page": 1, "safesearch": "true"},
        timeout=30,
    )
    resp.raise_for_status()
    hits = resp.json().get("hits", [])

    clips = []
    for hit in hits:
        files = [f for f in hit.get("videos", {}).values() if f.get("url")]
        if not files:
            continue
        # Pixabay doesn't offer a portrait-only filter like Pexels does, but
        # everything gets scaled+cropped to 1080x1920 in prep_clip anyway,
        # so any orientation/quality works - just pick closest to target height.
        files.sort(key=lambda f: abs(f.get("height", 0) - H))
        # Pixabay gives real tags, unlike Pexels - the strongest relevance
        # signal we have for this source.
        clips.append({
            "source": "pixabay",
            "link": files[0]["url"],
            "duration": hit.get("duration", SEGMENT_SECONDS),
            "keywords": extract_keywords(hit.get("tags", "")),
        })
    return clips


STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "at", "to", "and", "or", "with",
    "for", "is", "are", "its", "it's", "video", "footage", "stock",
}


def extract_keywords(text):
    return {
        w for w in re.findall(r"[a-z]+", text.lower())
        if w not in STOPWORDS and len(w) > 2
    }


# Clickbait/filler words that show up in almost every generated title but
# say nothing about the actual subject - stripped out when deriving the
# anchor below, so e.g. "The Weight Of Every Ant On Earth Will Shock You"
# yields {weight, ant, earth}, not {shock, you, every}.
TITLE_FILLER = {
    "will", "never", "always", "secret", "secrets", "hidden", "real",
    "truth", "shock", "shocking", "shocked", "amazing", "incredible",
    "unbelievable", "insane", "crazy", "mind", "blowing", "actually",
    "really", "you", "your", "this", "that", "every", "one", "day", "most",
    "why", "how", "what", "just", "even", "still", "yet", "before",
}


def extract_anchor_keywords(title, max_words=3):
    """A small set of words naming the video's real subject, derived from
    its title. This exists because render.py otherwise has nothing at all
    tying its stock-footage search back to what the video is actually
    about - it only ever sees Gemini's 5 freeform search_query phrases, and
    if even one of those drifts abstract (despite the prompt begging it not
    to - the same unreliable-self-policing problem as the topic dedup),
    there was nothing to catch a beat like "collective strength" returning
    a literal top-ranked clip of people drumming at a concert instead of
    ants. Every search below gets anchored back to this, so a vague beat
    query still lands on-subject instead of on whatever ranks top for its
    own, possibly meaningless, words. Scans the title in its original
    left-to-right word order (not via extract_keywords's set, which would
    silently drop the subject noun at random - e.g. 'Ants Outweigh Humans'
    could lose 'ants' entirely to Python's unordered set iteration)."""
    ordered = re.findall(r"[a-z]+", title.lower())
    words = [w for w in ordered
             if len(w) > 2 and w not in STOPWORDS and w not in TITLE_FILLER]
    seen, anchor = set(), []
    for w in words:
        if w not in seen:
            seen.add(w)
            anchor.append(w)
        if len(anchor) >= max_words:
            break
    return anchor


ANCHOR_WORDS = extract_anchor_keywords(TITLE)
ANCHOR = " ".join(ANCHOR_WORDS)
if ANCHOR:
    print(f"Stock-footage anchor (from title): {ANCHOR!r}")
else:
    print("No usable anchor words from title - searches will rely on "
          "search_query alone")


def search_clips(query, use_anchor=True):
    """Combine both free stock-footage sources for one query, then rank by
    how well each clip's own slug/tags actually overlap with the search
    query - instead of just trusting the API's relevance ranking and
    shuffling blindly, which is how unrelated clips were sneaking in.
    Ties (and the near-ties just below the best score) still get shuffled
    for variety, but a clip that shares none of the query's keywords only
    gets used if nothing better came back at all - and even then, we lean
    on the API's own relevance order (its best guess for this query) rather
    than shuffling across the whole wide pool, which is how an abstract
    closing-line beat (no literal keyword match exists for it at all) used
    to end up with a near-random clip from deep in the results.

    Every actual API call is anchored to the video's real subject (see
    ANCHOR above), not just the raw beat phrase Gemini wrote - this is what
    stops a vague beat like "collective strength" from literally searching
    just that phrase and getting back a top-ranked clip of a concert crowd
    that has nothing to do with the video. If even the anchored query comes
    back with no keyword overlap at all, we fall back to the anchor alone
    (still on-subject) rather than trusting raw top results for a query
    that may itself be meaningless."""
    effective_query = f"{ANCHOR} {query}".strip() if (use_anchor and ANCHOR) else query
    pexels = search_pexels(effective_query)
    pixabay = search_pixabay(effective_query)
    clips = pexels + pixabay
    if not clips:
        return []
    query_words = extract_keywords(query) | set(ANCHOR_WORDS)
    scored = [(len(c["keywords"] & query_words), c) for c in clips]
    best_score = max(s for s, _ in scored)
    if best_score > 0:
        chosen = [c for s, c in scored if s == best_score]
        if len(chosen) < 6 and best_score > 1:
            chosen += [c for s, c in scored if s == best_score - 1]
        random.shuffle(chosen)
    elif ANCHOR and use_anchor:
        # No overlap even with the anchor baked into the query text itself -
        # don't trust raw top results for what may be a meaningless phrase.
        # Search the anchor alone instead, which is guaranteed on-subject.
        print(f"No keyword-matching clips for '{effective_query}' - "
              f"falling back to the subject anchor '{ANCHOR}' alone")
        return search_clips(ANCHOR, use_anchor=False)
    else:
        # No anchor available (title missing) and no keyword overlap either
        # - stay close to each API's own top-ranked results instead of
        # shuffling the full pool - only lightly shuffle within that
        # top slice so it's not the exact same clip every run.
        print(f"No keyword-matching clips for '{effective_query}' - using each source's top results")
        top_slice = pexels[:8] + pixabay[:8]
        random.shuffle(top_slice)
        chosen = top_slice
    return chosen


def download(url, dest):
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)


def prep_clip(clip, idx):
    """Download one stock clip (Pexels or Pixabay) and crop/encode it into a
    usable segment."""
    link = clip.get("link")
    if not link:
        return None, 0.0
    raw = WORK / f"raw_{idx}.mp4"
    seg = WORK / f"seg_{idx}.mp4"
    try:
        download(link, raw)
    except Exception as exc:
        print(f"Download failed for clip {idx} ({clip.get('source')}): {exc}")
        return None, 0.0
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-t", SEGMENT_SECONDS,
        "-vf", (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},fps={FPS},setsar=1"),
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
        "-pix_fmt", "yuv420p", seg,
    ])
    dur = min(float(clip.get("duration", SEGMENT_SECONDS)), SEGMENT_SECONDS)
    return seg, dur


def build_segments(needed_seconds):
    """Fetch clips query-by-query so the footage roughly follows the script's
    own sequence of scene beats, instead of one generic look for the whole
    video.

    Critically, this also guarantees the final reel actually reaches
    needed_seconds. Previously, if the per-beat searches came up short
    (download failures, a thin result pool, etc.), the leftover gap got
    filled by ffmpeg looping the whole short reel to match the audio length
    - which is exactly why entire videos were visibly repeating their clips
    end-to-end. Now we track every clip already used (by URL) so we never
    download the same clip twice, and if we're still short after going
    through every beat once, we keep pulling additional - still query-
    relevant, still never-repeated - clips until we actually hit the
    target length.

    On top of that in-video dedup, used_links also starts seeded with the
    persisted cross-video log (see USED_LOG_PATH above), so a clip that
    already appeared in one of the last ~25-30 videos is skipped here too -
    that's what stops the same top-ranked "space stars" or "ocean waves"
    clip from showing up again and again across unrelated videos."""
    segments, total, idx = [], 0.0, 0
    used_links = set(PERSISTED_LINKS)
    added_this_video = []
    per_query_target = max(SEGMENT_SECONDS, needed_seconds / len(QUERIES))

    def take_from(videos, budget):
        nonlocal total, idx
        used_here = 0.0
        added_any = False
        for video in videos:
            if (used_here >= budget
                    or total >= needed_seconds + 1
                    or len(segments) >= MAX_SEGMENTS):
                break
            link = video.get("link")
            if not link or link in used_links:
                continue
            seg, dur = prep_clip(video, idx)
            if not seg:
                continue
            used_links.add(link)
            added_this_video.append(link)
            segments.append(seg)
            total += dur
            used_here += dur
            idx += 1
            added_any = True
        return added_any

    for query in QUERIES:
        if total >= needed_seconds + 1 or len(segments) >= MAX_SEGMENTS:
            break
        videos = search_clips(query)
        if not videos:
            print(f"No results for '{query}', skipping that beat")
            continue
        take_from(videos, per_query_target)

    # Top-up pass: if the per-beat searches left us short of the narration
    # length, cycle back through the same beats (now allowing a bigger
    # budget per query) picking up any still-unused clips, instead of
    # letting the final encode loop the short reel and visibly repeat it.
    attempts = 0
    while total < needed_seconds - 1 and len(segments) < MAX_SEGMENTS and attempts < 3:
        attempts += 1
        progressed = False
        for query in QUERIES:
            if total >= needed_seconds - 1 or len(segments) >= MAX_SEGMENTS:
                break
            videos = search_clips(query)
            if not videos:
                continue
            if take_from(videos, needed_seconds):
                progressed = True
        if not progressed:
            break

    if not segments:
        print("Per-beat search found nothing usable, falling back to 'nature'")
        videos = search_clips("nature")
        take_from(videos, needed_seconds)

    # Last resort: still short (rare) - rather than let ffmpeg loop and
    # visibly repeat the sequence, pad with more generic, still on-brand
    # footage until we reach the target.
    if total < needed_seconds - 1 and len(segments) < MAX_SEGMENTS:
        print(f"Still short ({total:.1f}s/{needed_seconds:.1f}s) - padding with broader on-topic footage")
        # Search across all the beats' keywords combined instead of one
        # narrow phrase, so the pad-out footage still matches the video's
        # actual subject instead of defaulting to something generic.
        broad_query = " ".join(QUERIES)
        videos = search_clips(broad_query)
        take_from(videos, needed_seconds)
        if total < needed_seconds - 1:
            take_from(search_clips("nature"), needed_seconds)

    # Absolute last resort: the cross-video exclusion log starved every
    # query for this particular topic (only plausible for a very narrow
    # niche subject). Drop that exclusion - keeping only this-video's own
    # dedup - rather than ever fail the render or let ffmpeg loop and
    # visibly repeat footage.
    if total < needed_seconds - 1 and len(segments) < MAX_SEGMENTS:
        print("Still short even ignoring repeats is better than failing - "
              "dropping the cross-video exclusion as a last resort")
        used_links = set(added_this_video)
        take_from(search_clips(" ".join(QUERIES)), needed_seconds)
        if total < needed_seconds - 1:
            take_from(search_clips("nature"), needed_seconds)

    if not segments:
        sys.exit("Could not prepare any video segments")
    return segments, added_this_video


def pick_music():
    if not MUSIC_DIR.exists():
        return None
    tracks = [p for p in MUSIC_DIR.iterdir()
              if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg")]
    return random.choice(tracks) if tracks else None


def mix_audio(voice, total):
    """Lays soft background music under the narration, ducked low with a
    fade in/out. Returns the voice path unchanged if no music is available
    yet, so the pipeline keeps working while the music/ folder is empty."""
    track = pick_music()
    if not track:
        print("No files in music/ yet - rendering with voice only")
        return voice
    mixed = WORK / "mixed.wav"
    fade_out_start = max(0.0, total - 1.5)
    filt = (
        f"[1:a]aloop=loop=-1:size=2e9,atrim=0:{total:.2f},"
        f"volume={MUSIC_VOLUME},afade=t=in:st=0:d=1.5,"
        f"afade=t=out:st={fade_out_start:.2f}:d=1.5[music];"
        f"[0:a][music]amix=inputs=2:duration=first:dropout_transition=0:weights=1 0.6[aout]"
    )
    try:
        run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", voice, "-ss", str(MUSIC_START_OFFSET), "-i", track,
            "-filter_complex", filt, "-map", "[aout]",
            "-t", f"{total:.2f}", mixed,
        ])
        print(f"Background music mixed in: {track.name}")
        return mixed
    except subprocess.CalledProcessError as exc:
        print(f"Music mixing failed, continuing with voice only: {exc}")
        return voice


def final_encode(joined, audio, total, ass_path):
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-stream_loop", "-1", "-i", joined, "-i", audio,
        "-t", f"{total:.2f}",
        "-map", "0:v", "-map", "1:a",
    ]
    if ass_path:
        cmd += ["-vf", f"ass={ass_path}"]
    cmd += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(VIDEO_CRF),
        "-maxrate", f"{VIDEO_MAXRATE_KBPS}k", "-bufsize", f"{VIDEO_MAXRATE_KBPS * 2}k",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-ac", "2",
        "-movflags", "+faststart", OUT / "video.mp4",
    ]
    run(cmd)


def main():
    voice, words = make_voice()
    length = min(audio_duration(voice), MAX_SECONDS)
    print(f"Narration length: {length:.1f}s")

    if not words:
        words = estimate_words(SCRIPT, length)
    ass_path = WORK / "captions.ass"
    try:
        count = build_ass(words, ass_path)
        print(f"Captions built for {count} words")
    except Exception as exc:
        print(f"Captions skipped: {exc}")
        ass_path = None

    segments, new_links = build_segments(length)

    concat_list = WORK / "list.txt"
    concat_list.write_text("".join(f"file '{s.resolve()}'\n" for s in segments))
    joined = WORK / "joined.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", concat_list, "-c", "copy", joined])

    total = length + 0.4
    audio = mix_audio(voice, total)

    try:
        final_encode(joined, audio, total, ass_path)
    except subprocess.CalledProcessError:
        if not ass_path:
            raise
        print("Caption burn-in failed, rendering without captions")
        final_encode(joined, audio, total, None)

    size_mb = (OUT / "video.mp4").stat().st_size / 1024 / 1024
    print(f"Done: {OUT / 'video.mp4'} ({size_mb:.1f} MB)")

    save_used_links(new_links)
    print(f"Logged {len(new_links)} clip(s) to {USED_LOG_PATH} "
          f"({min(len(PERSISTED_LINKS) + len(new_links), MAX_PERSISTED_LINKS)} total tracked)")


if __name__ == "__main__":
    main()
