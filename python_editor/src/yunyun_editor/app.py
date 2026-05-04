from __future__ import annotations

import copy
import logging
import math
from pathlib import Path
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import time

from .audio import AudioEngine, HitSfxScheduler
from .audio_convert import convert_audio_file_to_ogg, ensure_ogg_audio
from .drafts import CURRENT_DRAFT_ID, DraftStore
from .editor_state import (
    ChartState,
    EditorState,
    MIN_LONG_NOTE_DURATION,
    add_bpm_change,
    add_phase_change,
    add_time_signature_change,
    clamp_long_note_tail_tick,
    copy_selected_notes,
    create_hold,
    create_rush,
    create_single,
    current_bpm_event,
    current_ts_event,
    delete_notes,
    find_note,
    iter_notes,
    move_selection_to,
    paste_notes_at_tick,
    place_conduct_note,
    resize_long_note_tail,
    select_note_ids_in_tick_lane_box,
    selection_after_note_click,
    selected_notes,
)
from .io import ImportedMod, build_zip_bytes, load_example_folder, parse_zip, sanitize_folder_name
from .history import HistoryManager
from .model import (
    BpmEvent,
    HoldNote,
    LANE_MAX,
    LANE_MIN,
    LevelJson,
    PhaseEvent,
    RushNote,
    SingleNote,
    SongLevelRef,
    TimeSignatureEvent,
    audio_to_music_path,
    clamp_lane,
    clamp_rush_lane,
    empty_level,
    new_id,
)
from .renderer_math import (
    NOTE_HEIGHT,
    Viewport,
    hold_visible,
    lane_to_x,
    pick_lane,
    seconds_to_y,
    stack_timeline_event_labels,
    tick_to_y,
    y_to_seconds,
)
from .timing import SNAP_DIVISIONS, build_tempo_map, seconds_to_tick, tick_to_seconds
from .waveform import WaveformEnvelope, load_waveform_bytes


PYTHON_EDITOR_DIR = Path(__file__).resolve().parents[2]
NOTE_TICK_PATH = PYTHON_EDITOR_DIR / "assets" / "audio" / "NoteTick.ogg"
AUDIO_FILETYPES = [
    ("Audio files", "*.ogg *.wav *.mp3 *.flac *.aiff *.aif *.m4a *.aac *.opus"),
    ("All files", "*.*"),
]

BG = "#14151a"
BG0 = "#101116"
BG2 = "#1b1d25"
BG3 = "#242733"
FG = "#e6e8ef"
DIM = "#a4a7b0"
MUTE = "#6f7380"
ACCENT = "#6aa9ff"
EDGE = "#b97cff"
MID = "#3fcf6f"
RUSH = "#ffb454"
PLAYHEAD = "#ff6b6b"


