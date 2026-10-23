from __future__ import annotations

import itertools
import math
import re
from typing import Callable, Protocol

from .domain import Combo, Evaluation, Match, MatchContext, Quote
from .odds import implied_probability, multiply_odds
from .providers.football_data import StatsUnavailable


class ContextProvider(Protocol):
    def context_for(self, match: Match) -> MatchContext: ...


def _poisson(k: int, mean: float) -> float:
    return math.exp(-mean) * mean ** k / math.factorial(k)


def _score_matrix(home_mean: float, away_mean: float, cap: int = 10) -> list[tuple[int, int, float]]:
    cells = [(h, a, _poisson(h, home_mean) * _poisson(a, away_mean))
             for h in range(cap + 1) for a in range(cap + 1)]
    total = sum(p for _h, _a, p in cells)
    return [(h, a, p / total) for h, a, p in cells]


def _negative_binomial_pmf(k: int, mean: float, dispersion: float = 1.22) -> float:
    if mean <= 0:
        return 1.0 if k == 0 else 0.0
    r = mean / max(0.001, dispersion - 1.0)
    p = r / (r + mean)
    return math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
                    + r * math.log(p) + k * math.log(1.0 - p))


def _corner_probability(line: float, mean: float, over: bool) -> float:
    below = sum(_negative_binomial_pmf(k, mean) for k in range(0, int(math.floor(line)) + 1))
    return (1.0 - below) if over else below


def _expected_goals(context: MatchContext) -> tuple[float, float]:
    h, a = context.home, context.away
    home = 0.38 * h.home_gf + 0.34 * a.away_ga + 0.14 * h.gf + 0.14 * a.ga
    away = 0.38 * a.away_gf + 0.34 * h.home_ga + 0.14 * a.gf + 0.14 * h.ga
    home = 0.90 * home + 0.10 * 1.42
    away = 0.90 * away + 0.10 * 1.16
    return min(4.5, max(0.20, home)), min(4.5, max(0.20, away))


def _probability(match: Match, quote: Quote, context: MatchContext) -> tuple[float | None, str]:
    market = quote.market.casefold()
    selection = quote.selection.casefold()
    if "esquina" in market or "corner" in market:
        if min(context.home.corner_games, context.away.corner_games) < 8 or quote.line is None:
            return None, "Faltan al menos ocho partidos de córners por equipo."
        expected = ((context.home.corners_for + context.away.corners_against) / 2.0
                    + (context.away.corners_for + context.home.corners_against) / 2.0)
        if "más" in selection or "mas" in selection:
            return _corner_probability(quote.line, expected, True), f"Media ajustada de córners: {expected:.1f}."
        if "menos" in selection:
            return _corner_probability(quote.line, expected, False), f"Media ajustada de córners: {expected:.1f}."
        return None, "El tipo de selección de córners no pudo interpretarse."

    home_mean, away_mean = _expected_goals(context)
    cells = _score_matrix(home_mean, away_mean)
    if market == "1x2":
        if selection == match.home.casefold():
            p = sum(prob for h, a, prob in cells if h > a)
        elif selection == match.away.casefold():
            p = sum(prob for h, a, prob in cells if a > h)
        elif "empate" in selection:
            p = sum(prob for h, a, prob in cells if h == a)
        else:
            return None, "La selección 1x2 no coincide con los equipos."
        return p, f"Goles esperados: {match.home} {home_mean:.2f}, {match.away} {away_mean:.2f}."

    if "gol" in market and quote.line is not None:
        threshold = quote.line
        if "más" in selection or "mas" in selection:
            p = sum(prob for h, a, prob in cells if h + a > threshold)
        elif "menos" in selection:
            p = sum(prob for h, a, prob in cells if h + a < threshold)
        else:
            return None, "El tipo de total de goles no pudo interpretarse."
        return p, f"Goles esperados totales: {home_mean + away_mean:.2f}."
    return None, "Mercado todavía no compatible con el motor automático."


def _quality(match: Match, context: MatchContext) -> int:
    sample = min(context.home.games, context.away.games)
    score = 62 + min(sample, 10) * 3
    if "DEMO" in match.competition:
        return min(92, score)
    if context.notes:
        score -= 5
    if any(word in match.competition.casefold() for word in ("cup", "copa", "league")):
        score -= 2
    return max(0, min(100, score))


