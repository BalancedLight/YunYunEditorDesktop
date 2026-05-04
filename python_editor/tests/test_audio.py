from __future__ import annotations

import numpy as np

from yunyun_editor.audio import AudioEngine, HitSfxScheduler


def test_audio_speed_changes_editor_progression_for_tests() -> None:
    engine = AudioEngine()
    engine.load_array(np.zeros((44100 * 4, 2), dtype=np.float32), 44100)
    engine.set_speed(2.0)
    engine.playing = True

    engine.advance_for_tests(0.5)

    assert round(engine.song_seconds(), 3) == 1.0


def test_hit_sfx_scheduler_triggers_once_and_resets_on_rewind() -> None:
    scheduler = HitSfxScheduler()

    assert scheduler.crossed(0, 200, [("a", 120), ("b", 240)]) == ["a"]
    assert scheduler.crossed(200, 300, [("a", 120), ("b", 240)]) == ["b"]
    assert scheduler.crossed(0, 300, [("a", 120), ("b", 240)]) == []
    assert scheduler.crossed(300, 100, [("a", 120), ("b", 240)]) == []
    assert scheduler.crossed(100, 130, [("a", 120), ("b", 240)]) == ["a"]


def test_hit_sfx_scheduler_repeats_rush_without_unbounded_spam() -> None:
    scheduler = HitSfxScheduler()

    hits = scheduler.crossed_with_repeats(
        0,
        1200,
        [("single", 120)],
        [("rush", 240, 1200)],
        interval_ticks=240,
        max_hits=4,
    )

    assert hits == ["single", "rush", "rush", "rush"]
    assert scheduler.crossed_with_repeats(1200, 1500, [], [("rush", 240, 1200)]) == []
