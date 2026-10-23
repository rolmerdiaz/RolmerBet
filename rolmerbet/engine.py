from __future__ import annotations

import itertools
import math
from collections import defaultdict
from typing import Callable, Protocol

from .domain import Combo, Evaluation, Match, MatchContext, Quote
from .odds import implied_probability, multiply_odds
from .policy import grade_for, market_family, presentation_order, rule_for, sample_size
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


def _over_under_probability(line: float, mean: float, selection: str) -> float | None:
    over = "mas" in normalize(selection)
    under = "menos" in normalize(selection)
    if not over and not under:
        return None
    below = sum(_negative_binomial_pmf(k, mean)
                for k in range(0, int(math.floor(line)) + 1))
    return 1.0 - below if over else below


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
    family = market_family(match, quote)
    market_norm = normalize(quote.market)
    selection_norm = normalize(quote.selection)
    home_norm, away_norm = normalize(match.home), normalize(match.away)

    if family == "corners":
        if quote.line is None:
            return None, "Triunfobet no mostró una línea de córners interpretable."
        home_expected = (context.home.corners_for + context.away.corners_against) / 2.0
        away_expected = (context.away.corners_for + context.home.corners_against) / 2.0
        if home_norm in market_norm:
            expected, label = home_expected, match.home
        elif away_norm in market_norm:
            expected, label = away_expected, match.away
        else:
            expected, label = home_expected + away_expected, "el partido"
        probability = _over_under_probability(quote.line, expected, quote.selection)
        if probability is None:
            return None, "La selección de córners no pudo interpretarse."
        return probability, f"Media ajustada de córners para {label}: {expected:.1f}."

    if family in {"team_shots", "player_shots"}:
        if quote.line is None:
            return None, "Triunfobet no mostró una línea de remates al arco interpretable."
        if family == "team_shots":
            home_expected = (context.home.shots_on_target_for
                             + context.away.shots_on_target_against) / 2.0
            away_expected = (context.away.shots_on_target_for
                             + context.home.shots_on_target_against) / 2.0
            if home_norm in market_norm:
                expected, label = home_expected, match.home
            elif away_norm in market_norm:
                expected, label = away_expected, match.away
            else:
                expected, label = home_expected + away_expected, "el partido"
            probability = _over_under_probability(quote.line, expected, quote.selection)
            if probability is None:
                return None, "El total de remates al arco no pudo interpretarse."
            return probability, f"Media ajustada de remates al arco para {label}: {expected:.1f}."

        player = _player_name(quote.market, quote.selection)
        player_key = normalize(player)
        if not player:
            return None, "No se pudo identificar al jugador."
        if not context.lineup_confirmed:
            return None, "El jugador se descarta hasta que la alineación sea oficial."
        if not any(similarity(player_key, starter) >= 0.82 for starter in context.confirmed_starters):
            return None, f"{player} no figura como titular confirmado."
        form = context.player_shots_on_target.get(player_key)
        if not form or form.games < 5:
            return None, f"Faltan cinco titularidades recientes con datos para {player}."
        probability = _over_under_probability(quote.line, form.shots_on_target, quote.selection)
        if probability is None:
            return None, "El mercado de remates del jugador no pudo interpretarse."
        return probability, (f"{player}: {form.shots_on_target:.2f} remates al arco por partido "
                             f"en {form.games} apariciones; titular confirmado.")

    home_mean, away_mean = _expected_goals(context)
    cells = _score_matrix(home_mean, away_mean)
    if family == "double_chance":
        home_win = sum(prob for h, a, prob in cells if h > a)
        draw = sum(prob for h, a, prob in cells if h == a)
        away_win = sum(prob for h, a, prob in cells if a > h)
        has_home = home_norm in selection_norm
        has_away = away_norm in selection_norm
        has_draw = "empate" in selection_norm
        if has_home and has_draw:
            probability = home_win + draw
        elif has_away and has_draw:
            probability = away_win + draw
        elif has_home and has_away:
            probability = home_win + away_win
        else:
            return None, "La doble oportunidad no coincide con los equipos."
        return probability, (f"Doble oportunidad con goles esperados: "
                             f"{match.home} {home_mean:.2f}; {match.away} {away_mean:.2f}.")

    if family == "match_winner":
        if selection_norm == home_norm:
            probability = sum(prob for h, a, prob in cells if h > a)
        elif selection_norm == away_norm:
            probability = sum(prob for h, a, prob in cells if a > h)
        elif "empate" in selection_norm:
            probability = sum(prob for h, a, prob in cells if h == a)
        else:
            return None, "La selección 1X2 no coincide con los equipos."
        return probability, (f"Goles esperados: {match.home} {home_mean:.2f}; "
                             f"{match.away} {away_mean:.2f}.")

    if family in {"safe_goals", "goals", "team_goals"} and quote.line is not None:
        if home_norm in market_norm:
            value = lambda h, a: h
            expected, label = home_mean, match.home
        elif away_norm in market_norm:
            value = lambda h, a: a
            expected, label = away_mean, match.away
        else:
            value = lambda h, a: h + a
            expected, label = home_mean + away_mean, "el partido"
        if "mas" in selection_norm:
            probability = sum(prob for h, a, prob in cells if value(h, a) > quote.line)
        elif "menos" in selection_norm:
            probability = sum(prob for h, a, prob in cells if value(h, a) < quote.line)
        else:
            return None, "El tipo de total de goles no pudo interpretarse."
        return probability, f"Goles esperados para {label}: {expected:.2f}."

    return None, "Mercado no compatible con el perfil conservador."


