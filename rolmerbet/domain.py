from __future__ import annotations

from dataclasses import MISSING, asdict, dataclass, field
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
    shot_games: int = 0
    shots_on_target_for: float = 0.0
    shots_on_target_against: float = 0.0


@dataclass(slots=True)
class PlayerForm:
    games: int
    shots_on_target: float


@dataclass(slots=True)
class MatchContext:
    home: TeamForm
    away: TeamForm
    source: str
    notes: list[str] = field(default_factory=list)
    lineup_confirmed: bool = False
    confirmed_starters: set[str] = field(default_factory=set)
    player_shots_on_target: dict[str, PlayerForm] = field(default_factory=dict)
    source_names: list[str] = field(default_factory=list)
    source_count: int = 1
    source_agreement: float = 0.75
    injuries_checked: bool = False
    rotation_risk: str = "unknown"


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
    market_family: str = "unknown"
    evidence_grade: str = "Insuficiente"
    confidence_low: float = 0.0
    confidence_high: float = 0.0
    ranking_score: float = 0.0
    presentation_tier: str = "DESCARTADA"
    rejection_codes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evaluation":
        # Los historiales 0.5.x no contienen los campos de evidencia de 0.6.
        # Usar los valores por defecto mantiene esos registros legibles sin
        # hacerlos pasar por análisis nuevos.
        values: dict[str, Any] = {}
        for name, definition in cls.__dataclass_fields__.items():
            if name in data:
                values[name] = data[name]
            elif definition.default_factory is not MISSING:
                values[name] = definition.default_factory()
            elif definition.default is not MISSING:
                values[name] = definition.default
        return cls(**values)


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

