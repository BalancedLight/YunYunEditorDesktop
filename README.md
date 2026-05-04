# YunYunEditor

Desktop chart editor for [YunYunLoader](https://github.com/EBro912/YunYunLoader/) mods.

This repository now uses the Python/Tkinter editor as the main editor. The old web/Svelte editor has been removed.

## Quick Start

On Windows, run:

```bat
LaunchYunYunEditor.bat
```

The launcher will:

1. Create `python_editor\.venv` if it does not exist.
2. Install the Python requirements into that venv.
3. Launch the editor.

If audio import for formats like MP3/AAC/M4A fails, install `ffmpeg` and make sure it is available on `PATH`.

## Manual Run

```bash
cd python_editor
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m yunyun_editor
```

## Features

- Import existing YunYunLoader mod ZIPs.
- Import common audio formats and normalize them to OGG/Vorbis for export.
- Edit notes, holds, rush notes, BPM, time signatures, and phase events.
- Waveform background, bar/beat labels, snap controls, speed control, hit SFX, conduct mode, undo/redo, drafts, and ZIP export.
- Drafts are stored in the local app-data folder and the most recent draft resumes on launch.

## Shortcuts

| Key | Action |
| --- | --- |
| `Space` | Play / pause |
| `Home` / `End` | Seek to start / end |
| `1` / `2` / `3` / `4` | Single / Hold / Rush / Eraser |
| `V` | Select |
| `S` | Toggle snap, or conduct left lane when Conduct mode is on |
| `D` / `K` / `L` | Conduct middle-left / middle-right / right lanes |
| `[` / `]` | Halve / double snap division |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / redo |
| `Ctrl+S` | Save draft |
| `Ctrl+E` | Export ZIP |
| `Ctrl+O` | Import ZIP |
| `Delete` | Remove selected notes |
| `,` / `.` | Nudge selection by snap unit |
| `<` / `>` | Nudge selection by a beat |

## Tests

```bash
cd python_editor
.venv\Scripts\python -m pip install -e .[test]
.venv\Scripts\python -m pytest tests
```

*Disclaimer: This project contains AI-generated code.*