def _quality(match: Match, context: MatchContext, quote: Quote | None = None) -> int:
    family = market_family(match, quote) if quote else "goals"
    observed = sample_size(family, context, quote) if quote else min(context.home.games, context.away.games)
    required = rule_for(match, quote).min_games if quote else 8
    sample_score = 35.0 * min(1.0, observed / max(1, required))
    source_count = max(1, context.source_count or len(context.source_names))
    source_score = 18.0 if source_count == 1 else (26.0 if source_count == 2 else 30.0)
    agreement_score = 20.0 * max(0.0, min(1.0, context.source_agreement))
    if family == "player_shots":
        verification_score = 10.0 if context.lineup_confirmed else 0.0
    elif family in {"match_winner", "double_chance", "goals", "safe_goals", "team_goals"}:
        verification_score = 10.0 if context.injuries_checked else 5.0
    else:
        verification_score = 8.0
    score = sample_score + source_score + agreement_score + verification_score
    if any(word in normalize(match.competition) for word in ("cup", "copa", "coppa", "carabao")):
        score -= 3.0
    return max(0, min(100, round(score)))


def _confidence_band(match: Match, quote: Quote, context: MatchContext,
                     probability: float) -> tuple[float, float]:
    family = market_family(match, quote)
    rule = rule_for(match, quote)
    observed = sample_size(family, context, quote)
    margin = .018
    if observed < rule.min_games:
        margin += .045 * (1.0 - observed / max(1, rule.min_games))
    if max(1, context.source_count) == 1:
        margin += .025
    margin += max(0.0, .82 - context.source_agreement) * .10
    if context.rotation_risk == "high":
        margin += .035
    elif context.rotation_risk == "medium":
        margin += .015
    if any(word in normalize(match.competition)
           for word in ("cup", "copa", "coppa", "carabao", "champions", "europa")):
        margin += .012
    return max(0.0, probability - margin), min(.99, probability + margin)


def _risk_label(probability: float, quality: int) -> str:
    if probability >= .76 and quality >= 80:
        return "Bajo"
    if probability >= .64 and quality >= 68:
        return "Medio"
    return "Alto"


def _ranking(probability: float, quality: int, decimal: float, implied: float,
             family: str) -> float:
    price_fit = max(0.0, 1.0 - abs(decimal - 1.42) / .55)
    edge = max(-.08, min(.08, probability - implied))
    family_bonus = .035 if family in {"double_chance", "safe_goals"} else 0.0
    return probability * .58 + (quality / 100.0) * .24 + price_fit * .10 + edge + family_bonus


