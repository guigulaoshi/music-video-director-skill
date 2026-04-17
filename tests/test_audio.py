"""Tests for mvd/audio.py — beat detection and section detection."""

import pytest
import numpy as np


# ---------------------------------------------------------------------------
# Beat detection
# ---------------------------------------------------------------------------

class TestBeatDetection:
    def test_bpm_within_5pct(self, audio_analysis_120, click_track_120):
        """Detected BPM should be within 5% of the true 120 BPM."""
        detected = audio_analysis_120["bpm"]
        expected = click_track_120["bpm"]
        assert abs(detected - expected) / expected < 0.05, (
            f"BPM {detected:.1f} is more than 5% off from expected {expected}"
        )

    def test_beat_count_within_10pct(self, audio_analysis_120, click_track_120):
        """Detected beat count should be within 10% of true count."""
        detected = len(audio_analysis_120["beats"])
        expected = len(click_track_120["beat_times"])
        assert abs(detected - expected) / expected < 0.10, (
            f"Beat count {detected} is more than 10% off from expected {expected}"
        )

    def test_beat_precision(self, audio_analysis_120, click_track_120):
        """
        For each detected beat, the nearest ground-truth click should be
        within 50ms. We check the median error (not max, to allow for
        occasional boundary effects at start/end of audio).
        """
        detected = np.array(audio_analysis_120["beats"])
        ground_truth = np.array(click_track_120["beat_times"])

        errors_ms = []
        for bt in detected:
            nearest = float(np.min(np.abs(ground_truth - bt)))
            errors_ms.append(nearest * 1000)

        median_error = float(np.median(errors_ms))
        assert median_error < 50.0, (
            f"Median beat position error {median_error:.1f}ms exceeds 50ms threshold"
        )

    def test_first_beat_not_before_zero(self, audio_analysis_120):
        """No beat should have a negative timestamp."""
        assert all(b >= 0 for b in audio_analysis_120["beats"])

    def test_beats_are_sorted(self, audio_analysis_120):
        beats = audio_analysis_120["beats"]
        assert beats == sorted(beats), "Beats are not in ascending order"

    def test_beat_intervals_are_regular(self, audio_analysis_120):
        """
        For a clean click track, beat intervals should be very regular.
        Stdev / mean < 10% is a reasonable regularity threshold.
        """
        beats = np.array(audio_analysis_120["beats"])
        intervals = np.diff(beats)
        cv = np.std(intervals) / np.mean(intervals)  # coefficient of variation
        assert cv < 0.10, (
            f"Beat interval coefficient of variation {cv:.3f} exceeds 0.10 "
            f"(mean={np.mean(intervals)*1000:.1f}ms, std={np.std(intervals)*1000:.1f}ms)"
        )


# ---------------------------------------------------------------------------
# Output JSON schema
# ---------------------------------------------------------------------------

class TestAudioOutputSchema:
    REQUIRED_KEYS = {"file", "duration", "bpm", "beats", "downbeats",
                     "sections", "energy_curve", "lyrics", "time_signature"}

    def test_required_keys_present(self, audio_analysis_120):
        missing = self.REQUIRED_KEYS - set(audio_analysis_120.keys())
        assert not missing, f"Missing keys in audio analysis output: {missing}"

    def test_duration_matches_file(self, audio_analysis_120, click_track_120):
        assert abs(audio_analysis_120["duration"] - click_track_120["duration"]) < 0.1

    def test_energy_curve_aligned_to_beats(self, audio_analysis_120):
        """energy_curve should have one entry per beat."""
        n_beats = len(audio_analysis_120["beats"])
        n_energy = len(audio_analysis_120["energy_curve"])
        assert n_beats == n_energy, (
            f"energy_curve has {n_energy} entries but beats has {n_beats}"
        )

    def test_energy_curve_timestamps_match_beats(self, audio_analysis_120):
        for ec, bt in zip(audio_analysis_120["energy_curve"], audio_analysis_120["beats"]):
            assert abs(ec["time"] - bt) < 0.001, (
                f"energy_curve time {ec['time']} doesn't match beat {bt}"
            )

    def test_sections_cover_full_duration(self, audio_analysis_120):
        sections = audio_analysis_120["sections"]
        assert sections[0]["start"] == 0.0, "First section doesn't start at 0"
        last_end = sections[-1]["end"]
        total = audio_analysis_120["duration"]
        assert abs(last_end - total) < 0.5, (
            f"Sections end at {last_end:.2f}s but duration is {total:.2f}s"
        )

    def test_sections_are_contiguous(self, audio_analysis_120):
        sections = audio_analysis_120["sections"]
        for i in range(1, len(sections)):
            prev_end = sections[i - 1]["end"]
            curr_start = sections[i]["start"]
            assert abs(prev_end - curr_start) < 0.01, (
                f"Gap between section {i-1} (end={prev_end}) and section {i} (start={curr_start})"
            )

    def test_section_types_are_valid(self, audio_analysis_120):
        valid = {"intro", "verse", "pre-chorus", "chorus", "bridge", "outro", "unknown"}
        for s in audio_analysis_120["sections"]:
            assert s["type"] in valid, f"Unknown section type: {s['type']!r}"

    def test_bpm_is_positive(self, audio_analysis_120):
        assert audio_analysis_120["bpm"] > 0

    def test_lyrics_is_list(self, audio_analysis_120):
        assert isinstance(audio_analysis_120["lyrics"], list)
