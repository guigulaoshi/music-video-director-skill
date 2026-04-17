"""Audio analysis: beat detection, musical structure, lyrics transcription."""

import os
import sys
from typing import Optional

import numpy as np

from .utils import save_json


def analyze(
    audio_path: str,
    output_path: Optional[str] = None,
    whisper_model: str = "base",
) -> dict:
    """
    Full audio analysis pipeline.
    Returns structured dict with beats, sections, energy curve, and lyrics.
    """
    try:
        import librosa
    except ImportError:
        print("librosa not installed. Run: mvd install", file=sys.stderr)
        sys.exit(1)

    print(f"Loading audio: {audio_path}")
    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    duration = float(librosa.get_duration(y=y, sr=sr))
    print(f"  Duration: {duration:.1f}s")

    # Beat tracking — try madmom first (higher quality), fall back to librosa
    print("Detecting beats...")
    beat_times, bpm = _detect_beats(y, sr, audio_path)
    print(f"  BPM: {bpm:.1f}  Beats: {len(beat_times)}")

    # Downbeats — simplified: every 4th beat (4/4 time assumed)
    downbeat_times = beat_times[::4]

    # Energy curve (RMS at each beat)
    print("Computing energy curve...")
    hop = 512
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    energy_curve = []
    for i, bt in enumerate(beat_times):
        frame = int(librosa.time_to_frames(bt, sr=sr, hop_length=hop))
        frame = min(frame, len(rms) - 1)
        energy_curve.append({
            "time": round(bt, 3),
            "rms": round(float(rms[frame]), 4),
            "beat_index": i,
        })

    # Musical structure
    print("Detecting musical structure...")
    sections = _detect_sections(y, sr, beat_times, energy_curve, duration)
    print(f"  Sections: {' → '.join(s['type'] for s in sections)}")

    # Lyrics transcription — pass whisper_model=None to skip entirely
    if whisper_model is None:
        lyrics = []
        print("Skipping lyric transcription (whisper_model=None)")
    else:
        print("Transcribing lyrics (this may take a minute)...")
        lyrics = _transcribe(audio_path, whisper_model)
    if lyrics:
        print(f"  Found {len(lyrics)} lyric segments")
    else:
        print("  No lyrics detected (instrumental or transcription returned empty)")

    result = {
        "file": os.path.abspath(audio_path),
        "duration": round(duration, 3),
        "bpm": round(bpm, 2),
        "time_signature": 4,
        "beats": [round(t, 3) for t in beat_times],
        "downbeats": [round(t, 3) for t in downbeat_times],
        "sections": sections,
        "energy_curve": energy_curve,
        "lyrics": lyrics,
    }

    if output_path:
        save_json(result, output_path)
        print(f"Audio analysis saved: {output_path}")

    return result


def _detect_beats(y: np.ndarray, sr: int, audio_path: str) -> tuple:
    """
    Beat detection with quality tiers:
      1. madmom RNN+DBN (best — works well for non-Western music)
      2. librosa with percussive source separation (HPSS)
      3. librosa plain (last resort)

    Returns (beat_times_array, bpm_float).
    """
    import librosa

    # Tier 1: madmom
    try:
        import madmom  # noqa: F401
        beat_times, bpm = _beats_madmom(audio_path, sr)
        print("  (using madmom RNN beat tracker)")
        return beat_times, bpm
    except ImportError:
        pass
    except Exception as exc:
        print(f"  madmom failed ({exc}), falling back to librosa")

    # Tier 2: librosa + percussive separation (HPSS)
    # Isolate the percussive component so the beat tracker locks to rhythm,
    # not to melodic peaks — crucial for orchestral and other melody-heavy music.
    try:
        y_perc = librosa.effects.hpss(y)[1]  # [0]=harmonic, [1]=percussive
        tempo, beat_frames = librosa.beat.beat_track(
            y=y_perc, sr=sr, units="frames", hop_length=256, tightness=100
        )
        beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=256)
        bpm = float(np.atleast_1d(tempo)[0])
        print("  (using librosa+HPSS beat tracker)")
        if len(beat_times) > 0:
            return beat_times, bpm
    except Exception as exc:
        print(f"  HPSS beat tracking failed ({exc}), falling back to plain librosa")

    # Tier 3: plain librosa (original behaviour)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0])
    print("  (using librosa plain beat tracker)")
    return beat_times, bpm