def evaluate_match(match: Match, context: MatchContext, config: dict) -> list[Evaluation]:
    evaluations: list[Evaluation] = []
    quality = _quality(match, context)
    sample = min(context.home.games, context.away.games)
    uncertainty = 0.025 + (0.035 if sample < 8 else 0.0)
    if any(x in match.competition.casefold() for x in ("cup", "copa", "champions", "europa")):
        uncertainty += 0.02
    for quote in match.quotes:
        implied = implied_probability(quote.decimal)
        model, note = _probability(match, quote, context)
        if model is None:
            adjusted = 0.0
            accepted = False
            reason = note
            main_risk = "Información insuficiente o mercado no compatible."
        else:
            adjusted = max(0.0, min(0.99, model - uncertainty))
            edge = adjusted - implied
            accepted = (
                quality >= int(config["min_quality"])
                and adjusted >= float(config["min_leg_probability"])
                and edge >= float(config["min_edge"])
                and quote.decimal >= 1.15
            )
            decision = "Cumple los filtros." if accepted else "No supera todos los filtros conservadores."
            reason = (f"{note} Forma: {match.home} {context.home.ppg:.2f} puntos/partido; "
                      f"{match.away} {context.away.ppg:.2f}. {decision}")
            main_risk = ("Variación propia de los goles y posibles cambios de alineación."
                         if "gol" in quote.market.casefold() or quote.market == "1x2"
                         else "El volumen de córners depende del desarrollo del partido.")
        risk = "Bajo" if adjusted >= .78 else ("Medio" if adjusted >= .68 else "Alto")
        route = (f"Fútbol → {match.country or 'Competición'} → {match.competition} → {match.name} "
                 f"→ {quote.market} → {quote.selection}")
        evaluations.append(Evaluation(
            match_id=match.match_id, competition=match.competition,
            kickoff_iso=match.kickoff_iso, match_name=match.name,
            market=quote.market, selection=quote.selection, american=quote.american,
            decimal=quote.decimal, implied=implied, model_probability=model or 0.0,
            adjusted_probability=adjusted, quality=quality, accepted=accepted,
            reason=reason, risk=risk, route=route, main_risk=main_risk,
        ))
    return evaluations


def analyze_matches(matches: list[Match], provider: ContextProvider, config: dict,
                    progress: Callable[[str], None] | None = None) -> list[Evaluation]:
    progress = progress or (lambda _msg: None)
    out: list[Evaluation] = []
    for index, match in enumerate(matches, 1):
        progress(f"Analizando {index}/{len(matches)}: {match.name}")
        try:
            context = provider.context_for(match)
            out.extend(evaluate_match(match, context, config))
        except StatsUnavailable as exc:
            for quote in match.quotes:
                out.append(Evaluation(
                    match_id=match.match_id, competition=match.competition,
                    kickoff_iso=match.kickoff_iso, match_name=match.name,
                    market=quote.market, selection=quote.selection, american=quote.american,
                    decimal=quote.decimal, implied=implied_probability(quote.decimal),
                    model_probability=0.0, adjusted_probability=0.0, quality=0,
                    accepted=False, reason=str(exc), risk="Sin evaluar",
                    route=f"Fútbol → {match.competition} → {match.name} → {quote.market} → {quote.selection}",
                    main_risk="No existe información estadística suficiente.",
                ))
    return out


def build_combo(evaluations: list[Evaluation], config: dict) -> Combo:
    candidates = [e for e in evaluations if e.accepted]
    lo, hi = float(config["target_odds_min"]), float(config["target_odds_max"])
    max_legs = max(2, min(int(config["max_legs"]), 8))
    min_total = float(config["min_total_probability"])
    best: tuple[float, float, tuple[Evaluation, ...]] | None = None
    for size in range(2, min(max_legs, len(candidates)) + 1):
        for group in itertools.combinations(candidates, size):
            if len({e.match_id for e in group}) != size:
                continue
            odds = multiply_odds([e.decimal for e in group])
            if not (lo <= odds <= hi):
                continue
            probability = math.prod(e.adjusted_probability for e in group)
            if probability < min_total:
                continue
            rank = probability
            distance = abs(odds - (lo + hi) / 2.0)
            if best is None or rank > best[0] or (abs(rank - best[0]) < 1e-12 and distance < best[1]):
                best = (rank, distance, group)
    if best is None:
        return Combo([], 1.0, 1.0, 0.0, "NO_APOSTAR",
                     "No existe una combinación entre las cuotas solicitadas sin reducir los filtros.")
    group = list(best[2])
    total = multiply_odds([e.decimal for e in group])
    estimated = math.prod(e.adjusted_probability for e in group)
    return Combo(group, total, implied_probability(total), estimated, "LISTA",
                 "La combinada cumple los filtros configurados. Revisa las cuotas antes de apostar.")

