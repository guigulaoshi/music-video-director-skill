"""Tests for mvd/video.py — scene detection and keyframe extraction."""

import os
import pytest


# ---------------------------------------------------------------------------
# Scene detection
# ---------------------------------------------------------------------------

class TestSceneDetection:
    def test_detects_approximate_scene_count(self, scene_analysis_5, color_clip_5scenes):
        """
        Should detect close to the ground-truth 5 scenes.
        We allow ±2 because scene detection threshold can split or merge
        at clip boundaries depending on encoding.
        """
        gt_count = len(color_clip_5scenes["scenes"])
        detected = len(scene_analysis_5["scenes"])
        assert abs(detected - gt_count) <= 2, (
            f"Detected {detected} scenes but expected ~{gt_count}"
        )

    def test_scenes_span_full_duration(self, scene_analysis_5, color_clip_5scenes):
        scenes = scene_analysis_5["scenes"]
        assert scenes[0]["start_time"] == 0.0, "First scene must start at 0.0"
        last_end = scenes[-1]["end_time"]
        total = color_clip_5scenes["total_duration"]
        assert abs(last_end - total) < 0.5, (
            f"Scenes end at {last_end:.2f}s but clip is {total:.2f}s"
        )

    def test_scenes_are_contiguous(self, scene_analysis_5):
        scenes = scene_analysis_5["scenes"]
        for i in range(1, len(scenes)):
            gap = abs(scenes[i]["start_time"] - scenes[i - 1]["end_time"])
            assert gap < 0.1, (
                f"Gap of {gap:.3f}s between scene {i-1} and scene {i}"
            )

    def test_each_scene_has_positive_duration(self, scene_analysis_5):
        for s in scene_analysis_5["scenes"]:
            assert s["duration"] > 0, f"Scene {s['index']} has non-positive duration"

    def test_scene_indices_are_sequential(self, scene_analysis_5):
        indices = [s["index"] for s in scene_analysis_5["scenes"]]
        assert indices == list(range(len(indices))), "Scene indices are not sequential"


# ---------------------------------------------------------------------------
# Keyframe extraction
# ---------------------------------------------------------------------------

class TestKeyframeExtraction:
    def test_every_scene_has_keyframe_path(self, scene_analysis_5):
        for s in scene_analysis_5["scenes"]:
            assert "keyframe_path" in s, f"Scene {s['index']} missing keyframe_path"

    def test_keyframe_files_exist(self, scene_analysis_5):
        missing = []
        for s in scene_analysis_5["scenes"]:
            kf = s.get("keyframe_path")
            if kf and not os.path.exists(kf):
                missing.append(kf)
        assert not missing, f"Missing keyframe files: {missing}"

    def test_keyframe_files_are_nonempty(self, scene_analysis_5):
        for s in scene_analysis_5["scenes"]:
            kf = s.get("keyframe_path")
            if kf and os.path.exists(kf):
                size = os.path.getsize(kf)
                assert size > 1000, f"Keyframe {kf} is suspiciously small ({size} bytes)"

    def test_keyframe_files_are_jpeg(self, scene_analysis_5):
        for s in scene_analysis_5["scenes"]:
            kf = s.get("keyframe_path")
            if kf and os.path.exists(kf):
                with open(kf, "rb") as f:
                    header = f.read(3)
                # JPEG magic bytes: FF D8 FF
                assert header == b"\xff\xd8\xff", (
                    f"Keyframe {kf} is not a valid JPEG (got {header.hex()})"
                )


# ---------------------------------------------------------------------------
# Output JSON schema
# ---------------------------------------------------------------------------

class TestVideoOutputSchema:
    REQUIRED_KEYS = {"file", "duration", "fps", "width", "height", "resolution", "scenes"}

    def test_required_keys_present(self, scene_analysis_5):
        missing = self.REQUIRED_KEYS - set(scene_analysis_5.keys())
        assert not missing, f"Missing keys in video analysis output: {missing}"

    def test_duration_is_positive(self, scene_analysis_5):
        assert scene_analysis_5["duration"] > 0

    def test_fps_is_reasonable(self, scene_analysis_5):
        fps = scene_analysis_5["fps"]
        assert 1 < fps < 200, f"FPS {fps} is outside reasonable range"

    def test_resolution_format(self, scene_analysis_5):
        res = scene_analysis_5["resolution"]
        assert "x" in res, f"Resolution {res!r} not in WxH format"
        w, h = res.split("x")
        assert int(w) > 0 and int(h) > 0

    def test_scene_required_fields(self, scene_analysis_5):
        required = {"index", "start_time", "end_time", "duration"}
        for s in scene_analysis_5["scenes"]:
            missing = required - set(s.keys())
            assert not missing, f"Scene {s.get('index')} missing fields: {missing}"
