from __future__ import annotations

import itertools
import math
import re
from typing import Callable, Protocol

from .domain import Combo, Evaluation, Match, MatchContext, Quote
from .odds import implied_probability, multiply_odds
from .providers.football_data import StatsUnavailable, normalize, similarity


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


def _over_under_probability(line: float, mean: float, selection: str) -> float | None:
    over = "mas" in normalize(selection)
    under = "menos" in normalize(selection)
    if not over and not under:
        return None
    return _corner_probability(line, mean, over)


def _player_name(market: str, selection: str) -> str:
    if "—" in selection:
        return selection.rsplit("—", 1)[-1].strip()
    if " - " in market:
        return market.rsplit(" - ", 1)[-1].strip()
    return ""


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
    market_norm = normalize(quote.market)
    selection_norm = normalize(quote.selection)
    home_norm, away_norm = normalize(match.home), normalize(match.away)

    if "esquina" in market or "corner" in market:
        if min(context.home.corner_games, context.away.corner_games) < 5 or quote.line is None:
            return None, "Faltan al menos cinco partidos con datos de córners por equipo."
        home_expected = (context.home.corners_for + context.away.corners_against) / 2.0
        away_expected = (context.away.corners_for + context.home.corners_against) / 2.0
        if home_norm in market_norm:
            expected, label = home_expected, match.home
        elif away_norm in market_norm:
            expected, label = away_expected, match.away
        else:
            expected, label = home_expected + away_expected, "el partido"
        p = _over_under_probability(quote.line, expected, quote.selection)
        if p is None:
            return None, "El tipo de selección de córners no pudo interpretarse."
        return p, f"Media ajustada de córners para {label}: {expected:.1f}."

    if "remates a puerta" in market_norm:
        if quote.line is None:
            return None, "Triunfobet no mostró una línea interpretable de remates a puerta."
        if "total" in market_norm:
            if min(context.home.shot_games, context.away.shot_games) < 5:
                return None, "Faltan cinco partidos con remates a puerta por equipo."
            home_expected = (context.home.shots_on_target_for + context.away.shots_on_target_against) / 2.0
            away_expected = (context.away.shots_on_target_for + context.home.shots_on_target_against) / 2.0
            if home_norm in market_norm:
                expected, label = home_expected, match.home
            elif away_norm in market_norm:
                expected, label = away_expected, match.away
            else:
                expected, label = home_expected + away_expected, "el partido"
            p = _over_under_probability(quote.line, expected, quote.selection)
            if p is None:
                return None, "El tipo de total de remates a puerta no pudo interpretarse."
            return p, f"Media ajustada de remates a puerta para {label}: {expected:.1f}."

        player = _player_name(quote.market, quote.selection)
        player_key = normalize(player)
        if not player:
            return None, "No se pudo identificar al jugador de este mercado."
        if not context.lineup_confirmed:
            return None, "El remate del jugador se descarta hasta que la alineación sea oficial."
        if not any(similarity(player_key, starter) >= 0.82 for starter in context.confirmed_starters):
            return None, f"{player} no figura como titular confirmado."
        form = context.player_shots_on_target.get(player_key)
        if not form or form.games < 3:
            return None, f"Faltan al menos tres apariciones recientes con datos para {player}."
        p = _over_under_probability(quote.line, form.shots_on_target, quote.selection)
        if p is None:
            return None, "El tipo de remate a puerta del jugador no pudo interpretarse."
        return p, (f"{player}: {form.shots_on_target:.2f} remates a puerta por partido "
                   f"en {form.games} apariciones; titular confirmado.")

    home_mean, away_mean = _expected_goals(context)
    cells = _score_matrix(home_mean, away_mean)
    if "doble oportunidad" in market_norm:
        home_win = sum(prob for h, a, prob in cells if h > a)
        draw = sum(prob for h, a, prob in cells if h == a)
        away_win = sum(prob for h, a, prob in cells if a > h)
        has_home = home_norm in selection_norm
        has_away = away_norm in selection_norm
        has_draw = "empate" in selection_norm
        if has_home and has_draw:
            p = home_win + draw
        elif has_away and has_draw:
            p = away_win + draw
        elif has_home and has_away:
            p = home_win + away_win
        else:
            return None, "La doble oportunidad no coincide con los equipos."
        return p, (f"Doble oportunidad calculada con goles esperados: "
                   f"{match.home} {home_mean:.2f}, {match.away} {away_mean:.2f}.")

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
        if home_norm in market_norm:
            value = lambda h, a: h
            label = match.home
        elif away_norm in market_norm:
            value = lambda h, a: a
            label = match.away
        else:
            value = lambda h, a: h + a
            label = "el partido"
        if "más" in selection or "mas" in selection:
            p = sum(prob for h, a, prob in cells if value(h, a) > threshold)
        elif "menos" in selection:
            p = sum(prob for h, a, prob in cells if value(h, a) < threshold)
        else:
            return None, "El tipo de total de goles no pudo interpretarse."
        expected = home_mean if label == match.home else (away_mean if label == match.away else home_mean + away_mean)
        return p, f"Goles esperados para {label}: {expected:.2f}."
    return None, "Mercado todavía no compatible con el motor automático."


def _quality(match: Match, context: MatchContext) -> int:
    sample = min(context.home.games, context.away.games)
    score = 62 + min(sample, 10) * 3
    if "DEMO" in match.competition:
        return min(92, score)
    # Las notas pueden referirse a un mercado distinto. Por ejemplo, que aún no
    # haya titulares no debe reducir la calidad de un total de goles o un 1X2.
    # Cada mercado ya valida sus propios datos dentro de _probability().
    if any(word in match.competition.casefold() for word in ("cup", "copa", "coppa", "carabao")):
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
            failures: list[str] = []
            if quality < int(config["min_quality"]):
                failures.append(f"calidad {quality} < {int(config['min_quality'])}")
            if adjusted < float(config["min_leg_probability"]):
                failures.append(
                    f"probabilidad ajustada {adjusted:.1%} < {float(config['min_leg_probability']):.1%}"
                )
            if edge < float(config["min_edge"]):
                failures.append(
                    f"diferencia frente a la cuota {edge:+.1%} < {float(config['min_edge']):+.1%}"
                )
            if quote.decimal < 1.15:
                failures.append(f"cuota decimal {quote.decimal:.2f} < 1.15")
            accepted = not failures
            decision = ("Cumple los filtros."
                        if accepted else "Descartada por: " + "; ".join(failures) + ".")
            reason = (f"{note} Forma: {match.home} {context.home.ppg:.2f} puntos/partido; "
                      f"{match.away} {context.away.ppg:.2f}. {decision}")
            quote_norm = normalize(quote.market)
            if "remates a puerta" in quote_norm:
                main_risk = "Los remates dependen de los minutos jugados, la función táctica y el rival."
            elif "esquina" in quote_norm or "corner" in quote_norm:
                main_risk = "El volumen de córners depende del desarrollo del partido."
            else:
                main_risk = "Variación propia de los goles y posibles cambios de alineación."
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

