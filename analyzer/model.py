"""PitchVision canonical data model.

This is the single source of truth for the unified JSON exchanged between the
CV/analysis engine (Python, GPU worker) and the web viewer (Next.js).

Design rule: **all pitch coordinates are in meters**, with the origin at one
corner of the pitch. x runs along the length (goal-to-goal), y along the width.
Keeping coordinates in meters decouples all downstream logic (events, stats,
radar) from camera angle and resolution.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


# Standard full-size pitch. Goals are centered on the y axis at x=0 and x=length.
DEFAULT_PITCH_LENGTH_M = 105.0
DEFAULT_PITCH_WIDTH_M = 68.0
GOAL_WIDTH_M = 7.32


class Team(str, Enum):
    HOME = "home"
    AWAY = "away"


class EventType(str, Enum):
    PASS = "pass"            # successful pass to a teammate
    KEY_PASS = "key_pass"    # pass that directly created a shot/goal
    ASSIST = "assist"        # pass that directly led to a goal
    LOSS = "loss"            # lost possession to the opponent
    TACKLE = "tackle"        # won possession from the opponent
    GOAL = "goal"            # ball entered the goal


@dataclass
class Pitch:
    length_m: float = DEFAULT_PITCH_LENGTH_M
    width_m: float = DEFAULT_PITCH_WIDTH_M
    goal_width_m: float = GOAL_WIDTH_M

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Pitch":
        return Pitch(
            length_m=float(d.get("length_m", DEFAULT_PITCH_LENGTH_M)),
            width_m=float(d.get("width_m", DEFAULT_PITCH_WIDTH_M)),
            goal_width_m=float(d.get("goal_width_m", GOAL_WIDTH_M)),
        )


@dataclass
class MatchMeta:
    id: str
    date: str
    home_team: str
    away_team: str
    fps: float
    duration_s: float
    pitch: Pitch = field(default_factory=Pitch)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["pitch"] = self.pitch.to_dict()
        return d

    @staticmethod
    def from_dict(d: dict) -> "MatchMeta":
        return MatchMeta(
            id=str(d["id"]),
            date=str(d["date"]),
            home_team=str(d["home_team"]),
            away_team=str(d["away_team"]),
            fps=float(d["fps"]),
            duration_s=float(d["duration_s"]),
            pitch=Pitch.from_dict(d.get("pitch", {})),
        )


@dataclass
class Player:
    id: str
    team: Team
    label: str            # display name
    color: str            # hex, for radar/overlay
    number: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "team": self.team.value,
            "label": self.label,
            "color": self.color,
            "number": self.number,
        }

    @staticmethod
    def from_dict(d: dict) -> "Player":
        return Player(
            id=str(d["id"]),
            team=Team(d["team"]),
            label=str(d["label"]),
            color=str(d["color"]),
            number=d.get("number"),
        )


@dataclass
class Position:
    player: str           # player id
    x: float              # meters
    y: float              # meters

    def to_dict(self) -> dict:
        return {"player": self.player, "x": round(self.x, 3), "y": round(self.y, 3)}

    @staticmethod
    def from_dict(d: dict) -> "Position":
        return Position(player=str(d["player"]), x=float(d["x"]), y=float(d["y"]))


@dataclass
class Frame:
    t: float                          # seconds
    ball: Optional[tuple[float, float]]  # (x, y) meters, or None if not detected
    positions: list[Position] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "t": round(self.t, 3),
            "ball": None if self.ball is None else [round(self.ball[0], 3), round(self.ball[1], 3)],
            "positions": [p.to_dict() for p in self.positions],
        }

    @staticmethod
    def from_dict(d: dict) -> "Frame":
        ball = d.get("ball")
        return Frame(
            t=float(d["t"]),
            ball=None if ball is None else (float(ball[0]), float(ball[1])),
            positions=[Position.from_dict(p) for p in d.get("positions", [])],
        )


@dataclass
class Event:
    t: float
    type: EventType
    player: str                    # primary player id
    target: Optional[str] = None   # e.g. pass receiver
    outcome: Optional[str] = None  # free-form: "completed", "intercepted", ...
    confidence: float = 1.0
    confirmed: bool = False        # HITL flag

    def to_dict(self) -> dict:
        return {
            "t": round(self.t, 3),
            "type": self.type.value,
            "player": self.player,
            "target": self.target,
            "outcome": self.outcome,
            "confidence": round(self.confidence, 3),
            "confirmed": self.confirmed,
        }

    @staticmethod
    def from_dict(d: dict) -> "Event":
        return Event(
            t=float(d["t"]),
            type=EventType(d["type"]),
            player=str(d["player"]),
            target=d.get("target"),
            outcome=d.get("outcome"),
            confidence=float(d.get("confidence", 1.0)),
            confirmed=bool(d.get("confirmed", False)),
        )


@dataclass
class PlayerStats:
    player: str
    passes: int = 0
    passes_completed: int = 0
    key_passes: int = 0
    losses: int = 0
    tackles: int = 0
    goals: int = 0
    assists: int = 0
    distance_m: float = 0.0
    top_speed_kmh: float = 0.0
    possession_s: float = 0.0
    possession_pct: float = 0.0

    @property
    def pass_pct(self) -> float:
        return 0.0 if self.passes == 0 else 100.0 * self.passes_completed / self.passes

    def to_dict(self) -> dict:
        return {
            "player": self.player,
            "passes": self.passes,
            "passes_completed": self.passes_completed,
            "pass_pct": round(self.pass_pct, 1),
            "key_passes": self.key_passes,
            "losses": self.losses,
            "tackles": self.tackles,
            "goals": self.goals,
            "assists": self.assists,
            "distance_m": round(self.distance_m, 1),
            "top_speed_kmh": round(self.top_speed_kmh, 1),
            "possession_s": round(self.possession_s, 1),
            "possession_pct": round(self.possession_pct, 1),
        }

    @staticmethod
    def from_dict(d: dict) -> "PlayerStats":
        s = PlayerStats(player=str(d["player"]))
        for k in (
            "passes", "passes_completed", "key_passes", "losses",
            "tackles", "goals", "assists",
        ):
            setattr(s, k, int(d.get(k, 0)))
        for k in ("distance_m", "top_speed_kmh", "possession_s", "possession_pct"):
            setattr(s, k, float(d.get(k, 0.0)))
        return s


@dataclass
class MatchData:
    """The complete unified payload: the only thing that crosses Python <-> Web."""

    match: MatchMeta
    players: list[Player] = field(default_factory=list)
    frames: list[Frame] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    stats: dict[str, PlayerStats] = field(default_factory=dict)

    def player(self, pid: str) -> Optional[Player]:
        return next((p for p in self.players if p.id == pid), None)

    def to_dict(self) -> dict:
        return {
            "match": self.match.to_dict(),
            "players": [p.to_dict() for p in self.players],
            "frames": [f.to_dict() for f in self.frames],
            "events": [e.to_dict() for e in self.events],
            "stats": {pid: s.to_dict() for pid, s in self.stats.items()},
        }

    @staticmethod
    def from_dict(d: dict) -> "MatchData":
        return MatchData(
            match=MatchMeta.from_dict(d["match"]),
            players=[Player.from_dict(p) for p in d.get("players", [])],
            frames=[Frame.from_dict(f) for f in d.get("frames", [])],
            events=[Event.from_dict(e) for e in d.get("events", [])],
            stats={k: PlayerStats.from_dict(v) for k, v in d.get("stats", {}).items()},
        )

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def load(path: str) -> "MatchData":
        with open(path, encoding="utf-8") as fh:
            return MatchData.from_dict(json.load(fh))
