from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from ..domain import Match, MatchContext, PlayerForm, TeamForm
from .football_data import StatsUnavailable, normalize, similarity


API = "https://site.api.espn.com/apis/site/v2/sports/soccer"

LEAGUES = {
    "premier league": "eng.1",
    "la liga": "esp.1",
    "laliga": "esp.1",
    "serie a": "ita.1",
    "bundesliga": "ger.1",
    "ligue 1": "fra.1",
    "champions league": "uefa.champions",
    "uefa champions league": "uefa.champions",
    "europa league": "uefa.europa",
    "uefa europa league": "uefa.europa",
    "carabao cup": "eng.league_cup",
    "efl cup": "eng.league_cup",
    "coppa italia": "ita.coppa_italia",
    "uefa nations league": "uefa.nations",
    "nations league": "uefa.nations",
    "world cup qualifying uefa": "fifa.worldq.uefa",
    "world cup qualification uefa": "fifa.worldq.uefa",
    "world cup qualifying conmebol": "fifa.worldq.conmebol",
    "world cup qualification conmebol": "fifa.worldq.conmebol",
    "european championship qualifying": "uefa.euroq",
    "euro qualification": "uefa.euroq",
}


def league_slug(name: str) -> str | None:
    key = normalize(name)
    for alias, slug in LEAGUES.items():
        if normalize(alias) in key or key in normalize(alias):
            return slug
    return None