class ChartCanvas(tk.Canvas):
    LEFT_GUTTER = 96
    PLAYHEAD_RATIO = 0.7
    MAX_LANE_WIDTH = 140
    MIN_LANE_WIDTH = 40

    def __init__(self, master: tk.Widget, app: "YunYunEditorApp") -> None:
        super().__init__(master, bg=BG, highlightthickness=0)
        self.app = app
        self.drag: dict | None = None
        self.bind("<Button-1>", self.on_mouse_down)
        self.bind("<B1-Motion>", self.on_mouse_move)
        self.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.bind("<MouseWheel>", self.on_wheel)
        self.bind("<Configure>", lambda _event: self.redraw())

    def viewport(self) -> Viewport | None:
        level = self.app.state.active_level()
        if not level:
            return None
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        lane_count = LANE_MAX - LANE_MIN + 1
        available = max(self.MIN_LANE_WIDTH * lane_count, width - self.LEFT_GUTTER)
        lane_width = min(self.MAX_LANE_WIDTH, max(self.MIN_LANE_WIDTH, available // lane_count))
        playfield_width = lane_width * lane_count
        playfield_x = max(self.LEFT_GUTTER, round(self.LEFT_GUTTER + (width - self.LEFT_GUTTER - playfield_width) / 2))
        tempo_map = build_tempo_map(level.InitBpm, level.BpmChangeEvents)
        playhead_sec = tick_to_seconds(self.app.state.playhead_tick, tempo_map, level.ScoreOffset)
        return Viewport(
            width=width,
            height=height,
            playfield_x=playfield_x,
            playfield_width=playfield_width,
            lane_width=lane_width,
            lane_start=LANE_MIN,
            lane_count=lane_count,
            pixels_per_second=self.app.state.pixels_per_second,
            playhead_y=height * self.PLAYHEAD_RATIO,
            playhead_sec=playhead_sec,
        )

    def redraw(self) -> None:
        self.delete("all")
        level = self.app.state.active_level()
        vp = self.viewport()
        if not level or not vp:
            self.create_rectangle(0, 0, self.winfo_width(), self.winfo_height(), fill=BG, outline="")
            self.create_text(
                self.winfo_width() / 2,
                self.winfo_height() / 2,
                text="No level loaded. Import a mod ZIP or add a level.",
                fill=DIM,
                font=("Segoe UI", 11),
            )
            return
        tempo_map = build_tempo_map(level.InitBpm, level.BpmChangeEvents)
        self.create_rectangle(0, 0, vp.width, vp.height, fill=BG, outline="")
        self.draw_lanes(vp)
        self.draw_waveform(vp)
        self.draw_grid(vp, level, tempo_map)
        self.draw_events(vp, level, tempo_map)
        self.draw_notes(vp, level, tempo_map)
        self.draw_drag_overlay(vp, level, tempo_map)
        self.draw_playhead(vp)

    def draw_lanes(self, vp: Viewport) -> None:
        for idx in range(vp.lane_count):
            lane = vp.lane_start + idx
            x = lane_to_x(lane, vp)
            fill = "#1a1622" if lane in (LANE_MIN, LANE_MAX) else "#152017"
            self.create_rectangle(x, 0, x + vp.lane_width, vp.height, fill=fill, outline="#222530")
        self.create_line(vp.playfield_x + vp.playfield_width, 0, vp.playfield_x + vp.playfield_width, vp.height, fill="#222530")

    def draw_waveform(self, vp: Viewport) -> None:
        env = self.app.waveform
        if not env or not len(env.peaks):
            return
        center_x = vp.playfield_x + vp.playfield_width / 2
        max_w = vp.playfield_width * 0.42
        points_left: list[float] = []
        points_right: list[float] = []
        step = 4
        for y in range(-step, vp.height + step, step):
            sec = y_to_seconds(y, vp)
            amp = env.amplitude_at(sec)
            w = amp * max_w
            points_left.extend([center_x - w, y])
            points_right.extend([center_x + w, y])
        if len(points_left) >= 4:
            right_pairs = [(points_right[i], points_right[i + 1]) for i in range(0, len(points_right), 2)]
            flat = points_left[:]
            for px, py in reversed(right_pairs):
                flat.extend([px, py])
            self.create_polygon(flat, fill="#263f5f", outline="")

    def draw_grid(self, vp: Viewport, level: LevelJson, tempo_map) -> None:
        left = vp.playfield_x
        right = vp.playfield_x + vp.playfield_width
        ts_list = [level.InitTimeSignature, *sorted(level.TimeSignature, key=lambda ev: ev.Tick)]
        far_tick = 2_000_000
        from .timing import TPQN, bar_ticks

        tick_a = seconds_to_tick(y_to_seconds(0, vp), tempo_map, level.ScoreOffset)
        tick_b = seconds_to_tick(y_to_seconds(vp.height, vp), tempo_map, level.ScoreOffset)
        visible_min = max(0, min(tick_a, tick_b) - TPQN * 2)
        visible_max = max(tick_a, tick_b) + TPQN * 2
        label_x = min(right + 10, vp.width - 56)
        bar_number_base = 1
        for idx, ts in enumerate(ts_list):
            next_tick = ts_list[idx + 1].Tick if idx + 1 < len(ts_list) else far_tick
            bar = bar_ticks(ts)
            if next_tick < visible_min or ts.Tick > visible_max:
                if next_tick < far_tick:
                    bar_number_base += max(0, (next_tick - ts.Tick + bar - 1) // bar)
                continue
            start_bar = max(0, (visible_min - ts.Tick) // max(1, bar))
            end_bar = max(0, (min(next_tick, visible_max) - ts.Tick + bar - 1) // max(1, bar))
            for bar_idx in range(start_bar, end_bar + 1):
                tick = ts.Tick + bar_idx * max(1, bar)
                if tick >= next_tick:
                    break
                y = tick_to_y(tick, vp, tempo_map, level.ScoreOffset)
                if -2 <= y <= vp.height + 2:
                    self.create_line(left, round(y), right, round(y), fill="#3b3f4a")
                    self.create_text(label_x, round(y) - 7, text=f"Bar {bar_number_base + bar_idx}", anchor="w", fill=DIM, font=("Consolas", 9, "bold"))
            start_beat = max(0, (visible_min - ts.Tick) // TPQN)
            end_beat = max(0, (min(next_tick, visible_max) - ts.Tick + TPQN - 1) // TPQN)
            for beat_idx in range(start_beat, end_beat + 1):
                tick = ts.Tick + beat_idx * TPQN
                if tick >= next_tick:
                    break
                if (tick - ts.Tick) % bar == 0:
                    continue
                y = tick_to_y(tick, vp, tempo_map, level.ScoreOffset)
                if -2 <= y <= vp.height + 2:
                    self.create_line(left, round(y), right, round(y), fill="#262932")
                    bar_idx = (tick - ts.Tick) // max(1, bar)
                    beat_in_bar = ((tick - ts.Tick) % max(1, bar)) // TPQN + 1
                    self.create_text(label_x, round(y) - 5, text=f"{bar_number_base + bar_idx}.{beat_in_bar}", anchor="w", fill=MUTE, font=("Consolas", 8))
            if next_tick < far_tick:
                bar_number_base += max(0, (next_tick - ts.Tick + bar - 1) // bar)

    def draw_events(self, vp: Viewport, level: LevelJson, tempo_map) -> None:
        events: list[tuple[int, str, str]] = [
            (level.InitBpm.Tick, ACCENT, f"{format_bpm(level.InitBpm.Bpm)} BPM"),
            (level.InitTimeSignature.Tick, RUSH, f"{level.InitTimeSignature.Numerator}/{level.InitTimeSignature.Denominator}"),
        ]
        events.extend((ev.Tick, ACCENT, f"{format_bpm(ev.Bpm)} BPM") for ev in level.BpmChangeEvents)
        events.extend((ev.Tick, RUSH, f"{ev.Numerator}/{ev.Denominator}") for ev in level.TimeSignature)
        events.extend((ev.Tick, EDGE, "phase") for ev in level.PhaseChangeEvents)

        for event in stack_timeline_event_labels(events):
            y = tick_to_y(event.tick, vp, tempo_map, level.ScoreOffset)
            if -12 <= y <= vp.height + 12:
                text_y = y - 8 - (event.stack_index * 12)
                self.create_rectangle(0, y - 1, self.LEFT_GUTTER - 4, y + 1, fill=event.color, outline="")
                self.create_text(4, text_y, text=event.label, anchor="w", fill=event.color, font=("Consolas", 9))

    def draw_notes(self, vp: Viewport, level: LevelJson, tempo_map) -> None:
        for note in level.HoldNotes:
            self.draw_hold(vp, level, tempo_map, note)
        for note in level.RushNotes:
            self.draw_rush(vp, level, tempo_map, note)
        for note in level.SingleNotes:
            self.draw_single(vp, level, tempo_map, note)

    def draw_single(self, vp: Viewport, level: LevelJson, tempo_map, note: SingleNote) -> None:
        if not (LANE_MIN <= note.Lane <= LANE_MAX):
            return
        y = tick_to_y(note.Tick, vp, tempo_map, level.ScoreOffset)
        if y < -NOTE_HEIGHT or y > vp.height + NOTE_HEIGHT:
            return
        x = lane_to_x(note.Lane, vp)
        pad = 6
        fill = EDGE if note.Lane in (LANE_MIN, LANE_MAX) else MID
        self.create_rectangle(x + pad, y - NOTE_HEIGHT / 2, x + vp.lane_width - pad, y + NOTE_HEIGHT / 2, fill=fill, outline="")
        self.create_line(x + pad, y - NOTE_HEIGHT / 2, x + vp.lane_width - pad, y - NOTE_HEIGHT / 2, fill="#ffffff")
        if note.id in self.app.state.selection:
            self.create_rectangle(x + pad - 2, y - NOTE_HEIGHT / 2 - 2, x + vp.lane_width - pad + 2, y + NOTE_HEIGHT / 2 + 2, outline=ACCENT)

    def draw_long_note_tail(self, left: float, right: float, y: float, fill: str, selected: bool) -> None:
        tail_half_h = max(4.0, NOTE_HEIGHT * 0.22)
        inset = 4.0
        top = y - tail_half_h
        bottom = y + tail_half_h
        self.create_rectangle(left + inset, top, right - inset, bottom, fill=fill, outline="")
        if selected:
            self.create_rectangle(left + inset - 2, top - 2, right - inset + 2, bottom + 2, outline=ACCENT)

    def long_note_tail_hit(self, x: int, y: int, left: float, right: float, tail_y: float) -> bool:
        half_h = NOTE_HEIGHT / 2 + 2
        return left <= x < right and abs(y - tail_y) <= half_h

    def draw_hold(self, vp: Viewport, level: LevelJson, tempo_map, note: HoldNote) -> None:
        if not (LANE_MIN <= note.Lane <= LANE_MAX):
            return
        y1 = tick_to_y(note.Tick, vp, tempo_map, level.ScoreOffset)
        y2 = tick_to_y(note.Tick + note.Duration, vp, tempo_map, level.ScoreOffset)
        if not hold_visible(y1, y2, vp.height):
            return
        x = lane_to_x(note.Lane, vp)
        pad = 6
        rw = vp.lane_width - pad * 2
        fill = "#7d579f" if note.Lane in (LANE_MIN, LANE_MAX) else "#2b8949"
        self.create_rectangle(x + pad + rw * 0.25, min(y1, y2), x + pad + rw * 0.75, max(y1, y2), fill=fill, outline="")
        tail_fill = EDGE if note.Lane in (LANE_MIN, LANE_MAX) else MID
        self.draw_long_note_tail(x + pad, x + vp.lane_width - pad, y2, tail_fill, note.id in self.app.state.selection)
        self.draw_single(vp, level, tempo_map, note)

    def draw_rush(self, vp: Viewport, level: LevelJson, tempo_map, note: RushNote) -> None:
        if note.Lane < LANE_MIN or note.Lane + 1 > LANE_MAX:
            return
        y1 = tick_to_y(note.Tick, vp, tempo_map, level.ScoreOffset)
        y2 = tick_to_y(note.Tick + note.Duration, vp, tempo_map, level.ScoreOffset)
        if not hold_visible(y1, y2, vp.height):
            return
        x1 = lane_to_x(note.Lane, vp)
        x2 = lane_to_x(note.Lane + 2, vp)
        pad = 6
        self.create_rectangle(x1 + pad + (x2 - x1) * 0.15, min(y1, y2), x2 - pad - (x2 - x1) * 0.15, max(y1, y2), fill="#8a602d", outline="")
        self.draw_long_note_tail(x1 + pad, x2 - pad, y2, RUSH, note.id in self.app.state.selection)
        self.create_rectangle(x1 + pad, y1 - NOTE_HEIGHT / 2, x2 - pad, y1 + NOTE_HEIGHT / 2, fill=RUSH, outline="")
        if note.id in self.app.state.selection:
            self.create_rectangle(x1 + pad - 2, y1 - NOTE_HEIGHT / 2 - 2, x2 - pad + 2, y1 + NOTE_HEIGHT / 2 + 2, outline=ACCENT)

    def draw_drag_overlay(self, vp: Viewport, level: LevelJson, tempo_map) -> None:
        if not self.drag:
            return
        if self.drag.get("kind") == "box":
            x1 = self.drag["start_x"]
            y1 = tick_to_y(self.drag["start_tick"], vp, tempo_map, level.ScoreOffset)
            x2 = self.drag.get("current_x", x1)
            y2 = tick_to_y(self.drag.get("current_tick", self.drag["start_tick"]), vp, tempo_map, level.ScoreOffset)
            self.create_rectangle(x1, y1, x2, y2, fill="#6aa9ff", outline="", stipple="gray75")
            self.create_rectangle(x1, y1, x2, y2, outline=ACCENT, dash=(3, 2))
            return
        if self.drag.get("kind") == "resize_tail":
            y1 = tick_to_y(self.drag["start_tick"], vp, tempo_map, level.ScoreOffset)
            y2 = tick_to_y(self.drag["current_tick"], vp, tempo_map, level.ScoreOffset)
            lane = self.drag["lane"]
            pad = 6
            if self.drag["note_kind"] == "hold":
                x = lane_to_x(lane, vp)
                rw = vp.lane_width - pad * 2
                self.create_rectangle(
                    x + pad + rw * 0.25,
                    min(y1, y2),
                    x + pad + rw * 0.75,
                    max(y1, y2),
                    fill=ACCENT,
                    outline="",
                    stipple="gray50",
                )
                tail_fill = EDGE if lane in (LANE_MIN, LANE_MAX) else MID
                self.draw_long_note_tail(x + pad, x + vp.lane_width - pad, y2, tail_fill, True)
            else:
                x1 = lane_to_x(lane, vp)
                x2 = lane_to_x(lane + 2, vp)
                self.create_rectangle(
                    x1 + pad + (x2 - x1) * 0.15,
                    min(y1, y2),
                    x2 - pad - (x2 - x1) * 0.15,
                    max(y1, y2),
                    fill=RUSH,
                    outline="",
                    stipple="gray50",
                )
                self.draw_long_note_tail(x1 + pad, x2 - pad, y2, RUSH, True)
            return
        if self.drag.get("kind") != "place":
            return
        y1 = tick_to_y(self.drag["start_tick"], vp, tempo_map, level.ScoreOffset)
        y2 = tick_to_y(self.drag["current_tick"], vp, tempo_map, level.ScoreOffset)
        lane = self.drag["lane"]
        x = lane_to_x(lane, vp)
        pad = 6
        width = vp.lane_width - pad * 2
        fill = "#6aa9ff" if self.drag["tool"] == "hold" else RUSH
        if self.drag["tool"] == "rush":
            width = vp.lane_width * 2 - pad * 2
        self.create_rectangle(x + pad, min(y1, y2), x + pad + width, max(y1, y2), fill=fill, outline="", stipple="gray50")

    def draw_playhead(self, vp: Viewport) -> None:
        y = vp.playhead_y
        self.create_line(vp.playfield_x, y, vp.playfield_x + vp.playfield_width, y, fill=PLAYHEAD)
        self.create_polygon(vp.playfield_x - 8, y - 5, vp.playfield_x, y, vp.playfield_x - 8, y + 5, fill=PLAYHEAD, outline="")

    def event_xy(self, event: tk.Event) -> tuple[int, int]:
        return int(event.x), int(event.y)

    def pick_cell(self, x: int, y: int, vp: Viewport, level: LevelJson) -> tuple[int, int]:
        lane = pick_lane(x, vp)
        tempo_map = build_tempo_map(level.InitBpm, level.BpmChangeEvents)
        sec = y_to_seconds(y, vp)
        tick = seconds_to_tick(sec, tempo_map, level.ScoreOffset)
        return lane, max(0, tick)

    def hit_test(self, x: int, y: int, vp: Viewport, level: LevelJson):
        tempo_map = build_tempo_map(level.InitBpm, level.BpmChangeEvents)
        half_h = NOTE_HEIGHT / 2 + 2
        for note in reversed(level.RushNotes):
            px1 = lane_to_x(note.Lane, vp)
            px2 = lane_to_x(note.Lane + 2, vp)
            py2 = tick_to_y(note.Tick + note.Duration, vp, tempo_map, level.ScoreOffset)
            if self.long_note_tail_hit(x, y, px1 + 6, px2 - 6, py2):
                return "rush-tail", note
        for note in reversed(level.HoldNotes):
            px = lane_to_x(note.Lane, vp)
            py2 = tick_to_y(note.Tick + note.Duration, vp, tempo_map, level.ScoreOffset)
            if self.long_note_tail_hit(x, y, px + 6, px + vp.lane_width - 6, py2):
                return "hold-tail", note
        for note in reversed(level.SingleNotes):
            px = lane_to_x(note.Lane, vp)
            py = tick_to_y(note.Tick, vp, tempo_map, level.ScoreOffset)
            if px <= x < px + vp.lane_width and abs(y - py) <= half_h:
                return "single", note
        for note in reversed(level.HoldNotes):
            px = lane_to_x(note.Lane, vp)
            py1 = tick_to_y(note.Tick, vp, tempo_map, level.ScoreOffset)
            py2 = tick_to_y(note.Tick + note.Duration, vp, tempo_map, level.ScoreOffset)
            if px <= x < px + vp.lane_width and min(py1, py2) - half_h <= y <= max(py1, py2) + half_h:
                return "hold", note
        for note in reversed(level.RushNotes):
            px1 = lane_to_x(note.Lane, vp)
            px2 = lane_to_x(note.Lane + 2, vp)
            py1 = tick_to_y(note.Tick, vp, tempo_map, level.ScoreOffset)
            py2 = tick_to_y(note.Tick + note.Duration, vp, tempo_map, level.ScoreOffset)
            if px1 <= x < px2 and min(py1, py2) - half_h <= y <= max(py1, py2) + half_h:
                return "rush", note
        return None

    def on_mouse_down(self, event: tk.Event) -> None:
        level = self.app.state.active_level()
        vp = self.viewport()
        if not level or not vp:
            return
        x, y = self.event_xy(event)
        if x < vp.playfield_x or x >= vp.playfield_x + vp.playfield_width:
            tempo_map = build_tempo_map(level.InitBpm, level.BpmChangeEvents)
            tick = seconds_to_tick(y_to_seconds(y, vp), tempo_map, level.ScoreOffset)
            self.app.seek_tick(max(0, tick))
            return
        hit = self.hit_test(x, y, vp, level)
        tool = self.app.state.tool
        if tool == "eraser" and hit:
            self.app.push_history("Erase note")
            delete_notes(level, [hit[1].id])
            self.app.state.selection.clear()
            self.app.refresh_all()
            return
        if hit:
            additive = bool(event.state & 0x0001)
            self.app.state.selection = selection_after_note_click(self.app.state.selection, hit[1].id, additive)
            if additive:
                self.app.refresh_all()
                return
            if hit[0] in ("hold-tail", "rush-tail"):
                self.drag = {
                    "kind": "resize_tail",
                    "note_id": hit[1].id,
                    "note_kind": "rush" if hit[0] == "rush-tail" else "hold",
                    "lane": hit[1].Lane,
                    "start_tick": hit[1].Tick,
                    "current_tick": hit[1].Tick + hit[1].Duration,
                }
            else:
                lane, tick = self.pick_cell(x, y, vp, level)
                self.drag = {"kind": "move", "anchor_id": hit[1].id, "start_lane": lane, "start_tick": tick}
            self.app.refresh_all()
            return
        lane, tick = self.pick_cell(x, y, vp, level)
        tick = self.app.state.snapped_tick(tick)
        if tool == "single":
            self.app.push_history("Place note")
            note = create_single(level, tick, lane)
            self.app.state.select_only(note.id)
            self.app.refresh_all()
        elif tool in ("hold", "rush"):
            lane = clamp_rush_lane(lane) if tool == "rush" else clamp_lane(lane)
            self.drag = {"kind": "place", "tool": tool, "lane": lane, "start_tick": tick, "current_tick": tick}
        elif tool == "select":
            self.drag = {
                "kind": "box",
                "start_x": x,
                "start_y": y,
                "start_tick": self.pick_cell(x, y, vp, level)[1],
                "current_x": x,
                "current_y": y,
                "current_tick": self.pick_cell(x, y, vp, level)[1],
                "additive": bool(event.state & 0x0001),
            }

    def on_mouse_move(self, event: tk.Event) -> None:
        if not self.drag:
            return
        level = self.app.state.active_level()
        vp = self.viewport()
        if not level or not vp:
            return
        x, y = self.event_xy(event)
        lane, tick = self.pick_cell(x, y, vp, level)
        if self.drag["kind"] == "place":
            self.drag["current_tick"] = self.app.state.snapped_tick(tick)
            self.redraw()
        elif self.drag["kind"] == "resize_tail":
            snapped_tick = self.app.state.snapped_tick(tick)
            self.drag["current_tick"] = clamp_long_note_tail_tick(self.drag["start_tick"], snapped_tick)
            self.redraw()
        elif self.drag["kind"] == "move":
            self.drag["target_lane"] = lane
            self.drag["target_tick"] = self.app.state.snapped_tick(tick)
        elif self.drag["kind"] == "box":
            self.drag["current_x"] = x
            self.drag["current_y"] = y
            self.drag["current_tick"] = tick
            self.redraw()

    def on_mouse_up(self, event: tk.Event) -> None:
        if not self.drag:
            return
        level = self.app.state.active_level()
        if not level:
            self.drag = None
            return
        if self.drag["kind"] == "place":
            self.app.push_history("Place long note")
            if self.drag["tool"] == "hold":
                note = create_hold(level, self.drag["start_tick"], self.drag["current_tick"], self.drag["lane"])
            else:
                note = create_rush(level, self.drag["start_tick"], self.drag["current_tick"], self.drag["lane"])
            self.app.state.select_only(note.id)
        elif self.drag["kind"] == "resize_tail":
            vp = self.viewport()
            if vp:
                _lane, tick = self.pick_cell(*self.event_xy(event), vp, level)
                tick = self.app.state.snapped_tick(tick)
                tick = max(self.drag["start_tick"] + MIN_LONG_NOTE_DURATION, tick)
                kind, note = find_note(level, self.drag["note_id"])
                if kind in ("hold", "rush") and isinstance(note, HoldNote) and note.Tick + note.Duration != tick:
                    self.app.push_history("Resize long note")
                    resize_long_note_tail(level, self.drag["note_id"], tick)
        elif self.drag["kind"] == "move":
            vp = self.viewport()
            if vp:
                x, y = self.event_xy(event)
                lane, tick = self.pick_cell(x, y, vp, level)
                tick = self.app.state.snapped_tick(tick)
                self.app.push_history("Move note")
                move_selection_to(level, self.app.state.selection, self.drag["anchor_id"], tick, lane)
        elif self.drag["kind"] == "box":
            vp = self.viewport()
            if vp:
                x1 = int(self.drag["start_x"])
                y1 = int(self.drag["start_y"])
                x2 = int(self.drag.get("current_x", x1))
                y2 = int(self.drag.get("current_y", y1))
                if abs(x2 - x1) < 4 and abs(y2 - y1) < 4:
                    if not self.drag.get("additive"):
                        self.app.state.clear_selection()
                else:
                    lane_a = pick_lane(x1, vp)
                    lane_b = pick_lane(x2, vp)
                    tick_a = int(self.drag["start_tick"])
                    tick_b = int(self.drag.get("current_tick", tick_a))
                    ids = select_note_ids_in_tick_lane_box(level, tick_a, tick_b, lane_a, lane_b)
                    if self.drag.get("additive"):
                        self.app.state.selection.update(ids)
                    else:
                        self.app.state.selection = ids
        self.drag = None
        self.app.refresh_all()

    def on_wheel(self, event: tk.Event) -> None:
        if event.state & 0x0004:
            factor = 1.15 if event.delta > 0 else 1 / 1.15
            self.app.state.set_zoom(self.app.state.pixels_per_second * factor)
        else:
            self.app.seek_tick(max(0, self.app.state.playhead_tick - int(event.delta / 120 * 480)))
        self.app.refresh_all()


class YunYunEditorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.log_path = DraftStore().root / "editor.log"
        logging.basicConfig(
            filename=self.log_path,
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
        self.title("YunYunEditor Desktop")
        self.geometry("1280x820")
        self.configure(bg=BG0)
        self.state_obj = EditorState()
        self.history = HistoryManager()
        self.audio = AudioEngine()
        self.scheduler = HitSfxScheduler()
        self.drafts = DraftStore()
        self.waveform: WaveformEnvelope | None = None
        self.last_tick_for_sfx = 0
        self.current_draft_id: str | None = None
        self.current_draft_name = ""
        self.status_after_id: str | None = None
        self.conduct_keys_down: set[str] = set()
        self.note_clipboard: list[tuple[str, SingleNote]] = []
        self.vars: dict[str, tk.Variable] = {}
        self._build_style()
        self._build_ui()
        self._load_sfx()
        self.after(0, self.resume_last_draft_on_launch)
        self.after(16, self.tick)

    @property
    def state(self) -> EditorState:
        return self.state_obj

    def report_callback_exception(self, exc, val, tb) -> None:
        logging.error("Unhandled Tk callback exception", exc_info=(exc, val, tb))
        message = "".join(traceback.format_exception_only(exc, val)).strip()
        self.set_status(f"Unexpected error: {message}. Log: {self.log_path}", temporary=False)
        messagebox.showerror("Unexpected editor error", f"{message}\n\nLog written to:\n{self.log_path}")

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG0, foreground=FG, fieldbackground=BG2, bordercolor="#303441")
        style.configure("TFrame", background=BG0)
        style.configure("Panel.TFrame", background=BG)
        style.configure("TLabel", background=BG0, foreground=FG)
        style.configure("Panel.TLabel", background=BG, foreground=FG)
        style.configure("TButton", background=BG2, foreground=FG)
        style.configure("TCheckbutton", background=BG0, foreground=FG)
        style.configure("TRadiobutton", background=BG, foreground=FG)
        style.configure("Treeview", background=BG2, fieldbackground=BG2, foreground=FG)
        style.map("Treeview", background=[("selected", "#254766")])

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        for label, command in [
            ("New", self.new_project),
            ("Import ZIP", self.import_zip),
            ("Import Audio", self.import_audio),
            ("Export ZIP", self.export_zip),
        ]:
            ttk.Button(toolbar, text=label, command=command, takefocus=False).pack(side=tk.LEFT, padx=3, pady=5)

        self.time_label = ttk.Label(toolbar, text="00:00.000 / 00:00.000")
        self.time_label.pack(side=tk.RIGHT, padx=8)

        body = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        left = ttk.Frame(body, style="Panel.TFrame", width=300)
        center = ttk.Frame(body, style="TFrame")
        right = ttk.Frame(body, style="Panel.TFrame", width=350)
        body.add(left, weight=0)
        body.add(center, weight=1)
        body.add(right, weight=0)

        self._build_left(left)
        self.canvas = ChartCanvas(center, self)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self._build_transport(center)
        self._build_right(right)
        self.status_label = ttk.Label(self, text="Ready", anchor="w")
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(0, 3))
        self.disable_button_focus(self)
        self.bind_all("<space>", self.on_space_shortcut)
        self.bind_all("<Control-s>", self.on_save_shortcut)
        self.bind_all("<Control-S>", self.on_save_shortcut)
        self.bind_all("<Control-z>", self.on_undo_shortcut)
        self.bind_all("<Control-Z>", self.on_undo_shortcut)
        self.bind_all("<Control-Shift-Z>", self.on_redo_shortcut)
        self.bind_all("<Control-y>", self.on_redo_shortcut)
        self.bind_all("<Control-Y>", self.on_redo_shortcut)
        self.bind_all("<Control-e>", self.on_export_shortcut)
        self.bind_all("<Control-E>", self.on_export_shortcut)
        self.bind_all("<Control-o>", self.on_import_shortcut)
        self.bind_all("<Control-O>", self.on_import_shortcut)
        self.bind_all("<Control-c>", self.on_copy_shortcut)
        self.bind_all("<Control-C>", self.on_copy_shortcut)
        self.bind_all("<Control-v>", self.on_paste_shortcut)
        self.bind_all("<Control-V>", self.on_paste_shortcut)
        self.bind_class("TButton", "<space>", self.on_space_shortcut)
        self.bind_class("TCheckbutton", "<space>", self.on_space_shortcut)
        self.bind_class("TRadiobutton", "<space>", self.on_space_shortcut)
        for key in ("s", "d", "k", "l"):
            self.bind_all(f"<KeyPress-{key}>", self.on_conduct_key_press)
            self.bind_all(f"<KeyPress-{key.upper()}>", self.on_conduct_key_press)
            self.bind_all(f"<KeyRelease-{key}>", self.on_conduct_key_release)
            self.bind_all(f"<KeyRelease-{key.upper()}>", self.on_conduct_key_release)
        self.bind("<Home>", lambda _e: self.seek_tick(0))
        self.bind("<End>", lambda _e: self.seek_end())
        self.bind("<Delete>", lambda _e: self.delete_selection())
        self.bind("<BackSpace>", lambda _e: self.delete_selection())
        self.bind(",", lambda _e: self.nudge_selected(-SNAP_DIVISIONS[self.state.snap_division], 0))
        self.bind(".", lambda _e: self.nudge_selected(SNAP_DIVISIONS[self.state.snap_division], 0))
        self.bind("<less>", lambda _e: self.nudge_selected(-480, 0))
        self.bind("<greater>", lambda _e: self.nudge_selected(480, 0))
        self.bind("[", lambda _e: self.step_snap_division(-1))
        self.bind("]", lambda _e: self.step_snap_division(1))
        for key, tool in [("1", "single"), ("2", "hold"), ("3", "rush"), ("4", "eraser"), ("v", "select")]:
            self.bind(key, lambda e, t=tool: self.on_tool_shortcut(e, t))

    def disable_button_focus(self, widget: tk.Widget) -> None:
        for child in widget.winfo_children():
            try:
                if child.winfo_class() in {"TButton", "TCheckbutton", "TRadiobutton", "Button", "Checkbutton", "Radiobutton", "Scale", "TScale"}:
                    child.configure(takefocus=False)
            except tk.TclError:
                pass
            self.disable_button_focus(child)

    def focus_is_text_input(self) -> bool:
        widget = self.focus_get()
        if not widget:
            return False
        return widget.winfo_class() in {"Entry", "TEntry", "Text", "TCombobox", "Spinbox", "TSpinbox"}

    def on_space_shortcut(self, _event: tk.Event):
        if self.focus_is_text_input():
            return None
        self.toggle_play()
        return "break"

    def on_save_shortcut(self, _event: tk.Event):
        self.quick_save_draft()
        return "break"

    def on_undo_shortcut(self, _event: tk.Event):
        self.undo()
        return "break"

    def on_redo_shortcut(self, _event: tk.Event):
        self.redo()
        return "break"

    def on_export_shortcut(self, _event: tk.Event):
        if self.focus_is_text_input():
            return None
        self.export_zip()
        return "break"

    def on_import_shortcut(self, _event: tk.Event):
        if self.focus_is_text_input():
            return None
        self.import_zip()
        return "break"

    def on_copy_shortcut(self, _event: tk.Event):
        if self.focus_is_text_input():
            return None
        self.copy_selection_to_clipboard()
        return "break"

    def on_paste_shortcut(self, _event: tk.Event):
        if self.focus_is_text_input():
            return None
        self.paste_note_clipboard()
        return "break"

    def on_tool_shortcut(self, event: tk.Event, tool: str):
        if self.focus_is_text_input() or (event.state & 0x0004):
            return None
        self.set_tool(tool)
        return "break"

    def on_conduct_key_press(self, event: tk.Event):
        key = (event.keysym or "").lower()
        if event.state & 0x0004 or self.focus_is_text_input() or not self.state.conduct_mode:
            if key == "s" and not (event.state & 0x0004) and not self.focus_is_text_input():
                self.toggle_snap()
                return "break"
            return None
        if key in self.conduct_keys_down:
            return "break"
        self.conduct_keys_down.add(key)
        self.push_history("Conduct note")
        note = place_conduct_note(self.state, key)
        if note:
            self.state.selection = {note.id}
            self.refresh_selection()
            self.canvas.redraw()
            self.set_status(f"Conduct: lane {note.Lane} at tick {note.Tick}", temporary=True)
        return "break"

    def on_conduct_key_release(self, event: tk.Event):
        self.conduct_keys_down.discard((event.keysym or "").lower())
        if self.state.conduct_mode and not self.focus_is_text_input():
            return "break"
        return None

    def push_history(self, _label: str = "") -> None:
        self.history.push(self.state)

    def undo(self) -> None:
        previous_audio = self.state.chart.audio_bytes
        if not self.history.undo(self.state):
            self.set_status("Nothing to undo.", temporary=True)
            return
        self.after_history_restore(previous_audio)
        self.set_status("Undid last edit.", temporary=True)

    def redo(self) -> None:
        previous_audio = self.state.chart.audio_bytes
        if not self.history.redo(self.state):
            self.set_status("Nothing to redo.", temporary=True)
            return
        self.after_history_restore(previous_audio)
        self.set_status("Redid edit.", temporary=True)

    def after_history_restore(self, previous_audio: bytes) -> None:
        if self.state.chart.audio_bytes != previous_audio:
            self.load_audio_bytes(self.state.chart.audio_bytes)
        self.sync_audio_to_playhead()
        self.refresh_all()

    def sync_audio_to_playhead(self) -> None:
        level = self.state.active_level()
        if not level:
            return
        tempo_map = build_tempo_map(level.InitBpm, level.BpmChangeEvents)
        self.audio.seek(tick_to_seconds(self.state.playhead_tick, tempo_map, level.ScoreOffset))
        self.scheduler.reset()
        self.last_tick_for_sfx = self.state.playhead_tick

    def toggle_snap(self) -> None:
        self.state.snap_enabled = not self.state.snap_enabled
        self.vars["snap"].set(self.state.snap_enabled)
        self.set_status(f"Snap {'on' if self.state.snap_enabled else 'off'}.", temporary=True)

    def step_snap_division(self, direction: int) -> None:
        divisions = ["1/3", "1/4", "1/6", "1/8", "1/16", "1/32"]
        current = self.state.snap_division
        idx = divisions.index(current) if current in divisions else divisions.index("1/8")
        next_idx = max(0, min(len(divisions) - 1, idx + direction))
        self.state.snap_division = divisions[next_idx]
        self.vars["snap_division"].set(self.state.snap_division)
        self.set_status(f"Snap division {self.state.snap_division}.", temporary=True)

    def set_status(self, message: str, temporary: bool = True) -> None:
        if hasattr(self, "status_label"):
            self.status_label.configure(text=message)
        if self.status_after_id:
            self.after_cancel(self.status_after_id)
            self.status_after_id = None
        if temporary:
            self.status_after_id = self.after(6000, lambda: self.status_label.configure(text="Ready"))

    def draft_display_name(self) -> str:
        return self.state.chart.song.Title or self.state.chart.song.ID or "Untitled"

    @staticmethod
    def _format_project_value(value: str) -> str:
        value = value.strip()
        return value or "(blank)"

    def _save_overwrite_warning(self, draft_id: str) -> str | None:
        meta = self.drafts.get_meta(draft_id)
        if not meta:
            return None
        saved_identity = self.drafts.get_saved_song_identity(draft_id)
        saved_song_id, saved_song_title = saved_identity or (meta.song_id, meta.song_title)
        mismatches: list[str] = []
        current_song_id = self.state.chart.song.ID.strip()
        if current_song_id != saved_song_id.strip():
            mismatches.append(
                f'ID: "{self._format_project_value(saved_song_id)}" -> "{self._format_project_value(current_song_id)}"'
            )
        current_song_title = self.state.chart.song.Title.strip()
        if current_song_title != saved_song_title.strip():
            mismatches.append(
                f'Name: "{self._format_project_value(saved_song_title)}" -> "{self._format_project_value(current_song_title)}"'
            )
        if not mismatches:
            return None
        target = 'the "working" entry' if draft_id == CURRENT_DRAFT_ID else f'"{meta.name or "current draft"}"'
        return (
            f"Saving now will overwrite {target} instead of creating a new save.\n\n"
            "The chart's project values changed since this save was loaded:\n"
            f"{'\n'.join(mismatches)}\n\n"
            'Use "Save As" if you want a separate draft.\n\n'
            "Save anyway?"
        )

    def _build_left(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Song", style="Panel.TLabel").pack(anchor="w", padx=8, pady=(8, 2))
        fields = ["ID", "Audio", "Title", "Artist", "Lyricist", "Composer", "Arranger"]
        for field_name in fields:
            row = ttk.Frame(parent, style="Panel.TFrame")
            row.pack(fill=tk.X, padx=8, pady=2)
            ttk.Label(row, text=field_name, width=9, style="Panel.TLabel").pack(side=tk.LEFT)
            var = tk.StringVar()
            self.vars[f"song_{field_name}"] = var
            entry = ttk.Entry(row, textvariable=var)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            entry.bind("<FocusOut>", lambda _e, f=field_name, v=var: self.update_song(f, v.get()))
            entry.bind("<Return>", lambda _e, f=field_name, v=var: self.update_song(f, v.get()))

        ttk.Separator(parent).pack(fill=tk.X, pady=6)
        ttk.Label(parent, text="Levels", style="Panel.TLabel").pack(anchor="w", padx=8)
        self.level_list = tk.Listbox(parent, bg=BG2, fg=FG, height=8, selectbackground="#254766", borderwidth=0)
        self.level_list.pack(fill=tk.X, padx=8, pady=4)
        self.level_list.bind("<<ListboxSelect>>", lambda _e: self.select_level_from_list())
        level_buttons = ttk.Frame(parent, style="Panel.TFrame")
        level_buttons.pack(fill=tk.X, padx=8)
        ttk.Button(level_buttons, text="+ Level", command=self.add_level).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(level_buttons, text="Duplicate", command=self.duplicate_level).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(level_buttons, text="Remove", command=self.remove_level).pack(side=tk.LEFT, expand=True, fill=tk.X)

        ttk.Label(parent, text="Active Level", style="Panel.TLabel").pack(anchor="w", padx=8, pady=(8, 2))
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(row, text="Offset s", width=9, style="Panel.TLabel").pack(side=tk.LEFT)
        var = tk.StringVar()
        self.vars["level_score_offset"] = var
        self.level_score_offset_entry = ttk.Entry(row, textvariable=var)
        self.level_score_offset_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.level_score_offset_entry.bind("<FocusOut>", lambda _e, v=var: self.update_level_score_offset(v.get()))
        self.level_score_offset_entry.bind("<Return>", lambda _e, v=var: self.update_level_score_offset(v.get()))

        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(row, text="Init BPM", width=9, style="Panel.TLabel").pack(side=tk.LEFT)
        var = tk.StringVar()
        self.vars["level_init_bpm"] = var
        self.level_init_bpm_entry = ttk.Entry(row, textvariable=var)
        self.level_init_bpm_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.level_init_bpm_entry.bind("<FocusOut>", lambda _e, v=var: self.update_level_init_bpm(v.get()))
        self.level_init_bpm_entry.bind("<Return>", lambda _e, v=var: self.update_level_init_bpm(v.get()))

        ttk.Separator(parent).pack(fill=tk.X, pady=6)
        ttk.Label(parent, text="Drafts", style="Panel.TLabel").pack(anchor="w", padx=8)
        self.draft_list = tk.Listbox(parent, bg=BG2, fg=FG, height=8, selectbackground="#254766", borderwidth=0)
        self.draft_list.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        draft_buttons = ttk.Frame(parent, style="Panel.TFrame")
        draft_buttons.pack(fill=tk.X, padx=8, pady=(0, 8))
        ttk.Button(draft_buttons, text="Save", command=self.quick_save_draft, takefocus=False).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(draft_buttons, text="Save As", command=self.save_draft_as, takefocus=False).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(draft_buttons, text="Load", command=self.load_selected_draft, takefocus=False).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(draft_buttons, text="Delete", command=self.delete_selected_draft, takefocus=False).pack(side=tk.LEFT, expand=True, fill=tk.X)

    def _build_transport(self, parent: ttk.Frame) -> None:
        transport = ttk.Frame(parent)
        transport.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Button(transport, text="|<", command=lambda: self.seek_tick(0)).pack(side=tk.LEFT, padx=2, pady=4)
        self.play_button = ttk.Button(transport, text="Play", command=self.toggle_play)
        self.play_button.pack(side=tk.LEFT, padx=2, pady=4)
        ttk.Button(transport, text=">|", command=self.seek_end).pack(side=tk.LEFT, padx=2, pady=4)

        self.vars["snap"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(transport, text="snap", variable=self.vars["snap"], command=self.update_snap).pack(side=tk.LEFT, padx=8)
        self.vars["snap_division"] = tk.StringVar(value=self.state.snap_division)
        ttk.Combobox(transport, values=list(SNAP_DIVISIONS.keys()), width=6, textvariable=self.vars["snap_division"], state="readonly").pack(side=tk.LEFT)
        self.vars["snap_division"].trace_add("write", lambda *_: self.update_snap())

        ttk.Button(transport, text="-", command=lambda: self.set_zoom(self.state.pixels_per_second / 1.25)).pack(side=tk.LEFT, padx=(12, 1))
        self.zoom_label = ttk.Label(transport, text=f"{self.state.pixels_per_second} px/s")
        self.zoom_label.pack(side=tk.LEFT)
        ttk.Button(transport, text="+", command=lambda: self.set_zoom(self.state.pixels_per_second * 1.25)).pack(side=tk.LEFT, padx=1)

        ttk.Label(transport, text="Speed").pack(side=tk.LEFT, padx=(14, 2))
        self.vars["speed"] = tk.DoubleVar(value=1.0)
        ttk.Scale(transport, from_=0.25, to=2.0, variable=self.vars["speed"], command=self.update_speed).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self.speed_label = ttk.Label(transport, text="1.00x", width=6)
        self.speed_label.pack(side=tk.LEFT)
        self.vars["sfx"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(transport, text="hit SFX", variable=self.vars["sfx"], command=self.update_sfx_toggle).pack(side=tk.LEFT, padx=8)
        self.vars["conduct"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(transport, text="conduct S/D/K/L", variable=self.vars["conduct"], command=self.update_conduct_toggle).pack(side=tk.LEFT, padx=8)

    def _build_right(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Tools", style="Panel.TLabel").pack(anchor="w", padx=8, pady=(8, 2))
        self.vars["tool"] = tk.StringVar(value=self.state.tool)
        tool_frame = ttk.Frame(parent, style="Panel.TFrame")
        tool_frame.pack(fill=tk.X, padx=8)
        for label, value in [("Select", "select"), ("Single", "single"), ("Hold", "hold"), ("Rush", "rush"), ("Eraser", "eraser")]:
            ttk.Radiobutton(tool_frame, text=label, value=value, variable=self.vars["tool"], command=lambda v=value: self.set_tool(v)).pack(anchor="w")

        self._build_shortcuts(parent)

        ttk.Separator(parent).pack(fill=tk.X, pady=6)
        ttk.Label(parent, text="Selection", style="Panel.TLabel").pack(anchor="w", padx=8)
        self.selection_label = ttk.Label(parent, text="Click a note to select.", style="Panel.TLabel")
        self.selection_label.pack(anchor="w", padx=8, pady=4)
        nudge = ttk.Frame(parent, style="Panel.TFrame")
        nudge.pack(fill=tk.X, padx=8)
        ttk.Button(nudge, text="-snap", command=lambda: self.nudge_selected(-SNAP_DIVISIONS[self.state.snap_division], 0)).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(nudge, text="+snap", command=lambda: self.nudge_selected(SNAP_DIVISIONS[self.state.snap_division], 0)).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(nudge, text="< lane", command=lambda: self.nudge_selected(0, -1)).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(nudge, text="lane >", command=lambda: self.nudge_selected(0, 1)).pack(side=tk.LEFT, expand=True, fill=tk.X)

        ttk.Separator(parent).pack(fill=tk.X, pady=6)
        ttk.Label(parent, text="Events", style="Panel.TLabel").pack(anchor="w", padx=8)
        self.event_tabs = ttk.Notebook(parent)
        self.event_tabs.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self.event_trees: dict[str, ttk.Treeview] = {}
        for kind, columns in [("bpm", ("Tick", "BPM")), ("ts", ("Tick", "Num", "Den")), ("phase", ("Tick",))]:
            frame = ttk.Frame(self.event_tabs, style="Panel.TFrame")
            self.event_tabs.add(frame, text={"bpm": "BPM", "ts": "Crotchets Per Bar", "phase": "Level End"}[kind])
            tree = ttk.Treeview(frame, columns=columns, show="headings", height=8)
            for col in columns:
                tree.heading(col, text=col)
                tree.column(col, width=70, stretch=True)
            tree.pack(fill=tk.BOTH, expand=True)
            tree.bind("<<TreeviewSelect>>", lambda _e, k=kind: self.populate_event_editor(k))
            self.event_trees[kind] = tree
            ttk.Button(frame, text=f"+ {kind.upper()} change", command=lambda k=kind: self.add_event(k)).pack(fill=tk.X, pady=3)

        edit = ttk.Frame(parent, style="Panel.TFrame")
        edit.pack(fill=tk.X, padx=8, pady=(0, 8))
        self.vars["event_tick"] = tk.StringVar()
        self.vars["event_a"] = tk.StringVar()
        self.vars["event_b"] = tk.StringVar()
        for label, key in [("Tick", "event_tick"), ("A", "event_a"), ("B", "event_b")]:
            ttk.Label(edit, text=label, style="Panel.TLabel").pack(side=tk.LEFT)
            ttk.Entry(edit, textvariable=self.vars[key], width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(edit, text="Apply", command=self.apply_event_edit).pack(side=tk.LEFT, padx=2)
        ttk.Button(edit, text="Delete", command=self.delete_event).pack(side=tk.LEFT, padx=2)

    def _build_shortcuts(self, parent: ttk.Frame) -> None:
        ttk.Separator(parent).pack(fill=tk.X, pady=6)
        ttk.Label(parent, text="Shortcuts", style="Panel.TLabel").pack(anchor="w", padx=8)
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(fill=tk.X, padx=8, pady=(0, 4))
        rows = [
            ("Space", "Play / pause"),
            ("Home / End", "Seek start / end"),
            ("1 / 2 / 3 / 4", "Single / Hold / Rush / Eraser"),
            ("V", "Select"),
            ("S", "Toggle snap / conduct lane 2"),
            ("D / K / L", "Conduct lanes 3 / 4 / 5"),
            ("[ / ]", "Snap division down / up"),
            ("Ctrl+Z / Ctrl+Shift+Z", "Undo / redo"),
            ("Ctrl+S", "Save draft"),
            ("Ctrl+E", "Export ZIP"),
            ("Ctrl+O", "Import ZIP"),
            ("Delete", "Remove selected notes"),
            (", / .", "Nudge by snap"),
            ("< / >", "Nudge by beat"),
        ]
        for idx, (key, action) in enumerate(rows):
            ttk.Label(frame, text=key, width=20, style="Panel.TLabel").grid(row=idx, column=0, sticky="w", padx=(0, 6), pady=1)
            ttk.Label(frame, text=action, style="Panel.TLabel").grid(row=idx, column=1, sticky="w", pady=1)

    def _load_sfx(self) -> None:
        if not NOTE_TICK_PATH.exists():
            return
        try:
            self.audio.load_sfx_file(NOTE_TICK_PATH)
        except RuntimeError:
            pass

    def load_imported_mod(self, mod: ImportedMod, draft_id: str | None = None, draft_name: str = "") -> None:
        if mod.audio_bytes:
            try:
                audio_filename, audio_bytes = ensure_ogg_audio(mod.audio_filename or mod.song.Audio, mod.audio_bytes)
            except Exception as exc:
                messagebox.showerror("Audio conversion failed", str(exc))
                self.set_status(f"Audio conversion failed: {exc}", temporary=False)
                return
            mod.audio_filename = audio_filename
            mod.audio_bytes = audio_bytes
            mod.song.Audio = audio_filename
            music_path = audio_to_music_path(audio_filename)
            for level in mod.levels.values():
                level.MusicPath = music_path
        chart = ChartState(
            song=mod.song,
            levels=mod.levels,
            active_level_path=mod.song.Levels[0].Path if mod.song.Levels else None,
            audio_filename=mod.audio_filename,
            audio_bytes=mod.audio_bytes,
            mod_folder_name=mod.mod_folder_name,
        )
        self.state.replace_chart(chart)
        self.history.clear()
        self.load_audio_bytes(mod.audio_bytes)
        self.scheduler.reset()
        self.current_draft_id = draft_id
        self.current_draft_name = draft_name
        self.refresh_all()
        if mod.warnings:
            messagebox.showwarning("Import warnings", "\n".join(mod.warnings))
        label = draft_name or mod.song.Title or mod.song.ID or mod.mod_folder_name
        self.set_status(f'Loaded "{label}" at song start.', temporary=True)

    def resume_last_draft_on_launch(self) -> None:
        meta = self.drafts.latest()
        if not meta:
            self.refresh_drafts()
            self.set_status("Ready. Import a ZIP or load a draft.", temporary=False)
            return
        try:
            song, levels, audio_filename, audio_bytes = self.drafts.load(meta.id)
            self.load_imported_mod(ImportedMod(song, levels, audio_filename, audio_bytes, meta.name, []), meta.id, meta.name)
            self.seek_tick(0)
            self.set_status(f'Resumed "{meta.name}" from the start. Ctrl+S saves it.', temporary=False)
        except Exception as exc:
            self.refresh_drafts()
            self.set_status(f"Could not resume last draft: {exc}", temporary=False)

    def load_audio_bytes(self, audio_bytes: bytes) -> None:
        self.waveform = None
        if not audio_bytes:
            return
        try:
            self.audio.load_bytes(audio_bytes)
            if NOTE_TICK_PATH.exists():
                self.audio.load_sfx_file(NOTE_TICK_PATH)
        except Exception as exc:
            logging.exception("Audio playback load failed")
            messagebox.showwarning("Audio unavailable", f"{exc}\n\nThe chart can still be edited.")
            self.set_status(f"Audio playback unavailable: {exc}", temporary=False)
        try:
            self.waveform = load_waveform_bytes(audio_bytes)
        except Exception:
            logging.exception("Waveform generation failed")
            self.waveform = None

    def new_project(self) -> None:
        if messagebox.askyesno("New project", "Clear the current project?"):
            self.push_history("New project")
            self.audio.stop()
            self.waveform = None
            self.current_draft_id = None
            self.current_draft_name = ""
            self.state.new_project()
            self.refresh_all()

    def import_zip(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("YunYun mod ZIP", "*.zip"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.load_imported_mod(parse_zip(path))
            self.canvas.focus_set()
            self.quick_save_draft(name=f"Imported - {self.draft_display_name()}", show_message=False, confirm_overwrite=False)
            self.set_status(f'Imported "{Path(path).name}" and saved a resumable draft.', temporary=True)
        except Exception as exc:
            messagebox.showerror("Import failed", str(exc))
            self.set_status(f"Import failed: {exc}", temporary=False)

    def import_audio(self) -> None:
        path = filedialog.askopenfilename(filetypes=AUDIO_FILETYPES)
        if not path:
            return
        try:
            self.set_status(f'Converting "{Path(path).name}" to OGG...', temporary=False)
            self.update_idletasks()
            audio_filename, data = convert_audio_file_to_ogg(path)
        except Exception as exc:
            logging.exception("Audio import failed for %s", path)
            messagebox.showerror("Audio import failed", str(exc))
            self.set_status(f"Audio import failed: {exc}", temporary=False)
            return
        self.push_history("Import audio")
        self.state.set_audio(audio_filename, data)
        self.load_audio_bytes(data)
        self.current_draft_id = None
        self.current_draft_name = ""
        self.refresh_all()
        self.set_status(f'Imported "{Path(path).name}" as "{audio_filename}". Press Ctrl+S to save.', temporary=True)

    def export_zip(self) -> None:
        if not self.state.chart.song.Levels:
            messagebox.showerror("Export failed", "At least one level is required.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".zip",
            filetypes=[("YunYun mod ZIP", "*.zip")],
            initialfile=f"{sanitize_folder_name(self.state.chart.song.ID or self.state.chart.mod_folder_name)}.zip",
        )
        if not path:
            self.canvas.focus_set()
            return
        try:
            data = build_zip_bytes(
                self.state.chart.song,
                self.state.chart.levels,
                self.state.chart.audio_filename,
                self.state.chart.audio_bytes,
                sanitize_folder_name(self.state.chart.song.ID or self.state.chart.mod_folder_name),
            )
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            self.set_status(f"Export failed: {exc}", temporary=False)
            return
        Path(path).write_bytes(data)
        self.canvas.focus_set()
        self.set_status(f'Exported "{Path(path).name}". Space will still play/pause.', temporary=True)

    def quick_save_draft(self, name: str | None = None, show_message: bool = True, confirm_overwrite: bool = True) -> None:
        draft_id = self.current_draft_id
        draft_name = name or self.current_draft_name or f"Working - {self.draft_display_name()}"
        if not draft_id:
            draft_id = CURRENT_DRAFT_ID
        if confirm_overwrite:
            warning = self._save_overwrite_warning(draft_id)
            if warning and not messagebox.askyesno("Overwrite current save?", warning):
                self.canvas.focus_set()
                self.set_status("Save canceled.", temporary=True)
                return
        self.save_draft_to(draft_id, draft_name, show_message=show_message)

    def save_draft_as(self) -> None:
        name = simpledialog.askstring("Save draft as", "Draft name:", initialvalue=self.current_draft_name or self.draft_display_name())
        if not name:
            self.set_status("Save canceled.", temporary=True)
            return
        self.save_draft_to(new_id(), name, show_message=True)

    def save_draft_to(self, draft_id: str, name: str, show_message: bool = True) -> None:
        try:
            meta = self.drafts.save(
                draft_id,
                name,
                self.state.chart.song,
                self.state.chart.levels,
                self.state.chart.audio_filename,
                self.state.chart.audio_bytes,
            )
        except Exception as exc:
            self.set_status(f"Save failed: {exc}", temporary=False)
            messagebox.showerror("Save failed", str(exc))
            return
        self.current_draft_id = meta.id
        self.current_draft_name = meta.name
        self.refresh_drafts()
        self.select_draft_in_list(meta.id)
        if show_message:
            self.set_status(f'Saved "{meta.name}" at {time.strftime("%H:%M:%S")}.', temporary=True)

    def load_selected_draft(self) -> None:
        selection = self.draft_list.curselection()
        if not selection:
            self.set_status("Select a draft to load.", temporary=True)
            return
        meta = self.drafts.list()[selection[0]]
        try:
            song, levels, audio_filename, audio_bytes = self.drafts.load(meta.id)
            self.load_imported_mod(ImportedMod(song, levels, audio_filename, audio_bytes, meta.name, []), meta.id, meta.name)
            self.seek_tick(0)
            self.select_draft_in_list(meta.id)
        except Exception as exc:
            self.set_status(f"Load failed: {exc}", temporary=False)
            messagebox.showerror("Load failed", str(exc))

    def delete_selected_draft(self) -> None:
        selection = self.draft_list.curselection()
        if not selection:
            return
        meta = self.drafts.list()[selection[0]]
        if messagebox.askyesno("Delete draft", f'Delete "{meta.name}"?'):
            self.drafts.delete(meta.id)
            if self.current_draft_id == meta.id:
                self.current_draft_id = None
                self.current_draft_name = ""
            self.refresh_drafts()
            self.set_status(f'Deleted draft "{meta.name}".', temporary=True)

    def add_level(self) -> None:
        editor = simpledialog.askstring("Add level", "Editor:", initialvalue="Editor") or "Editor"
        difficulty = simpledialog.askinteger("Add level", "Difficulty:", minvalue=1, maxvalue=20, initialvalue=1) or 1
        slot = simpledialog.askinteger("Add level", "Level slot:", minvalue=1, maxvalue=20, initialvalue=1) or 1
        self.push_history("Add level")
        self.state.add_level(editor, difficulty, slot)
        self.refresh_all()

    def duplicate_level(self) -> None:
        idx = self.selected_level_index()
        if idx is None:
            return
        ref = self.state.chart.song.Levels[idx]
        level = self.state.chart.levels.get(ref.Path)
        if not level:
            return
        self.push_history("Duplicate level")
        path = f"level_{new_id()[:6]}.json"
        self.state.chart.song.Levels.insert(idx + 1, SongLevelRef(ref.Editor, ref.Difficulty, path))
        self.state.chart.levels[path] = copy.deepcopy(level)
        self.state.chart.active_level_path = path
        self.refresh_all()

    def remove_level(self) -> None:
        idx = self.selected_level_index()
        if idx is None:
            return
        self.push_history("Remove level")
        ref = self.state.chart.song.Levels.pop(idx)
        if not any(item.Path == ref.Path for item in self.state.chart.song.Levels):
            self.state.chart.levels.pop(ref.Path, None)
        self.state.chart.active_level_path = self.state.chart.song.Levels[0].Path if self.state.chart.song.Levels else None
        self.refresh_all()

    def selected_level_index(self) -> int | None:
        selection = self.level_list.curselection()
        return int(selection[0]) if selection else None

    def select_level_from_list(self) -> None:
        idx = self.selected_level_index()
        if idx is None:
            return
        self.state.chart.active_level_path = self.state.chart.song.Levels[idx].Path
        self.state.selection.clear()
        self.sync_audio_to_playhead()
        self.refresh_all()

    def update_song(self, field_name: str, value: str) -> None:
        if getattr(self.state.chart.song, field_name, None) == value:
            return
        self.push_history("Edit song metadata")
        self.state.update_song_field(field_name, value)
        self.refresh_levels()

    def update_level_score_offset(self, value: str) -> None:
        level = self.state.active_level()
        if not level:
            self.refresh_level_metadata()
            return
        raw = value.strip()
        try:
            offset = float(raw)
        except ValueError:
            self.set_status("Score offset must be a number of seconds.", temporary=True)
            self.refresh_level_metadata()
            return
        if not math.isfinite(offset):
            self.set_status("Score offset must be finite.", temporary=True)
            self.refresh_level_metadata()
            return
        if level.ScoreOffset == offset:
            self.refresh_level_metadata()
            return
        self.push_history("Edit level metadata")
        level.ScoreOffset = offset
        self.sync_audio_to_playhead()
        self.refresh_all()
        self.set_status(f"Score offset {format_score_offset(offset)} s.", temporary=True)

    def update_level_init_bpm(self, value: str) -> None:
        level = self.state.active_level()
        if not level:
            self.refresh_level_metadata()
            return
        raw = value.strip()
        try:
            bpm = float(raw)
        except ValueError:
            self.set_status("Init BPM must be a number.", temporary=True)
            self.refresh_level_metadata()
            return
        if not math.isfinite(bpm):
            self.set_status("Init BPM must be finite.", temporary=True)
            self.refresh_level_metadata()
            return
        if bpm <= 0:
            self.set_status("Init BPM must be greater than zero.", temporary=True)
            self.refresh_level_metadata()
            return
        if level.InitBpm.Bpm == bpm:
            self.refresh_level_metadata()
            return
        self.push_history("Edit level metadata")
        level.InitBpm.Bpm = bpm
        self.sync_audio_to_playhead()
        self.refresh_all()
        self.set_status(f"Init BPM {format_bpm(bpm)}.", temporary=True)

    def set_tool(self, tool: str) -> None:
        self.state.tool = tool
        self.vars["tool"].set(tool)

    def update_snap(self) -> None:
        self.state.snap_enabled = bool(self.vars["snap"].get())
        self.state.snap_division = str(self.vars["snap_division"].get())

    def set_zoom(self, value: float) -> None:
        self.state.set_zoom(value)
        self.zoom_label.configure(text=f"{self.state.pixels_per_second} px/s")
        self.canvas.redraw()

    def update_speed(self, _value=None) -> None:
        speed = float(self.vars["speed"].get())
        self.state.set_speed(speed)
        self.audio.set_speed(self.state.editor_speed)
        self.speed_label.configure(text=f"{self.state.editor_speed:.2f}x")

    def update_sfx_toggle(self) -> None:
        self.state.note_sfx_enabled = bool(self.vars["sfx"].get())
        if not self.state.note_sfx_enabled:
            self.scheduler.reset()

    def update_conduct_toggle(self) -> None:
        self.state.conduct_mode = bool(self.vars["conduct"].get())
        self.conduct_keys_down.clear()
        if self.state.conduct_mode:
            self.set_status("Conduct mode on: S/D/K/L place notes on lanes 2/3/4/5.", temporary=False)
        else:
            self.set_status("Conduct mode off.", temporary=True)

    def toggle_play(self) -> None:
        if self.audio.playing:
            self.audio.pause()
            self.scheduler.reset()
        else:
            level = self.state.active_level()
            if level:
                tempo_map = build_tempo_map(level.InitBpm, level.BpmChangeEvents)
                self.audio.seek(tick_to_seconds(self.state.playhead_tick, tempo_map, level.ScoreOffset))
            try:
                self.audio.play()
            except RuntimeError as exc:
                messagebox.showwarning("Playback unavailable", str(exc))

    def seek_tick(self, tick: int) -> None:
        self.state.set_playhead(tick)
        level = self.state.active_level()
        if level:
            tempo_map = build_tempo_map(level.InitBpm, level.BpmChangeEvents)
            self.audio.seek(tick_to_seconds(self.state.playhead_tick, tempo_map, level.ScoreOffset))
        self.scheduler.reset()
        self.last_tick_for_sfx = self.state.playhead_tick
        self.refresh_all()

    def seek_end(self) -> None:
        level = self.state.active_level()
        if not level:
            return
        tempo_map = build_tempo_map(level.InitBpm, level.BpmChangeEvents)
        self.seek_tick(seconds_to_tick(self.audio.duration_seconds, tempo_map, level.ScoreOffset))

    def delete_selection(self) -> None:
        level = self.state.active_level()
        if not level or not self.state.selection:
            return
        self.push_history("Delete selection")
        delete_notes(level, self.state.selection)
        self.state.selection.clear()
        self.refresh_all()

    def nudge_selected(self, delta_tick: int, delta_lane: int) -> None:
        level = self.state.active_level()
        if not level or not self.state.selection:
            return
        from .editor_state import nudge_selection

        self.push_history("Nudge selection")
        nudge_selection(level, self.state.selection, delta_tick, delta_lane)
        self.refresh_all()

    def copy_selection_to_clipboard(self) -> None:
        level = self.state.active_level()
        if not level or not self.state.selection:
            return
        self.note_clipboard = copy_selected_notes(level, self.state.selection)
        self.set_status(f"Copied {len(self.note_clipboard)} note{'s' if len(self.note_clipboard) != 1 else ''}.", temporary=True)

    def paste_note_clipboard(self) -> None:
        level = self.state.active_level()
        if not level or not self.note_clipboard:
            return
        target_tick = self.state.snapped_tick(self.state.playhead_tick)
        self.push_history("Paste notes")
        pasted_ids = paste_notes_at_tick(level, self.note_clipboard, target_tick)
        if not pasted_ids:
            return
        self.state.selection = set(pasted_ids)
        self.refresh_all()
        self.set_status(f"Pasted {len(pasted_ids)} note{'s' if len(pasted_ids) != 1 else ''} at tick {target_tick}.", temporary=True)

    def add_event(self, kind: str) -> None:
        if not self.state.active_level():
            return
        self.push_history("Add event")
        if kind == "bpm":
            ev = add_bpm_change(self.state)
        elif kind == "ts":
            ev = add_time_signature_change(self.state)
        else:
            ev = add_phase_change(self.state)
        self.refresh_events(select=(kind, ev.id if ev else None))

    def selected_event(self) -> tuple[str, str] | None:
        tab_id = self.event_tabs.select()
        if not tab_id:
            return None
        tab_text = self.event_tabs.tab(tab_id, "text")
        kind = {"BPM": "bpm", "Crotchets Per Bar": "ts", "Level End": "phase"}.get(tab_text)
        if not kind:
            return None
        selection = self.event_trees[kind].selection()
        if not selection:
            return None
        return kind, selection[0]

    def populate_event_editor(self, kind: str) -> None:
        level = self.state.active_level()
        if not level:
            return
        selection = self.event_trees[kind].selection()
        if not selection:
            return
        event_id = selection[0]
        ev = self.find_event(kind, event_id)
        if not ev:
            return
        self.vars["event_tick"].set(str(ev.Tick))
        if kind == "bpm":
            self.vars["event_a"].set(format_bpm(ev.Bpm))
            self.vars["event_b"].set("")
        elif kind == "ts":
            self.vars["event_a"].set(str(ev.Numerator))
            self.vars["event_b"].set(str(ev.Denominator))
        else:
            self.vars["event_a"].set("")
            self.vars["event_b"].set("")

    def apply_event_edit(self) -> None:
        selected = self.selected_event()
        if not selected:
            return
        kind, event_id = selected
        ev = self.find_event(kind, event_id)
        if not ev:
            return
        try:
            next_tick = max(0, int(float(self.vars["event_tick"].get())))
            next_a = float(self.vars["event_a"].get()) if kind == "bpm" else None
            next_num = max(1, int(float(self.vars["event_a"].get()))) if kind == "ts" else None
            next_den = max(1, int(float(self.vars["event_b"].get()))) if kind == "ts" else None
        except ValueError:
            messagebox.showerror("Invalid event", "Event fields must be numeric.")
            return
        self.push_history("Edit event")
        ev.Tick = next_tick
        if kind == "bpm":
            ev.Bpm = float(next_a)
        elif kind == "ts":
            ev.Numerator = int(next_num)
            ev.Denominator = int(next_den)
        self.sort_event_lists()
        self.refresh_events(select=(kind, event_id))
        self.canvas.redraw()

    def delete_event(self) -> None:
        selected = self.selected_event()
        level = self.state.active_level()
        if not selected or not level:
            return
        self.push_history("Delete event")
        kind, event_id = selected
        if kind == "bpm":
            level.BpmChangeEvents = [ev for ev in level.BpmChangeEvents if ev.id != event_id]
        elif kind == "ts":
            level.TimeSignature = [ev for ev in level.TimeSignature if ev.id != event_id]
        else:
            level.PhaseChangeEvents = [ev for ev in level.PhaseChangeEvents if ev.id != event_id]
        self.refresh_events()
        self.canvas.redraw()

    def find_event(self, kind: str, event_id: str):
        level = self.state.active_level()
        if not level:
            return None
        events = {
            "bpm": level.BpmChangeEvents,
            "ts": level.TimeSignature,
            "phase": level.PhaseChangeEvents,
        }[kind]
        return next((ev for ev in events if ev.id == event_id), None)

    def sort_event_lists(self) -> None:
        level = self.state.active_level()
        if not level:
            return
        level.BpmChangeEvents.sort(key=lambda ev: (ev.Tick, ev.id))
        level.TimeSignature.sort(key=lambda ev: (ev.Tick, ev.id))
        level.PhaseChangeEvents.sort(key=lambda ev: (ev.Tick, ev.id))

    def refresh_all(self) -> None:
        self.refresh_song()
        self.refresh_level_metadata()
        self.refresh_levels()
        self.refresh_drafts()
        self.refresh_events()
        self.refresh_selection()
        self.canvas.redraw()

    def refresh_song(self) -> None:
        song = self.state.chart.song
        for field_name in ["ID", "Audio", "Title", "Artist", "Lyricist", "Composer", "Arranger"]:
            var = self.vars.get(f"song_{field_name}")
            if var and var.get() != getattr(song, field_name):
                var.set(getattr(song, field_name))

    def refresh_level_metadata(self) -> None:
        offset_var = self.vars.get("level_score_offset")
        offset_entry = getattr(self, "level_score_offset_entry", None)
        bpm_var = self.vars.get("level_init_bpm")
        bpm_entry = getattr(self, "level_init_bpm_entry", None)
        if not offset_var or offset_entry is None or not bpm_var or bpm_entry is None:
            return
        level = self.state.active_level()
        if not level:
            if offset_var.get():
                offset_var.set("")
            if bpm_var.get():
                bpm_var.set("")
            offset_entry.state(["disabled"])
            bpm_entry.state(["disabled"])
            return
        offset_text = format_score_offset(level.ScoreOffset)
        if offset_var.get() != offset_text:
            offset_var.set(offset_text)
        bpm_text = format_bpm(level.InitBpm.Bpm)
        if bpm_var.get() != bpm_text:
            bpm_var.set(bpm_text)
        offset_entry.state(["!disabled"])
        bpm_entry.state(["!disabled"])

    def refresh_levels(self) -> None:
        current = self.state.chart.active_level_path
        self.level_list.delete(0, tk.END)
        active_idx = None
        for idx, ref in enumerate(self.state.chart.song.Levels):
            level = self.state.chart.levels.get(ref.Path)
            slot = level.Level if level else "?"
            self.level_list.insert(tk.END, f"L{slot} star {ref.Difficulty} - {ref.Editor or 'unnamed'} - {ref.Path}")
            if ref.Path == current:
                active_idx = idx
        if active_idx is not None:
            self.level_list.selection_set(active_idx)

    def refresh_drafts(self) -> None:
        self.draft_list.delete(0, tk.END)
        for item in self.drafts.list():
            self.draft_list.insert(tk.END, f"{item.name} ({item.song_id or 'untitled'})")
        if self.current_draft_id:
            self.select_draft_in_list(self.current_draft_id)

    def select_draft_in_list(self, draft_id: str) -> None:
        for idx, item in enumerate(self.drafts.list()):
            if item.id == draft_id:
                self.draft_list.selection_clear(0, tk.END)
                self.draft_list.selection_set(idx)
                self.draft_list.see(idx)
                break

    def refresh_events(self, select: tuple[str, str | None] | None = None) -> None:
        level = self.state.active_level()
        for tree in self.event_trees.values():
            children = tree.get_children()
            if children:
                tree.delete(*children)
        if not level:
            return
        for ev in level.BpmChangeEvents:
            self.event_trees["bpm"].insert("", tk.END, iid=ev.id, values=(ev.Tick, format_bpm(ev.Bpm)))
        for ev in level.TimeSignature:
            self.event_trees["ts"].insert("", tk.END, iid=ev.id, values=(ev.Tick, ev.Numerator, ev.Denominator))
        for ev in level.PhaseChangeEvents:
            self.event_trees["phase"].insert("", tk.END, iid=ev.id, values=(ev.Tick,))
        if select and select[1]:
            kind, event_id = select
            if self.event_trees[kind].exists(event_id):
                self.event_trees[kind].selection_set(event_id)
                self.event_trees[kind].see(event_id)

    def refresh_selection(self) -> None:
        level = self.state.active_level()
        if not level or not self.state.selection:
            self.selection_label.configure(text="Click a note to select.")
            return
        notes = selected_notes(level, self.state.selection)
        if len(notes) == 1:
            kind, note = notes[0]
            extra = f", Duration {note.Duration}" if isinstance(note, HoldNote) else ""
            self.selection_label.configure(text=f"{kind}: Tick {note.Tick}, Lane {note.Lane}{extra}")
        else:
            self.selection_label.configure(text=f"{len(notes)} selected")

    def tick(self) -> None:
        if self.audio.playing:
            level = self.state.active_level()
            if level:
                tempo_map = build_tempo_map(level.InitBpm, level.BpmChangeEvents)
                current = seconds_to_tick(self.audio.song_seconds(), tempo_map, level.ScoreOffset)
                self.state.set_playhead(current)
                self.fire_crossed_note_sfx(level, self.last_tick_for_sfx, self.state.playhead_tick)
                self.last_tick_for_sfx = self.state.playhead_tick
                self.canvas.redraw()
        self.update_time_label()
        self.play_button.configure(text="Pause" if self.audio.playing else "Play")
        self.after(16, self.tick)

    def fire_crossed_note_sfx(self, level: LevelJson, previous_tick: int, current_tick: int) -> None:
        if not self.state.note_sfx_enabled:
            return
        events: list[tuple[str, int]] = []
        for note in level.SingleNotes:
            events.append((note.id, note.Tick))
        for note in level.HoldNotes:
            events.append((note.id, note.Tick))
        rush_events: list[tuple[str, int, int]] = []
        for note in level.RushNotes:
            rush_events.append((note.id, note.Tick, note.Tick + note.Duration))
        for _note_id in self.scheduler.crossed_with_repeats(previous_tick, current_tick, events, rush_events, interval_ticks=240, max_hits=6):
            self.audio.trigger_sfx()

    def update_time_label(self) -> None:
        current = self.audio.song_seconds()
        duration = self.audio.duration_seconds
        self.time_label.configure(text=f"{format_seconds(current)} / {format_seconds(duration)}")


def format_seconds(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:
        seconds = 0
    minutes = int(seconds // 60)
    rem = seconds - minutes * 60
    return f"{minutes:02d}:{rem:06.3f}"


def format_bpm(bpm: float) -> str:
    text = f"{float(bpm):.3f}".rstrip("0").rstrip(".")
    if "." not in text:
        text += ".0"
    return text or "0"


def format_score_offset(offset: float) -> str:
    text = f"{float(offset):.6f}".rstrip("0").rstrip(".")
    if "." not in text:
        text += ".0"
    return text or "0.0"


def main() -> None:
    app = YunYunEditorApp()
    app.mainloop()
