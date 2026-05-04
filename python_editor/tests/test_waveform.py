from __future__ import annotations

import numpy as np

from yunyun_editor.waveform import build_waveform


def test_waveform_peaks_are_normalized_and_time_addressable() -> None:
    samples = np.array([0.0, 0.5, -1.0, 0.25, 0.0, 0.25, -0.5, 0.0], dtype=np.float32)

    env = build_waveform(samples, sample_rate=8, samples_per_peak=4)

    assert env.peaks.tolist() == [1.0, 0.5]
    assert env.amplitude_at(0.1) == 1.0
    assert env.amplitude_at(0.7) == 0.5

