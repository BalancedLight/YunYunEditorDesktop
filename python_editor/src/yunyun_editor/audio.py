from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
import threading
from typing import Iterable

import numpy as np


@dataclass
class HitSfxScheduler:
    triggered: set[str] = field(default_factory=set)
    repeat_next: dict[str, int] = field(default_factory=dict)

    def reset(self) -> None:
        self.triggered.clear()
        self.repeat_next.clear()

    def crossed(self, previous_tick: int, current_tick: int, note_events: Iterable[tuple[str, int]]) -> list[str]:
        if current_tick < previous_tick:
            self.reset()
            previous_tick = current_tick
        hit_ids: list[str] = []
        for note_id, tick in note_events:
            if note_id in self.triggered:
                continue
            if previous_tick < tick <= current_tick:
                self.triggered.add(note_id)
                hit_ids.append(note_id)
        return hit_ids

    def crossed_with_repeats(
        self,
        previous_tick: int,
        current_tick: int,
        one_shot_events: Iterable[tuple[str, int]],
        repeat_events: Iterable[tuple[str, int, int]],
        interval_ticks: int = 240,
        max_hits: int = 6,
    ) -> list[str]:
        if current_tick < previous_tick:
            self.reset()
            previous_tick = current_tick
        interval_ticks = max(1, int(interval_ticks))
        max_hits = max(1, int(max_hits))
        hit_ids = self.crossed(previous_tick, current_tick, one_shot_events)
        if len(hit_ids) >= max_hits:
            return hit_ids[:max_hits]
        for note_id, start_tick, end_tick in repeat_events:
            if len(hit_ids) >= max_hits:
                break
            if end_tick < previous_tick or start_tick > current_tick:
                continue
            next_tick = self.repeat_next.get(note_id, int(start_tick))
            while next_tick <= previous_tick:
                next_tick += interval_ticks
            while next_tick <= current_tick and next_tick <= end_tick and len(hit_ids) < max_hits:
                hit_ids.append(note_id)
                next_tick += interval_ticks
            self.repeat_next[note_id] = next_tick
        return hit_ids


