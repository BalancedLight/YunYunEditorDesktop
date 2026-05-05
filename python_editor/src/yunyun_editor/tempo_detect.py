from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class TempoDetectionResult:
    bpm: float
    offset: float
    fitness: float


def detect_tempo(
    samples: np.ndarray,
    sample_rate: int,
    min_bpm: float = 89.0,
    max_bpm: float = 205.0,
) -> list[TempoDetectionResult]:
    mono, rate = _prepare_audio(samples, sample_rate)
    if mono.size < rate:
        return [TempoDetectionResult(120.0, 0.0, 0.0)]
    novelty, hop = _spectral_flux(mono, rate)
    onset_frames, strengths = _pick_onsets(novelty, rate, hop)
    if onset_frames.size < 2:
        return [TempoDetectionResult(120.0, 0.0, 0.0)]
    onset_times = onset_frames.astype(np.float64) * float(hop) / float(rate)
    weights = strengths.astype(np.float64)
    weights /= max(float(np.max(weights)), 1.0e-9)

    candidates: list[TempoDetectionResult] = []
    for bpm in np.arange(float(min_bpm), float(max_bpm) + 0.0001, 0.1):
        offset, fitness = _score_bpm(onset_times, weights, float(bpm))
        if fitness > 0:
            candidates.append(TempoDetectionResult(_rounded_bpm(float(bpm)), offset, fitness))
    candidates.sort(key=lambda item: item.fitness, reverse=True)
    return _dedupe_results(candidates)[:3] or [TempoDetectionResult(120.0, 0.0, 0.0)]


def _prepare_audio(samples: np.ndarray, sample_rate: int) -> tuple[np.ndarray, int]:
    rate = max(1, int(sample_rate))
    arr = np.asarray(samples, dtype=np.float32)
    if arr.ndim == 2:
        arr = arr.mean(axis=1)
    elif arr.ndim > 2:
        arr = arr.reshape((arr.shape[0], -1)).mean(axis=1)
    arr = np.nan_to_num(arr, copy=False)
    if arr.size == 0:
        return np.zeros(0, dtype=np.float32), rate
    peak = float(np.max(np.abs(arr)))
    if peak > 0:
        arr = arr / peak
    target_rate = 22_050
    if rate > target_rate:
        step = max(1, int(round(rate / target_rate)))
        arr = arr[::step]
        rate = int(round(rate / step))
    return arr.astype(np.float32, copy=False), rate


def _spectral_flux(samples: np.ndarray, sample_rate: int) -> tuple[np.ndarray, int]:
    win_size = 1024
    hop = 512
    if samples.size < win_size:
        return np.zeros(0, dtype=np.float32), hop
    frame_count = 1 + (samples.size - win_size) // hop
    strides = (samples.strides[0] * hop, samples.strides[0])
    frames = np.lib.stride_tricks.as_strided(samples, shape=(frame_count, win_size), strides=strides)
    window = np.hanning(win_size).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(frames * window, axis=1))
    diff = np.diff(spectrum, axis=0)
    flux = np.maximum(diff, 0.0).sum(axis=1)
    if flux.size == 0:
        return np.zeros(0, dtype=np.float32), hop
    flux = np.concatenate([[0.0], flux]).astype(np.float32)
    smooth = max(1, int(round(0.04 * sample_rate / hop)))
    if smooth > 1:
        kernel = np.ones(smooth, dtype=np.float32) / float(smooth)
        flux = np.convolve(flux, kernel, mode="same").astype(np.float32)
    peak = float(np.max(flux))
    if peak > 0:
        flux /= peak
    return flux, hop


def _pick_onsets(novelty: np.ndarray, sample_rate: int, hop: int) -> tuple[np.ndarray, np.ndarray]:
    if novelty.size < 3:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float32)
    threshold = max(0.08, float(np.percentile(novelty, 75)) + float(np.std(novelty)) * 0.35)
    local_max = (novelty[1:-1] >= novelty[:-2]) & (novelty[1:-1] > novelty[2:])
    candidates = np.flatnonzero(local_max & (novelty[1:-1] >= threshold)) + 1
    if candidates.size < 2:
        top = np.argsort(novelty)[-min(64, novelty.size):]
        candidates = np.sort(top[novelty[top] > 0])

    min_gap = max(1, int(round(0.08 * sample_rate / hop)))
    chosen: list[int] = []
    for idx in candidates[np.argsort(novelty[candidates])[::-1]]:
        if all(abs(int(idx) - existing) >= min_gap for existing in chosen):
            chosen.append(int(idx))
    chosen.sort()
    frames = np.asarray(chosen, dtype=np.int64)
    return frames, novelty[frames].astype(np.float32, copy=False)


def _score_bpm(onset_times: np.ndarray, weights: np.ndarray, bpm: float) -> tuple[float, float]:
    period = 60.0 / bpm
    bins = max(48, min(256, int(round(period / 0.004))))
    phases = np.mod(onset_times, period)
    indices = np.minimum((phases / period * bins).astype(np.int64), bins - 1)
    hist = np.bincount(indices, weights=weights, minlength=bins).astype(np.float64)
    if not np.any(hist):
        return 0.0, 0.0
    smooth_bins = max(3, int(round(0.045 / period * bins)))
    smooth = _circular_smooth(hist, smooth_bins)
    combined = smooth + np.roll(smooth, bins // 2) * 0.5
    best = int(np.argmax(combined))
    offset = _refined_offset(phases, weights, period, (best + 0.5) / bins * period)
    fitness = float(combined[best] / max(float(np.sum(weights)), 1.0e-9))
    return offset, fitness


def _circular_smooth(values: np.ndarray, window_len: int) -> np.ndarray:
    window_len = max(1, min(int(window_len), values.size))
    if window_len <= 1:
        return values
    if window_len % 2 == 0:
        window_len += 1
    window = np.hamming(window_len)
    window /= max(float(np.sum(window)), 1.0e-9)
    pad = window_len // 2
    wrapped = np.concatenate([values[-pad:], values, values[:pad]])
    return np.convolve(wrapped, window, mode="same")[pad:pad + values.size]


def _refined_offset(phases: np.ndarray, weights: np.ndarray, period: float, center: float) -> float:
    distance = np.abs(((phases - center + period / 2.0) % period) - period / 2.0)
    tolerance = max(0.025, min(0.07, period * 0.12))
    mask = distance <= tolerance
    if not np.any(mask):
        return float(center % period)
    angles = phases[mask] / period * math.tau
    selected = weights[mask]
    vector = np.sum(selected * np.exp(1j * angles))
    if abs(vector) <= 1.0e-9:
        return float(center % period)
    angle = math.atan2(vector.imag, vector.real)
    if angle < 0:
        angle += math.tau
    return float(angle / math.tau * period)


def _rounded_bpm(bpm: float) -> float:
    rounded = round(bpm)
    if abs(bpm - rounded) < 0.05:
        return float(rounded)
    return round(bpm, 3)


def _dedupe_results(results: list[TempoDetectionResult]) -> list[TempoDetectionResult]:
    kept: list[TempoDetectionResult] = []
    for item in results:
        duplicate = False
        for existing in kept:
            bpm = item.bpm
            other = existing.bpm
            if min(abs(bpm - other), abs(bpm * 2.0 - other), abs(bpm * 0.5 - other)) < 0.25:
                duplicate = True
                break
        if not duplicate:
            kept.append(item)
    return kept
