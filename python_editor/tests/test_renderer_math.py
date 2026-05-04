from __future__ import annotations

from yunyun_editor.renderer_math import hold_visible


def test_hold_visible_uses_min_and_max_y_values() -> None:
    assert hold_visible(700, 100, 600)
    assert hold_visible(100, 700, 600)
    assert not hold_visible(-100, -50, 600)
    assert not hold_visible(650, 700, 600)

