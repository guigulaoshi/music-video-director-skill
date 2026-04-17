# Music Video Director

An AI agent skill that turns music + raw footage into an edited music video — with beat sync, lyric imagery matching, shot grammar, and emotional arc planning.

Works with any AI agent that can run shell commands and (optionally) read images.

## How it works

1. You provide: a music audio URL/file, video clip URLs/files, and a director's instruction.
2. The agent downloads everything, analyzes the audio (beats, structure, lyrics) and clips (scene detection, keyframe extraction) using the `mvd` CLI.
3. The agent examines the keyframe images — using image analysis if available, or scene metadata otherwise — and describes each scene.
4. The agent generates a shot-by-shot Edit Decision List (EDL) applying professional editorial rules: beat-sync timing, lyric imagery matching, shot grammar, energy-arc matching, color coherence.
5. The agent presents the edit plan for your review and approval.
6. On approval, the agent renders the final `.mp4`.

**Division of labor**: The `mvd` Python CLI handles technical work (downloading, beat detection, scene detection, ffmpeg rendering). The AI agent handles all creative work (scene description, edit planning, editorial judgment). No AI API calls from the CLI — the agent is the AI.

---

## Installation

### One step

Drop `skill.md` wherever your agent looks for skills. Everything else installs itself on first run.

**Claude Code:**
```bash
curl -fsSL https://raw.githubusercontent.com/guigulaoshi/music-video-director-skill/main/skill.md \
  -o ~/.claude/commands/mv-director.md
```
Then invoke with `/mv-director`. The skill will auto-install the `mvd` Python toolkit on first use.

**Other agents:** paste the contents of `skill.md` into the agent's system prompt, or reference it as a task file per that agent's convention. The skill handles its own dependency installation at runtime.

### The only true prerequisite: ffmpeg

ffmpeg is a system binary that pip cannot install. If the auto-installer reports it missing:

```bash
# macOS
brew install ffmpeg

# Linux
sudo apt-get install -y ffmpeg

# Windows
winget install ffmpeg
```

Everything else (`yt-dlp`, `librosa`, `whisper`, `scenedetect`, …) is installed automatically by the skill on first run.

---

## Usage

Invoke the skill (or paste its contents to your agent) and follow the prompts. The agent will ask for:

- **Audio source**: YouTube/Bilibili URL or local file — audio is extracted, video from this source is discarded
- **Video clips**: One or more URLs or local file paths for footage
- **Director's instruction**: The creative direction — mood, story, approach

Example director's instructions:
- *"Melancholic urban isolation that builds toward cathartic release. Tight beat-sync on the chorus."*
- *"High-energy performance edit — cut on every beat in the chorus, breathing room in the verses."*
- *"Abstract and dreamy. Imagery should be metaphorical, not literal. Use cool tones throughout."*
- *"Tell the story of someone falling in love — intimate close-ups in the verse, wide open spaces in the chorus."*

---

## The `mvd` CLI

The skill uses these commands internally. You can also run them directly:

```bash
# Check / install dependencies
mvd install -y

# Download from URL or copy local file
mvd download "https://www.youtube.com/watch?v=..." --output-dir ./project --name "clip1"
mvd download "https://www.youtube.com/watch?v=..." --output-dir ./project --audio-only --name "audio"

# Analyze audio (beats, structure, lyrics)
mvd analyze-audio ./project/audio.mp3 --output ./project/audio_analysis.json

# Detect scenes and extract keyframes
mvd detect-scenes ./project/clip1.mp4 --output ./project/clip1_scenes.json

# Render from an EDL
mvd render ./project/edit_plan.json --output ./project/output.mp4
```

See `mvd --help` or `mvd <command> --help` for full options.

---

## Output Files

All outputs land in a project directory (default: `/tmp/mvd_YYYYMMDD_HHMMSS/`):

```
project/
├── sources/
│   ├── audio.mp3          # Extracted music audio
│   ├── clip1.mp4          # Downloaded / copied clips
│   └── clip2.mp4
├── audio_analysis.json    # Beats, sections, energy curve, lyrics
├── clip1_scenes.json      # Scene boundaries + keyframe paths
├── clip2_scenes.json
├── keyframes/
│   ├── clip1/
│   │   ├── scene_0000.jpg # Keyframe images for agent visual analysis
│   │   └── ...
│   └── clip2/
├── edit_plan.json         # The EDL — re-renderable artifact
└── output.mp4             # Final rendered music video
```

The `edit_plan.json` is the key artifact: edit it manually and re-run `mvd render` to produce a new cut without re-analyzing anything.

---

## EDL Format

The edit plan JSON the agent generates:

```json
{
  "metadata": {
    "song_title": "...",
    "bpm": 128.5,
    "total_duration": 213.45,
    "total_cuts": 47,
    "avg_shot_length": 4.5,
    "emotional_arc": "Opens with isolation, builds toward cathartic release, resolves with quiet peace."
  },
  "audio_file": "/absolute/path/to/audio.mp3",
  "output_file": "/tmp/mvd_xxx/output.mp4",
  "cuts": [
    {
      "n": 1,
      "timeline_start": 0.000,
      "timeline_end": 7.917,
      "source_file": "/absolute/path/to/clip1.mp4",
      "source_in": 0.300,
      "source_out": 8.217,
      "section": "intro",
      "lyric": null,
      "description": "Wide exterior, empty city street at dusk",
      "rationale": "Establishes the lonely urban world before vocals enter"
    }
  ]
}
```

---

## Editorial Philosophy (what the skill encodes)

The skill embeds professional music video editorial knowledge:

- **Beat sync**: 1-frame-early rule (cuts land 2 frames before the beat for perceived tightness)
- **Musical structure**: Different visual treatment for intro / verse / pre-chorus / chorus / bridge / outro
- **Energy matching**: ASL (average shot length) tracks the song's dynamic envelope
- **Shot grammar**: 30° rule, Kuleshov effect, match cuts, motion vector matching, shot scale progression
- **Lyric imagery**: Literal / conceptual / metaphorical / counterpoint approaches
- **Color coherence**: Consecutive shot palette compatibility; color as emotional signal
- **Repetition avoidance**: 30-second window; same scene twice = noticed
- **Emotional arc**: Visual story has a beginning, middle, peak, and resolution
- **Scene boundary respect**: Detected scene atoms are never split

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `yt-dlp` | Download from YouTube, Bilibili, and 1000+ sites |
| `librosa` | Beat tracking, energy analysis, structural segmentation |
| `openai-whisper` | Lyric transcription with timestamps |
| `scenedetect` | Scene boundary detection |
| `ffmpeg-python` | FFmpeg Python bindings |
| `ffmpeg` (system) | Video encoding, decoding, rendering |
| `numpy`, `scipy` | Signal processing |
| `Pillow` | Image handling |
| `click` | CLI framework |

---

## License

MIT
