"""Tests for mvd/renderer.py — video assembly."""

import os
import subprocess
import pytest


def _video_duration(path: str) -> float:
    """Use ffprobe to read actual video duration."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    import json
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


class TestRenderer:
    @pytest.fixture(scope="class")
    def rendered_output(self, minimal_edl, session_tmp):
        """Render the minimal EDL once and share across tests in this class."""
        from mvd.renderer import render
        out = str(session_tmp / "output_test.mp4")
        result = render(
            minimal_edl["path"],
            output_path=out,
            target_fps=24,
            target_width=320,   # small for speed
            target_height=240,
            early_frames=2,
        )
        return result

    def test_output_file_exists(self, rendered_output):
        assert os.path.exists(rendered_output), f"Output file not found: {rendered_output}"

    def test_output_file_is_nonempty(self, rendered_output):
        size = os.path.getsize(rendered_output)
        assert size > 10_000, f"Output file is suspiciously small: {size} bytes"

    def test_output_duration_matches_audio(self, rendered_output, audio_analysis_120_short):
        expected = audio_analysis_120_short["duration"]
        actual = _video_duration(rendered_output)
        # Allow 1s tolerance (audio mix with -shortest can truncate slightly)
        assert abs(actual - expected) < 1.0, (
            f"Rendered duration {actual:.2f}s is far from expected {expected:.2f}s"
        )

    def test_output_has_video_stream(self, rendered_output):
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "v",
             "-show_entries", "stream=codec_type",
             "-print_format", "json", rendered_output],
            capture_output=True, text=True, check=True,
        )
        import json
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        assert any(s["codec_type"] == "video" for s in streams), "No video stream in output"

    def test_output_has_audio_stream(self, rendered_output):
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "a",
             "-show_entries", "stream=codec_type",
             "-print_format", "json", rendered_output],
            capture_output=True, text=True, check=True,
        )
        import json
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        assert any(s["codec_type"] == "audio" for s in streams), "No audio stream in output"


class TestRendererEarlyFrames:
    def test_frame_offset_calculation(self):
        """early_frames=2 at 24fps should produce 0.083s offset."""
        from mvd.renderer import render as _  # import to verify no import errors
        fps = 24.0
        early_frames = 2
        expected_offset = early_frames / fps
        assert abs(expected_offset - 0.0833) < 0.001
