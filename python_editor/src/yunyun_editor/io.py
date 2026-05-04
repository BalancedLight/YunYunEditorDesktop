from __future__ import annotations

import copy
from dataclasses import dataclass
import json
from pathlib import Path
import zipfile

from .audio_convert import ensure_ogg_audio
from .model import LevelJson, SongJson
from .model import audio_to_music_path


@dataclass
class ImportedMod:
    song: SongJson
    levels: dict[str, LevelJson]
    audio_filename: str
    audio_bytes: bytes
    mod_folder_name: str
    warnings: list[str]


class ImportErrorWithIssues(Exception):
    def __init__(self, message: str, issues: list[str] | None = None) -> None:
        super().__init__(message)
        self.issues = issues or [message]


def parse_song_json(text: str) -> SongJson:
    return SongJson.from_dict(json.loads(text))


def parse_level_json(text: str) -> LevelJson:
    return LevelJson.from_dict(json.loads(text))


def stringify_song(song: SongJson) -> str:
    return json.dumps(song.to_dict(), indent="\t", ensure_ascii=False) + "\n"


def stringify_level(level: LevelJson) -> str:
    return json.dumps(level.to_dict(), indent="\t", ensure_ascii=False) + "\n"


def parse_zip(path: str | Path) -> ImportedMod:
    path = Path(path)
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
        song_candidates = [
            name for name in names if name == "song.json" or name.endswith("/song.json")
        ]
        if not song_candidates:
            raise ImportErrorWithIssues("song.json not found in zip")
        song_path = min(song_candidates, key=lambda name: len([p for p in name.split("/") if p]))
        base = song_path[: -len("song.json")]
        song = parse_song_json(zf.read(song_path).decode("utf-8-sig"))
        mod_folder = base.rstrip("/").split("/")[-1] if base else (song.ID or path.stem or "mod")

        levels: dict[str, LevelJson] = {}
        warnings: list[str] = []
        for ref in song.Levels:
            full = base + ref.Path
            if full not in names:
                warnings.append(f'level file "{ref.Path}" not found in zip')
                continue
            levels[ref.Path] = parse_level_json(zf.read(full).decode("utf-8-sig"))

        audio_path = base + song.Audio
        if audio_path not in names:
            raise ImportErrorWithIssues(f'audio file "{song.Audio}" not found in zip')
        audio_bytes = zf.read(audio_path)
        try:
            audio_filename, audio_bytes = ensure_ogg_audio(song.Audio, audio_bytes)
        except Exception as exc:
            raise ImportErrorWithIssues(f'Could not convert "{song.Audio}" to OGG: {exc}') from exc
        song.Audio = audio_filename
        music_path = audio_to_music_path(audio_filename)
        for level in levels.values():
            level.MusicPath = music_path

    return ImportedMod(song, levels, song.Audio, audio_bytes, mod_folder, warnings)


def load_example_folder(path: str | Path) -> ImportedMod:
    path = Path(path)
    song = parse_song_json((path / "song.json").read_text(encoding="utf-8-sig"))
    levels = {
        ref.Path: parse_level_json((path / ref.Path).read_text(encoding="utf-8-sig"))
        for ref in song.Levels
        if (path / ref.Path).exists()
    }
    audio_bytes = (path / song.Audio).read_bytes() if song.Audio else b""
    return ImportedMod(song, levels, song.Audio, audio_bytes, path.name, [])


def build_zip_bytes(song: SongJson, levels: dict[str, LevelJson], audio_filename: str, audio_bytes: bytes, mod_folder: str) -> bytes:
    from io import BytesIO

    song, levels, audio_filename, audio_bytes = prepare_export_audio(song, levels, audio_filename, audio_bytes)
    mem = BytesIO()
    folder = sanitize_folder_name(mod_folder)
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr(f"{folder}/song.json", stringify_song(song))
        written: set[str] = set()
        for ref in song.Levels:
            if ref.Path in written or ref.Path not in levels:
                continue
            written.add(ref.Path)
            zf.writestr(f"{folder}/{ref.Path}", stringify_level(levels[ref.Path]))
        if audio_bytes:
            zf.writestr(f"{folder}/{song.Audio or audio_filename}", audio_bytes)
    return mem.getvalue()


def prepare_export_audio(
    song: SongJson,
    levels: dict[str, LevelJson],
    audio_filename: str,
    audio_bytes: bytes,
) -> tuple[SongJson, dict[str, LevelJson], str, bytes]:
    if not audio_bytes:
        return song, levels, audio_filename, audio_bytes
    source_name = song.Audio or audio_filename or "audio.ogg"
    ogg_filename, ogg_bytes = ensure_ogg_audio(source_name, audio_bytes)
    if song.Audio == ogg_filename and audio_filename == ogg_filename and ogg_bytes is audio_bytes:
        return song, levels, audio_filename, audio_bytes
    song_out = copy.deepcopy(song)
    levels_out = copy.deepcopy(levels)
    song_out.Audio = ogg_filename
    music_path = audio_to_music_path(ogg_filename)
    for level in levels_out.values():
        level.MusicPath = music_path
    return song_out, levels_out, ogg_filename, ogg_bytes


def export_zip(path: str | Path, song: SongJson, levels: dict[str, LevelJson], audio_filename: str, audio_bytes: bytes, mod_folder: str) -> None:
    Path(path).write_bytes(build_zip_bytes(song, levels, audio_filename, audio_bytes, mod_folder))


def sanitize_folder_name(raw: str) -> str:
    cleaned = "".join("_" if ch in '\\/:*?"<>|' else ch for ch in raw.strip())
    cleaned = "_".join(cleaned.split())
    return cleaned or "mod"
