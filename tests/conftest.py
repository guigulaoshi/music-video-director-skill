"""
Shared pytest fixtures.

All fixtures use tmp_path so files are cleaned up after each test session.
Heavy fixtures (audio analysis, scene detection) are session-scoped — generated
once per pytest run to keep the suite fast.
"""

import json
import os

import pytest

from .fixtures import make_click_track, make_color_clip, default_clip_scenes


# ---------------------------------------------------------------------------
# Raw media files — session scope (generate once, reuse across tests)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def session_tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("mvd_tests")


@pytest.fixture(scope="session")
def click_track_120(session_tmp):
    """30-second WAV click track at 120 BPM."""
    path = str(session_tmp / "click_120.wav")
    return make_click_track(path, bpm=120.0, duration=30.0)


@pytest.fixture(scope="session")
def click_track_120_short(session_tmp):
    """12-second WAV click track at 120 BPM — sized to match edl_clip."""
    path = str(session_tmp / "click_120_short.wav")
    return make_click_track(path, bpm=120.0, duration=12.0)


@pytest.fixture(scope="session")
def click_track_95(session_tmp):
    """30-second WAV click track at 95 BPM — slower tempo for beat detection tests."""
    path = str(session_tmp / "click_95.wav")
    return make_click_track(path, bpm=95.0, duration=30.0)


@pytest.fixture(scope="session")
def color_clip_5scenes(session_tmp):
    """Video with 5 solid-color scenes (5s each = 25s total)."""
    path = str(session_tmp / "clip_5scenes.mp4")
    return make_color_clip(path, default_clip_scenes(5, 5.0))


@pytest.fixture(scope="session")
def edl_clip(session_tmp):
    """12-second video with 3 scenes (4s each) — matches click_track_120_short duration."""
    path = str(session_tmp / "edl_clip.mp4")
    return make_color_clip(path, [("blue", 4.0), ("red", 4.0), ("green", 4.0)])


# ---------------------------------------------------------------------------
# Analysis results — session scope (run analysis once, reuse)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def audio_analysis_120(session_tmp, click_track_120):
    """Audio analysis JSON for the 30s 120 BPM click track."""
    from mvd.audio import analyze
    out = str(session_tmp / "analysis_120.json")
    return analyze(click_track_120["path"], output_path=out, whisper_model=None)


@pytest.fixture(scope="session")
def audio_analysis_120_short(session_tmp, click_track_120_short):
    """Audio analysis JSON for the 12s 120 BPM click track."""
    from mvd.audio import analyze
    out = str(session_tmp / "analysis_120_short.json")
    return analyze(click_track_120_short["path"], output_path=out, whisper_model=None)


@pytest.fixture(scope="session")
def scene_analysis_5(session_tmp, color_clip_5scenes):
    """Scene analysis JSON for the 5-scene color clip."""
    from mvd.video import analyze_clip
    out = str(session_tmp / "scenes_5.json")
    kf_dir = str(session_tmp / "keyframes_5")
    return analyze_clip(
        color_clip_5scenes["path"],
        output_dir=kf_dir,
        output_json=out,
        threshold=27.0,
    )


# ---------------------------------------------------------------------------
# Minimal EDL for renderer tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def minimal_edl(session_tmp, click_track_120_short, edl_clip, audio_analysis_120_short):
    """
    A 3-cut EDL using the 12s synthetic click track and matching 12s color clip.
    Cuts are snapped to beats; source_in values are properly forward-ordered.
    """
    beats = audio_analysis_120_short["beats"]
    clip = edl_clip["path"]
    audio = click_track_120_short["path"]
    total_dur = audio_analysis_120_short["duration"]
    fps = 24.0
    early = 2 / fps  # 0.083s

    # Divide into 3 equal sections by beats: 0–⌊N/3⌋, ⌊N/3⌋–⌊2N/3⌋, ⌊2N/3⌋–end
    n_beats = len(beats)
    b0, b1, b2 = 0, n_beats // 3, 2 * n_beats // 3

    def snap(beat_idx):
        return round(float(beats[beat_idx]) - early, 3)

    # Timeline positions
    ts = [snap(b0), snap(b1), snap(b2), round(total_dur, 3)]

    # Source positions: each cut uses a contiguous slice of the clip
    # starting 0.3s in to avoid scene-open artifact.
    src_start = 0.3
    cuts = []
    for i in range(3):
        t_start = ts[i]
        t_end = ts[i + 1]
        dur = round(t_end - t_start, 3)
        si = round(src_start, 3)
        so = round(si + dur, 3)
        cuts.append({
            "n": i + 1,
            "timeline_start": t_start,
            "timeline_end": t_end,
            "source_file": clip,
            "source_in": si,
            "source_out": so,
            "section": ["intro", "verse", "outro"][i],
            "lyric": None,
            "description": f"Synthetic cut {i+1}",
            "rationale": f"test → cut {i+1}",
        })
        src_start = so  # next cut starts where this one ends

    edl = {
        "metadata": {
            "song_title": "Test Click Track Short",
            "artist": "synthetic",
            "bpm": audio_analysis_120_short["bpm"],
            "total_duration": total_dur,
            "total_cuts": 3,
            "avg_shot_length": round(total_dur / 3, 2),
            "emotional_arc": "test arc",
        },
        "audio_file": audio,
        "output_file": str(session_tmp / "output_minimal.mp4"),
        "cuts": cuts,
    }

    edl_path = str(session_tmp / "minimal_edl.json")
    with open(edl_path, "w") as f:
        json.dump(edl, f, indent=2)

    return {"path": edl_path, "edl": edl}
