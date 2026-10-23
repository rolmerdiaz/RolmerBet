from __future__ import annotations

from dataclasses import fields

from ..domain import Match, MatchContext, PlayerForm, TeamForm
from .football_data import StatsUnavailable, normalize


_AVERAGED_FIELDS = {
    "gf", "ga", "ppg", "home_gf", "home_ga", "away_gf", "away_ga",
    "over15", "over25", "btts", "corners_for", "corners_against",
    "shots_on_target_for", "shots_on_target_against",
}


def _combine_forms(forms: list[TeamForm]) -> TeamForm:
    def average(name: str) -> float:
        values = [float(getattr(item, name)) for item in forms]
        return sum(values) / len(values)

    data = {}
    for definition in fields(TeamForm):
        name = definition.name
        if name in _AVERAGED_FIELDS:
            data[name] = average(name)
        elif name in {"games", "corner_games", "shot_games"}:
            data[name] = min(int(getattr(item, name)) for item in forms)
        elif name == "sequence":
            data[name] = forms[0].sequence
    return TeamForm(**data)


def _agreement(contexts: list[MatchContext]) -> float:
    if len(contexts) < 2:
        return contexts[0].source_agreement if contexts else 0.0
    differences: list[float] = []
    scales = {"gf": 2.0, "ga": 2.0, "ppg": 3.0, "over15": 1.0,
              "corners_for": 8.0, "shots_on_target_for": 7.0}
    for side in ("home", "away"):
        for name, scale in scales.items():
            values = [float(getattr(getattr(item, side), name)) for item in contexts]
            if name in {"corners_for", "shots_on_target_for"} and not any(values):
                continue
            differences.append(min(1.0, (max(values) - min(values)) / scale))
    return max(.35, min(.98, 1.0 - (sum(differences) / len(differences) if differences else .25)))


def _player_forms(contexts: list[MatchContext]) -> dict[str, PlayerForm]:
    keys = {key for context in contexts for key in context.player_shots_on_target}
    output: dict[str, PlayerForm] = {}
    for key in keys:
        values = [context.player_shots_on_target[key]
                  for context in contexts if key in context.player_shots_on_target]
        if not values:
            continue
        total_games = sum(item.games for item in values)
        output[key] = PlayerForm(
            games=min(item.games for item in values),
            shots_on_target=(sum(item.shots_on_target * item.games for item in values)
                             / max(1, total_games)),
        )
    return output


class MultiSourceProvider:
    """Combina fuentes estadísticas; ninguna puede aportar cuotas."""

    def __init__(self, providers: list[object]):
        self.providers = providers

    def context_for(self, match: Match) -> MatchContext:
        contexts: list[MatchContext] = []
        failures: list[str] = []
        for provider in self.providers:
            name = provider.__class__.__name__.replace("Provider", "")
            try:
                contexts.append(provider.context_for(match))
            except StatsUnavailable as exc:
                failures.append(f"{name}: {exc}")
            except Exception as exc:
                failures.append(f"{name}: error inesperado ({exc})")
        if not contexts:
            detail = " · ".join(failures)
            raise StatsUnavailable(f"Ninguna fuente estadística pudo evaluar el partido. {detail}")

        names: list[str] = []
        for context in contexts:
            candidates = context.source_names or [context.source]
            for name in candidates:
                if name and name not in names:
                    names.append(name)
        notes = [note for context in contexts for note in context.notes]
        if failures:
            notes.append("Fuentes sin respuesta: " + " · ".join(failures))
        starters = set().union(*(context.confirmed_starters for context in contexts))
        lineup_confirmed = any(context.lineup_confirmed for context in contexts)
        risk_order = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
        rotation = max((context.rotation_risk for context in contexts),
                       key=lambda item: risk_order.get(item, 0), default="unknown")
        agreement = _agreement(contexts)
        return MatchContext(
            home=_combine_forms([context.home for context in contexts]),
            away=_combine_forms([context.away for context in contexts]),
            source=" + ".join(names), notes=notes,
            lineup_confirmed=lineup_confirmed, confirmed_starters=starters,
            player_shots_on_target=_player_forms(contexts),
            source_names=names, source_count=len(names), source_agreement=agreement,
            injuries_checked=any(context.injuries_checked for context in contexts),
            rotation_risk=rotation,
        )

