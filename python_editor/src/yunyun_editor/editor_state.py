from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .model import (
    BpmEvent,
    HoldNote,
    LANE_MAX,
    LANE_MIN,
    LevelJson,
    PhaseEvent,
    RushNote,
    SingleNote,
    SongJson,
    TimeSignatureEvent,
    audio_to_music_path,
    clamp_lane,
    clamp_rush_lane,
    empty_level,
    empty_song,
    new_id,
)
from .timing import SNAP_DIVISIONS, snap_tick


Tool = str


@dataclass
class ChartState:
    song: SongJson = field(default_factory=empty_song)
    levels: dict[str, LevelJson] = field(default_factory=dict)
    active_level_path: str | None = None
    audio_filename: str = ""
    audio_bytes: bytes = b""
    mod_folder_name: str = "mod"

    @property
    def active_level(self) -> LevelJson | None:
        if not self.active_level_path:
            return None
        return self.levels.get(self.active_level_path)


@dataclass
class EditorState:
    chart: ChartState = field(default_factory=ChartState)
    tool: Tool = "select"
    snap_enabled: bool = True
    snap_division: str = "1/8"
    pixels_per_second: int = 220
    playhead_tick: int = 0
    selection: set[str] = field(default_factory=set)
    note_sfx_enabled: bool = True
    editor_speed: float = 1.0
    conduct_mode: bool = False

    def active_level(self) -> LevelJson | None:
        return self.chart.active_level

    def snapped_tick(self, tick: float | None = None) -> int:
        lvl = self.active_level()
        raw = self.playhead_tick if tick is None else tick
        if not lvl or not self.snap_enabled:
            return max(0, int(round(raw)))
        return snap_tick(raw, lvl.InitTimeSignature, lvl.TimeSignature, self.snap_division)

    def set_playhead(self, tick: float) -> None:
        self.playhead_tick = max(0, int(round(tick)))

    def set_speed(self, speed: float) -> None:
        self.editor_speed = max(0.25, min(2.0, float(speed)))

    def set_zoom(self, pixels_per_second: float) -> None:
        self.pixels_per_second = max(40, min(1200, int(round(pixels_per_second))))

    def replace_chart(self, chart: ChartState) -> None:
        self.chart = chart
        self.selection.clear()
        self.playhead_tick = 0

    def new_project(self) -> None:
        self.replace_chart(ChartState())

    def update_song_field(self, field_name: str, value: str) -> None:
        if not hasattr(self.chart.song, field_name):
            return
        old_audio = self.chart.song.Audio
        setattr(self.chart.song, field_name, value)
        if field_name == "ID":
            for lvl in self.chart.levels.values():
                lvl.MusicInfoName = value
        if field_name == "Audio" and value != old_audio:
            self.chart.audio_filename = value
            music_path = audio_to_music_path(value)
            for lvl in self.chart.levels.values():
                lvl.MusicPath = music_path

    def set_audio(self, filename: str, audio_bytes: bytes) -> None:
        self.chart.audio_filename = filename
        self.chart.audio_bytes = audio_bytes
        self.update_song_field("Audio", filename)

    def add_level(self, editor: str = "Editor", difficulty: int = 1, level_slot: int = 1) -> str:
        path = f"level_{new_id()[:6]}.json"
        lvl = empty_level(self.chart.song.ID, level_slot, audio_to_music_path(self.chart.song.Audio))
        from .model import SongLevelRef

        self.chart.song.Levels.append(SongLevelRef(editor or "Editor", int(difficulty), path))
        self.chart.levels[path] = lvl
        self.chart.active_level_path = path
        self.selection.clear()
        return path

    def select_only(self, note_id: str) -> None:
        self.selection = {note_id}

    def clear_selection(self) -> None:
        self.selection.clear()


def sorted_events(events: list) -> list:
    return sorted(events, key=lambda item: (item.Tick, item.id))


def current_bpm_event(level: LevelJson, tick: int) -> BpmEvent:
    current = level.InitBpm
    for ev in sorted(level.BpmChangeEvents, key=lambda item: item.Tick):
        if ev.Tick > tick:
            break
        current = ev
    return current


def current_ts_event(level: LevelJson, tick: int) -> TimeSignatureEvent:
    current = level.InitTimeSignature
    for ev in sorted(level.TimeSignature, key=lambda item: item.Tick):
        if ev.Tick > tick:
            break
        current = ev
    return current


def add_bpm_change(editor: EditorState) -> BpmEvent | None:
    level = editor.active_level()
    if not level:
        return None
    tick = max(level.InitBpm.Tick + 1, editor.snapped_tick())
    prev = current_bpm_event(level, tick)
    ev = BpmEvent(Tick=tick, Bpm=prev.Bpm)
    level.BpmChangeEvents.append(ev)
    level.BpmChangeEvents = sorted_events(level.BpmChangeEvents)
    return ev


def add_time_signature_change(editor: EditorState) -> TimeSignatureEvent | None:
    level = editor.active_level()
    if not level:
        return None
    tick = max(level.InitTimeSignature.Tick + 1, editor.snapped_tick())
    prev = current_ts_event(level, tick)
    ev = TimeSignatureEvent(Tick=tick, Numerator=prev.Numerator, Denominator=prev.Denominator)
    level.TimeSignature.append(ev)
    level.TimeSignature = sorted_events(level.TimeSignature)
    return ev


