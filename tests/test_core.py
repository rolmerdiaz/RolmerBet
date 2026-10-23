from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from rolmerbet.config import DEFAULTS
from rolmerbet.demo import DemoProvider, demo_matches
from rolmerbet.domain import Combo
from rolmerbet.engine import analyze_matches, build_combo
from rolmerbet.odds import american_to_decimal, multiply_odds, visible_to_decimal
from rolmerbet.scrapers.triunfobet import TriunfoBetCollector, parse_cards
from rolmerbet.storage import Database
from rolmerbet.providers.football_data import competition_code
from rolmerbet.providers.espn import league_slug
from rolmerbet.updater import UpdateError, is_newer, parse_manifest


class OddsTests(unittest.TestCase):
    def test_american_conversion(self) -> None:
        self.assertAlmostEqual(american_to_decimal("-200"), 1.5)
        self.assertAlmostEqual(american_to_decimal("+250"), 3.5)
        self.assertAlmostEqual(visible_to_decimal("-200"), 1.5)
        self.assertAlmostEqual(visible_to_decimal("1.66"), 1.66)
        self.assertAlmostEqual(visible_to_decimal("2,25"), 2.25)
        self.assertAlmostEqual(multiply_odds([1.5, 2.0]), 3.0)


class ScraperParserTests(unittest.TestCase):
    def test_parses_public_card_shape(self) -> None:
        payload = [{
            "date": "24/10 • 16:00",
            "comp": "Premier League • Inglaterra",
            "teams": ["Arsenal", "Everton"],
            "live": False,
            "markets": [
                {"index": 0, "lineText": "", "buttons": [
                    {"value": "-220", "label": "Arsenal"},
                    {"value": "+320", "label": "Empate"},
                    {"value": "+700", "label": "Everton"},
                ]},
                {"index": 1, "lineText": "2.5", "buttons": [
                    {"value": "-115", "label": "Más de"},
                    {"value": "-105", "label": "Menos de"},
                ]},
            ],
        }]
        matches = parse_cards(payload, "https://triunfobet.com/altenar#/overview",
                              "2026-10-22T08:00:00")
        self.assertEqual(len(matches), 1)
        match = matches[0]
        self.assertEqual(match.competition, "Premier League")
        self.assertEqual(match.country, "Inglaterra")
        self.assertEqual(len(match.quotes), 5)
        self.assertEqual(match.quotes[3].market, "Total de goles")
        self.assertEqual(match.quotes[3].line, 2.5)
        self.assertAlmostEqual(match.quotes[0].decimal, 1.45454545)

    def test_skips_live_cards(self) -> None:
        payload = [{"date": "22/10 • 12:00", "comp": "Serie A • Italia",
                    "teams": ["A", "B"], "live": True,
                    "markets": [{"index": 0, "buttons": [{"value": "+100", "label": "A"}]}]}]
        self.assertEqual(parse_cards(payload, "https://example.invalid"), [])

    def test_parses_decimal_odds_without_reconverting(self) -> None:
        payload = [{
            "date": "23/10 • 21:00", "comp": "Premier League • Inglaterra",
            "teams": ["Ipswich", "Nottingham Forest"], "live": False,
            "markets": [{"index": 0, "lineText": "", "buttons": [
                {"value": "1.66", "label": "Nottingham Forest"},
            ]}],
        }]
        matches = parse_cards(payload, "https://triunfobet.com/altenar#/coupon/66/2")
        self.assertEqual(matches[0].quotes[0].american, "1.66")
        self.assertAlmostEqual(matches[0].quotes[0].decimal, 1.66)

    def test_reads_total_line_embedded_in_visible_label(self) -> None:
        payload = [{
            "date": "23/10 • 21:00", "comp": "Premier League • Inglaterra",
            "teams": ["Ipswich", "Nottingham Forest"], "live": False,
            "markets": [{"index": 1, "lineText": "", "buttons": [
                {"value": "-129", "label": "Más de 2.5"},
                {"value": "+105", "label": "Menos de 2.5"},
            ]}],
        }]
        quotes = parse_cards(payload, "https://triunfobet.com")[0].quotes
        self.assertEqual([q.line for q in quotes], [2.5, 2.5])

    def test_parses_supported_detail_markets_without_inventing_prices(self) -> None:
        payload = [{
            "date": "24/10 • 16:00", "comp": "Premier League • Inglaterra",
            "teams": ["Arsenal", "Everton"], "live": False,
            "markets": [{"index": 0, "buttons": [{"value": "-220", "label": "Arsenal"}]}],
            "detailMarkets": [
                {"name": "Doble oportunidad", "buttons": [
                    {"value": "-1100", "label": "Arsenal o empate"}]},
                {"name": "Total de goles", "lineText": "1.5", "buttons": [
                    {"value": "-300", "label": "Más de 1.5"}]},
                {"name": "Total Tiros De Esquina", "lineText": "8.5", "buttons": [
                    {"value": "-125", "label": "Más de 8.5"}]},
                {"name": "Remates a Puerta", "buttons": [
                    {"value": "-200", "label": "Más de 0.5 — Bukayo Saka"}]},
                {"name": "Arsenal Remates a Puerta totales", "lineText": "4.5", "buttons": [
                    {"value": "-115", "label": "Más de 4.5"}]},
            ],
        }]
        quotes = parse_cards(payload, "https://triunfobet.com")[0].quotes
        markets = {quote.market for quote in quotes}
        self.assertIn("Doble oportunidad", markets)
        self.assertIn("Total Tiros De Esquina", markets)
        self.assertIn("Remates a Puerta", markets)
        self.assertIn("Arsenal Remates a Puerta totales", markets)
        player = next(q for q in quotes if "Bukayo" in q.selection)
        self.assertEqual(player.line, 0.5)
        self.assertAlmostEqual(player.decimal, 1.5)

    def test_only_opens_the_configured_country_league(self) -> None:
        self.assertTrue(TriunfoBetCollector._wanted_header(
            "Bundesliga • Alemania\nPA\nBB", ["Bundesliga"]))
        self.assertTrue(TriunfoBetCollector._wanted_header(
            "🇩🇪 Bundesliga • Alemania\nPA\nBB", ["Bundesliga"]))
        self.assertFalse(TriunfoBetCollector._wanted_header(
            "Bundesliga • Austria\nBB", ["Bundesliga"]))

    def test_competition_aliases(self) -> None:
        self.assertEqual(competition_code("La Liga • España"), "PD")
        self.assertEqual(competition_code("UEFA Champions League"), "CL")
        self.assertIsNone(competition_code("Copa desconocida"))
        self.assertEqual(league_slug("Premier League"), "eng.1")
        self.assertEqual(league_slug("Coppa Italia"), "ita.coppa_italia")


