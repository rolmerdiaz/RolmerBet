from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime

from ..domain import Match, MatchContext, PlayerForm, TeamForm
from .football_data import StatsUnavailable, normalize, similarity


API = "https://www.sofascore.com/api/v1"


def _number(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class SofascoreProvider:
    """Contexto deportivo visible públicamente; nunca lee ni reemplaza cuotas."""

    def __init__(self, recent_games: int = 8):
        self.recent_games = max(5, min(int(recent_games), 10))
        self._cache: dict[str, dict] = {}

    def _get(self, path: str) -> dict:
        url = API + path
        if url in self._cache:
            return self._cache[url]
        request = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 RolmerBet/0.6"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise StatsUnavailable(f"Sofascore respondió HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise StatsUnavailable(f"No se pudo leer Sofascore: {exc}") from exc
        self._cache[url] = data
        return data

    @staticmethod
    def _date_for(match: Match) -> datetime:
        try:
            return datetime.fromisoformat(match.kickoff_iso)
        except ValueError:
            return datetime.now()

    def _resolve(self, match: Match) -> dict:
        day = self._date_for(match).date().isoformat()
        payload = self._get(f"/sport/football/scheduled-events/{day}")
        best: tuple[float, dict] | None = None
        for event in payload.get("events", []):
            home = str(event.get("homeTeam", {}).get("name", ""))
            away = str(event.get("awayTeam", {}).get("name", ""))
            score = (similarity(match.home, home) + similarity(match.away, away)) / 2.0
            if best is None or score > best[0]:
                best = (score, event)
        if not best or best[0] < .56:
            raise StatsUnavailable("Sofascore no pudo relacionar los equipos")
        return best[1]

    def _recent(self, team_id: int) -> list[dict]:
        rows: list[dict] = []
        page = 0
        while len(rows) < self.recent_games and page < 3:
            payload = self._get(f"/team/{team_id}/events/last/{page}")
            for event in payload.get("events", []):
                status = normalize(str(event.get("status", {}).get("type", "")))
                if status in {"finished", "afterpenalties", "afterextra"}:
                    rows.append(event)
                    if len(rows) >= self.recent_games:
                        break
            if not payload.get("hasNextPage"):
                break
            page += 1
        return rows[:self.recent_games]

    @staticmethod
    def _score(event: dict, side: str) -> int | None:
        score = event.get(f"{side}Score", {})
        value = score.get("current", score.get("normaltime"))
        return int(value) if value is not None else None

    @staticmethod
    def _base_form(team_id: int, rows: list[dict]) -> TeamForm:
        games: list[tuple[int, int, bool]] = []
        for event in rows:
            home_id = int(event.get("homeTeam", {}).get("id") or -1)
            away_id = int(event.get("awayTeam", {}).get("id") or -1)
            home_score = SofascoreProvider._score(event, "home")
            away_score = SofascoreProvider._score(event, "away")
            if home_score is None or away_score is None or team_id not in {home_id, away_id}:
                continue
            is_home = team_id == home_id
            games.append((home_score if is_home else away_score,
                          away_score if is_home else home_score, is_home))
        if not games:
            raise StatsUnavailable("Sofascore no tiene resultados recientes suficientes")

        def avg(values: list[int], fallback: float) -> float:
            return sum(values) / len(values) if values else fallback

        gf_all = [row[0] for row in games]
        ga_all = [row[1] for row in games]
        home = [row for row in games if row[2]]
        away = [row for row in games if not row[2]]
        points = [3 if gf > ga else (1 if gf == ga else 0) for gf, ga, _ in games]
        return TeamForm(
            games=len(games), gf=avg(gf_all, 1.25), ga=avg(ga_all, 1.25),
            ppg=sum(points) / len(points),
            home_gf=avg([row[0] for row in home], avg(gf_all, 1.25)),
            home_ga=avg([row[1] for row in home], avg(ga_all, 1.25)),
            away_gf=avg([row[0] for row in away], avg(gf_all, 1.25)),
            away_ga=avg([row[1] for row in away], avg(ga_all, 1.25)),
            over15=sum(gf + ga >= 2 for gf, ga, _ in games) / len(games),
            over25=sum(gf + ga >= 3 for gf, ga, _ in games) / len(games),
            btts=sum(gf > 0 and ga > 0 for gf, ga, _ in games) / len(games),
            sequence=" ".join("G" if gf > ga else ("E" if gf == ga else "P")
                              for gf, ga, _ in games),
        )

    @staticmethod
    def _all_stats(payload: dict) -> list[dict]:
        periods = payload.get("statistics", [])
        period = next((item for item in periods if item.get("period") == "ALL"),
                      periods[0] if periods else {})
        return [stat for group in period.get("groups", []) for stat in group.get("statisticsItems", [])]

    @staticmethod
    def _stat(stats: list[dict], names: set[str], side: str) -> float | None:
        for item in stats:
            if normalize(str(item.get("name", ""))) in names:
                value = item.get(side)
                return _number(value) if value is not None else None
        return None

    def _special_stats(self, form: TeamForm, team_id: int, rows: list[dict],
                       wanted_players: set[str], player_values: dict[str, list[float]]) -> None:
        corners_for: list[float] = []
        corners_against: list[float] = []
        shots_for: list[float] = []
        shots_against: list[float] = []
        for event in rows[:self.recent_games]:
            event_id = event.get("id")
            if not event_id:
                continue
            is_home = int(event.get("homeTeam", {}).get("id") or -1) == team_id
            own, opponent = ("home", "away") if is_home else ("away", "home")
            try:
                stats = self._all_stats(self._get(f"/event/{event_id}/statistics"))
                own_corner = self._stat(stats, {"corner kicks", "corners"}, own)
                opp_corner = self._stat(stats, {"corner kicks", "corners"}, opponent)
                own_shots = self._stat(stats, {"shots on target"}, own)
                opp_shots = self._stat(stats, {"shots on target"}, opponent)
                if own_corner is not None and opp_corner is not None:
                    corners_for.append(own_corner)
                    corners_against.append(opp_corner)
                if own_shots is not None and opp_shots is not None:
                    shots_for.append(own_shots)
                    shots_against.append(opp_shots)
            except StatsUnavailable:
                pass
            if wanted_players:
                try:
                    lineup = self._get(f"/event/{event_id}/lineups")
                    for side in ("home", "away"):
                        for row in lineup.get(side, {}).get("players", []):
                            name = normalize(str(row.get("player", {}).get("name", "")))
                            key = next((wanted for wanted in wanted_players
                                        if similarity(name, wanted) >= .82), None)
                            if key:
                                stats = row.get("statistics", {})
                                value = stats.get("onTargetScoringAttempt", stats.get("shotsOnTarget"))
                                if value is not None:
                                    player_values.setdefault(key, []).append(_number(value))
                except StatsUnavailable:
                    pass
        if corners_for:
            form.corner_games = len(corners_for)
            form.corners_for = sum(corners_for) / len(corners_for)
            form.corners_against = sum(corners_against) / len(corners_against)
        if shots_for:
            form.shot_games = len(shots_for)
            form.shots_on_target_for = sum(shots_for) / len(shots_for)
            form.shots_on_target_against = sum(shots_against) / len(shots_against)

    def _lineup(self, event_id: int) -> tuple[bool, set[str]]:
        try:
            payload = self._get(f"/event/{event_id}/lineups")
        except StatsUnavailable:
            return False, set()
        groups = [payload.get("home", {}).get("players", []),
                  payload.get("away", {}).get("players", [])]
        starters = [[str(row.get("player", {}).get("name", "")) for row in group
                     if row.get("starter") is True] for group in groups]
        confirmed = all(len(group) >= 11 for group in starters)
        return confirmed, {normalize(name) for group in starters for name in group if name}

    def context_for(self, match: Match) -> MatchContext:
        event = self._resolve(match)
        home_id = int(event.get("homeTeam", {}).get("id") or -1)
        away_id = int(event.get("awayTeam", {}).get("id") or -1)
        home_rows, away_rows = self._recent(home_id), self._recent(away_id)
        home, away = self._base_form(home_id, home_rows), self._base_form(away_id, away_rows)
        wanted = {_player_name for quote in match.quotes
                  if (_player_name := normalize(quote.selection.rsplit("—", 1)[-1].strip()
                                                if "—" in quote.selection else ""))}
        values: dict[str, list[float]] = {}
        self._special_stats(home, home_id, home_rows, wanted, values)
        self._special_stats(away, away_id, away_rows, wanted, values)
        player_forms = {name: PlayerForm(len(rows), sum(rows) / len(rows))
                        for name, rows in values.items() if rows}
        confirmed, starters = self._lineup(int(event.get("id") or -1))
        injuries_checked = False
        try:
            self._get(f"/event/{event.get('id')}/missing-players")
            injuries_checked = True
        except StatsUnavailable:
            pass
        notes = []
        if min(home.games, away.games) < 8:
            notes.append("Sofascore aportó menos de ocho resultados para un equipo.")
        if min(home.corner_games, away.corner_games) < 8:
            notes.append("La cobertura de córners de Sofascore es inferior a ocho partidos.")
        if not confirmed:
            notes.append("Sofascore aún no muestra dos onces titulares completos.")
        return MatchContext(
            home=home, away=away, source="Sofascore", notes=notes,
            lineup_confirmed=confirmed, confirmed_starters=starters,
            player_shots_on_target=player_forms, source_names=["Sofascore"],
            source_count=1, source_agreement=.75, injuries_checked=injuries_checked,
            rotation_risk="unknown",
        )

