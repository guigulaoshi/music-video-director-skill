"""CLI entry point for the mvd toolkit."""

import json
import os
import sys
from pathlib import Path

import click

from . import __version__


@click.group()
@click.version_option(__version__)
def cli():
    """Music Video Director — AI-powered music video editing toolkit.

    Used by the mv-director AI agent skill.
    Run `mvd install` first to verify all dependencies.
    """


@cli.command()
@click.option("--yes", "-y", is_flag=True, help="Auto-install without confirmation")
def install(yes):
    """Check and install all required dependencies."""
    from .installer import install_all
    install_all(auto_install=yes or True)


@cli.command()
@click.argument("source")
@click.option("--output-dir", "-o", default=".", show_default=True, help="Destination directory")
@click.option("--audio-only", is_flag=True, help="Extract audio as mp3 only")
@click.option("--name", "-n", default=None, help="Output filename stem (no extension)")
def download(source, output_dir, audio_only, name):
    """Download from a URL or copy a local file.

    SOURCE may be a YouTube URL, Bilibili URL, or local file path.
    Prints a JSON result with the output file path and duration.
    """
    from .downloader import download as do_download
    result = do_download(source, output_dir, audio_only=audio_only, name=name)
    print(json.dumps(result, indent=2))


@cli.command("analyze-audio")
@click.argument("audio_file")
@click.option("--output", "-o", default=None,
              help="Output JSON path (default: same dir as audio, _analysis.json suffix)")
@click.option(
    "--whisper-model", default="base", show_default=True,
    type=click.Choice(["tiny", "base", "small", "medium", "large"]),
    help="Whisper model for lyric transcription",
)
def analyze_audio(audio_file, output, whisper_model):
    """Analyze a music audio file: beats, structure, energy, and lyrics.

    Outputs a JSON file with all data the AI agent needs for edit planning.
    No AI involved here — pure signal processing.
    """
    if not os.path.exists(audio_file):
        click.echo(f"Error: not found: {audio_file}", err=True)
        sys.exit(1)

    if output is None:
        stem = Path(audio_file).stem
        output = str(Path(audio_file).parent / f"{stem}_analysis.json")

    from .audio import analyze
    result = analyze(audio_file, output_path=output, whisper_model=whisper_model)

    click.echo("\nSummary:")
    click.echo(f"  Duration : {result['duration']:.1f}s")
    click.echo(f"  BPM      : {result['bpm']:.1f}")
    click.echo(f"  Beats    : {len(result['beats'])}")
    click.echo(f"  Sections : {' → '.join(s['type'] for s in result['sections'])}")
    click.echo(f"  Lyrics   : {len(result['lyrics'])} segments")
    click.echo(f"\nSaved: {output}")


@cli.command("detect-scenes")
@click.argument("video_file")
@click.option("--output", "-o", default=None, help="Output JSON path")
@click.option("--keyframes-dir", "-k", default=None, help="Directory for keyframe JPEGs")
@click.option(
    "--threshold", default=27.0, show_default=True,
    help="Scene change sensitivity — lower = more scenes detected",
)
def detect_scenes(video_file, output, keyframes_dir, threshold):
    """Detect scene boundaries and extract keyframe images from a video clip.

    Outputs a JSON file with scene list and keyframe image paths.
    The AI agent reads the keyframe images for visual scene description.
    """
    if not os.path.exists(video_file):
        click.echo(f"Error: not found: {video_file}", err=True)
        sys.exit(1)

    if output is None:
        stem = Path(video_file).stem
        output = str(Path(video_file).parent / f"{stem}_scenes.json")

    from .video import analyze_clip
    result = analyze_clip(
        video_file,
        output_dir=keyframes_dir,
        output_json=output,
        threshold=threshold,
    )

    scenes = result["scenes"]
    click.echo(f"\nScenes found: {len(scenes)}")
    for s in scenes[:8]:
        click.echo(
            f"  {s['index']:3d}  {s['start_time']:6.1f}s → {s['end_time']:6.1f}s"
            f"  ({s['duration']:.1f}s)  → {s.get('keyframe_path', '?')}"
        )
    if len(scenes) > 8:
        click.echo(f"  ... and {len(scenes) - 8} more")
    click.echo(f"\nSaved: {output}")


@cli.command()
@click.argument("edl_file")
@click.option("--json", "as_json", is_flag=True, help="Output results as JSON")
def validate(edl_file, as_json):
    """Validate an EDL JSON file for common errors before rendering.

    Checks performed:
      - source_validity   : source_out > source_in for every cut
      - source_overlaps   : no two cuts share overlapping source ranges (same file)
      - contiguity        : timeline_start/end are gapless (if present)
      - source_ordering   : source_in values non-decreasing per source (if ordered)
      - no_repeats        : no duplicate (source_file, source_in) pairs

    Exits with code 0 if all checks pass, 1 if any fail.
    """
    import json as _json
    if not os.path.exists(edl_file):
        click.echo(f"Error: EDL file not found: {edl_file}", err=True)
        sys.exit(1)

    with open(edl_file) as f:
        edl = _json.load(f)

    # Simple EDLs (edit_plan.json) have cuts without 'n'; add index for reporting
    cuts = edl.get("cuts", [])
    for i, cut in enumerate(cuts):
        if "n" not in cut:
            cut["n"] = i + 1

    from .validate import validate_edl
    result = validate_edl(edl)

    if as_json:
        click.echo(_json.dumps(result, indent=2))
    else:
        click.echo(f"\nEDL: {edl_file}")
        click.echo(f"Cuts: {len(cuts)}")
        click.echo(f"Result: {result['summary']}\n")
        any_errors = False
        for check, errors in result["errors"].items():
            if errors:
                any_errors = True
                click.echo(f"  FAIL [{check}]")
                for e in errors:
                    click.echo(f"       {e}")
            else:
                click.echo(f"  pass [{check}]")
        if not any_errors:
            click.echo("\nAll clear — EDL is valid.")

    sys.exit(0 if result["passed"] else 1)


@cli.command()
@click.argument("edl_file")
@click.option("--output", "-o", default=None, help="Output .mp4 path (overrides EDL setting)")
@click.option("--fps", default=24.0, show_default=True, help="Output framerate")
@click.option("--width", default=1920, show_default=True, help="Output width in pixels")
@click.option("--height", default=1080, show_default=True, help="Output height in pixels")
@click.option(
    "--early-frames", default=0, show_default=True,
    help="Shift source extraction N frames before source_in. Keep 0 unless EDL source_in values were set N frames past the intended start frame.",
)
def render(edl_file, output, fps, width, height, early_frames):
    """Render the final music video from an EDL JSON file.

    EDL_FILE is the edit_plan.json produced by the AI agent during planning.
    Assembles all clips, normalizes resolution/framerate, and mixes in audio.
    """
    if not os.path.exists(edl_file):
        click.echo(f"Error: EDL file not found: {edl_file}", err=True)
        sys.exit(1)

    from .renderer import render as do_render
    result = do_render(
        edl_file,
        output_path=output,
        target_fps=fps,
        target_width=width,
        target_height=height,
        early_frames=early_frames,
    )
    click.echo(f"\nRender complete: {result}")


if __name__ == "__main__":
    cli()
