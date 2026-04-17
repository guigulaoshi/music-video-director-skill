"""
EDL validation — the checklist from the skill's Technical Quick Reference.

Each check returns a list of error strings (empty = pass).
Call validate_edl() to run all checks at once.
"""

from typing import Optional


def check_beat_alignment(
    cuts: list,
    beats: list,
    fps: float = 24.0,
    tolerance_ms: float = 30.0,
    early_frames: int = 2,
) -> list:
    """
    Every beat-sync cut's timeline_start must be within tolerance_ms of
    some beats[i] - (early_frames / fps).

    Cuts with section == 'intro' at timeline_start == 0.0 are excluded
    (the very first cut may open before the first detected beat).
    """
    if not beats:
        return ["No beats provided — cannot check alignment"]

    import numpy as np
    beats_arr = np.array(beats)
    early = early_frames / fps
    errors = []

    for cut in cuts:
        ts = cut["timeline_start"]
        # Skip the absolute start of the video — often pre-beat
        if ts == 0.0:
            continue
        nearest = float(np.min(np.abs(beats_arr - early - ts)))
        if nearest * 1000 > tolerance_ms:
            errors.append(
                f"Cut #{cut['n']} timeline_start={ts:.3f}s is {nearest*1000:.1f}ms "
                f"from nearest beat-early position (tolerance={tolerance_ms}ms)"
            )
    return errors


def check_contiguity(cuts: list, tolerance_s: float = 0.002) -> list:
    """Every cut's timeline_start must equal the previous cut's timeline_end."""
    errors = []
    for i in range(1, len(cuts)):
        prev_end = cuts[i - 1]["timeline_end"]
        curr_start = cuts[i]["timeline_start"]
        gap = abs(curr_start - prev_end)
        if gap > tolerance_s:
            errors.append(
                f"Gap between cut #{cuts[i-1]['n']} (end={prev_end:.3f}) "
                f"and cut #{cuts[i]['n']} (start={curr_start:.3f}): {gap*1000:.1f}ms"
            )
    return errors


def check_source_ordering(cuts: list, tolerance_s: float = 0.001) -> list:
    """
    Within each source clip, source_in values must be non-decreasing
    (strictly greater, or equal for back-to-back cuts).
    """
    from collections import defaultdict
    high_water = defaultdict(float)
    errors = []

    for cut in cuts:
        src = cut["source_file"]
        si = cut["source_in"]
        hw = high_water[src]
        if hw > 0 and si < hw - tolerance_s:
            errors.append(
                f"Cut #{cut['n']}: {src!r} source_in={si:.3f} < "
                f"previous source_out={hw:.3f} (backward ordering)"
            )
        high_water[src] = max(hw, cut["source_out"])
    return errors


def check_source_validity(cuts: list, min_source_in: float = 0.0) -> list:
    """source_out > source_in for every cut; source_in >= min_source_in."""
    errors = []
    for cut in cuts:
        si, so = cut["source_in"], cut["source_out"]
        if so <= si:
            errors.append(
                f"Cut #{cut['n']}: source_out={so:.3f} <= source_in={si:.3f}"
            )
        if si < min_source_in:
            errors.append(
                f"Cut #{cut['n']}: source_in={si:.3f} < minimum {min_source_in:.3f}"
            )
    return errors


def check_coverage(cuts: list, audio_duration: float, tolerance_s: float = 0.5) -> list:
    """The last cut's timeline_end must be within tolerance of audio_duration."""
    if not cuts:
        return ["EDL has no cuts"]
    last_end = cuts[-1]["timeline_end"]
    gap = abs(last_end - audio_duration)
    if gap > tolerance_s:
        return [
            f"Last cut ends at {last_end:.3f}s but audio duration is {audio_duration:.3f}s "
            f"(gap={gap:.3f}s, tolerance={tolerance_s}s)"
        ]
    return []


def check_no_repeats(cuts: list) -> list:
    """No (source_file, source_in) pair should appear more than once."""
    seen = {}
    errors = []
    for cut in cuts:
        key = (cut["source_file"], round(cut["source_in"], 2))
        if key in seen:
            errors.append(
                f"Cut #{cut['n']} reuses source_in={cut['source_in']:.2f} from "
                f"cut #{seen[key]} in {cut['source_file']!r}"
            )
        seen[key] = cut["n"]
    return errors


