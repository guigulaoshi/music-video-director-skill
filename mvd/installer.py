"""Check and install required dependencies."""

import platform
import shutil
import subprocess
import sys
from typing import Optional


PYTHON_PACKAGES = [
    ("yt-dlp", "yt_dlp"),
    ("librosa", "librosa"),
    ("openai-whisper", "whisper"),
    ("scenedetect[opencv]", "scenedetect"),
    ("ffmpeg-python", "ffmpeg"),
    ("numpy", "numpy"),
    ("scipy", "scipy"),
    ("Pillow", "PIL"),
    ("click", "click"),
    ("tqdm", "tqdm"),
]

# Optional packages that improve quality but are not required.
# madmom: RNN+DBN beat tracker — significantly better than librosa for
# stylized or non-Western music (orchestral, traditional, non-4/4 rhythms).
# Install: pip install madmom
OPTIONAL_PACKAGES = [
    ("madmom", "madmom", "RNN beat tracker — better beat-sync for orchestral/non-Western music"),
]


def ffmpeg_install_hint() -> str:
    system = platform.system()
    if system == "Darwin":
        return "brew install ffmpeg"
    elif system == "Linux":
        return "sudo apt-get install -y ffmpeg"
    elif system == "Windows":
        return "winget install ffmpeg"
    return "See https://ffmpeg.org/download.html"


def check_ffmpeg() -> Optional[str]:
    path = shutil.which("ffmpeg")
    if not path:
        return None
    result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
    return result.stdout.split("\n")[0]


def is_importable(import_name: str) -> bool:
    try:
        __import__(import_name)
        return True
    except ImportError:
        return False


def run_check(verbose: bool = True) -> dict:
    status = {"ffmpeg": None, "packages": {}, "all_ok": False}

    ffmpeg_version = check_ffmpeg()
    status["ffmpeg"] = ffmpeg_version
    if verbose:
        if ffmpeg_version:
            print(f"  [ok] ffmpeg: {ffmpeg_version.split(',')[0]}")
        else:
            print(f"  [MISSING] ffmpeg — install with: {ffmpeg_install_hint()}")

    missing = []
    for install_name, import_name in PYTHON_PACKAGES:
        ok = is_importable(import_name)
        display_name = install_name.split("[")[0]
        status["packages"][display_name] = ok
        if verbose:
            symbol = "[ok]" if ok else "[MISSING]"
            print(f"  {symbol} {display_name}")
        if not ok:
            missing.append(install_name)

    status["missing"] = missing

    # Report optional packages separately — not required, not installed by default
    if verbose:
        print("\n  Optional (quality upgrades):")
        for install_name, import_name, description in OPTIONAL_PACKAGES:
            ok = is_importable(import_name)
            symbol = "[ok]" if ok else "[off]"
            hint = f"  ← pip install {install_name}" if not ok else ""
            print(f"  {symbol} {install_name}: {description}{hint}")

    status["all_ok"] = (ffmpeg_version is not None) and (not missing)
    return status


def install_all(auto_install: bool = True) -> None:
    print("Checking dependencies...\n")
    status = run_check(verbose=True)

    if status["ffmpeg"] is None:
        print(f"\n[ERROR] ffmpeg is required but not installed.")
        print(f"Install it with:\n  {ffmpeg_install_hint()}")
        print("\nThen re-run: mvd install")
        sys.exit(1)

    missing = status.get("missing", [])
    if missing:
        if auto_install:
            print(f"\nInstalling {len(missing)} missing package(s)...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install"] + missing,
                check=True,
            )
            print("\nDone. Verifying...")
            run_check(verbose=True)
        else:
            print(f"\nMissing: {', '.join(missing)}")
            print("Run: mvd install -y  (to auto-install)")
            sys.exit(1)
    else:
        print("\nAll dependencies satisfied.")
