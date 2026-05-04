from __future__ import annotations

from pathlib import Path

from yunyun_editor.io import build_zip_bytes, load_example_folder, parse_zip, stringify_level


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_example_folder_roundtrips_without_editor_ids(tmp_path: Path) -> None:
    mod = load_example_folder(REPO_ROOT / "Example")
    assert mod.song.ID == "ExampleSong"
    assert "level1.json" in mod.levels
    assert mod.levels["level1.json"].SingleNotes[0].id

    text = stringify_level(mod.levels["level1.json"])
    assert '"id"' not in text

    zip_bytes = build_zip_bytes(mod.song, mod.levels, mod.audio_filename, mod.audio_bytes, "ExampleSong")
    zip_path = tmp_path / "example.zip"
    zip_path.write_bytes(zip_bytes)
    reparsed = parse_zip(zip_path)

    assert reparsed.song.ID == mod.song.ID
    assert set(reparsed.levels) == set(mod.levels)
    assert reparsed.audio_bytes == mod.audio_bytes

