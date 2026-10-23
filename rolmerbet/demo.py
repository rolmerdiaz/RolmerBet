from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .domain import Match, MatchContext, PlayerForm, Quote, TeamForm


def _form(gf: float, ga: float, ppg: float, o15: float, o25: float,
          cf: float, ca: float, seq: str) -> TeamForm:
    return TeamForm(
        games=10, gf=gf, ga=ga, ppg=ppg,
        home_gf=gf + 0.12, home_ga=max(0.35, ga - 0.08),
        away_gf=max(0.35, gf - 0.10), away_ga=ga + 0.10,
        over15=o15, over25=o25, btts=min(o15, 0.58), sequence=seq,
        corner_games=10, corners_for=cf, corners_against=ca,
        shot_games=10, shots_on_target_for=max(2.2, gf * 2.4),
        shots_on_target_against=max(2.0, ga * 2.2),
    )


def demo_matches(target_date: date | None = None) -> tuple[list[Match], dict[str, MatchContext]]:
    target_date = target_date or date.today()
    base = datetime.combine(target_date, time(10, 0))
    captured = datetime.now().isoformat(timespec="seconds")
    data = [
        ("d1", "Premier League (DEMO)", "Rojos FC", "Azules United", 3,
         [("1x2", "Rojos FC", "-250", None), ("1x2", "Empate", "+380", None),
          ("1x2", "Azules United", "+700", None),
          ("Doble oportunidad", "Rojos FC o empate", "-450", None),
          ("Total de goles", "Más de 1.5", "-280", 1.5),
          ("Rojos FC total de goles", "Más de 1.5", "-125", 1.5),
          ("Rojos FC Remates a Puerta totales", "Más de 3.5", "-220", 3.5),
          ("Remates a Puerta", "Más de 0.5 — Mateo Demo", "-250", 0.5)],
         _form(2.05, .72, 2.35, .90, .60, 6.4, 3.8, "G G E G G G P G G E"),
         _form(.88, 1.62, .85, .70, .40, 4.2, 5.7, "P E P G P E P P G P")),
        ("d2", "LaLiga (DEMO)", "Atlético Central", "Deportivo Norte", 5,
         [("1x2", "Atlético Central", "-165", None), ("1x2", "Empate", "+260", None),
          ("1x2", "Deportivo Norte", "+475", None), ("Total de goles", "Menos de 3.5", "-240", 3.5)],
         _form(1.48, .76, 2.10, .70, .30, 5.6, 4.0, "G E G G P G G E G G"),
         _form(.92, 1.24, 1.05, .60, .30, 4.5, 5.1, "E P G P E P G P E P")),
        ("d3", "Serie A (DEMO)", "Torino Azul", "Milano Blanco", 7,
         [("1x2", "Torino Azul", "+155", None), ("1x2", "Empate", "+210", None),
          ("1x2", "Milano Blanco", "+190", None), ("Total de goles", "Más de 1.5", "-190", 1.5)],
         _form(1.28, 1.10, 1.55, .80, .40, 5.1, 4.8, "G E P G G E E P G E"),
         _form(1.35, 1.18, 1.60, .80, .50, 5.4, 4.6, "E G G P E G P G E P")),
        ("d4", "Bundesliga (DEMO)", "Berlín 04", "Renania FC", 9,
         [("1x2", "Berlín 04", "-210", None), ("1x2", "Empate", "+340", None),
          ("1x2", "Renania FC", "+600", None),
          ("Total Tiros De Esquina", "Más de 7.5", "-200", 7.5)],
         _form(1.82, .95, 2.05, .80, .50, 6.8, 4.1, "G G P G E G G E G P"),
         _form(1.02, 1.65, .95, .70, .50, 4.7, 6.0, "P P E G P E P G P E")),
        ("d5", "Ligue 1 (DEMO)", "París Azul", "Costa FC", 11,
         [("1x2", "París Azul", "-300", None), ("1x2", "Empate", "+450", None),
          ("1x2", "Costa FC", "+850", None), ("Total de goles", "Más de 1.5", "-260", 1.5)],
         _form(2.22, .82, 2.45, .90, .70, 6.0, 3.9, "G G G E G G G P G G"),
         _form(.95, 1.55, .90, .70, .40, 4.3, 5.8, "P E P G P P E G P P")),
    ]
    matches: list[Match] = []
    contexts: dict[str, MatchContext] = {}
    for match_id, competition, home, away, hours, quotes, hf, af in data:
        kickoff = base + timedelta(hours=hours)
        qlist = [Quote(market, selection, american,
                       1 + (float(american) / 100 if float(american) > 0 else 100 / abs(float(american))),
                       line, captured) for market, selection, american, line in quotes]
        matches.append(Match(
            match_id=f"{target_date.isoformat()}-{match_id}", date_text=kickoff.strftime("%d/%m • %H:%M"),
            kickoff_iso=kickoff.isoformat(timespec="minutes"), competition=competition,
            country="DEMO", home=home, away=away, source_url="demo://local", quotes=qlist,
        ))
        context = MatchContext(
            hf, af, "Datos de demostración", ["Estos equipos y estadísticas son ficticios."]
        )
        if match_id == "d1":
            context.lineup_confirmed = True
            context.confirmed_starters = {"mateo demo"}
            context.player_shots_on_target = {
                "mateo demo": PlayerForm(games=8, shots_on_target=1.18)
            }
        contexts[f"{target_date.isoformat()}-{match_id}"] = context
    return matches, contexts


class DemoProvider:
    def __init__(self, contexts: dict[str, MatchContext]):
        self.contexts = contexts

    def context_for(self, match: Match) -> MatchContext:
        return self.contexts[match.match_id]

