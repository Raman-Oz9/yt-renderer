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
PEXELS_KEY = os.environ["PEXELS_API_KEY"]
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

GEMINI_TTS_MODEL = "gemini-3.1-flash-tts-preview"
GEMINI_VOICE = os.environ.get("GEMINI_VOICE", "Algenib")  # deep, gravelly male narrator voice
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
MUSIC_VOLUME = 0.30      # raised again from 0.20 - more audible under the voice
MUSIC_START_OFFSET = 20  # skip the first 20s of the track (skip past quiet intros)

WORK = Path("work")
OUT = Path("output")
WORK.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)


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
    resp = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": PEXELS_KEY},
        params={"query": query, "per_page": 20, "orientation": "portrait"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("videos", [])


def best_file(video):
    """Portrait mp4 closest to the target height."""
    files = [
        f for f in video.get("video_files", [])
        if f.get("file_type") == "video/mp4"
        and f.get("height", 0) >= f.get("width", 0)
    ]
    files.sort(key=lambda f: abs(f["height"] - H))
    return files[0]["link"] if files else None


def download(url, dest):
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)


def prep_clip(video, idx):
    """Download one Pexels video and crop/encode it into a usable segment."""
    link = best_file(video)
    if not link:
        return None, 0.0
    raw = WORK / f"raw_{idx}.mp4"
    seg = WORK / f"seg_{idx}.mp4"
    try:
        download(link, raw)
    except Exception as exc:
        print(f"Download failed for clip {idx}: {exc}")
        return None, 0.0
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-t", SEGMENT_SECONDS,
        "-vf", (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},fps={FPS},setsar=1"),
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
        "-pix_fmt", "yuv420p", seg,
    ])
    dur = min(float(video.get("duration", SEGMENT_SECONDS)), SEGMENT_SECONDS)
    return seg, dur


def build_segments(needed_seconds):
    """Fetch clips query-by-query so the footage roughly follows the script's
    own sequence of scene beats, instead of one generic look for the whole
    video."""
    segments, total, idx = [], 0.0, 0
    per_query_target = max(SEGMENT_SECONDS, needed_seconds / len(QUERIES))

    for query in QUERIES:
        if total >= needed_seconds + 1 or len(segments) >= MAX_SEGMENTS:
            break
        videos = search_pexels(query)
        if not videos:
            print(f"No results for '{query}', skipping that beat")
            continue
        random.shuffle(videos)
        used_for_query = 0.0
        for video in videos:
            if (used_for_query >= per_query_target
                    or total >= needed_seconds + 1
                    or len(segments) >= MAX_SEGMENTS):
                break
            seg, dur = prep_clip(video, idx)
            if not seg:
                continue
            segments.append(seg)
            total += dur
            used_for_query += dur
            idx += 1

    if not segments:
        print("Per-beat search found nothing usable, falling back to 'nature'")
        videos = search_pexels("nature")
        random.shuffle(videos)
        for video in videos:
            if total >= needed_seconds + 1 or len(segments) >= MAX_SEGMENTS:
                break
            seg, dur = prep_clip(video, idx)
            if not seg:
                continue
            segments.append(seg)
            total += dur
            idx += 1

    if not segments:
        sys.exit("Could not prepare any video segments")
    return segments


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
    try:
        voice = deepen_voice(voice, WORK / "voice_deep.wav")
        print(f"Voice pitch lowered (factor {PITCH_FACTOR})")
    except subprocess.CalledProcessError as exc:
        print(f"Pitch-lowering failed, using voice as-is: {exc}")
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

    segments = build_segments(length)

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


if __name__ == "__main__":
    main()
