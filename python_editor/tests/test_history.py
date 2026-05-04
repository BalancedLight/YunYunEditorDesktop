from __future__ import annotations

from yunyun_editor.editor_state import ChartState, EditorState, create_single
from yunyun_editor.history import HistoryManager
from yunyun_editor.model import LevelJson


def test_history_undo_redo_restores_chart_notes() -> None:
    level = LevelJson()
    state = EditorState(chart=ChartState(levels={"level.json": level}, active_level_path="level.json"))
    history = HistoryManager()

    history.push(state)
    create_single(level, 120, 3)

    assert len(state.active_level().SingleNotes) == 1
    assert history.undo(state)
    assert len(state.active_level().SingleNotes) == 0
    assert history.redo(state)
    assert len(state.active_level().SingleNotes) == 1


def test_history_restore_keeps_audio_bytes_value() -> None:
    level = LevelJson()
    state = EditorState(
        chart=ChartState(levels={"level.json": level}, active_level_path="level.json", audio_filename="a.ogg", audio_bytes=b"OggSfake")
    )
    history = HistoryManager()

    history.push(state)
    state.chart.audio_filename = "b.ogg"
    state.chart.audio_bytes = b"OggSother"

    assert history.undo(state)
    assert state.chart.audio_filename == "a.ogg"
    assert state.chart.audio_bytes == b"OggSfake"