def _number(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _stat(items: list[dict], name: str) -> float | None:
    for item in items or []:
        if item.get("name") == name:
            return _number(item.get("value", item.get("displayValue")))
    return None


def _player_from_quote(market: str, selection: str) -> str:
    if "—" in selection:
        return selection.rsplit("—", 1)[-1].strip()
    if " - " in market:
        return market.rsplit(" - ", 1)[-1].strip()
    return ""


class EspnProvider:
    """Resultados y estadísticas públicas; nunca aporta ni reemplaza cuotas."""

    def __init__(self, recent_games: int = 8):
        self.recent_games = max(5, min(int(recent_games), 10))
        self._cache: dict[str, dict] = {}

    def _get(self, slug: str, endpoint: str, params: dict | None = None) -> dict:
        query = "?" + urllib.parse.urlencode(params or {}) if params else ""
        url = f"{API}/{slug}/{endpoint}{query}"
        if url in self._cache:
            return self._cache[url]
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 RolmerBet/0.6"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise StatsUnavailable(f"La fuente estadística respondió HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise StatsUnavailable(f"No se pudo leer la fuente estadística pública: {exc}") from exc
        self._cache[url] = data
        return data

    @staticmethod
    def _date_for(match: Match) -> datetime:
        try:
            return datetime.fromisoformat(match.kickoff_iso)
        except ValueError:
            return datetime.now()

    def _resolve(self, match: Match) -> tuple[str, dict, dict]:
        slug = league_slug(match.competition)
        if not slug:
            raise StatsUnavailable(f"{match.competition} no está disponible en la fuente estadística")
        day = self._date_for(match).strftime("%Y%m%d")
        scoreboard = self._get(slug, "scoreboard", {"dates": day, "limit": 200})
        best: tuple[float, dict] | None = None
        for event in scoreboard.get("events", []):
            competitors = event.get("competitions", [{}])[0].get("competitors", [])
            home = next((x for x in competitors if x.get("homeAway") == "home"), None)
            away = next((x for x in competitors if x.get("homeAway") == "away"), None)
            if not home or not away:
                continue
            score = (
                similarity(match.home, home.get("team", {}).get("displayName", ""))
                + similarity(match.away, away.get("team", {}).get("displayName", ""))
            ) / 2.0
            if best is None or score > best[0]:
                best = (score, event)
        if not best or best[0] < 0.54:
            raise StatsUnavailable("No se pudieron relacionar los equipos con la fuente estadística")
        event = best[1]
        summary = self._get(slug, "summary", {"event": event.get("id")})
        return slug, event, summary

    @staticmethod
    def _recent_rows(summary: dict, team_id: str) -> list[dict]:
        groups = summary.get("lastFiveGames", [])
        group = next((x for x in groups if str(x.get("team", {}).get("id")) == str(team_id)), None)
        return list((group or {}).get("events", []))

    @staticmethod
    def _base_form(team_id: str, rows: list[dict]) -> TeamForm:
        games: list[tuple[int, int, bool]] = []
        for row in rows:
            home_id, away_id = str(row.get("homeTeamId")), str(row.get("awayTeamId"))
            home_score, away_score = row.get("homeTeamScore"), row.get("awayTeamScore")
            if home_score is None or away_score is None or team_id not in {home_id, away_id}:
                continue
            is_home = team_id == home_id
            gf = int(_number(home_score if is_home else away_score))
            ga = int(_number(away_score if is_home else home_score))
            games.append((gf, ga, is_home))
        if not games:
            raise StatsUnavailable("No hay resultados recientes suficientes para ambos equipos")

        def avg(values: list[int], fallback: float) -> float:
            return sum(values) / len(values) if values else fallback

        gf_all = [g[0] for g in games]
        ga_all = [g[1] for g in games]
        home = [g for g in games if g[2]]
        away = [g for g in games if not g[2]]
        points = [3 if gf > ga else (1 if gf == ga else 0) for gf, ga, _ in games]
        return TeamForm(
            games=len(games), gf=avg(gf_all, 1.25), ga=avg(ga_all, 1.25),
            ppg=sum(points) / len(points),
            home_gf=avg([g[0] for g in home], avg(gf_all, 1.25)),
            home_ga=avg([g[1] for g in home], avg(ga_all, 1.25)),
            away_gf=avg([g[0] for g in away], avg(gf_all, 1.25)),
            away_ga=avg([g[1] for g in away], avg(ga_all, 1.25)),
            over15=sum(gf + ga >= 2 for gf, ga, _ in games) / len(games),
            over25=sum(gf + ga >= 3 for gf, ga, _ in games) / len(games),
            btts=sum(gf > 0 and ga > 0 for gf, ga, _ in games) / len(games),
            sequence=" ".join("G" if gf > ga else ("E" if gf == ga else "P")
                              for gf, ga, _ in games),
        )

    def _event_summary(self, current_slug: str, row: dict) -> dict | None:
        event_id = row.get("id")
        if not event_id:
            return None
        other_slug = league_slug(
            str(row.get("leagueName") or row.get("leagueAbbreviation") or "")
        ) or current_slug
        try:
            return self._get(other_slug, "summary", {"event": event_id})
        except StatsUnavailable:
            return None

    @staticmethod
    def _box_team(summary: dict, team_id: str) -> dict | None:
        return next((x for x in summary.get("boxscore", {}).get("teams", [])
                     if str(x.get("team", {}).get("id")) == str(team_id)), None)

    @staticmethod
    def _roster_team(summary: dict, team_id: str) -> dict | None:
        return next((x for x in summary.get("rosters", [])
                     if str(x.get("team", {}).get("id")) == str(team_id)), None)

    def _special_stats(self, form: TeamForm, team_id: str, rows: list[dict],
                       current_slug: str, wanted_players: set[str],
                       player_totals: dict[str, list[float]]) -> None:
        corners_for: list[float] = []
        corners_against: list[float] = []
        shots_for: list[float] = []
        shots_against: list[float] = []
        for row in rows[:self.recent_games]:
            summary = self._event_summary(current_slug, row)
            if not summary:
                continue
            own = self._box_team(summary, team_id)
            if own:
                opponents = [x for x in summary.get("boxscore", {}).get("teams", []) if x is not own]
                opponent = opponents[0] if opponents else None
                own_corner = _stat(own.get("statistics", []), "wonCorners")
                opp_corner = _stat((opponent or {}).get("statistics", []), "wonCorners")
                own_shots = _stat(own.get("statistics", []), "shotsOnTarget")
                opp_shots = _stat((opponent or {}).get("statistics", []), "shotsOnTarget")
                if own_corner is not None and opp_corner is not None:
                    corners_for.append(own_corner)
                    corners_against.append(opp_corner)
                if own_shots is not None and opp_shots is not None:
                    shots_for.append(own_shots)
                    shots_against.append(opp_shots)
            roster = self._roster_team(summary, team_id)
            for member in (roster or {}).get("roster", []):
                appearances = _stat(member.get("stats", []), "appearances") or 0
                if appearances <= 0:
                    continue
                name = member.get("athlete", {}).get("displayName", "")
                matched = next((p for p in wanted_players if similarity(p, name) >= 0.78), None)
                if matched:
                    sot = _stat(member.get("stats", []), "shotsOnTarget") or 0.0
                    player_totals.setdefault(normalize(matched), []).append(sot)
        if corners_for:
            form.corner_games = len(corners_for)
            form.corners_for = sum(corners_for) / len(corners_for)
            form.corners_against = sum(corners_against) / len(corners_against)
        if shots_for:
            form.shot_games = len(shots_for)
            form.shots_on_target_for = sum(shots_for) / len(shots_for)
            form.shots_on_target_against = sum(shots_against) / len(shots_against)

    @staticmethod
    def _teams(event: dict) -> tuple[dict, dict]:
        competitors = event.get("competitions", [{}])[0].get("competitors", [])
        home = next(x for x in competitors if x.get("homeAway") == "home")
        away = next(x for x in competitors if x.get("homeAway") == "away")
        return home, away

    @staticmethod
    def _confirmed_starters(summary: dict) -> tuple[bool, set[str]]:
        groups = summary.get("rosters", [])
        if len(groups) < 2:
            return False, set()
        starters_by_team = [
            [member.get("athlete", {}).get("displayName", "") for member in group.get("roster", [])
             if member.get("starter")]
            for group in groups
        ]
        confirmed = len(starters_by_team) == 2 and all(len(names) >= 11 for names in starters_by_team)
        names = {normalize(name) for group in starters_by_team for name in group if name}
        return confirmed, names

    def context_for(self, match: Match) -> MatchContext:
        slug, event, summary = self._resolve(match)
        home_event, away_event = self._teams(event)
        home_id = str(home_event.get("team", {}).get("id"))
        away_id = str(away_event.get("team", {}).get("id"))
        home_rows = self._recent_rows(summary, home_id)[:self.recent_games]
        away_rows = self._recent_rows(summary, away_id)[:self.recent_games]
        home = self._base_form(home_id, home_rows)
        away = self._base_form(away_id, away_rows)

        wanted_players = {
            _player_from_quote(quote.market, quote.selection)
            for quote in match.quotes
            if "remates a puerta" in normalize(quote.market)
               and "total" not in normalize(quote.market)
        }
        wanted_players.discard("")
        totals: dict[str, list[float]] = {}
        self._special_stats(home, home_id, home_rows, slug, wanted_players, totals)
        self._special_stats(away, away_id, away_rows, slug, wanted_players, totals)
        player_forms = {
            key: PlayerForm(games=len(values), shots_on_target=sum(values) / len(values))
            for key, values in totals.items() if values
        }
        lineup_confirmed, starters = self._confirmed_starters(summary)
        notes: list[str] = []
        if min(home.games, away.games) < 5:
            notes.append("La muestra de resultados tiene menos de cinco partidos.")
        if min(home.corner_games, away.corner_games) < 5:
            notes.append("No hay cinco partidos con córners para ambos equipos.")
        if not lineup_confirmed:
            notes.append("Las alineaciones oficiales todavía no están confirmadas.")
        return MatchContext(
            home=home, away=away,
            source="ESPN (resultados, córners, remates y alineaciones)", notes=notes,
            lineup_confirmed=lineup_confirmed, confirmed_starters=starters,
            player_shots_on_target=player_forms,
            source_names=["ESPN"], source_count=1, source_agreement=.75,
            injuries_checked=False, rotation_risk="unknown",
        )
