from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile

import numpy as np


OGG_HEADER = b"OggS"


def is_ogg_filename(filename: str) -> bool:
    return filename.lower().endswith(".ogg")


def is_ogg_bytes(data: bytes) -> bool:
    return data.startswith(OGG_HEADER)


def canonical_ogg_filename(filename: str, default: str = "audio.ogg") -> str:
    raw = Path(filename).name.strip()
    stem = Path(raw).stem if raw else Path(default).stem
    stem = stem.strip() or Path(default).stem
    return f"{stem}.ogg"


def convert_audio_file_to_ogg(path: str | Path) -> tuple[str, bytes]:
    path = Path(path)
    ogg_name = canonical_ogg_filename(path.name)
    with path.open("rb") as fh:
        header = fh.read(4)
    if header == OGG_HEADER:
        return ogg_name, path.read_bytes()

    soundfile_error: Exception | None = None
    try:
        return ogg_name, stream_soundfile_file_to_ogg(path)
    except Exception as exc:
        soundfile_error = exc

    try:
        return ogg_name, convert_with_pydub_file(path)
    except Exception as exc:
        raise RuntimeError(
            f'Could not convert "{path.name}" to OGG. '
            f"soundfile streaming error: {soundfile_error}; pydub/ffmpeg error: {exc}"
        ) from exc


def ensure_ogg_audio(filename: str, data: bytes) -> tuple[str, bytes]:
    ogg_name = canonical_ogg_filename(filename)
    if is_ogg_bytes(data):
        return ogg_name, data
    return ogg_name, convert_audio_bytes_to_ogg(data, filename)


def convert_audio_bytes_to_ogg(data: bytes, source_name: str = "audio") -> bytes:
    samples, sample_rate = decode_audio_bytes(data, source_name)
    return encode_ogg_bytes(samples, sample_rate)


def stream_soundfile_file_to_ogg(path: str | Path, blocksize: int = 262_144) -> bytes:
    try:
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("soundfile is required to encode OGG/Vorbis audio") from exc

    path = Path(path)
    with sf.SoundFile(str(path), "r") as source:
        channels = int(source.channels)
        sample_rate = int(source.samplerate)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            with sf.SoundFile(
                str(tmp_path),
                "w",
                samplerate=sample_rate,
                channels=channels,
                format="OGG",
                subtype="VORBIS",
            ) as target:
                for block in source.blocks(blocksize=blocksize, dtype="float32", always_2d=True):
                    target.write(block)
            return tmp_path.read_bytes()
        finally:
            tmp_path.unlink(missing_ok=True)


def decode_audio_bytes(data: bytes, source_name: str = "audio") -> tuple[np.ndarray, int]:
    soundfile_error: Exception | None = None
    try:
        import soundfile as sf

        samples, sample_rate = sf.read(BytesIO(data), always_2d=True, dtype="float32")
        return np.asarray(samples, dtype=np.float32), int(sample_rate)
    except Exception as exc:
        soundfile_error = exc

    try:
        return decode_with_pydub(data, source_name)
    except Exception as exc:
        raise RuntimeError(
            f'Could not decode "{source_name}". Install ffmpeg/pydub for formats not supported by soundfile. '
            f"soundfile error: {soundfile_error}; pydub error: {exc}"
        ) from exc


def decode_with_pydub(data: bytes, source_name: str) -> tuple[np.ndarray, int]:
    from pydub import AudioSegment

    ext = Path(source_name).suffix.lower().lstrip(".") or None
    segment = AudioSegment.from_file(BytesIO(data), format=ext)
    channels = int(segment.channels)
    sample_rate = int(segment.frame_rate)
    width = int(segment.sample_width)
    raw = np.array(segment.get_array_of_samples())
    if channels > 1:
        raw = raw.reshape((-1, channels))
    else:
        raw = raw.reshape((-1, 1))
    scale = float(1 << (width * 8 - 1))
    samples = raw.astype(np.float32) / scale
    return samples, sample_rate


def convert_with_pydub_file(path: str | Path) -> bytes:
    from pydub import AudioSegment

    path = Path(path)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        AudioSegment.from_file(str(path)).export(str(tmp_path), format="ogg", codec="libvorbis")
        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)


def encode_ogg_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    try:
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("soundfile is required to encode OGG/Vorbis audio") from exc

    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim == 1:
        samples = np.column_stack([samples, samples])
    mem = BytesIO()
    sf.write(mem, samples, int(sample_rate), format="OGG", subtype="VORBIS")
    return mem.getvalue()