def check_source_overlaps(cuts: list, tolerance_s: float = 0.001) -> list:
    """
    No two cuts from the same source file may have overlapping [source_in, source_out)
    ranges, regardless of their order in the EDL.

    Overlap means: A.source_in < B.source_out AND B.source_in < A.source_out
    (standard interval intersection test).

    This catches the case where the same footage appears twice with different
    EDL indices — producing duplicate frames visible to the viewer.
    """
    from collections import defaultdict
    import os

    # Group cuts by source file (use basename to be robust to path differences)
    by_source = defaultdict(list)
    for i, cut in enumerate(cuts):
        src = cut["source_file"]
        si = float(cut["source_in"])
        so = float(cut["source_out"])
        # Index is position in cuts list (0-based) or 'n' if present
        idx = cut.get("n", i + 1)
        by_source[src].append((idx, si, so))

    errors = []
    for src, intervals in by_source.items():
        name = os.path.basename(src)
        # Sort by source_in for O(n log n) sweep
        intervals.sort(key=lambda x: x[1])
        for j in range(len(intervals)):
            for k in range(j + 1, len(intervals)):
                idx_a, a_in, a_out = intervals[j]
                idx_b, b_in, b_out = intervals[k]
                # Once b_in >= a_out (with tolerance), no further overlap possible
                if b_in >= a_out - tolerance_s:
                    break
                overlap_start = max(a_in, b_in)
                overlap_end = min(a_out, b_out)
                overlap = overlap_end - overlap_start
                errors.append(
                    f"Overlap in {name!r}: cut #{idx_a} [{a_in:.3f}→{a_out:.3f}] "
                    f"overlaps cut #{idx_b} [{b_in:.3f}→{b_out:.3f}] "
                    f"by {overlap:.3f}s"
                )
    return errors


def validate_edl(
    edl: dict,
    beats: Optional[list] = None,
    audio_duration: Optional[float] = None,
    fps: float = 24.0,
    beat_tolerance_ms: float = 30.0,
    early_frames: int = 2,
) -> dict:
    """
    Run all EDL validation checks. Returns:
      {
        "passed": bool,
        "errors": {check_name: [error_str, ...]},
        "summary": "N checks passed, M failed"
      }

    beats and audio_duration are optional — if not supplied, those checks
    are skipped (useful when validating structure without audio analysis).
    """
    cuts = edl.get("cuts", [])
    meta = edl.get("metadata", {})

    if audio_duration is None:
        audio_duration = meta.get("total_duration")

    results = {}

    results["source_validity"] = check_source_validity(cuts)
    results["source_overlaps"] = check_source_overlaps(cuts)
    # contiguity and source_ordering require timeline_start/timeline_end fields
    # which are only present in full EDLs (not simple edit_plan.json format)
    if cuts and "timeline_start" in cuts[0]:
        results["contiguity"] = check_contiguity(cuts)
        results["source_ordering"] = check_source_ordering(cuts)
    results["no_repeats"] = check_no_repeats(cuts)

    if beats is not None:
        results["beat_alignment"] = check_beat_alignment(
            cuts, beats, fps=fps,
            tolerance_ms=beat_tolerance_ms,
            early_frames=early_frames,
        )

    if audio_duration is not None:
        results["coverage"] = check_coverage(cuts, audio_duration)

    all_errors = [e for errs in results.values() for e in errs]
    n_checks = len(results)
    n_failed = sum(1 for errs in results.values() if errs)

    return {
        "passed": len(all_errors) == 0,
        "errors": results,
        "summary": f"{n_checks - n_failed}/{n_checks} checks passed",
    }


def assert_valid_edl(edl: dict, beats: Optional[list] = None,
                     audio_duration: Optional[float] = None, **kwargs) -> None:
    """Raise AssertionError with a full report if validation fails."""
    result = validate_edl(edl, beats=beats, audio_duration=audio_duration, **kwargs)
    if not result["passed"]:
        lines = [f"EDL validation failed — {result['summary']}"]
        for check, errors in result["errors"].items():
            for e in errors:
                lines.append(f"  [{check}] {e}")
        raise AssertionError("\n".join(lines))
