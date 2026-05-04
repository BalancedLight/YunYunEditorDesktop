from __future__ import annotations

from yunyun_editor.drafts import CURRENT_DRAFT_ID, DraftStore
from yunyun_editor.model import LevelJson, SongJson, SongLevelRef


def test_draft_store_saves_loads_latest_and_replaces_stale_audio(tmp_path) -> None:
    store = DraftStore(tmp_path)
    song = SongJson(ID="SongA", Audio="a.ogg", Title="Song A", Levels=[SongLevelRef("me", 1, "level1.json")])
    levels = {"level1.json": LevelJson(MusicInfoName="SongA", MusicPath="a")}

    first = store.save(CURRENT_DRAFT_ID, "Working - Song A", song, levels, "a.ogg", b"aaa")

    assert store.latest() is not None
    assert store.latest().id == first.id
    loaded_song, loaded_levels, loaded_audio_name, loaded_audio = store.load(CURRENT_DRAFT_ID)
    assert loaded_song.ID == "SongA"
    assert set(loaded_levels) == {"level1.json"}
    assert loaded_audio_name == "a.ogg"
    assert loaded_audio == b"aaa"

    song.Audio = "b.ogg"
    store.save(CURRENT_DRAFT_ID, "Working - Song A", song, levels, "b.ogg", b"bbb")

    assert not (tmp_path / CURRENT_DRAFT_ID / "a.ogg").exists()
    assert (tmp_path / CURRENT_DRAFT_ID / "b.ogg").read_bytes() == b"bbb"

