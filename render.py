#!/usr/bin/env python3
"""Faceless Short renderer: edge-tts voiceover + Pexels stock clips + FFmpeg.

Reads SCRIPT, SEARCH_QUERY and PEXELS_API_KEY from the environment and
writes output/video.mp4 (1080x1920, 30fps, H.264 + AAC).
"""
import asyncio
import os
import random
import subprocess
import sys
from pathlib import Path

import edge_tts
import requests

SCRIPT = os.environ["SCRIPT"].strip()
QUERY = os.environ.get("SEARCH_QUERY", "").strip() or "nature"
PEXELS_KEY = os.environ["PEXELS_API_KEY"]

VOICES = ["en-US-EmmaMultilingualNeural", "en-US-AriaNeural"]  # 2nd is fallback
MAX_SECONDS = 59      # keep it a Short
SEGMENT_SECONDS = 8   # max length taken from each stock clip
W, H, FPS = 1080, 1920, 30

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


async def make_voice(path):
    for voice in VOICES:
        try:
            await edge_tts.Communicate(SCRIPT, voice).save(str(path))
            if path.exists() and path.stat().st_size > 1000:
                print(f"Voice OK: {voice}")
                return
        except Exception as exc:  # try the next voice
            print(f"Voice {voice} failed: {exc}")
    sys.exit("Text-to-speech failed with all voices")


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
    """Portrait mp4 closest to 1080x1920."""
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
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", seg,
        ])
        segments.append(seg)
        total += min(float(video.get("duration", SEGMENT_SECONDS)), SEGMENT_SECONDS)

    if not segments:
        sys.exit("Could not prepare any video segments")
    return segments


def main():
    voice = WORK / "voice.mp3"
    asyncio.run(make_voice(voice))
    length = min(audio_duration(voice), MAX_SECONDS)
    print(f"Narration length: {length:.1f}s")

    segments = build_segments(length)

    concat_list = WORK / "list.txt"
    concat_list.write_text("".join(f"file '{s.resolve()}'\n" for s in segments))
    joined = WORK / "joined.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", concat_list, "-c", "copy", joined])

    # Loop the visuals if they are shorter than the voice, then mux.
    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-stream_loop", "-1", "-i", joined, "-i", voice,
        "-t", f"{length + 0.4:.2f}",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", OUT / "video.mp4",
    ])
    print("Done:", OUT / "video.mp4")


if __name__ == "__main__":
    main()