def evaluate_match(match: Match, context: MatchContext, config: dict) -> list[Evaluation]:
    evaluations: list[Evaluation] = []
    sources = context.source_names or [x.strip() for x in context.source.split("+") if x.strip()]
    source_count = max(context.source_count, len(sources), 1)
    for quote in match.quotes:
        family = market_family(match, quote)
        rule = rule_for(match, quote)
        quality = _quality(match, context, quote)
        implied = implied_probability(quote.decimal)
        model, note = _probability(match, quote, context)
        failures: list[str] = []
        if model is None:
            low = high = 0.0
            failures.append("sin_modelo")
        else:
            low, high = _confidence_band(match, quote, context, model)
            observed = sample_size(family, context, quote)
            if observed < rule.min_games:
                failures.append("muestra_insuficiente")
            if quality < rule.min_quality:
                failures.append("evidencia_insuficiente")
            if low < rule.min_probability:
                failures.append("probabilidad_insuficiente")
            if quote.decimal < rule.min_odds:
                failures.append("cuota_demasiado_baja")
            if quote.decimal > rule.max_odds:
                failures.append("cuota_demasiado_alta")
            if model - implied < -.08:
                failures.append("precio_desfavorable")
            if rule.confirmed_lineup and not context.lineup_confirmed:
                failures.append("alineacion_no_confirmada")
            if rule.injuries_required and not context.injuries_checked:
                failures.append("bajas_no_verificadas")
            if context.source_count >= 2 and context.source_agreement < .60:
                failures.append("fuentes_en_conflicto")
            if context.rotation_risk == "high" and family in {"match_winner", "player_shots"}:
                failures.append("rotacion_alta")

        accepted = model is not None and not failures
        near_threshold = (model is not None and low >= max(.55, rule.min_probability - .07)
                          and quality >= rule.min_quality - 10 and quote.decimal >= 1.15)
        tier = "VIABLE" if accepted else ("ALTERNATIVA" if near_threshold else "DESCARTADA")
        grade = grade_for(quality, source_count, context.source_agreement)
        score = _ranking(low, quality, quote.decimal, implied, family) if model is not None else 0.0
        if accepted:
            decision = f"Cumple el filtro de {rule.label}."
        else:
            labels = {
                "sin_modelo": "mercado sin datos interpretables",
                "muestra_insuficiente": "muestra estadística insuficiente",
                "evidencia_insuficiente": "calidad de evidencia insuficiente",
                "probabilidad_insuficiente": "probabilidad prudente insuficiente",
                "cuota_demasiado_baja": "cuota demasiado baja para añadir riesgo",
                "cuota_demasiado_alta": "cuota fuera del perfil conservador",
                "precio_desfavorable": "precio claramente desfavorable",
                "alineacion_no_confirmada": "titularidad no confirmada",
                "bajas_no_verificadas": "bajas y sanciones sin verificar",
                "fuentes_en_conflicto": "las fuentes deportivas discrepan demasiado",
                "rotacion_alta": "riesgo alto de rotación",
            }
            decision = "No cumple: " + ", ".join(labels[x] for x in failures) + "."
        reason = (f"{note} Probabilidad central {model:.1%}; intervalo prudente "
                  f"{low:.1%}–{high:.1%}. {decision}" if model is not None else f"{note} {decision}")
        if family in {"player_shots", "team_shots"}:
            main_risk = "Los remates dependen del rol, los minutos y el planteamiento del rival."
        elif family == "corners":
            main_risk = "Los córners son sensibles al marcador y al desarrollo del partido."
        elif family in {"match_winner", "double_chance"}:
            main_risk = "Bajas, rotaciones y cambios de once pueden alterar la superioridad prevista."
        else:
            main_risk = "La definición y un cambio temprano del guion pueden alterar el total de goles."
        route = (f"Fútbol → {match.country or 'Competición'} → {match.competition} → {match.name} "
                 f"→ {quote.market} → {quote.selection}")
        evaluations.append(Evaluation(
            match_id=match.match_id, competition=match.competition,
            kickoff_iso=match.kickoff_iso, match_name=match.name,
            market=quote.market, selection=quote.selection, american=quote.american,
            decimal=quote.decimal, implied=implied, model_probability=model or 0.0,
            adjusted_probability=low, quality=quality, accepted=accepted,
            reason=reason, risk=_risk_label(low, quality), route=route,
            main_risk=main_risk, market_family=family, evidence_grade=grade,
            confidence_low=low, confidence_high=high, ranking_score=score,
            presentation_tier=tier, rejection_codes=failures, sources=sources,
            source_warnings=list(dict.fromkeys(context.notes)),
        ))
    return evaluations


