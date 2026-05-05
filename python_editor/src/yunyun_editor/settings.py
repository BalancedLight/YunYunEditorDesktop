from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import os
from pathlib import Path


def app_data_dir() -> Path:
    root = os.environ.get("APPDATA")
    if root:
        return Path(root) / "YunYunEditorDesktop"
    return Path.home() / ".yunyun_editor_desktop"


@dataclass
class EditorSettings:
    yunyun_install_path: str = ""
    prompted_for_yunyun_install: bool = False


class SettingsStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or app_data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "settings.json"

    def load(self) -> EditorSettings:
        if not self.path.exists():
            return EditorSettings()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return EditorSettings()
        if not isinstance(raw, dict):
            return EditorSettings()
        return EditorSettings(
            yunyun_install_path=str(raw.get("yunyun_install_path", "")),
            prompted_for_yunyun_install=bool(raw.get("prompted_for_yunyun_install", False)),
        )

    def save(self, settings: EditorSettings) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
        tmp.replace(self.path)
