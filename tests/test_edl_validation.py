"""Tests for mvd/validate.py — EDL validation logic."""

import copy
import pytest
from mvd.validate import (
    check_beat_alignment,
    check_contiguity,
    check_source_ordering,
    check_source_validity,
    check_coverage,
    check_no_repeats,
    validate_edl,
    assert_valid_edl,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cut(n, ts, te, src="/fake/clip.mp4", si=1.0, so=None):
    so = so if so is not None else si + (te - ts)
    return {
        "n": n,
        "timeline_start": ts,
        "timeline_end": te,
        "source_file": src,
        "source_in": si,
        "source_out": so,
        "section": "verse",
        "lyric": None,
        "description": "test",
        "rationale": "test",
    }


def _minimal_edl(cuts, audio_duration=10.0):
    return {
        "metadata": {"total_duration": audio_duration, "bpm": 120.0},
        "audio_file": "/fake/audio.mp3",
        "output_file": "/fake/output.mp4",
        "cuts": cuts,
    }


# ---------------------------------------------------------------------------
# Beat alignment
# ---------------------------------------------------------------------------

class TestBeatAlignment:
    def test_perfect_snap_passes(self):
        # beats at 0.5, 1.0, 1.5 ... (120 BPM), early=0.083
        beats = [0.5 * i for i in range(1, 21)]
        early = 2 / 24
        cuts = [
            _make_cut(1, ts=round(beats[0] - early, 3), te=round(beats[4] - early, 3)),
            _make_cut(2, ts=round(beats[4] - early, 3), te=round(beats[8] - early, 3)),
        ]
        errors = check_beat_alignment(cuts, beats)
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_large_offset_fails(self):
        beats = [0.5 * i for i in range(1, 21)]
        early = 2 / 24
        # Cut deliberately placed 200ms after beat position
        cuts = [_make_cut(1, ts=round(beats[0] - early + 0.200, 3), te=2.0)]
        errors = check_beat_alignment(cuts, beats, tolerance_ms=30.0)
        assert errors, "Expected beat alignment error for 200ms offset"

    def test_timeline_start_zero_is_exempt(self):
        beats = [1.0, 2.0, 3.0]
        cuts = [_make_cut(1, ts=0.0, te=0.917)]  # starts before first beat
        errors = check_beat_alignment(cuts, beats)
        assert errors == [], "timeline_start=0.0 should be exempt from beat alignment"

    def test_off_beat_cut_fails(self):
        """A cut landing between beats (not on any beat) should fail."""
        beats = [0.5 * i for i in range(1, 21)]
        early = 2 / 24
        # Place cut 150ms past a beat-early position — well between two beats
        off_beat_ts = round(beats[2] - early + 0.150, 3)
        cuts = [_make_cut(1, ts=off_beat_ts, te=3.0)]
        errors = check_beat_alignment(cuts, beats, tolerance_ms=30.0)
        assert errors, f"Off-beat cut at {off_beat_ts}s should fail alignment check"

    def test_one_beat_syncopation_passes(self):
        """
        A cut shifted by exactly one full beat lands on the next beat —
        it is beat-aligned, just at a different beat than originally intended.
        The validator correctly allows this.
        """
        beats = [0.5 * i for i in range(1, 21)]
        early = 2 / 24
        # Shift by exactly one beat interval (0.5s at 120 BPM)
        cut_at_next_beat = round(beats[3] - early, 3)  # same as beats[2] - early + 0.5
        cuts = [_make_cut(1, ts=cut_at_next_beat, te=3.0)]
        errors = check_beat_alignment(cuts, beats, tolerance_ms=30.0)
        assert errors == [], "A cut landing exactly on a different beat should pass"

    def test_beat_snapped_edl_passes_alignment(self, minimal_edl, audio_analysis_120_short):
        """An EDL whose cuts are snapped to the beat grid must pass alignment."""
        errors = check_beat_alignment(
            minimal_edl["edl"]["cuts"],
            audio_analysis_120_short["beats"],
        )
        assert errors == [], "Beat-snapped EDL failed alignment:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# Contiguity
# ---------------------------------------------------------------------------

class TestContiguity:
    def test_contiguous_passes(self):
        cuts = [
            _make_cut(1, ts=0.0, te=2.0),
            _make_cut(2, ts=2.0, te=5.0),
            _make_cut(3, ts=5.0, te=8.0),
        ]
        assert check_contiguity(cuts) == []

    def test_gap_fails(self):
        cuts = [
            _make_cut(1, ts=0.0, te=2.0),
            _make_cut(2, ts=2.5, te=5.0),  # 500ms gap
        ]
        errors = check_contiguity(cuts)
        assert errors, "Gap between cuts should produce an error"
        assert "2" in errors[0]  # mentions the offending cut number

    def test_overlap_fails(self):
        cuts = [
            _make_cut(1, ts=0.0, te=3.0),
            _make_cut(2, ts=2.5, te=5.0),  # 500ms overlap
        ]
        errors = check_contiguity(cuts)
        assert errors, "Overlap between cuts should produce an error"

    def test_single_cut_passes(self):
        cuts = [_make_cut(1, ts=0.0, te=5.0)]
        assert check_contiguity(cuts) == []


# ---------------------------------------------------------------------------
# Source ordering
# ---------------------------------------------------------------------------

class TestSourceOrdering:
    def test_forward_ordering_passes(self):
        cuts = [
            _make_cut(1, ts=0.0, te=2.0, si=1.0, so=3.0),
            _make_cut(2, ts=2.0, te=4.0, si=3.0, so=5.0),
            _make_cut(3, ts=4.0, te=6.0, si=5.0, so=7.0),
        ]
        assert check_source_ordering(cuts) == []

    def test_backward_ordering_fails(self):
        cuts = [
            _make_cut(1, ts=0.0, te=2.0, si=5.0, so=7.0),
            _make_cut(2, ts=2.0, te=4.0, si=3.0, so=5.0),  # goes backward
        ]
        errors = check_source_ordering(cuts)
        assert errors, "Backward source ordering should fail"

    def test_equal_source_in_is_ok(self):
        """Back-to-back cuts (source_out[n] == source_in[n+1]) should pass."""
        cuts = [
            _make_cut(1, ts=0.0, te=2.0, si=1.0, so=3.0),
            _make_cut(2, ts=2.0, te=4.0, si=3.0, so=5.0),  # exactly at hw
        ]
        assert check_source_ordering(cuts) == []

    def test_different_clips_are_independent(self):
        """Backward ordering in clip2 should not affect clip1's high-water mark."""
        cuts = [
            _make_cut(1, ts=0.0, te=2.0, src="/a.mp4", si=5.0, so=7.0),
            _make_cut(2, ts=2.0, te=4.0, src="/b.mp4", si=1.0, so=3.0),  # diff clip, lower si = fine
            _make_cut(3, ts=4.0, te=6.0, src="/a.mp4", si=7.0, so=9.0),  # a.mp4 continues forward
        ]
        assert check_source_ordering(cuts) == []


# ---------------------------------------------------------------------------
# Source validity
# ---------------------------------------------------------------------------

class TestSourceValidity:
    def test_valid_passes(self):
        cuts = [_make_cut(1, ts=0.0, te=2.0, si=0.5, so=2.5)]
        assert check_source_validity(cuts) == []

    def test_source_out_lte_source_in_fails(self):
        cuts = [_make_cut(1, ts=0.0, te=2.0, si=3.0, so=2.0)]
        errors = check_source_validity(cuts)
        assert errors

    def test_negative_source_in_fails(self):
        cuts = [_make_cut(1, ts=0.0, te=2.0, si=-0.5, so=1.5)]
        errors = check_source_validity(cuts, min_source_in=0.0)
        assert errors


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------

class TestCoverage:
    def test_exact_coverage_passes(self):
        cuts = [_make_cut(1, ts=0.0, te=30.0)]
        assert check_coverage(cuts, audio_duration=30.0) == []

    def test_within_tolerance_passes(self):
        cuts = [_make_cut(1, ts=0.0, te=29.8)]
        assert check_coverage(cuts, audio_duration=30.0, tolerance_s=0.5) == []

    def test_large_gap_fails(self):
        cuts = [_make_cut(1, ts=0.0, te=25.0)]
        errors = check_coverage(cuts, audio_duration=30.0)
        assert errors

    def test_empty_cuts_fails(self):
        errors = check_coverage([], audio_duration=30.0)
        assert errors


# ---------------------------------------------------------------------------
# No repeats
# ---------------------------------------------------------------------------

class TestNoRepeats:
    def test_unique_cuts_pass(self):
        cuts = [
            _make_cut(1, ts=0.0, te=2.0, si=1.0),
            _make_cut(2, ts=2.0, te=4.0, si=3.0),
        ]
        assert check_no_repeats(cuts) == []

    def test_repeated_source_in_fails(self):
        cuts = [
            _make_cut(1, ts=0.0, te=2.0, si=1.0),
            _make_cut(2, ts=2.0, te=4.0, si=1.0),  # same source_in
        ]
        errors = check_no_repeats(cuts)
        assert errors

    def test_same_source_in_different_clips_passes(self):
        cuts = [
            _make_cut(1, ts=0.0, te=2.0, src="/a.mp4", si=1.0),
            _make_cut(2, ts=2.0, te=4.0, src="/b.mp4", si=1.0),  # diff clip, same offset = fine
        ]
        assert check_no_repeats(cuts) == []


# ---------------------------------------------------------------------------
# validate_edl integration
# ---------------------------------------------------------------------------

class TestValidateEdl:
    def test_clean_edl_passes(self, minimal_edl, audio_analysis_120_short):
        result = validate_edl(
            minimal_edl["edl"],
            beats=audio_analysis_120_short["beats"],
            audio_duration=audio_analysis_120_short["duration"],
        )
        assert result["passed"], (
            f"Clean minimal EDL failed validation:\n"
            + "\n".join(
                f"  [{k}] {e}"
                for k, errs in result["errors"].items()
                for e in errs
            )
        )

    def test_assert_valid_edl_passes_on_clean(self, minimal_edl, audio_analysis_120_short):
        assert_valid_edl(
            minimal_edl["edl"],
            beats=audio_analysis_120_short["beats"],
            audio_duration=audio_analysis_120_short["duration"],
        )

    def test_assert_valid_edl_raises_on_broken(self, minimal_edl, audio_analysis_120_short):
        broken = copy.deepcopy(minimal_edl["edl"])
        # Introduce a gap
        broken["cuts"][1]["timeline_start"] += 0.5
        with pytest.raises(AssertionError, match="contiguity"):
            assert_valid_edl(
                broken,
                beats=audio_analysis_120_short["beats"],
                audio_duration=audio_analysis_120_short["duration"],
            )

    def test_without_beats_skips_beat_check(self, minimal_edl):
        result = validate_edl(minimal_edl["edl"])  # no beats kwarg
        assert "beat_alignment" not in result["errors"]

    def test_summary_format(self, minimal_edl, audio_analysis_120_short):
        result = validate_edl(
            minimal_edl["edl"],
            beats=audio_analysis_120_short["beats"],
            audio_duration=audio_analysis_120_short["duration"],
        )
        assert "/" in result["summary"]
        assert "passed" in result["summary"]