def _keep_one_market_per_match(evaluations: list[Evaluation]) -> None:
    grouped: dict[str, list[Evaluation]] = defaultdict(list)
    for item in evaluations:
        grouped[item.match_id].append(item)
    for group in grouped.values():
        viable = [x for x in group if x.accepted]
        if viable:
            winner = max(viable, key=lambda x: x.ranking_score)
            for item in viable:
                item.presentation_tier = "VIABLE" if item is winner else "ALTERNATIVA"
            continue
        alternatives = [x for x in group if x.presentation_tier == "ALTERNATIVA"]
        if alternatives:
            winner = max(alternatives, key=lambda x: x.ranking_score)
            for item in alternatives:
                if item is not winner:
                    item.presentation_tier = "DESCARTADA"


def analyze_matches(matches: list[Match], provider: ContextProvider, config: dict,
                    progress: Callable[[str], None] | None = None) -> list[Evaluation]:
    progress = progress or (lambda _msg: None)
    output: list[Evaluation] = []
    for index, match in enumerate(matches, 1):
        progress(f"Analizando {index}/{len(matches)}: {match.name}")
        try:
            context = provider.context_for(match)
            output.extend(evaluate_match(match, context, config))
        except StatsUnavailable as exc:
            for quote in match.quotes:
                output.append(Evaluation(
                    match_id=match.match_id, competition=match.competition,
                    kickoff_iso=match.kickoff_iso, match_name=match.name,
                    market=quote.market, selection=quote.selection, american=quote.american,
                    decimal=quote.decimal, implied=implied_probability(quote.decimal),
                    model_probability=0.0, adjusted_probability=0.0, quality=0,
                    accepted=False, reason=str(exc), risk="Sin evaluar",
                    route=f"Fútbol → {match.competition} → {match.name} → {quote.market} → {quote.selection}",
                    main_risk="No existe información estadística suficiente.",
                    market_family=market_family(match, quote), rejection_codes=["fuente_no_disponible"],
                    source_warnings=[str(exc)],
                ))
    _keep_one_market_per_match(output)
    return sorted(output, key=presentation_order)


def build_combo(evaluations: list[Evaluation], config: dict) -> Combo:
    candidates = [e for e in evaluations if e.accepted and e.presentation_tier == "VIABLE"]
    lo, hi = float(config["target_odds_min"]), float(config["target_odds_max"])
    max_legs = max(2, min(int(config["max_legs"]), 5))
    min_total = float(config.get("min_total_probability", .28))
    best: tuple[float, float, int, tuple[Evaluation, ...]] | None = None
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
            distance = abs(odds - (lo + hi) / 2.0)
            candidate = (probability, -distance, -size, group)
            if best is None or candidate[:3] > best[:3]:
                best = candidate
    if best is None:
        return Combo([], 1.0, 1.0, 0.0, "NO_APOSTAR",
                     "No existe una combinada 3.00–4.00 que conserve todos los filtros específicos. "
                     "La aplicación no añadirá una selección débil para completar la cuota.")
    group = list(best[3])
    for item in group:
        item.presentation_tier = "COMBINADA"
    total = multiply_odds([e.decimal for e in group])
    estimated = math.prod(e.adjusted_probability for e in group)
    return Combo(group, total, implied_probability(total), estimated, "LISTA",
                 "Cada partido aporta un único mercado y todas las selecciones cumplen su filtro específico.")

