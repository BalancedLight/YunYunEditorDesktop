from __future__ import annotations

from dataclasses import dataclass

from .model import LevelJson
from .timing import TempoSegment, tick_to_seconds


NOTE_HEIGHT = 22


@dataclass(frozen=True)
class Viewport:
    width: int
    height: int
    playfield_x: int
    playfield_width: int
    lane_width: int
    lane_start: int
    lane_count: int
    pixels_per_second: float
    playhead_y: float
    playhead_sec: float


@dataclass(frozen=True)
class TimelineEventLabel:
    tick: int
    color: str
    label: str
    stack_index: int


def seconds_to_y(sec: float, viewport: Viewport) -> float:
    return viewport.playhead_y - (sec - viewport.playhead_sec) * viewport.pixels_per_second


def tick_to_y(tick: float, viewport: Viewport, tempo_map: list[TempoSegment], score_offset: float) -> float:
    return seconds_to_y(tick_to_seconds(tick, tempo_map, score_offset), viewport)


def hold_visible(start_y: float, end_y: float, canvas_height: int, note_height: int = NOTE_HEIGHT) -> bool:
    top = min(start_y, end_y) - note_height
    bottom = max(start_y, end_y) + note_height
    return bottom >= 0 and top <= canvas_height


def y_to_seconds(y: float, viewport: Viewport) -> float:
    return viewport.playhead_sec - (y - viewport.playhead_y) / viewport.pixels_per_second


def lane_to_x(lane: int, viewport: Viewport) -> int:
    return viewport.playfield_x + (lane - viewport.lane_start) * viewport.lane_width


def pick_lane(x: float, viewport: Viewport) -> int:
    idx = int((x - viewport.playfield_x) // viewport.lane_width)
    return max(viewport.lane_start, min(viewport.lane_start + viewport.lane_count - 1, viewport.lane_start + idx))


def stack_timeline_event_labels(events: list[tuple[int, str, str]]) -> list[TimelineEventLabel]:
    counts_by_tick: dict[int, int] = {}
    laid_out: list[TimelineEventLabel] = []
    for tick, color, label in events:
        stack_index = counts_by_tick.get(tick, 0)
        counts_by_tick[tick] = stack_index + 1
        laid_out.append(TimelineEventLabel(tick=tick, color=color, label=label, stack_index=stack_index))
    return laid_out
