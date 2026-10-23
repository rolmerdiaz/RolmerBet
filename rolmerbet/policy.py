from __future__ import annotations

from dataclasses import dataclass

from .domain import Evaluation, Match, MatchContext, Quote
from .providers.football_data import normalize


@dataclass(frozen=True, slots=True)
class MarketRule:
    family: str
    label: str
    min_probability: float
    min_games: int
    min_quality: int
    min_odds: float = 1.15
    max_odds: float = 1.70
    confirmed_lineup: bool = False


# Un perfil conservador no puede medir todos los mercados con el mismo corte.
RULES = {
    "double_chance": MarketRule("double_chance", "Doble oportunidad", .72, 8, 72, 1.15, 1.62),
    "match_winner": MarketRule("match_winner", "Ganador 1X2", .64, 8, 76, 1.20, 1.68),
    "safe_goals": MarketRule("safe_goals", "Línea amplia de goles", .74, 8, 72, 1.15, 1.58),
    "goals": MarketRule("goals", "Total de goles", .68, 8, 74, 1.18, 1.68),
    "team_goals": MarketRule("team_goals", "Goles de equipo", .70, 8, 74, 1.18, 1.65),
    "corners": MarketRule("corners", "Córners", .68, 8, 76, 1.18, 1.68),
    "team_shots": MarketRule("team_shots", "Remates al arco del equipo", .68, 8, 76, 1.18, 1.68),
    "player_shots": MarketRule("player_shots", "Remates al arco de jugador", .65, 5, 80, 1.20, 1.70, True),
    "unsupported": MarketRule("unsupported", "Mercado no compatible", .99, 99, 99, 9.0, 9.0),
}


def market_family(match: Match, quote: Quote) -> str:
    market = normalize(quote.market)
    selection = normalize(quote.selection)
    home, away = normalize(match.home), normalize(match.away)

    if "doble oportunidad" in market:
        return "double_chance"
    if market == "1x2":
        return "match_winner"
    if "remates a puerta" in market or "remates al arco" in market:
        if "total" in market and (home in market or away in market):
            return "team_shots"
        return "player_shots"
    if "esquina" in market or "corner" in market:
        return "corners"
    if "gol" in market:
        if home in market or away in market:
            return "team_goals"
        line = quote.line
        if line is not None and (("mas" in selection and line <= 1.5)
                                 or ("menos" in selection and line >= 4.5)):
            return "safe_goals"
        return "goals"
    return "unsupported"


def rule_for(match: Match, quote: Quote) -> MarketRule:
    return RULES[market_family(match, quote)]


def sample_size(family: str, context: MatchContext, quote: Quote) -> int:
    if family == "corners":
        return min(context.home.corner_games, context.away.corner_games)
    if family == "team_shots":
        return min(context.home.shot_games, context.away.shot_games)
    if family == "player_shots":
        player = quote.selection.rsplit("—", 1)[-1].strip() if "—" in quote.selection else ""
        form = context.player_shots_on_target.get(normalize(player))
        return form.games if form else 0
    return min(context.home.games, context.away.games)


def grade_for(quality: int, source_count: int, agreement: float) -> str:
    if quality >= 86 and source_count >= 2 and agreement >= .82:
        return "A"
    if quality >= 74 and agreement >= .68:
        return "B"
    if quality >= 62:
        return "C"
    return "Insuficiente"


def presentation_order(item: Evaluation) -> tuple[int, float, int, float]:
    tier = {"COMBINADA": 0, "VIABLE": 1, "ALTERNATIVA": 2, "DESCARTADA": 3}
    return (tier.get(item.presentation_tier, 4), -item.ranking_score,
            -item.quality, -item.adjusted_probability)

