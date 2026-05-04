from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import time

from .io import parse_level_json, parse_song_json, stringify_level, stringify_song
from .model import LevelJson, SongJson


CURRENT_DRAFT_ID = "__current__"


def app_data_dir() -> Path:
    root = os.environ.get("APPDATA")
    if root:
        return Path(root) / "YunYunEditorDesktop"
    return Path.home() / ".yunyun_editor_desktop"


@dataclass
class DraftMeta:
    id: str
    name: str
    updated_at: float
    song_id: str = ""
    song_title: str = ""


class DraftStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or app_data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "drafts.json"

    def list(self) -> list[DraftMeta]:
        if not self.index_path.exists():
            return []
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [DraftMeta(**item) for item in raw if isinstance(item, dict)]

    def latest(self) -> DraftMeta | None:
        items = self.list()
        return items[0] if items else None

    def get_meta(self, draft_id: str) -> DraftMeta | None:
        return next((item for item in self.list() if item.id == draft_id), None)

    def get_saved_song_identity(self, draft_id: str) -> tuple[str, str] | None:
        meta = self.get_meta(draft_id)
        if not meta:
            return None
        if meta.song_id or meta.song_title:
            if meta.song_title:
                return meta.song_id, meta.song_title
        song_path = self.root / draft_id / "song.json"
        if not song_path.exists():
            return meta.song_id, meta.song_title
        try:
            song = parse_song_json(song_path.read_text(encoding="utf-8-sig"))
        except Exception:
            return meta.song_id, meta.song_title
        return song.ID, song.Title

    def _write_index(self, items: list[DraftMeta]) -> None:
        self._atomic_write_text(self.index_path, json.dumps([item.__dict__ for item in items], indent=2))

    def save(
        self,
        draft_id: str,
        name: str,
        song: SongJson,
        levels: dict[str, LevelJson],
        audio_filename: str,
        audio_bytes: bytes,
    ) -> DraftMeta:
        folder = self.root / draft_id
        folder.mkdir(parents=True, exist_ok=True)
        self._atomic_write_text(folder / "song.json", stringify_song(song))
        level_dir = folder / "levels"
        level_dir.mkdir(exist_ok=True)
        for path, level in levels.items():
            target = level_dir / path
            target.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write_text(target, stringify_level(level))
        keep_audio = audio_filename if audio_filename and audio_bytes else None
        for existing in folder.glob("*.ogg"):
            if existing.name != keep_audio:
                existing.unlink(missing_ok=True)
        if audio_filename and audio_bytes:
            self._atomic_write_bytes(folder / audio_filename, audio_bytes)
        items = [item for item in self.list() if item.id != draft_id]
        meta = DraftMeta(draft_id, name, time.time(), song.ID, song.Title)
        items.append(meta)
        self._write_index(sorted(items, key=lambda item: item.updated_at, reverse=True))
        return meta

    def load(self, draft_id: str) -> tuple[SongJson, dict[str, LevelJson], str, bytes]:
        folder = self.root / draft_id
        song_path = folder / "song.json"
        if not song_path.exists():
            raise FileNotFoundError(f'Draft "{draft_id}" is missing song.json')
        song = parse_song_json(song_path.read_text(encoding="utf-8-sig"))
        levels: dict[str, LevelJson] = {}
        for ref in song.Levels:
            level_path = folder / "levels" / ref.Path
            if level_path.exists():
                levels[ref.Path] = parse_level_json(level_path.read_text(encoding="utf-8-sig"))
        audio_path = folder / song.Audio
        audio_bytes = audio_path.read_bytes() if audio_path.exists() else b""
        return song, levels, song.Audio, audio_bytes

    def delete(self, draft_id: str) -> None:
        shutil.rmtree(self.root / draft_id, ignore_errors=True)
        self._write_index([item for item in self.list() if item.id != draft_id])

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def _atomic_write_bytes(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