def add_phase_change(editor: EditorState) -> PhaseEvent | None:
    level = editor.active_level()
    if not level:
        return None
    ev = PhaseEvent(Tick=editor.snapped_tick())
    level.PhaseChangeEvents.append(ev)
    level.PhaseChangeEvents = sorted_events(level.PhaseChangeEvents)
    return ev


def all_note_lists(level: LevelJson) -> list[tuple[str, list]]:
    return [
        ("single", level.SingleNotes),
        ("hold", level.HoldNotes),
        ("rush", level.RushNotes),
    ]


def iter_notes(level: LevelJson):
    for kind, notes in all_note_lists(level):
        for note in notes:
            yield kind, note


def find_note(level: LevelJson, note_id: str):
    for kind, note in iter_notes(level):
        if note.id == note_id:
            return kind, note
    return None, None


def create_single(level: LevelJson, tick: int, lane: int) -> SingleNote:
    note = SingleNote(Tick=max(0, int(tick)), Lane=clamp_lane(lane), Type=0)
    level.SingleNotes.append(note)
    return note


CONDUCT_KEY_LANES = {
    "s": LANE_MIN,
    "d": LANE_MIN + 1,
    "k": LANE_MAX - 1,
    "l": LANE_MAX,
}


def conduct_lane_for_key(key: str) -> int | None:
    return CONDUCT_KEY_LANES.get(key.lower())


def place_conduct_note(editor: EditorState, key: str) -> SingleNote | None:
    level = editor.active_level()
    lane = conduct_lane_for_key(key)
    if not level or lane is None:
        return None
    note = create_single(level, editor.snapped_tick(editor.playhead_tick), lane)
    return note


def create_hold(level: LevelJson, tick_from: int, tick_to: int, lane: int) -> HoldNote:
    tick_start = max(0, min(int(tick_from), int(tick_to)))
    duration = max(60, abs(int(tick_to) - int(tick_from)))
    note = HoldNote(Tick=tick_start, Lane=clamp_lane(lane), Type=0, Duration=duration)
    level.HoldNotes.append(note)
    return note


def create_rush(level: LevelJson, tick_from: int, tick_to: int, lane: int) -> RushNote:
    tick_start = max(0, min(int(tick_from), int(tick_to)))
    duration = max(60, abs(int(tick_to) - int(tick_from)))
    note = RushNote(Tick=tick_start, Lane=clamp_rush_lane(lane), Type=0, Duration=duration)
    level.RushNotes.append(note)
    return note


def delete_notes(level: LevelJson, ids: Iterable[str]) -> None:
    id_set = set(ids)
    level.SingleNotes = [n for n in level.SingleNotes if n.id not in id_set]
    level.HoldNotes = [n for n in level.HoldNotes if n.id not in id_set]
    level.RushNotes = [n for n in level.RushNotes if n.id not in id_set]


def move_selection_to(
    level: LevelJson,
    ids: Iterable[str],
    anchor_id: str,
    target_tick: int,
    target_lane: int,
) -> None:
    id_set = set(ids)
    anchor_kind, anchor = find_note(level, anchor_id)
    if not anchor:
        return
    if anchor_kind == "rush":
        target_lane = clamp_rush_lane(target_lane)
    else:
        target_lane = clamp_lane(target_lane)
    delta_tick = int(target_tick) - anchor.Tick
    delta_lane = int(target_lane) - anchor.Lane

    for kind, note in iter_notes(level):
        if note.id not in id_set:
            continue
        note.Tick = max(0, note.Tick + delta_tick)
        next_lane = note.Lane + delta_lane
        note.Lane = clamp_rush_lane(next_lane) if kind == "rush" else clamp_lane(next_lane)


def nudge_selection(level: LevelJson, ids: Iterable[str], delta_tick: int = 0, delta_lane: int = 0) -> None:
    id_set = set(ids)
    for kind, note in iter_notes(level):
        if note.id not in id_set:
            continue
        note.Tick = max(0, note.Tick + delta_tick)
        next_lane = note.Lane + delta_lane
        note.Lane = clamp_rush_lane(next_lane) if kind == "rush" else clamp_lane(next_lane)


def selected_notes(level: LevelJson, ids: Iterable[str]) -> list[tuple[str, SingleNote]]:
    id_set = set(ids)
    return [(kind, note) for kind, note in iter_notes(level) if note.id in id_set]


def select_note_ids_in_tick_lane_box(
    level: LevelJson,
    tick_min: int,
    tick_max: int,
    lane_min: int,
    lane_max: int,
) -> set[str]:
    tick_lo, tick_hi = sorted((int(tick_min), int(tick_max)))
    lane_lo, lane_hi = sorted((int(lane_min), int(lane_max)))
    found: set[str] = set()
    for note in level.SingleNotes:
        if tick_lo <= note.Tick <= tick_hi and lane_lo <= note.Lane <= lane_hi:
            found.add(note.id)
    for note in level.HoldNotes:
        note_tick_hi = note.Tick + note.Duration
        if note.Tick <= tick_hi and note_tick_hi >= tick_lo and lane_lo <= note.Lane <= lane_hi:
            found.add(note.id)
    for note in level.RushNotes:
        note_tick_hi = note.Tick + note.Duration
        if note.Tick <= tick_hi and note_tick_hi >= tick_lo and note.Lane <= lane_hi and note.Lane + 1 >= lane_lo:
            found.add(note.id)
    return found


def snap_delta_for_division(division: str) -> int:
    return SNAP_DIVISIONS.get(division, SNAP_DIVISIONS["1/8"])
