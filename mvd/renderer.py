"""Render the final music video from an Edit Decision List (EDL) using ffmpeg."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from .utils import ensure_dir


def render(
    edl_path: str,
    output_path: Optional[str] = None,
    target_fps: float = 24.0,
    target_width: int = 1920,
    target_height: int = 1080,
    early_frames: int = 0,
) -> str:
    """
    Render a music video from an EDL JSON file.

    The 'early_frames' offset shifts source extraction N frames *before* the
    EDL's source_in timestamp. Keep this at 0 (the default) unless the EDL
    source_in values were intentionally set N frames past the intended first
    frame. A non-zero value when source_in is already at the first clean frame
    will pull frames from the preceding scene, producing N-frame flash artifacts
    at the start of every cut.

    Returns the path to the rendered output file.
    """
    with open(edl_path) as f:
        edl = json.load(f)

    cuts = edl.get("cuts", [])
    audio_file = edl.get("audio_file")

    if output_path is None:
        output_path = edl.get("output_file", str(Path(edl_path).parent / "output.mp4"))

    if not cuts:
        print("Error: EDL has no cuts.", file=sys.stderr)
        sys.exit(1)

    if not audio_file:
        print("Error: EDL missing 'audio_file'.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(audio_file):
        print(f"Error: audio file not found: {audio_file}", file=sys.stderr)
        sys.exit(1)

    ensure_dir(os.path.dirname(os.path.abspath(output_path)))

    frame_offset = early_frames / target_fps
    n = len(cuts)

    print(f"Rendering {n} cuts → {output_path}")
    print(f"Target: {target_width}×{target_height} @ {target_fps}fps")
    print(f"Beat offset: -{frame_offset*1000:.0f}ms ({early_frames} frames early)\n")

    tmpdir = tempfile.mkdtemp(prefix="mvd_render_")
    try:
        segments = _extract_segments(cuts, tmpdir, target_fps, target_width, target_height, frame_offset)
        assembled = _concat_segments(segments, tmpdir)
        _mix_audio(assembled, audio_file, output_path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"\nDone! → {output_path}  ({size_mb:.1f} MB)")
    return output_path


def _extract_segments(cuts, tmpdir, fps, width, height, frame_offset):
    """Extract and normalize each EDL cut into a temp segment file."""
    scale = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1,"
        f"setpts=PTS-STARTPTS"
    )
    segments = []
    n = len(cuts)

    for i, cut in enumerate(cuts):
        source = cut["source_file"]
        src_in = max(0.0, float(cut["source_in"]) - frame_offset)
        src_out = max(src_in + 0.1, float(cut["source_out"]) - frame_offset)
        seg_duration = src_out - src_in
        # Hard-limit frame count to floor(duration * fps) to prevent the fps
        # resampler from pulling frames past src_out and crossing source-clip
        # internal scene boundaries.
        n_frames = int(seg_duration * fps)

        seg_file = os.path.join(tmpdir, f"seg_{i:05d}.mp4")
        print(f"  [{i+1:3d}/{n}] {Path(source).name}  {src_in:.2f}→{src_out:.2f}  ({seg_duration:.2f}s, {n_frames}f)")

        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", f"{src_in:.4f}",
                "-i", source,
                "-t", f"{seg_duration:.4f}",
                "-vf", scale,
                "-r", str(fps),
                "-vsync", "cfr",
                "-frames:v", str(n_frames),
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-an",
                seg_file,
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"\nffmpeg error on segment {i+1}:", file=sys.stderr)
            print(result.stderr[-1500:], file=sys.stderr)
            sys.exit(1)

        segments.append(seg_file)

    return segments


def _concat_segments(segments, tmpdir):
    """Concatenate segment files using the concat demuxer."""
    concat_txt = os.path.join(tmpdir, "concat.txt")
    with open(concat_txt, "w") as f:
        for seg in segments:
            # Escape any single quotes in the path
            safe = seg.replace("\\", "/").replace("'", "\\'")
            f.write(f"file '{safe}'\n")

    assembled = os.path.join(tmpdir, "assembled.mp4")
    print(f"\nConcatenating {len(segments)} segments...")

    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_txt,
            "-c", "copy",
            assembled,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print("ffmpeg concat error:", file=sys.stderr)
        print(result.stderr[-1500:], file=sys.stderr)
        sys.exit(1)

    return assembled


def _mix_audio(video_file, audio_file, output_path):
    """Overlay the music audio onto the assembled video."""
    print("Mixing audio track...")

    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video_file,
            "-i", audio_file,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "256k",
            "-shortest",
            output_path,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print("ffmpeg audio mix error:", file=sys.stderr)
        print(result.stderr[-1500:], file=sys.stderr)
        sys.exit(1)
