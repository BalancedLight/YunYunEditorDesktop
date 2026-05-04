from __future__ import annotations

from dataclasses import dataclass

from .model import BpmEvent, TimeSignatureEvent


TPQN = 480
SNAP_DIVISIONS: dict[str, int] = {
    "1/4": 480,
    "1/8": 240,
    "1/16": 120,
    "1/32": 60,
    "1/3": 160,
    "1/6": 80,
}


@dataclass(frozen=True)
class TempoSegment:
    tick: int
    sec: float
    spt: float
    bpm: float


def bpm_to_spt(bpm: float) -> float:
    return 60.0 / (float(bpm) * TPQN)


def build_tempo_map(init_bpm: BpmEvent, changes: list[BpmEvent]) -> list[TempoSegment]:
    sorted_changes = sorted(changes, key=lambda ev: ev.Tick)
    prev_tick = int(init_bpm.Tick)
    prev_bpm = float(init_bpm.Bpm)
    cumulative = 0.0
    segments = [TempoSegment(prev_tick, 0.0, bpm_to_spt(prev_bpm), prev_bpm)]
    for ev in sorted_changes:
        if ev.Tick <= prev_tick:
            continue
        cumulative += (ev.Tick - prev_tick) * bpm_to_spt(prev_bpm)
        prev_tick = int(ev.Tick)
        prev_bpm = float(ev.Bpm)
        segments.append(TempoSegment(prev_tick, cumulative, bpm_to_spt(prev_bpm), prev_bpm))
    return segments


def _find_segment_by_tick(segments: list[TempoSegment], tick: float) -> TempoSegment:
    lo = 0
    hi = len(segments) - 1
    while lo < hi:
        mid = (lo + hi + 1) >> 1
        if segments[mid].tick <= tick:
            lo = mid
        else:
            hi = mid - 1
    return segments[lo]


def _find_segment_by_sec(segments: list[TempoSegment], sec: float) -> TempoSegment:
    lo = 0
    hi = len(segments) - 1
    while lo < hi:
        mid = (lo + hi + 1) >> 1
        if segments[mid].sec <= sec:
            lo = mid
        else:
            hi = mid - 1
    return segments[lo]


def tick_to_seconds(tick: float, segments: list[TempoSegment], score_offset: float = 0.0) -> float:
    seg = _find_segment_by_tick(segments, tick)
    return float(score_offset) + seg.sec + (float(tick) - seg.tick) * seg.spt


def seconds_to_tick(sec: float, segments: list[TempoSegment], score_offset: float = 0.0) -> int:
    local = float(sec) - float(score_offset)
    seg = _find_segment_by_sec(segments, local)
    return int(round(seg.tick + (local - seg.sec) / seg.spt))


def most_recent_ts_tick(tick: float, init_ts: TimeSignatureEvent, changes: list[TimeSignatureEvent]) -> int:
    last = int(init_ts.Tick)
    for ev in sorted(changes, key=lambda item: item.Tick):
        if ev.Tick > tick:
            break
        last = int(ev.Tick)
    return last


def snap_tick(
    tick: float,
    init_ts: TimeSignatureEvent,
    changes: list[TimeSignatureEvent],
    division: str,
) -> int:
    step = SNAP_DIVISIONS[division]
    anchor = most_recent_ts_tick(tick, init_ts, changes)
    rel = float(tick) - anchor
    return max(0, int(anchor + round(rel / step) * step))


def bar_ticks(ts: TimeSignatureEvent) -> int:
    return int(round(TPQN * ts.Numerator * 4 / ts.Denominator))

