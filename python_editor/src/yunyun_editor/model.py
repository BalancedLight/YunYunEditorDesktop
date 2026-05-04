from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import uuid


LANE_MIN = 2
LANE_MAX = 5
SUPPORTED_LEVELS = (1, 3, 4, 5)


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class BpmEvent:
    Tick: int
    Bpm: float
    id: str = field(default_factory=new_id)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BpmEvent":
        return cls(Tick=int(raw.get("Tick", 0)), Bpm=float(raw.get("Bpm", 120.0)))

    def to_dict(self) -> dict[str, Any]:
        return {"Tick": int(self.Tick), "Bpm": float(self.Bpm)}


@dataclass
class TimeSignatureEvent:
    Tick: int
    Numerator: int
    Denominator: int
    id: str = field(default_factory=new_id)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TimeSignatureEvent":
        return cls(
            Tick=int(raw.get("Tick", 0)),
            Numerator=int(raw.get("Numerator", 4)),
            Denominator=int(raw.get("Denominator", 4)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "Tick": int(self.Tick),
            "Numerator": int(self.Numerator),
            "Denominator": int(self.Denominator),
        }


@dataclass
class PhaseEvent:
    Tick: int
    id: str = field(default_factory=new_id)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PhaseEvent":
        return cls(Tick=int(raw.get("Tick", 0)))

    def to_dict(self) -> dict[str, Any]:
        return {"Tick": int(self.Tick)}


@dataclass
class SingleNote:
    Tick: int
    Lane: int
    Type: int = 0
    id: str = field(default_factory=new_id)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SingleNote":
        return cls(
            Tick=int(raw.get("Tick", 0)),
            Lane=int(raw.get("Lane", LANE_MIN)),
            Type=int(raw.get("Type", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"Tick": int(self.Tick), "Lane": int(self.Lane), "Type": int(self.Type)}


@dataclass
class HoldNote(SingleNote):
    Duration: int = 1

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "HoldNote":
        return cls(
            Tick=int(raw.get("Tick", 0)),
            Lane=int(raw.get("Lane", LANE_MIN)),
            Type=int(raw.get("Type", 0)),
            Duration=int(raw.get("Duration", 1)),
        )

    def to_dict(self) -> dict[str, Any]:
        out = super().to_dict()
        out["Duration"] = int(self.Duration)
        return out


@dataclass
class RushNote(HoldNote):
    pass


ShiftNote = SingleNote


@dataclass
class SongLevelRef:
    Editor: str
    Difficulty: int
    Path: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SongLevelRef":
        return cls(
            Editor=str(raw.get("Editor", "")),
            Difficulty=int(raw.get("Difficulty", 1)),
            Path=str(raw.get("Path", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "Editor": self.Editor,
            "Difficulty": int(self.Difficulty),
            "Path": self.Path,
        }


@dataclass
class SongJson:
    ID: str = ""
    Audio: str = ""
    Title: str = ""
    Artist: str = ""
    Lyricist: str = ""
    Composer: str = ""
    Arranger: str = ""
    Levels: list[SongLevelRef] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SongJson":
        return cls(
            ID=str(raw.get("ID", "")),
            Audio=str(raw.get("Audio", "")),
            Title=str(raw.get("Title", "")),
            Artist=str(raw.get("Artist", "")),
            Lyricist=str(raw.get("Lyricist", "")),
            Composer=str(raw.get("Composer", "")),
            Arranger=str(raw.get("Arranger", "")),
            Levels=[SongLevelRef.from_dict(v) for v in raw.get("Levels", []) or []],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ID": self.ID,
            "Audio": self.Audio,
            "Title": self.Title,
            "Artist": self.Artist,
            "Lyricist": self.Lyricist,
            "Composer": self.Composer,
            "Arranger": self.Arranger,
            "Levels": [v.to_dict() for v in self.Levels],
        }


@dataclass
class LevelJson:
    Version: int = 1
    MusicInfoName: str = ""
    Level: int = 1
    MusicPath: str = ""
    ScoreOffset: float = 0.0
    InitBpm: BpmEvent = field(default_factory=lambda: BpmEvent(0, 120.0))
    InitTimeSignature: TimeSignatureEvent = field(default_factory=lambda: TimeSignatureEvent(0, 4, 4))
    BpmChangeEvents: list[BpmEvent] = field(default_factory=list)
    TimeSignature: list[TimeSignatureEvent] = field(default_factory=list)
    PhaseChangeEvents: list[PhaseEvent] = field(default_factory=list)
    SingleNotes: list[SingleNote] = field(default_factory=list)
    HoldNotes: list[HoldNote] = field(default_factory=list)
    ShiftNotes: list[ShiftNote] = field(default_factory=list)
    RushNotes: list[RushNote] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "LevelJson":
        return cls(
            Version=int(raw.get("Version", 1)),
            MusicInfoName=str(raw.get("MusicInfoName", "")),
            Level=int(raw.get("Level", 1)),
            MusicPath=str(raw.get("MusicPath", "")),
            ScoreOffset=float(raw.get("ScoreOffset", 0.0)),
            InitBpm=BpmEvent.from_dict(raw.get("InitBpm", {}) or {}),
            InitTimeSignature=TimeSignatureEvent.from_dict(raw.get("InitTimeSignature", {}) or {}),
            BpmChangeEvents=[BpmEvent.from_dict(v) for v in raw.get("BpmChangeEvents", []) or []],
            TimeSignature=[TimeSignatureEvent.from_dict(v) for v in raw.get("TimeSignature", []) or []],
            PhaseChangeEvents=[PhaseEvent.from_dict(v) for v in raw.get("PhaseChangeEvents", []) or []],
            SingleNotes=[SingleNote.from_dict(v) for v in raw.get("SingleNotes", []) or []],
            HoldNotes=[HoldNote.from_dict(v) for v in raw.get("HoldNotes", []) or []],
            ShiftNotes=[ShiftNote.from_dict(v) for v in raw.get("ShiftNotes", []) or []],
            RushNotes=[RushNote.from_dict(v) for v in raw.get("RushNotes", []) or []],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "Version": int(self.Version),
            "MusicInfoName": self.MusicInfoName,
            "Level": int(self.Level),
            "MusicPath": self.MusicPath,
            "ScoreOffset": float(self.ScoreOffset),
            "InitBpm": self.InitBpm.to_dict(),
            "InitTimeSignature": self.InitTimeSignature.to_dict(),
            "BpmChangeEvents": [v.to_dict() for v in self.BpmChangeEvents],
            "TimeSignature": [v.to_dict() for v in self.TimeSignature],
            "PhaseChangeEvents": [v.to_dict() for v in self.PhaseChangeEvents],
            "SingleNotes": [v.to_dict() for v in self.SingleNotes],
            "HoldNotes": [v.to_dict() for v in self.HoldNotes],
            "ShiftNotes": [],
            "RushNotes": [v.to_dict() for v in self.RushNotes],
        }


def empty_song() -> SongJson:
    return SongJson()


def empty_level(music_info_name: str, difficulty: int, music_path: str) -> LevelJson:
    return LevelJson(MusicInfoName=music_info_name, Level=difficulty, MusicPath=music_path)


def audio_to_music_path(audio: str) -> str:
    return audio[:-4] if audio.lower().endswith(".ogg") else audio


def clamp_lane(lane: int) -> int:
    return max(LANE_MIN, min(LANE_MAX, int(lane)))


def clamp_rush_lane(lane: int) -> int:
    return max(LANE_MIN, min(LANE_MAX - 1, int(lane)))

