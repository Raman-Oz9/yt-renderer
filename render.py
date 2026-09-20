#!/usr/bin/env python3
"""Faceless Short renderer.

Natural voice (Gemini TTS, falls back to edge-tts) + word-highlight captions
+ Pexels stock clips + FFmpeg. Writes output/video.mp4 (720x1280, ~4 MB).

Environment: SCRIPT, SEARCH_QUERY, PEXELS_API_KEY, GEMINI_API_KEY (optional).
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
QUERY = os.environ.get("SEARCH_QUERY", "").strip() or "nature"
PEXELS_KEY = os.environ["PEXELS_API_KEY"]
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

GEMINI_TTS_MODEL = "gemini-3.1-flash-tts-preview"
GEMINI_VOICE = os.environ.get("GEMINI_VOICE", "Kore")  # try Puck, Charon, Fenrir, Aoede
EDGE_VOICES = ["en-US-AndrewMultilingualNeural", "en-US-AriaNeural"]  # fallback

MAX_SECONDS = 59      # keep it a Short
SEGMENT_SECONDS = 8   # max length taken from each stock clip
W, H, FPS = 720, 1280, 30
TARGET_MB = 4.2       # Make's free plan can only download files up to 5 MB
AUDIO_KBPS = 64
CAPTION_FONT_SIZE = 54
CAPTION_MARGIN_V = 430  # distance from the bottom edge

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
    prompt = ("Say in a warm, expressive, conversational storyteller voice, "
              f"at a slightly fast pace with natural pauses: {SCRIPT}")
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


def make_voice():
    """Returns (audio_path, word_timings_or_None)."""
    if GEMINI_KEY:
        try:
            raw = WORK / "voice_raw.wav"
            gemini_tts(raw)
            print("Voice OK: Gemini TTS")
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
    return re.sub(r"[{}\\\"\u201c\u201d.,;:\u2026]", "", word).strip().upper()


def estimate_words(text, duration):
    """Spread the words over the audio, weighting by length and punctuation."""
    tokens = [t for t in text.split() if clean_word(t)]
    weights = []
    for t in tokens:
        w = len(clean_word(t)) + 1.5
        if re.search(r"[.!?\u2026]$", t):
            w += 4
        elif re.search(r"[,;:\u2014-]$", t):
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


def build_segments(needed_seconds):
    videos = search_pexels(QUERY)
    if not videos:
        print(f"No results for '{QUERY}', falling back to 'nature'")
        videos = search_pexels("nature")
    if not videos:
        sys.exit("Pexels returned no clips")
    random.shuffle(videos)

    segments, total = [], 0.0
    for i, video in enumerate(videos):
        if total >= needed_seconds + 1 or len(segments) >= 8:
            break
        link = best_file(video)
        if not link:
            continue
        raw = WORK / f"raw_{i}.mp4"
        seg = WORK / f"seg_{i}.mp4"
        try:
            download(link, raw)
        except Exception as exc:
            print(f"Download failed for clip {i}: {exc}")
            continue
        run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-t", SEGMENT_SECONDS,
            "-vf", (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                    f"crop={W}:{H},fps={FPS},setsar=1"),
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-pix_fmt", "yuv420p", seg,
        ])
        segments.append(seg)
        total += min(float(video.get("duration", SEGMENT_SECONDS)), SEGMENT_SECONDS)

    if not segments:
        sys.exit("Could not prepare any video segments")
    return segments


def final_encode(joined, voice, total, video_kbps, ass_path):
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-stream_loop", "-1", "-i", joined, "-i", voice,
        "-t", f"{total:.2f}",
        "-map", "0:v", "-map", "1:a",
    ]
    if ass_path:
        cmd += ["-vf", f"ass={ass_path}"]
    cmd += [
        "-c:v", "libx264", "-preset", "veryfast",
        "-b:v", f"{video_kbps}k", "-maxrate", f"{video_kbps}k",
        "-bufsize", f"{video_kbps * 2}k", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-ac", "1",
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

    segments = build_segments(length)

    concat_list = WORK / "list.txt"
    concat_list.write_text("".join(f"file '{s.resolve()}'\n" for s in segments))
    joined = WORK / "joined.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", concat_list, "-c", "copy", joined])

    # Loop the visuals if shorter than the voice, burn captions, and pick a
    # video bitrate that keeps the file under TARGET_MB.
    total = length + 0.4
    video_kbps = int(TARGET_MB * 8 * 1024 / total) - AUDIO_KBPS
    video_kbps = max(250, min(video_kbps, 1500))
    try:
        final_encode(joined, voice, total, video_kbps, ass_path)
    except subprocess.CalledProcessError:
        if not ass_path:
            raise
        print("Caption burn-in failed, rendering without captions")
        final_encode(joined, voice, total, video_kbps, None)

    size_mb = (OUT / "video.mp4").stat().st_size / 1024 / 1024
    print(f"Done: {OUT / 'video.mp4'} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
