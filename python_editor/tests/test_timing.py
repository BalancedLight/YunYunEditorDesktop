from __future__ import annotations

from yunyun_editor.model import BpmEvent, TimeSignatureEvent
from yunyun_editor.timing import build_tempo_map, seconds_to_tick, snap_tick, tick_to_seconds


def test_tempo_roundtrip_across_bpm_change() -> None:
    tempo = build_tempo_map(BpmEvent(0, 120.0), [BpmEvent(480, 240.0)])

    assert tick_to_seconds(480, tempo) == 0.5
    assert tick_to_seconds(960, tempo) == 0.75
    assert seconds_to_tick(0.75, tempo) == 960


def test_snap_anchors_to_current_time_signature_change() -> None:
    init = TimeSignatureEvent(0, 4, 4)
    changes = [TimeSignatureEvent(1000, 3, 4)]

    assert snap_tick(1121, init, changes, "1/8") == 1240
    assert snap_tick(1079, init, changes, "1/8") == 1000

