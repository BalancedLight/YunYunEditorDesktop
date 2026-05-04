from __future__ import annotations

import zipfile
from io import BytesIO

from yunyun_editor.audio_convert import canonical_ogg_filename, convert_audio_file_to_ogg, ensure_ogg_audio, is_ogg_bytes
from yunyun_editor.io import build_zip_bytes, prepare_export_audio
from yunyun_editor.model import LevelJson, SongJson, SongLevelRef


def test_canonical_ogg_filename_strips_source_extension() -> None:
    assert canonical_ogg_filename("music.mp3") == "music.ogg"
    assert canonical_ogg_filename(r"C:\songs\Mix.FLAC") == "Mix.ogg"
    assert canonical_ogg_filename("") == "audio.ogg"


def test_ogg_bytes_are_renamed_without_reencoding() -> None:
    data = b"OggSfake"

    name, converted = ensure_ogg_audio("track.wav", data)

    assert name == "track.ogg"
    assert converted is data
    assert is_ogg_bytes(converted)


def test_export_defensively_renames_ogg_audio_metadata() -> None:
    song = SongJson(ID="SongA", Audio="track.wav", Levels=[SongLevelRef("me", 1, "level1.json")])
    levels = {"level1.json": LevelJson(MusicInfoName="SongA", MusicPath="track")}

    song_out, levels_out, audio_name, audio_bytes = prepare_export_audio(song, levels, "track.wav", b"OggSfake")

    assert audio_name == "track.ogg"
    assert audio_bytes == b"OggSfake"
    assert song_out.Audio == "track.ogg"
    assert levels_out["level1.json"].MusicPath == "track"
    assert song.Audio == "track.wav"


def test_export_converts_non_ogg_audio_with_converter_monkeypatch() -> None:
    import yunyun_editor.io as io_mod

    old = io_mod.ensure_ogg_audio
    io_mod.ensure_ogg_audio = lambda filename, data: ("track.ogg", b"OggSconverted")
    try:
        song = SongJson(ID="SongA", Audio="track.mp3", Levels=[SongLevelRef("me", 1, "level1.json")])
        levels = {"level1.json": LevelJson(MusicInfoName="SongA", MusicPath="track")}
        zip_bytes = build_zip_bytes(song, levels, "track.mp3", b"not ogg", "SongA")
    finally:
        io_mod.ensure_ogg_audio = old

    with zipfile.ZipFile(BytesIO(zip_bytes), "r") as zf:
        assert "SongA/track.ogg" in zf.namelist()
        assert b'"Audio": "track.ogg"' in zf.read("SongA/song.json")
        assert zf.read("SongA/track.ogg") == b"OggSconverted"


def test_file_import_uses_streaming_converter_before_pydub(tmp_path) -> None:
    import yunyun_editor.audio_convert as convert_mod

    source = tmp_path / "big.wav"
    source.write_bytes(b"RIFFfake-wave")
    calls = []

    def fake_stream(path):
        calls.append(path)
        return b"OggSstreamed"

    old_stream = convert_mod.stream_soundfile_file_to_ogg
    convert_mod.stream_soundfile_file_to_ogg = fake_stream
    try:
        name, data = convert_audio_file_to_ogg(source)
    finally:
        convert_mod.stream_soundfile_file_to_ogg = old_stream

    assert name == "big.ogg"
    assert data == b"OggSstreamed"
    assert calls == [source]


def test_file_import_falls_back_to_pydub_converter(tmp_path) -> None:
    import yunyun_editor.audio_convert as convert_mod

    source = tmp_path / "song.wav"
    source.write_bytes(b"RIFFfake-wave")
    old_stream = convert_mod.stream_soundfile_file_to_ogg
    old_pydub = convert_mod.convert_with_pydub_file
    convert_mod.stream_soundfile_file_to_ogg = lambda path: (_ for _ in ()).throw(RuntimeError("nope"))
    convert_mod.convert_with_pydub_file = lambda path: b"OggSpydub"

    try:
        name, data = convert_audio_file_to_ogg(source)
    finally:
        convert_mod.stream_soundfile_file_to_ogg = old_stream
        convert_mod.convert_with_pydub_file = old_pydub

    assert name == "song.ogg"
    assert data == b"OggSpydub"