def _beats_madmom(audio_path: str, sr: int) -> tuple:
    """
    Use madmom's RNN + DBN beat tracker.
    madmom processes files directly (doesn't accept pre-loaded arrays).
    """
    from madmom.features.beats import RNNBeatProcessor, BeatTrackingProcessor

    act = RNNBeatProcessor()(audio_path)
    proc = BeatTrackingProcessor(fps=100)
    beat_times = np.array(proc(act), dtype=float)

    if len(beat_times) < 2:
        raise ValueError("madmom returned fewer than 2 beats")

    intervals = np.diff(beat_times)
    bpm = 60.0 / float(np.median(intervals))
    return beat_times, bpm


def _detect_sections(y, sr, beat_times, energy_curve: list, duration: float) -> list:
    """
    Structural detection using spectral novelty (chroma + MFCC self-similarity)
    combined with energy to label sections.

    Falls back to pure energy heuristic if librosa operations fail.
    """
    try:
        return _detect_sections_novelty(y, sr, beat_times, energy_curve, duration)
    except Exception as exc:
        print(f"  Novelty section detection failed ({exc}), using energy heuristic")
        return _detect_sections_energy(beat_times, energy_curve, duration)


def _detect_sections_novelty(y, sr, beat_times, energy_curve: list, duration: float) -> list:
    """
    Section detection via spectral novelty + recurrence/self-similarity matrix.
    Finds structural boundaries where musical content changes significantly.
    """
    import librosa

    hop = 512
    # Chroma CQT + MFCC both contribute: chroma captures harmonic changes,
    # MFCC captures timbral changes (section transitions often involve both).
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop, bins_per_octave=36)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, hop_length=hop, n_mfcc=13)

    # Beat-synchronise features so boundaries align to beats
    if len(beat_times) > 1:
        beat_frames_sync = librosa.time_to_frames(beat_times, sr=sr, hop_length=hop)
        chroma_sync = librosa.util.sync(chroma, beat_frames_sync, aggregate=np.median)
        mfcc_sync = librosa.util.sync(mfcc, beat_frames_sync, aggregate=np.median)
    else:
        chroma_sync = chroma
        mfcc_sync = mfcc

    # Stack and normalise
    feat = np.vstack([
        librosa.util.normalize(chroma_sync, axis=0),
        librosa.util.normalize(mfcc_sync, axis=0),
    ])

    # Recurrence matrix → Laplacian segmentation
    R = librosa.segment.recurrence_matrix(
        feat, width=max(2, len(beat_times) // 20), mode="affinity", sym=True
    )
    # Spectral novelty from recurrence
    novelty = librosa.segment.recurrence_to_lag(R).mean(axis=0)
    # Peak detection to find boundaries
    peaks = _pick_novelty_peaks(novelty, min_gap_beats=8, duration=duration, beat_times=beat_times)

    # Build boundary timestamps from beat indices
    boundary_times = [0.0]
    for p in peaks:
        if p < len(beat_times):
            boundary_times.append(float(beat_times[p]))
    boundary_times.append(duration)
    boundary_times = sorted(set(round(t, 3) for t in boundary_times))

    # Label each segment using energy + position
    energies = [e["rms"] for e in energy_curve]
    med = float(np.median(energies))
    p75 = float(np.percentile(energies, 75))
    p25 = float(np.percentile(energies, 25))

    sections = []
    for i in range(len(boundary_times) - 1):
        t_start = boundary_times[i]
        t_end = boundary_times[i + 1]
        pos = t_start / duration

        # Mean energy in this window
        seg_energies = [
            e["rms"] for e in energy_curve
            if t_start <= e["time"] < t_end
        ]
        e_mean = float(np.mean(seg_energies)) if seg_energies else med

        label = _label_section(pos, e_mean, duration, med, p75, p25,
                               sections, boundary_times, i, energies, energy_curve)
        energy_level = "high" if e_mean >= p75 else ("low" if e_mean <= p25 else "medium")
        sections.append({
            "type": label,
            "start": round(t_start, 3),
            "end": round(t_end, 3),
            "energy_level": energy_level,
        })

    return sections if sections else _detect_sections_energy(beat_times, energy_curve, duration)


def _pick_novelty_peaks(novelty: np.ndarray, min_gap_beats: int, duration: float,
                        beat_times) -> list:
    """Pick local maxima in novelty curve with minimum gap constraint."""
    if len(novelty) < 3:
        return []

    n = len(novelty)
    # Smooth
    kernel = np.hanning(min(min_gap_beats, n))
    kernel /= kernel.sum()
    smoothed = np.convolve(novelty, kernel, mode="same")

    threshold = float(np.percentile(smoothed, 70))
    peaks = []
    for i in range(1, n - 1):
        if smoothed[i] > smoothed[i - 1] and smoothed[i] > smoothed[i + 1]:
            if smoothed[i] >= threshold:
                # Enforce minimum gap
                if not peaks or (i - peaks[-1]) >= min_gap_beats:
                    peaks.append(i)
    return peaks


def _label_section(pos, e_mean, duration, med, p75, p25,
                   sections, boundary_times, idx, energies, energy_curve) -> str:
    """Assign a section label based on energy level and song position."""
    n_segs = len(boundary_times) - 1

    if pos < 0.12 and e_mean <= med * 1.1:
        return "intro"
    if pos > 0.88 and e_mean < med * 1.2:
        return "outro"
    if e_mean >= p75:
        return "chorus"
    if e_mean <= p25 and 0.15 < pos < 0.85:
        return "bridge"
    # Pre-chorus: medium energy followed by a higher-energy segment
    if idx + 1 < n_segs:
        t_next_start = boundary_times[idx + 1]
        t_next_end = boundary_times[idx + 2] if idx + 2 < len(boundary_times) else duration
        next_energies = [
            e["rms"] for e in energy_curve
            if t_next_start <= e["time"] < t_next_end
        ]
        if next_energies and float(np.mean(next_energies)) >= p75:
            return "pre-chorus"
    return "verse"


def _detect_sections_energy(beat_times, energy_curve: list, duration: float) -> list:
    """
    Fallback: pure energy heuristic (original implementation).
    """
    if not beat_times or not energy_curve:
        return [{"type": "unknown", "start": 0.0, "end": round(duration, 3), "energy_level": "medium"}]

    energies = [e["rms"] for e in energy_curve]
    med = float(np.median(energies))
    p75 = float(np.percentile(energies, 75))
    p25 = float(np.percentile(energies, 25))

    beat_times = list(beat_times)
    window_beats = 16
    n_windows = max(1, len(beat_times) // window_beats)
    windows = []
    for i in range(n_windows):
        b0 = i * window_beats
        b1 = min((i + 1) * window_beats, len(beat_times))
        e_vals = [energies[b] for b in range(b0, b1) if b < len(energies)]
        windows.append({
            "start": beat_times[b0],
            "end": beat_times[min(b1, len(beat_times) - 1)],
            "energy": float(np.mean(e_vals)) if e_vals else med,
            "index": i,
        })

    leftover_start = n_windows * window_beats
    if leftover_start < len(beat_times):
        e_vals = [energies[b] for b in range(leftover_start, len(beat_times)) if b < len(energies)]
        if e_vals:
            windows.append({
                "start": beat_times[leftover_start],
                "end": duration,
                "energy": float(np.mean(e_vals)),
                "index": n_windows,
            })

    if not windows:
        return [{"type": "verse", "start": 0.0, "end": round(duration, 3), "energy_level": "medium"}]

    n = len(windows)
    labeled = []
    for i, w in enumerate(windows):
        pos = w["start"] / duration
        e = w["energy"]
        if pos < 0.12 and e <= med:
            label = "intro"
        elif pos > 0.88 and e < med * 1.15:
            label = "outro"
        elif e >= p75:
            label = "chorus"
        elif e <= p25 and 0.15 < pos < 0.85:
            label = "bridge"
        elif e >= med * 0.75 and e < p75:
            next_e = windows[i + 1]["energy"] if i + 1 < n else 0
            label = "pre-chorus" if next_e >= p75 else "verse"
        else:
            label = "verse"

        energy_level = "high" if e >= p75 else ("low" if e <= p25 else "medium")
        labeled.append({"type": label, "start": w["start"], "energy_level": energy_level})

    merged = []
    for item in labeled:
        if merged and merged[-1]["type"] == item["type"]:
            continue
        if merged:
            merged[-1]["end"] = round(item["start"], 3)
        merged.append({
            "type": item["type"],
            "start": round(item["start"], 3),
            "energy_level": item["energy_level"],
        })
    if merged:
        merged[-1]["end"] = round(duration, 3)
        merged[0]["start"] = 0.0

    return merged


def _transcribe(audio_path: str, model_size: str = "base") -> list:
    """Transcribe with Whisper. Returns [] if not installed or fails."""
    try:
        import whisper
    except ImportError:
        print("  (whisper not installed — skipping transcription)")
        return []

    try:
        print(f"  Loading Whisper '{model_size}' model...")
        model = whisper.load_model(model_size)
        result = model.transcribe(audio_path, verbose=False)
        segments = []
        for seg in result.get("segments", []):
            text = seg["text"].strip()
            if text:
                segments.append({
                    "start": round(float(seg["start"]), 3),
                    "end": round(float(seg["end"]), 3),
                    "text": text,
                })
        return segments
    except Exception as exc:
        print(f"  Transcription failed: {exc}")
        return []
