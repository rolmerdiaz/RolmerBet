from __future__ import annotations

import difflib
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..domain import Match, MatchContext, TeamForm


API = "https://api.football-data.org/v4"
COMPETITION_CODES = {
    "Premier League": "PL",
    "LaLiga": "PD",
    "Primera Division": "PD",
    "Serie A": "SA",
    "Bundesliga": "BL1",
    "Ligue 1": "FL1",
    "Champions League": "CL",
    "UEFA Champions League": "CL",
    "Europa League": "EL",
    "UEFA Europa League": "EL",
}


class StatsUnavailable(RuntimeError):
    pass


def competition_code(name: str) -> str | None:
    """Relaciona variantes visibles de la casa sin confundir competiciones."""
    if name in COMPETITION_CODES:
        return COMPETITION_CODES[name]
    key = normalize(name)
    aliases = {
        "premier league": "PL", "england premier league": "PL",
        "laliga": "PD", "la liga": "PD", "primera division": "PD",
        "serie a": "SA", "italy serie a": "SA",
        "bundesliga": "BL1", "germany bundesliga": "BL1",
        "ligue 1": "FL1", "france ligue 1": "FL1",
        "champions league": "CL", "uefa champions league": "CL",
        "europa league": "EL", "uefa europa league": "EL",
    }
    for alias, code in aliases.items():
        if alias in key:
            return code
    return None


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\b(fc|cf|ac|ssc|calcio|club|deportivo|ud|rc|sc)\b", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()


@dataclass(slots=True)
class ApiFixture:
    fixture_id: int
    home_id: int
    away_id: int
    home: str
    away: str


class FootballDataProvider:
    """Forma reciente. Nunca aporta cuotas y nunca sustituye a Triunfobet."""

    def __init__(self, token: str, recent_games: int = 10):
        self.token = token.strip()
        self.recent_games = max(5, min(int(recent_games), 20))
        self._cache: dict[str, dict] = {}

    def _get(self, path: str, params: dict | None = None) -> dict:
        if not self.token:
            raise StatsUnavailable("Falta el token de Football-Data.org")
        query = "?" + urllib.parse.urlencode(params or {}) if params else ""
        url = API + path + query
        if url in self._cache:
            return self._cache[url]
        req = urllib.request.Request(url, headers={"X-Auth-Token": self.token, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise StatsUnavailable(f"Football-Data respondió HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise StatsUnavailable(f"No se pudo leer Football-Data: {exc}") from exc
        self._cache[url] = data
        return data

    @staticmethod
    def _date_for(match: Match) -> datetime:
        try:
            return datetime.fromisoformat(match.kickoff_iso)
        except ValueError:
            return datetime.now()

    def _resolve_fixture(self, match: Match) -> ApiFixture:
        code = competition_code(match.competition)
        if not code:
            raise StatsUnavailable(f"{match.competition} no está disponible en esta fuente")
        day = self._date_for(match).date()
        payload = self._get(
            f"/competitions/{code}/matches",
            {"dateFrom": (day - timedelta(days=1)).isoformat(), "dateTo": (day + timedelta(days=1)).isoformat()},
        )
        best: tuple[float, dict] | None = None
        for item in payload.get("matches", []):
            home = item.get("homeTeam", {}).get("name", "")
            away = item.get("awayTeam", {}).get("name", "")
            score = (similarity(match.home, home) + similarity(match.away, away)) / 2.0
            if best is None or score > best[0]:
                best = (score, item)
        if not best or best[0] < 0.54:
            raise StatsUnavailable("No se pudieron relacionar los nombres del partido con Football-Data")
        item = best[1]
        return ApiFixture(
            fixture_id=int(item["id"]),
            home_id=int(item["homeTeam"]["id"]), away_id=int(item["awayTeam"]["id"]),
            home=item["homeTeam"]["name"], away=item["awayTeam"]["name"],
        )

    def _recent(self, team_id: int) -> list[dict]:
        payload = self._get(f"/teams/{team_id}/matches", {"status": "FINISHED"})
        matches = payload.get("matches", [])
        matches.sort(key=lambda m: m.get("utcDate", ""), reverse=True)
        return matches[: self.recent_games]

    @staticmethod
    def _form(team_id: int, rows: list[dict]) -> TeamForm:
        games: list[tuple[int, int, bool]] = []
        for row in rows:
            score = row.get("score", {}).get("fullTime", {}) or {}
            if score.get("home") is None or score.get("away") is None:
                continue
            is_home = int(row.get("homeTeam", {}).get("id") or -1) == team_id
            gf = int(score["home"] if is_home else score["away"])
            ga = int(score["away"] if is_home else score["home"])
            games.append((gf, ga, is_home))
        if not games:
            raise StatsUnavailable("No hay resultados recientes suficientes")

        def avg(values: list[int], fallback: float) -> float:
            return sum(values) / len(values) if values else fallback

        gf_all = [g[0] for g in games]
        ga_all = [g[1] for g in games]
        home = [g for g in games if g[2]]
        away = [g for g in games if not g[2]]
        points = [3 if gf > ga else (1 if gf == ga else 0) for gf, ga, _ in games]
        sequence = " ".join("G" if gf > ga else ("E" if gf == ga else "P") for gf, ga, _ in games)
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
            sequence=sequence,
        )

    def context_for(self, match: Match) -> MatchContext:
        fixture = self._resolve_fixture(match)
        home = self._form(fixture.home_id, self._recent(fixture.home_id))
        away = self._form(fixture.away_id, self._recent(fixture.away_id))
        notes = []
        if min(home.games, away.games) < 8:
            notes.append("La muestra disponible tiene menos de ocho partidos para uno de los equipos.")
        return MatchContext(home=home, away=away, source="Football-Data.org", notes=notes)