class EngineTests(unittest.TestCase):
    def test_demo_produces_conservative_combo_in_target(self) -> None:
        matches, contexts = demo_matches()
        evaluations = analyze_matches(matches, DemoProvider(contexts), DEFAULTS)
        combo = build_combo(evaluations, DEFAULTS)
        self.assertEqual(combo.status, "LISTA")
        self.assertGreaterEqual(combo.total_odds, 3.0)
        self.assertLessEqual(combo.total_odds, 4.0)
        self.assertGreaterEqual(combo.estimated_probability, DEFAULTS["min_total_probability"])
        self.assertEqual(len(combo.selections), len({item.match_id for item in combo.selections}))
        self.assertTrue(all(item.accepted for item in combo.selections))

    def test_does_not_force_a_combo(self) -> None:
        cfg = dict(DEFAULTS, target_odds_min=8.0, target_odds_max=9.0)
        matches, contexts = demo_matches()
        combo = build_combo(analyze_matches(matches, DemoProvider(contexts), cfg), cfg)
        self.assertEqual(combo.status, "NO_APOSTAR")
        self.assertEqual(combo.selections, [])

    def test_demo_uses_selected_date(self) -> None:
        selected = date(2026, 10, 23)
        matches, _contexts = demo_matches(selected)
        self.assertTrue(matches)
        self.assertTrue(all(datetime.fromisoformat(m.kickoff_iso).date() == selected for m in matches))

    def test_engine_evaluates_the_new_market_families(self) -> None:
        matches, contexts = demo_matches()
        evaluations = analyze_matches(matches, DemoProvider(contexts), DEFAULTS)
        by_market = {}
        for item in evaluations:
            by_market.setdefault(item.market, []).append(item)
        self.assertGreater(by_market["Doble oportunidad"][0].model_probability, 0)
        self.assertGreater(by_market["Rojos FC total de goles"][0].model_probability, 0)
        self.assertGreater(by_market["Total Tiros De Esquina"][0].model_probability, 0)
        self.assertGreater(by_market["Rojos FC Remates a Puerta totales"][0].model_probability, 0)
        self.assertGreater(by_market["Remates a Puerta"][0].model_probability, 0)


class StorageTests(unittest.TestCase):
    def test_round_trip_and_result(self) -> None:
        matches, contexts = demo_matches()
        evaluations = analyze_matches(matches, DemoProvider(contexts), DEFAULTS)
        combo = build_combo(evaluations, DEFAULTS)
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "test.db")
            db.save_run("DEMO", matches, evaluations, combo)
            restored = Combo.from_dict(db.latest_combo())
            self.assertAlmostEqual(restored.total_odds, combo.total_odds)
            self.assertEqual(len(restored.selections), len(combo.selections))
            row = db.history()[0]
            db.mark_result(row["id"], "Ganada", 10.0)
            self.assertAlmostEqual(db.history()[0]["profit"], 10.0 * (combo.total_odds - 1.0))


class UpdaterTests(unittest.TestCase):
    def test_version_comparison(self) -> None:
        self.assertTrue(is_newer("0.4.0", "0.3.1"))
        self.assertFalse(is_newer("0.3.1", "0.3.1"))
        self.assertFalse(is_newer("0.3.0", "0.3.1"))

    def test_manifest_rejects_protected_paths(self) -> None:
        payload = {
            "repository": "rolmerdiaz/RolmerBet", "version": "0.4.0",
            "files": {"data/config.json": "a" * 64},
        }
        with self.assertRaises(UpdateError):
            parse_manifest(payload)

    def test_manifest_accepts_program_files(self) -> None:
        payload = {
            "repository": "rolmerdiaz/RolmerBet", "version": "0.4.0",
            "files": {"rolmerbet/ui.py": "b" * 64},
        }
        info = parse_manifest(payload)
        self.assertEqual(info.files["rolmerbet/ui.py"], "b" * 64)


if __name__ == "__main__":
    unittest.main()
