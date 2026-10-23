from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Quote:
    market: str
    selection: str
    american: str
    decimal: float
    line: float | None = None
    captured_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Match:
    match_id: str
    date_text: str
    kickoff_iso: str
    competition: str
    country: str
    home: str
    away: str
    source_url: str
    quotes: list[Quote] = field(default_factory=list)
    is_live: bool = False

    @property
    def name(self) -> str:
        return f"{self.home} vs {self.away}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["quotes"] = [q.to_dict() for q in self.quotes]
        return data


@dataclass(slots=True)
class TeamForm:
    games: int
    gf: float
    ga: float
    ppg: float
    home_gf: float
    home_ga: float
    away_gf: float
    away_ga: float
    over15: float
    over25: float
    btts: float
    sequence: str
    corner_games: int = 0
    corners_for: float = 0.0
    corners_against: float = 0.0


@dataclass(slots=True)
class MatchContext:
    home: TeamForm
    away: TeamForm
    source: str
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Evaluation:
    match_id: str
    competition: str
    kickoff_iso: str
    match_name: str
    market: str
    selection: str
    american: str
    decimal: float
    implied: float
    model_probability: float
    adjusted_probability: float
    quality: int
    accepted: bool
    reason: str
    risk: str
    route: str
    main_risk: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evaluation":
        return cls(**{name: data[name] for name in cls.__dataclass_fields__})


@dataclass(slots=True)
class Combo:
    selections: list[Evaluation]
    total_odds: float
    implied_probability: float
    estimated_probability: float
    status: str
    message: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "selections": [s.to_dict() for s in self.selections],
            "total_odds": self.total_odds,
            "implied_probability": self.implied_probability,
            "estimated_probability": self.estimated_probability,
            "status": self.status,
            "message": self.message,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Combo":
        return cls(
            selections=[Evaluation.from_dict(item) for item in data.get("selections", [])],
            total_odds=float(data.get("total_odds", 1.0)),
            implied_probability=float(data.get("implied_probability", 1.0)),
            estimated_probability=float(data.get("estimated_probability", 0.0)),
            status=str(data.get("status", "VACÍA")),
            message=str(data.get("message", "")),
            created_at=str(data.get("created_at", datetime.now().isoformat(timespec="seconds"))),
        )

