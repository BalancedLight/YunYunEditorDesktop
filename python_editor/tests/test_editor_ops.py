from __future__ import annotations

from yunyun_editor.editor_state import (
    ChartState,
    EditorState,
    MIN_LONG_NOTE_DURATION,
    add_bpm_change,
    add_phase_change,
    add_time_signature_change,
    copy_selected_notes,
    create_rush,
    create_single,
    conduct_lane_for_key,
    move_selection_to,
    paste_notes_at_tick,
    place_conduct_note,
    resize_long_note_tail,
    select_note_ids_in_tick_lane_box,
    selected_notes,
    selection_after_note_click,
)
from yunyun_editor.model import BpmEvent, LevelJson, TimeSignatureEvent


def editor_with_level(level: LevelJson | None = None) -> EditorState:
    level = level or LevelJson()
    return EditorState(chart=ChartState(levels={"level.json": level}, active_level_path="level.json"))


def test_event_creation_uses_snapped_playhead_and_current_defaults() -> None:
    level = LevelJson()
    level.BpmChangeEvents.append(BpmEvent(480, 150.0))
    level.TimeSignature.append(TimeSignatureEvent(480, 3, 4))
    editor = editor_with_level(level)
    editor.playhead_tick = 731
    editor.snap_division = "1/8"

    bpm = add_bpm_change(editor)
    ts = add_time_signature_change(editor)
    phase = add_phase_change(editor)

    assert bpm is not None and bpm.Tick == 720 and bpm.Bpm == 150.0
    assert ts is not None and ts.Tick == 720 and ts.Numerator == 3 and ts.Denominator == 4
    assert phase is not None and phase.Tick == 720


def test_event_ids_survive_tick_resort() -> None:
    level = LevelJson()
    a = BpmEvent(960, 130.0)
    b = BpmEvent(480, 140.0)
    level.BpmChangeEvents = [a, b]

    a.Tick = 240
    level.BpmChangeEvents.sort(key=lambda ev: (ev.Tick, ev.id))

    assert level.BpmChangeEvents[0].id == a.id
    assert {ev.id for ev in level.BpmChangeEvents} == {a.id, b.id}


def test_move_selection_places_anchor_on_snap_and_preserves_offsets() -> None:
    level = LevelJson()
    anchor = create_single(level, 100, 3)
    other = create_single(level, 220, 4)

    move_selection_to(level, {anchor.id, other.id}, anchor.id, 240, 5)

    assert anchor.Tick == 240
    assert other.Tick == 360
    assert anchor.Lane == 5
    assert other.Lane == 5


def test_rush_move_clamps_to_two_lane_span() -> None:
    level = LevelJson()
    rush = create_rush(level, 100, 340, 4)

    move_selection_to(level, {rush.id}, rush.id, 240, 5)

    assert rush.Tick == 240
    assert rush.Lane == 4


def test_clicking_selected_note_preserves_multi_selection_without_shift() -> None:
    selection = {"a", "b"}

    assert selection_after_note_click(selection, "a", additive=False) == {"a", "b"}
    assert selection_after_note_click(selection, "c", additive=False) == {"c"}


def test_paste_selected_notes_anchors_first_note_to_snapped_playhead() -> None:
    level = LevelJson()
    editor = editor_with_level(level)
    editor.playhead_tick = 731
    editor.snap_enabled = True
    editor.snap_division = "1/8"

    rush = create_rush(level, 100, 340, 4)
    single = create_single(level, 220, 2)

    clipboard = copy_selected_notes(level, {rush.id, single.id})
    pasted_ids = paste_notes_at_tick(level, clipboard, editor.snapped_tick(editor.playhead_tick))
    pasted = selected_notes(level, pasted_ids)
    pasted.sort(key=lambda item: (item[1].Tick, item[1].Lane, item[0]))

    assert len(pasted_ids) == 2
    assert {note.id for _kind, note in pasted}.isdisjoint({rush.id, single.id})
    assert pasted[0][0] == "rush"
    assert pasted[0][1].Tick == 720
    assert pasted[0][1].Lane == 4
    assert pasted[0][1].Duration == rush.Duration
    assert pasted[1][0] == "single"
    assert pasted[1][1].Tick == 840
    assert pasted[1][1].Lane == 2


def test_resize_long_note_tail_keeps_head_and_updates_duration() -> None:
    level = LevelJson()
    rush = create_rush(level, 100, 340, 4)

    changed = resize_long_note_tail(level, rush.id, 580)

    assert changed
    assert rush.Tick == 100
    assert rush.Duration == 480


def test_resize_long_note_tail_clamps_to_minimum_duration() -> None:
    level = LevelJson()
    rush = create_rush(level, 100, 340, 4)

    changed = resize_long_note_tail(level, rush.id, 120)

    assert changed
    assert rush.Tick == 100
    assert rush.Duration == MIN_LONG_NOTE_DURATION


def test_tick_lane_box_selection_handles_holds_and_rush_spans() -> None:
    level = LevelJson()
    single = create_single(level, 100, 2)
    from yunyun_editor.model import HoldNote

    held = HoldNote(Tick=200, Lane=3, Duration=400)
    level.HoldNotes.append(held)
    rush = create_rush(level, 500, 900, 4)

    ids = select_note_ids_in_tick_lane_box(level, 250, 650, 3, 5)

    assert single.id not in ids
    assert held.id in ids
    assert rush.id in ids


def test_conduct_key_lane_mapping() -> None:
    assert conduct_lane_for_key("s") == 2
    assert conduct_lane_for_key("D") == 3
    assert conduct_lane_for_key("k") == 4
    assert conduct_lane_for_key("L") == 5
    assert conduct_lane_for_key("x") is None


def test_conduct_note_uses_snapped_playhead_when_enabled() -> None:
    editor = editor_with_level()
    editor.playhead_tick = 731
    editor.snap_enabled = True
    editor.snap_division = "1/8"

    note = place_conduct_note(editor, "k")

    assert note is not None
    assert note.Tick == 720
    assert note.Lane == 4
    assert editor.active_level().SingleNotes == [note]


def test_conduct_note_uses_exact_playhead_when_snap_disabled() -> None:
    editor = editor_with_level()
    editor.playhead_tick = 731
    editor.snap_enabled = False

    note = place_conduct_note(editor, "s")

    assert note is not None
    assert note.Tick == 731
    assert note.Lane == 2
