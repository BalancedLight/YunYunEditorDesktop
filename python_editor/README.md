# YunYunEditor Desktop

Tkinter desktop editor for YunYunLoader chart mods.

Run from this directory, or use `..\LaunchYunYunEditor.bat` from the repo root:

```bash
python -m pip install -e .[test]
python -m yunyun_editor
```

This is the main editor. It reads and writes the YunYunLoader `song.json`, level JSON, `.ogg`,
and exported ZIP structure.

Imported audio is normalized to OGG/Vorbis immediately. `soundfile` handles common PCM/FLAC/OGG
paths; MP3/AAC/M4A and other compressed formats may require `ffmpeg` on PATH for the `pydub`
fallback decoder.

Editor-owned audio assets live in `assets/audio/`.
