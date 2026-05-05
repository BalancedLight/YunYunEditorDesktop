# YunYunEditor Desktop

Tkinter desktop editor for YunYunLoader chart mods.

Run from this directory, or use `..\LaunchYunYunEditor.bat` from the repo root:

```bash
python -m pip install -e .
python -m yunyun_editor
```

This is the main editor. It saves editable `.denpa` project files, keeps the project audio next
to the `.denpa`, and exports YunYunLoader `song.json`, level JSON, `.ogg`, ZIP, or unpacked game
folder structures.

Imported audio is normalized to OGG/Vorbis immediately. `soundfile` handles common PCM/FLAC/OGG
paths; MP3/AAC/M4A and other compressed formats may require `ffmpeg` on PATH for the `pydub`
fallback decoder.

Editor-owned audio assets live in `assets/audio/`.