class AudioEngine:
    def __init__(self) -> None:
        self.samples = np.zeros((0, 2), dtype=np.float32)
        self.sample_rate = 44100
        self.position = 0.0
        self.speed = 1.0
        self.playing = False
        self.stream = None
        self.sfx_samples = np.zeros((0, 2), dtype=np.float32)
        self.sfx_voices: list[float] = []
        self.max_sfx_voices = 8
        self.lock = threading.RLock()

    @property
    def duration_seconds(self) -> float:
        return len(self.samples) / self.sample_rate if self.sample_rate > 0 else 0.0

    def load_array(self, samples: np.ndarray, sample_rate: int) -> None:
        samples = self._as_stereo(samples)
        stream_to_close = None
        with self.lock:
            sample_rate = int(sample_rate)
            if self.stream is not None and sample_rate != self.sample_rate:
                stream_to_close = self.stream
                self.stream = None
            self.stop()
            self.samples = samples.astype(np.float32, copy=False)
            self.sample_rate = sample_rate
            self.position = 0.0
            self.sfx_voices.clear()
        self._close_stream(stream_to_close)

    def load_bytes(self, audio_bytes: bytes) -> None:
        try:
            import soundfile as sf
        except ImportError as exc:
            raise RuntimeError("soundfile is required for OGG playback") from exc
        data, sample_rate = sf.read(BytesIO(audio_bytes), always_2d=True, dtype="float32")
        self.load_array(data, int(sample_rate))

    def load_file(self, path: str | Path) -> None:
        self.load_bytes(Path(path).read_bytes())

    def load_sfx_file(self, path: str | Path) -> None:
        try:
            import soundfile as sf
        except ImportError as exc:
            raise RuntimeError("soundfile is required for OGG SFX playback") from exc
        data, sample_rate = sf.read(str(path), always_2d=True, dtype="float32")
        data = self._as_stereo(data)
        if int(sample_rate) != self.sample_rate and len(data) > 0:
            data = self._resample_nearest(data, int(sample_rate), self.sample_rate)
        with self.lock:
            self.sfx_samples = data.astype(np.float32, copy=False)

    def set_speed(self, speed: float) -> None:
        with self.lock:
            self.speed = max(0.25, min(2.0, float(speed)))

    def seek(self, seconds: float) -> None:
        with self.lock:
            self.position = max(0.0, min(float(seconds) * self.sample_rate, float(len(self.samples))))
            self.sfx_voices.clear()

    def song_seconds(self) -> float:
        with self.lock:
            return self.position / self.sample_rate if self.sample_rate else 0.0

    def play(self) -> None:
        if len(self.samples) == 0:
            return
        with self.lock:
            self.playing = True
        self._ensure_stream()

    def pause(self) -> None:
        with self.lock:
            self.playing = False
            self.sfx_voices.clear()

    def stop(self) -> None:
        with self.lock:
            self.playing = False
            self.position = 0.0
            self.sfx_voices.clear()

    def trigger_sfx(self) -> None:
        with self.lock:
            if len(self.sfx_samples) and len(self.sfx_voices) < self.max_sfx_voices:
                self.sfx_voices.append(0.0)

    def advance_for_tests(self, seconds: float) -> None:
        with self.lock:
            if self.playing:
                self.position = min(len(self.samples), self.position + seconds * self.sample_rate * self.speed)

    def _ensure_stream(self) -> None:
        if self.stream is not None:
            return
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("sounddevice is required for playback") from exc
        self.stream = sd.OutputStream(
            channels=2,
            samplerate=self.sample_rate,
            dtype="float32",
            callback=self._callback,
        )
        self.stream.start()

    def _close_stream(self, stream) -> None:
        if stream is None:
            return
        try:
            stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass

    def _callback(self, outdata, frames: int, _time, status) -> None:
        del status
        with self.lock:
            if not self.playing or len(self.samples) == 0:
                outdata[:] = 0
                return
            idx = self.position + np.arange(frames, dtype=np.float32) * self.speed
            int_idx = idx.astype(np.int64)
            valid = int_idx < len(self.samples)
            chunk = np.zeros((frames, 2), dtype=np.float32)
            if np.any(valid):
                chunk[valid] = self.samples[int_idx[valid]]
            self.position += frames * self.speed
            if self.position >= len(self.samples):
                self.position = float(len(self.samples))
                self.playing = False
            chunk += self._mix_sfx(frames)
            outdata[:] = np.clip(chunk, -1.0, 1.0)

    def _mix_sfx(self, frames: int) -> np.ndarray:
        mixed = np.zeros((frames, 2), dtype=np.float32)
        if len(self.sfx_samples) == 0:
            self.sfx_voices.clear()
            return mixed
        next_voices: list[float] = []
        for pos in self.sfx_voices:
            start = int(pos)
            end = min(start + frames, len(self.sfx_samples))
            count = max(0, end - start)
            if count:
                mixed[:count] += self.sfx_samples[start:end] * 0.65
            next_pos = pos + frames
            if next_pos < len(self.sfx_samples):
                next_voices.append(next_pos)
        self.sfx_voices = next_voices
        return mixed

    @staticmethod
    def _as_stereo(samples: np.ndarray) -> np.ndarray:
        arr = np.asarray(samples, dtype=np.float32)
        if arr.ndim == 1:
            arr = np.column_stack([arr, arr])
        if arr.shape[1] == 1:
            arr = np.repeat(arr, 2, axis=1)
        if arr.shape[1] > 2:
            arr = arr[:, :2]
        return arr

    @staticmethod
    def _resample_nearest(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
        if source_rate == target_rate or len(samples) == 0:
            return samples
        duration = len(samples) / source_rate
        out_len = max(1, int(round(duration * target_rate)))
        src_idx = np.minimum((np.arange(out_len) * source_rate / target_rate).astype(np.int64), len(samples) - 1)
        return samples[src_idx]
