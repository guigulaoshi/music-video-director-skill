"""
Synthetic media generators for tests.

All functions produce deterministic output given the same arguments.
No network access, no external downloads — everything is generated from scratch
using numpy (for audio) and ffmpeg (for video), both already required deps.
"""

import os
import struct
import subprocess
import tempfile
import wave

import numpy as np


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

def make_click_track(
    path: str,
    bpm: float = 120.0,
    duration: float = 30.0,
    sr: int = 22050,
) -> dict:
    """
    Write a WAV file containing a sine wave background plus a sharp click
    at every beat position.

    Returns a dict with ground-truth metadata:
      bpm, beat_times (list of floats), duration, sr, path
    """
    n_samples = int(sr * duration)
    y = np.zeros(n_samples, dtype=np.float32)

    # Low sine wave background (220 Hz) — gives librosa something to analyse
    t = np.linspace(0, duration, n_samples, endpoint=False)
    y += 0.25 * np.sin(2 * np.pi * 220 * t)

    # Click at every beat (20ms Hann envelope at 0.8 amplitude)
    beat_interval = 60.0 / bpm
    beat_times = []
    click_dur = int(sr * 0.020)  # 20ms

    b = 0.0
    while b < duration:
        beat_times.append(round(b, 6))
        idx = int(b * sr)
        end = min(idx + click_dur, n_samples)
        length = end - idx
        if length > 0:
            y[idx:end] += 0.8 * np.hanning(length).astype(np.float32)
        b += beat_interval

    # Clip and write as 16-bit mono WAV
    y = np.clip(y, -1.0, 1.0)
    y_i16 = (y * 32767).astype(np.int16)

    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(y_i16.tobytes())

    actual_duration = len(beat_times) and (int(duration * sr) / sr)
    return {
        "path": path,
        "bpm": bpm,
        "beat_times": beat_times,
        "duration": round(n_samples / sr, 6),
        "sr": sr,
    }


# ---------------------------------------------------------------------------
# Video
# ---------------------------------------------------------------------------

SCENE_COLORS = [
    "blue", "red", "green", "yellow", "purple",
    "orange", "cyan", "magenta", "white", "gray",
]


def make_color_clip(
    path: str,
    scenes: list,  # list of (color_str, duration_seconds)
    fps: int = 24,
    width: int = 320,
    height: int = 240,
) -> dict:
    """
    Generate a video made of solid-color segments separated by hard cuts.
    Scene boundaries are pixel-exact, making ContentDetector reliable.

    scenes: e.g. [("blue", 5.0), ("red", 5.0), ("green", 3.0)]

    Returns dict with ground-truth metadata:
      path, scenes (list of {color, start_time, end_time, duration}), total_duration
    """
    size = f"{width}x{height}"
    segments = []
    gt_scenes = []
    t = 0.0

    with tempfile.TemporaryDirectory(prefix="mvd_fixtures_") as tmp:
        for i, (color, dur) in enumerate(scenes):
            seg_path = os.path.join(tmp, f"seg_{i:03d}.mp4")
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "lavfi",
                    "-i", f"color=c={color}:s={size}:r={fps}:d={dur:.6f}",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    seg_path,
                ],
                check=True,
                capture_output=True,
            )
            segments.append(seg_path)
            gt_scenes.append({
                "color": color,
                "start_time": round(t, 3),
                "end_time": round(t + dur, 3),
                "duration": round(dur, 3),
            })
            t += dur

        # Concatenate segments
        concat_txt = os.path.join(tmp, "concat.txt")
        with open(concat_txt, "w") as f:
            for seg in segments:
                f.write(f"file '{seg}'\n")

        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_txt,
                "-c", "copy",
                path,
            ],
            check=True,
            capture_output=True,
        )

    return {
        "path": path,
        "scenes": gt_scenes,
        "total_duration": round(t, 3),
        "fps": fps,
        "width": width,
        "height": height,
    }


def default_clip_scenes(n: int = 5, dur_each: float = 5.0) -> list:
    """Return n (color, duration) pairs for make_color_clip."""
    colors = SCENE_COLORS[:n]
    return [(c, dur_each) for c in colors]
