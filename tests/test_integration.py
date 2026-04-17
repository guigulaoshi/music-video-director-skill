"""
Integration test: full pipeline with synthetic fixtures.

analyze-audio → detect-scenes → build EDL → render → validate output

This is the regression test that catches any breaking change across the
entire pipeline in a single run. It uses small synthetic media so it
stays fast enough to run on every change (~60-90s total).
"""

import json
import os

import numpy as np
import pytest

from mvd.audio import analyze as analyze_audio
from mvd.video import analyze_clip
from mvd.renderer import render
from mvd.validate import assert_valid_edl

from .fixtures import make_click_track, make_color_clip


@pytest.fixture(scope="module")
def pipeline_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("pipeline")


@pytest.fixture(scope="module")
def pipeline_audio(pipeline_dir):
    path = str(pipeline_dir / "audio.wav")
    return make_click_track(path, bpm=120.0, duration=20.0)


@pytest.fixture(scope="module")
def pipeline_clip(pipeline_dir):
    path = str(pipeline_dir / "clip.mp4")
    scenes = [
        ("blue",   4.0),
        ("red",    4.0),
        ("green",  4.0),
        ("yellow", 4.0),
        ("purple", 4.0),
    ]
    return make_color_clip(path, scenes, fps=24, width=320, height=240)


@pytest.fixture(scope="module")
def pipeline_analysis(pipeline_dir, pipeline_audio, pipeline_clip):
    audio_json = str(pipeline_dir / "audio_analysis.json")
    scenes_json = str(pipeline_dir / "scenes.json")
    kf_dir = str(pipeline_dir / "keyframes")

    audio_result = analyze_audio(
        pipeline_audio["path"],
        output_path=audio_json,
        whisper_model=None,
    )
    clip_result = analyze_clip(
        pipeline_clip["path"],
        output_dir=kf_dir,
        output_json=scenes_json,
        threshold=27.0,
    )
    return {"audio": audio_result, "clip": clip_result}


@pytest.fixture(scope="module")
def pipeline_edl(pipeline_dir, pipeline_analysis, pipeline_audio, pipeline_clip):
    """Build a beat-snapped EDL from the pipeline analysis results."""
    audio = pipeline_analysis["audio"]
    beats = np.array(audio["beats"])
    total_dur = audio["duration"]
    clip_path = pipeline_clip["path"]
    audio_path = pipeline_audio["path"]
    fps = 24.0
    early = 2 / fps  # 0.083s

    # Assign cuts: one per 8 beats, stepping through the clip
    beat_interval = float(np.median(np.diff(beats)))
    beats_per_cut = 8
    cut_dur = beats_per_cut * beat_interval

    cuts = []
    n = 1
    clip_hw = 0.3  # high-water mark for source clip

    beat_idx = 0
    while beat_idx + beats_per_cut < len(beats):
        ts = round(float(beats[beat_idx]) - early, 3)
        te_beat_idx = min(beat_idx + beats_per_cut, len(beats) - 1)
        te = round(float(beats[te_beat_idx]) - early, 3)

        # Last cut extends to audio end
        if beat_idx + 2 * beats_per_cut >= len(beats):
            te = round(total_dur, 3)

        si = clip_hw
        so = round(si + (te - ts), 3)

        # Don't exceed clip duration
        clip_dur = pipeline_clip["total_duration"]
        if so > clip_dur - 0.2:
            break

        cuts.append({
            "n": n,
            "timeline_start": ts,
            "timeline_end": te,
            "source_file": clip_path,
            "source_in": si,
            "source_out": so,
            "section": "verse",
            "lyric": None,
            "description": f"Synthetic cut {n}",
            "rationale": f"test cut {n} → synthetic",
        })

        clip_hw = so
        beat_idx += beats_per_cut
        n += 1

        if te >= total_dur:
            break

    # Ensure last cut reaches total_dur
    if cuts and cuts[-1]["timeline_end"] < total_dur - 0.01:
        cuts[-1]["timeline_end"] = round(total_dur, 3)
        dur = cuts[-1]["timeline_end"] - cuts[-1]["timeline_start"]
        cuts[-1]["source_out"] = round(cuts[-1]["source_in"] + dur, 3)

    edl = {
        "metadata": {
            "song_title": "Integration Test",
            "artist": "synthetic",
            "bpm": audio["bpm"],
            "total_duration": total_dur,
            "total_cuts": len(cuts),
            "avg_shot_length": total_dur / max(len(cuts), 1),
            "emotional_arc": "test arc",
        },
        "audio_file": audio_path,
        "output_file": str(pipeline_dir / "output.mp4"),
        "cuts": cuts,
    }

    edl_path = str(pipeline_dir / "edit_plan.json")
    with open(edl_path, "w") as f:
        json.dump(edl, f, indent=2)

    return {"path": edl_path, "edl": edl}


class TestFullPipeline:
    def test_audio_analysis_produced_results(self, pipeline_analysis):
        audio = pipeline_analysis["audio"]
        assert audio["bpm"] > 0
        assert len(audio["beats"]) > 10
        assert audio["duration"] > 0

    def test_scene_detection_found_scenes(self, pipeline_analysis):
        clip = pipeline_analysis["clip"]
        assert len(clip["scenes"]) >= 3, "Expected at least 3 detected scenes"

    def test_keyframes_were_extracted(self, pipeline_analysis):
        for s in pipeline_analysis["clip"]["scenes"]:
            kf = s.get("keyframe_path", "")
            assert os.path.exists(kf), f"Keyframe not found: {kf}"

    def test_edl_has_cuts(self, pipeline_edl):
        assert len(pipeline_edl["edl"]["cuts"]) > 0

    def test_edl_passes_validation(self, pipeline_edl, pipeline_analysis):
        assert_valid_edl(
            pipeline_edl["edl"],
            beats=pipeline_analysis["audio"]["beats"],
            audio_duration=pipeline_analysis["audio"]["duration"],
        )

    def test_render_produces_output(self, pipeline_edl, pipeline_dir):
        output = str(pipeline_dir / "output.mp4")
        result = render(
            pipeline_edl["path"],
            output_path=output,
            target_fps=24,
            target_width=320,
            target_height=240,
            early_frames=2,
        )
        assert os.path.exists(result), f"Rendered file not found: {result}"
        assert os.path.getsize(result) > 10_000

    def test_render_output_duration(self, pipeline_edl, pipeline_dir, pipeline_analysis):
        """Rendered video duration should be within 1s of audio duration."""
        import subprocess
        output = str(pipeline_dir / "output.mp4")
        if not os.path.exists(output):
            pytest.skip("Render output not found — run test_render_produces_output first")

        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", output],
            capture_output=True, text=True,
        )
        info = json.loads(r.stdout)
        actual = float(info["format"]["duration"])
        expected = pipeline_analysis["audio"]["duration"]
        assert abs(actual - expected) < 1.0, (
            f"Output duration {actual:.2f}s differs from audio {expected:.2f}s by more than 1s"
        )
