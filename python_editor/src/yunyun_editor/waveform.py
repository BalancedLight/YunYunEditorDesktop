from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import numpy as np


@dataclass
class WaveformEnvelope:
    sample_rate: int
    samples_per_peak: int
    peaks: np.ndarray

    @property
    def duration(self) -> float:
        if self.sample_rate <= 0:
            return 0.0
        return len(self.peaks) * self.samples_per_peak / self.sample_rate

    def amplitude_at(self, seconds: float) -> float:
        if len(self.peaks) == 0 or seconds < 0:
            return 0.0
        idx = int(seconds * self.sample_rate / self.samples_per_peak)
        if idx < 0 or idx >= len(self.peaks):
            return 0.0
        return float(self.peaks[idx])


def build_waveform(samples: np.ndarray, sample_rate: int, samples_per_peak: int = 1024) -> WaveformEnvelope:
    if samples.ndim == 2:
        mono = samples.mean(axis=1)
    else:
        mono = samples
    mono = np.asarray(mono, dtype=np.float32)
    if mono.size == 0:
        return WaveformEnvelope(sample_rate, samples_per_peak, np.zeros(0, dtype=np.float32))
    pad = (-mono.size) % samples_per_peak
    if pad:
        mono = np.pad(mono, (0, pad))
    windows = mono.reshape((-1, samples_per_peak))
    peaks = np.max(np.abs(windows), axis=1).astype(np.float32)
    max_peak = float(np.max(peaks)) if peaks.size else 0.0
    if max_peak > 0:
        peaks /= max_peak
    return WaveformEnvelope(sample_rate, samples_per_peak, peaks)


def load_waveform_bytes(audio_bytes: bytes, samples_per_peak: int = 1024) -> WaveformEnvelope:
    try:
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("soundfile is required to decode OGG waveform data") from exc

    data, sample_rate = sf.read(BytesIO(audio_bytes), always_2d=False, dtype="float32")
    return build_waveform(data, int(sample_rate), samples_per_peak=samples_per_peak)

