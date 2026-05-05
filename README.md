# YunYunEditor

Desktop chart editor for [YunYunLoader](https://github.com/EBro912/YunYunLoader/) mods.

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

## Build EXE

On Windows, run:

```bat
BuildYunYunEditorExe.bat
```

The build script will:

1. Reuse or create `python_editor\.venv`.
2. Install the editor and `pyinstaller` into that venv.
3. Build a PyInstaller onedir package.

The output executable is:

```text
dist\YunYunEditor\YunYunEditor.exe
```

Keep the full `dist\YunYunEditor` folder together when distributing it.

## Features

- Import existing YunYunLoader mod ZIPs.
- Save and load editable `.denpa` projects with embedded song/level JSON and copied audio.
- Import common audio formats and normalize them to OGG/Vorbis for export.
- Export directly to an unpacked YunYun install `Songs` folder.
- Detect initial BPM and score offset from the current audio.
- Edit notes, holds, rush notes, BPM, time signatures, and end level (phase) events.
- Waveform background, bar/beat labels, snap controls, speed control, hit SFX, conduct mode, undo/redo, and ZIP export.

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
| `Ctrl+S` | Save `.denpa` |
| `Ctrl+E` | Export ZIP |
| `Ctrl+O` | Open `.denpa` |
| `Delete` | Remove selected notes |
| `,` / `.` | Nudge selection by snap unit |
| `<` / `>` | Nudge selection by a beat |

*Disclaimer: This project contains AI-generated code.*
