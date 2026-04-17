"""Scene detection and keyframe extraction for video clips."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .utils import ensure_dir, get_video_info, save_json


def analyze_clip(
    video_path: str,
    output_dir: Optional[str] = None,
    output_json: Optional[str] = None,
    threshold: float = 27.0,
) -> dict:
    """
    Detect scene boundaries and extract one keyframe per scene.

    Keyframe images are sized to 960px wide for efficient vision analysis.
    Returns structured dict with a 'scenes' list; each scene has a 'keyframe_path'.
    """
    print(f"Analyzing clip: {video_path}")
    info = get_video_info(video_path)
    duration = info["duration"]
    fps = info["fps"]
    print(f"  Duration: {duration:.1f}s  FPS: {fps:.2f}  Res: {info['resolution']}")

    if output_dir is None:
        stem = Path(video_path).stem
        output_dir = str(Path(video_path).parent / "keyframes" / stem)
    ensure_dir(output_dir)

    print("  Detecting scene boundaries...")
    scenes = _detect_scenes(video_path, threshold, duration)
    print(f"  Found {len(scenes)} scenes")

    print("  Extracting keyframes...")
    for scene in scenes:
        kf_path = os.path.join(output_dir, f"scene_{scene['index']:04d}.jpg")
        # Sample at 1/3 into the scene for a more "action" frame
        t = scene["start_time"] + scene["duration"] * 0.33
        t = max(scene["start_time"] + 0.1, min(t, scene["end_time"] - 0.1))
        _extract_frame(video_path, t, kf_path)
        scene["keyframe_path"] = kf_path

    result = {
        "file": os.path.abspath(video_path),
        "duration": round(duration, 3),
        "fps": fps,
        "width": info["width"],
        "height": info["height"],
        "resolution": info["resolution"],
        "scenes": scenes,
    }

    if output_json:
        save_json(result, output_json)
        print(f"  Clip analysis saved: {output_json}")

    return result


def _detect_scenes(video_path: str, threshold: float, duration: float) -> list:
    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector

        video = open_video(video_path)
        mgr = SceneManager()
        mgr.add_detector(ContentDetector(threshold=threshold))
        mgr.detect_scenes(video, show_progress=False)
        scene_list = mgr.get_scene_list()

        scenes = []
        for i, (start, end) in enumerate(scene_list):
            s = round(start.get_seconds(), 3)
            e = round(end.get_seconds(), 3)
            scenes.append({
                "index": i,
                "start_time": s,
                "end_time": e,
                "duration": round(e - s, 3),
            })

        if scenes:
            return scenes

    except Exception as exc:
        print(f"  Scene detection error ({exc}), using fixed-window fallback")

    return _fixed_windows(duration)


def _fixed_windows(duration: float, window: float = 8.0) -> list:
    """Fallback: divide clip into equal-length windows."""
    scenes = []
    t, i = 0.0, 0
    while t < duration:
        end = min(t + window, duration)
        scenes.append({
            "index": i,
            "start_time": round(t, 3),
            "end_time": round(end, 3),
            "duration": round(end - t, 3),
        })
        t, i = end, i + 1
    return scenes


def _extract_frame(video_path: str, timestamp: float, output_path: str) -> None:
    """Extract a single JPEG frame at the given timestamp, scaled to 960px wide."""
    if os.path.exists(output_path):
        return

    # -ss before -i for fast seek; may be a few frames off but that's fine for preview
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", f"{timestamp:.3f}",
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "3",
            "-vf", "scale=960:-1",
            output_path,
        ],
        capture_output=True,
    )

    if result.returncode != 0:
        # Fallback: seek after -i (slower but more accurate)
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", video_path,
                "-ss", f"{timestamp:.3f}",
                "-vframes", "1",
                "-q:v", "3",
                "-vf", "scale=960:-1",
                output_path,
            ],
            capture_output=True,
        )
