"""Download video or audio from URLs (YouTube, Bilibili, etc.) or copy local files."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .utils import ensure_dir, get_video_info, get_audio_duration


def is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def download(
    source: str,
    output_dir: str,
    audio_only: bool = False,
    name: Optional[str] = None,
) -> dict:
    """Download from URL or copy local file.
    Returns: {"file": path, "duration": seconds, "title": str, "source": str}
    """
    ensure_dir(output_dir)
    if is_url(source):
        return _download_url(source, output_dir, audio_only, name)
    else:
        return _copy_local(source, output_dir, audio_only, name)


def _download_url(url: str, output_dir: str, audio_only: bool, name: Optional[str]) -> dict:
    try:
        import yt_dlp
    except ImportError:
        print("yt-dlp not installed. Run: mvd install", file=sys.stderr)
        sys.exit(1)

    stem = name or "%(title)s"
    output_template = os.path.join(output_dir, f"{stem}.%(ext)s")

    ydl_opts: dict = {
        "outtmpl": output_template,
        "quiet": False,
        "no_warnings": False,
    }

    if audio_only:
        ydl_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }],
        })
    else:
        ydl_opts.update({
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
        })

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title", "unknown")
        duration = float(info.get("duration") or 0)

    # Find the most recently modified matching file
    exts = ["mp3"] if audio_only else ["mp4", "webm", "mkv"]
    found = None
    for ext in exts:
        candidates = sorted(
            Path(output_dir).glob(f"*.{ext}"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            found = str(candidates[0])
            break

    if not found:
        raise FileNotFoundError(f"Downloaded file not found in {output_dir}")

    return {"file": found, "duration": duration, "title": title, "source": url}


def _copy_local(source: str, output_dir: str, audio_only: bool, name: Optional[str]) -> dict:
    if not os.path.exists(source):
        raise FileNotFoundError(f"Local file not found: {source}")

    src = Path(source)
    stem = name or src.stem

    if audio_only:
        dest = os.path.join(output_dir, f"{stem}.mp3")
        if src.suffix.lower() != ".mp3":
            subprocess.run(
                ["ffmpeg", "-y", "-i", source, "-vn", "-acodec", "libmp3lame", "-q:a", "2", dest],
                check=True, capture_output=True,
            )
        else:
            shutil.copy2(source, dest)
    else:
        dest = os.path.join(output_dir, f"{stem}{src.suffix}")
        shutil.copy2(source, dest)

    try:
        if audio_only or src.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}:
            duration = get_audio_duration(dest)
        else:
            info = get_video_info(dest)
            duration = info["duration"]
    except Exception:
        duration = 0.0

    return {"file": dest, "duration": duration, "title": src.stem, "source": source}
