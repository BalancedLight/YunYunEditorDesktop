from __future__ import annotations

from yunyun_editor.renderer_math import hold_visible, stack_timeline_event_labels


def test_hold_visible_uses_min_and_max_y_values() -> None:
    assert hold_visible(700, 100, 600)
    assert hold_visible(100, 700, 600)
    assert not hold_visible(-100, -50, 600)
    assert not hold_visible(650, 700, 600)


def test_stack_timeline_event_labels_offsets_same_tick_events() -> None:
    labels = stack_timeline_event_labels(
        [
            (70080, "#6aa9ff", "95.0 BPM"),
            (70080, "#ffb454", "6/4"),
            (70560, "#b97cff", "phase"),
        ]
    )

    assert [label.stack_index for label in labels] == [0, 1, 0]
    assert [label.label for label in labels] == ["95.0 BPM", "6/4", "phase"]
