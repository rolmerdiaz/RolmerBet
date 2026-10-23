from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from ..domain import Match, Quote
from ..odds import visible_to_decimal


class TriunfoBetError(RuntimeError):
    pass


CARD_SCRIPT = r"""
(root = document) => Array.from(root.querySelectorAll('div[class*="EventBoxContainerBase"]')).map((card) => {
  const txt = (sel) => card.querySelector(sel)?.innerText?.trim() || '';
  const date = txt('[class*="DateTime-"]');
  const comp = txt('[class*="CategoryChampionship-sc"]');
  const teams = Array.from(card.querySelectorAll('[class*="CompetitorName"]'))
    .map(x => x.innerText.trim()).filter(Boolean).slice(0, 2);
  const live = !!card.querySelector('img[alt="liveIcon"]') || /\b\d{1,3}'\b/.test(card.innerText);
  const markets = Array.from(card.querySelectorAll('div[class*="MarketBoxContainer"]')).map((box, index) => {
    const buttons = Array.from(box.querySelectorAll('button')).map((btn) => ({
      value: btn.querySelector('[class*="OddValue"]')?.innerText?.trim() || '',
      label: btn.querySelector('[class*="OddLabel"]')?.innerText?.trim() || ''
    })).filter(x => x.value && x.label);
    const lineText = box.querySelector('[class*="SpecialOddBoxValue"]')?.innerText?.trim() || '';
    return {index, lineText, buttons};
  }).filter(x => x.buttons.length);
  return {date, comp, teams, live, markets};
}).filter(x => x.date && x.comp && x.teams.length === 2 && x.markets.length)
"""


DETAIL_BOX_SCRIPT = r"""
(box) => {
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const name = clean(box.querySelector('div[class*="EventDetailsMarketName-sc"]')?.innerText
    || box.querySelector('[class*="EventDetailsMarketName"]')?.innerText);
  const lineText = clean(box.querySelector('[class*="EventDetailsSliderThumbLabel"]')?.innerText
    || box.querySelector('[class*="SpecialOddBoxValue"]')?.innerText
    || box.querySelector('input[type="range"]')?.getAttribute('aria-valuetext'));
  const buttons = Array.from(box.querySelectorAll('button')).map((button) => ({
    value: clean(button.querySelector('[class*="OddValue"]')?.innerText),
    label: clean(button.querySelector('[class*="OddLabel"]')?.innerText)
  })).filter(item => item.value && item.label);
  Array.from(box.querySelectorAll('div[class*="ChildMarketBoxContainer"]')).forEach((row) => {
    const player = clean(row.getAttribute('title')
      || row.querySelector('[class*="ChildMarketCompetitorName"]')?.innerText
      || row.querySelector('span')?.innerText);
    const line = clean(row.querySelector('[class*="ChildMarketLine"]')?.innerText)
      || (clean(row.innerText).match(/\b\d+(?:[.,]\d+)?\b/) || [])[0] || '';
    const value = clean(row.querySelector('button [class*="OddValue"]')?.innerText
      || row.querySelector('button')?.innerText);
    if (player && line && value && !buttons.some(x => x.value === value && x.label.includes(player))) {
      buttons.push({value, label: `Más de ${line.replace(',', '.')} — ${player}`});
    }
  });
  return {name, lineText, buttons};
}
"""


COMPETITION_LABELS = {
    "Premier League": (("Premier League", "Inglaterra"),),
    "LaLiga": (("LaLiga", "España"),),
    "Serie A": (("Serie A", "Italia"),),
    "Bundesliga": (("Bundesliga", "Alemania"),),
    "Ligue 1": (("Ligue 1", "Francia"),),
    "Champions League": (("Champions League", "Europa"), ("UEFA Champions League", "Europa")),
    "Europa League": (("Europa League", "Europa"), ("UEFA Europa League", "Europa")),
    "Carabao Cup": (("Carabao Cup", "Inglaterra"), ("EFL Cup", "Inglaterra")),
    "Coppa Italia": (("Coppa Italia", "Italia"),),
    "Nations League": (("UEFA Nations League", "Internacional"), ("Nations League", "Europa")),
    "World Cup Qualification": (("Clasificación Mundial", "Internacional"),
                                ("World Cup Qualification", "Internacional"),
                                ("Eliminatorias Mundial", "Internacional")),
    "European Championship Qualification": (("Clasificación Eurocopa", "Europa"),
                                              ("European Championship Qualification", "Europa"),
                                              ("Euro Qualification", "Europa")),
}


def _split_competition(text: str) -> tuple[str, str]:
    parts = [p.strip() for p in text.split("•")]
    return (parts[0], parts[1] if len(parts) > 1 else "")


def _kickoff_iso(date_text: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    match = re.search(r"(\d{1,2})/(\d{1,2})\s*•\s*(\d{1,2}):(\d{2})", date_text)
    if not match:
        return now.isoformat(timespec="minutes")
    day, month, hour, minute = map(int, match.groups())
    year = now.year
    candidate = datetime(year, month, day, hour, minute)
    if candidate < now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=180):
        candidate = candidate.replace(year=year + 1)
    return candidate.isoformat(timespec="minutes")


def _clean_market_name(value: str) -> str:
    return re.sub(r"\s+(?:BB|PA)(?:\s+(?:BB|PA))*\s*$", "", value.strip(), flags=re.I)


def _detail_market_supported(name: str, home: str, away: str) -> bool:
    clean = unicodedata.normalize("NFKD", _clean_market_name(name).casefold())
    clean = "".join(ch for ch in clean if not unicodedata.combining(ch))
    clean = re.sub(r"\s+", " ", clean).strip()
    if "1a mitad" in clean or "2a mitad" in clean:
        return False
    exact = {
        "doble oportunidad", "total de goles", "total tiros de esquina",
        "remates a puerta", "remates a puerta totales",
    }
    if clean in exact:
        return True
    team_names = [home, away]
    return any(
        re.sub(r"\s+", " ", unicodedata.normalize("NFKD", team.casefold())
               .encode("ascii", "ignore").decode()).strip() in clean
        and any(marker in clean for marker in (
            "total de goles", "total tiros de esquina", "remates a puerta totales"
        ))
        for team in team_names
    )


def parse_cards(payload: list[dict], source_url: str, captured_at: str | None = None) -> list[Match]:
    captured_at = captured_at or datetime.now().isoformat(timespec="seconds")
    matches: list[Match] = []
    seen: set[str] = set()
    for card in payload:
        teams = card.get("teams") or []
        if len(teams) != 2 or card.get("live"):
            continue
        competition, country = _split_competition(str(card.get("comp", "")))
        raw_key = f"{card.get('date')}|{competition}|{teams[0]}|{teams[1]}"
        match_id = hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:16]
        if match_id in seen:
            continue
        seen.add(match_id)
        quotes: list[Quote] = []
        market_rows = list(card.get("markets", [])) + list(card.get("detailMarkets", []))
        quote_keys: set[tuple[str, str, str, float | None]] = set()
        for market in market_rows:
            index = int(market.get("index", 99))
            market_name = _clean_market_name(str(market.get("name", "")))
            if not market_name:
                market_name = "1x2" if index == 0 else ("Total de goles" if index == 1 else f"Mercado {index + 1}")
            line_text = str(market.get("lineText", "")).replace(",", ".")
            try:
                line = float(line_text) if line_text else None
            except ValueError:
                line = None
            for item in market.get("buttons", []):
                original = str(item.get("value", "")).strip()
                selection = str(item.get("label", "")).strip()
                item_line = line
                if item_line is None and any(marker in market_name.casefold() for marker in (
                    "total", "remates a puerta", "tiros de esquina", "corner"
                )):
                    embedded_line = re.search(r"(\d+(?:[.,]\d+)?)", selection)
                    if embedded_line:
                        item_line = float(embedded_line.group(1).replace(",", "."))
                try:
                    decimal = visible_to_decimal(original)
                except ValueError:
                    continue
                key = (market_name.casefold(), selection.casefold(), original, item_line)
                if key not in quote_keys:
                    quote_keys.add(key)
                    quotes.append(Quote(market_name, selection, original, decimal, item_line, captured_at))
        if quotes:
            matches.append(Match(
                match_id=match_id, date_text=str(card.get("date", "")),
                kickoff_iso=_kickoff_iso(str(card.get("date", ""))),
                competition=competition, country=country,
                home=str(teams[0]), away=str(teams[1]), source_url=source_url,
                quotes=quotes, is_live=False,
            ))
    return matches


class TriunfoBetCollector:
    def __init__(self, url: str, diagnostics_dir: str | Path, headless: bool = True):
        self.url = url
        self.diagnostics_dir = Path(diagnostics_dir)
        self.headless = headless

    @staticmethod
    def _dismiss_overlays(page) -> None:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        for selector in (".welcome-close", "button.close", '[aria-label="Close"]'):
            try:
                locator = page.locator(selector).first
                if locator.count() and locator.is_visible():
                    locator.click(timeout=3000)
                    page.wait_for_timeout(250)
            except Exception:
                continue

    @staticmethod
    def _sports_frame(page, require_headers: bool = False):
        selector = ('div[class*="ChampionshipHeader"]' if require_headers
                    else 'div[class*="Sportsbook"], div[class*="MatchOdds"], button')
        for frame in page.frames:
            try:
                if frame.locator(selector).count():
                    if require_headers or frame.get_by_text("Fútbol", exact=True).count():
                        return frame
            except Exception:
                continue
        return None

    @staticmethod
    def _route_for(target_date: date) -> tuple[str, str]:
        today = date.today()
        if target_date == today:
            return "Partidos de hoy", "1"
        if target_date == today + timedelta(days=1):
            return "Partidos de mañana", "2"
        return "Próximos partidos", "3"

    @staticmethod
    def _wanted_header(text: str, enabled: list[str]) -> bool:
        clean = re.sub(r"\s+(?:PA|BB)(?:\s+(?:PA|BB))*\s*$", "", text.strip())
        competition, country = _split_competition(clean)

        def plain(value: str) -> str:
            value = unicodedata.normalize("NFKD", value.casefold())
            value = "".join(ch for ch in value if not unicodedata.combining(ch))
            return re.sub(r"[^a-z0-9]+", " ", value).strip()

        comp_norm = plain(competition)
        country_norm = plain(country)
        for configured in enabled:
            for name, expected_country in COMPETITION_LABELS.get(configured, ((configured, ""),)):
                name_norm = plain(name)
                if comp_norm != name_norm and not comp_norm.endswith(name_norm):
                    continue
                if not expected_country or plain(expected_country) in country_norm:
                    return True
        return False

    @staticmethod
    def _open_header(page, header) -> bool:
        """Abre una liga y comprueba el cambio real de estado."""
        for attempt in range(2):
            try:
                header.scroll_into_view_if_needed(timeout=5000)
                if attempt == 0:
                    header.click(timeout=5000)
                else:
                    header.evaluate("el => el.click()")
            except Exception:
                continue
            for _ in range(12):
                try:
                    if header.get_attribute("data-is-open") == "true":
                        return True
                except Exception:
                    break
                page.wait_for_timeout(250)
        return False

    @staticmethod
    def _read_detail_box(box) -> dict:
        return box.evaluate(DETAIL_BOX_SCRIPT)

    def _collect_detail_markets(self, page, sportsbook, card, home: str, away: str,
                                progress: Callable[[str], None]) -> list[dict]:
        """Abre el detalle de un evento y conserva solo mercados con modelo estadístico."""
        toggle = card.locator('button[class*="EventBoxDetailsButton"]').first
        if not toggle.count():
            return []
        try:
            toggle.click(timeout=5000)
            page.wait_for_timeout(450)
            try:
                tab = sportsbook.get_by_text("Todas", exact=True).last
                if tab.count() and tab.is_visible():
                    tab.click(timeout=3000)
                    page.wait_for_timeout(250)
            except Exception:
                pass

            boxes = sportsbook.locator('div[class*="EventDetailsMarketBoxContainer"]')
            output: list[dict] = []
            for index in range(boxes.count()):
                box = boxes.nth(index)
                try:
                    name = _clean_market_name(box.locator(
                        'div[class*="EventDetailsMarketName-sc"], [class*="EventDetailsMarketName"]'
                    ).first.inner_text(timeout=1200))
                except Exception:
                    continue
                if not _detail_market_supported(name, home, away):
                    continue
                try:
                    if not box.locator('[class*="OddValue"]').count():
                        box.locator('div[class*="EventDetailsMarketHeader"]').first.click(timeout=2500)
                        page.wait_for_timeout(180)
                except Exception:
                    try:
                        box.click(timeout=2000)
                        page.wait_for_timeout(180)
                    except Exception:
                        continue

                # El mercado de jugadores usa dos pestañas, una por equipo.
                if _clean_market_name(name).casefold() == "remates a puerta":
                    player_buttons: list[dict] = []
                    for team in (home, away):
                        try:
                            team_tab = box.get_by_role("button", name=re.compile(rf"^{re.escape(team)}$", re.I)).first
                            if team_tab.count() and team_tab.is_visible():
                                team_tab.click(timeout=2000)
                                page.wait_for_timeout(160)
                            more = box.get_by_role("button", name=re.compile("Más jugadores", re.I)).first
                            if more.count() and more.is_visible():
                                more.click(timeout=1500)
                                page.wait_for_timeout(120)
                        except Exception:
                            pass
                        payload = self._read_detail_box(box)
                        player_buttons.extend(payload.get("buttons", []))
                    output.append({"name": name, "lineText": "", "buttons": player_buttons})
                    continue

                payload = self._read_detail_box(box)
                payload["name"] = name
                if payload.get("buttons"):
                    output.append(payload)

                # La tarjeta principal muestra solo una línea. Para el total de goles
                # recorremos el control real de Triunfobet y añadimos 0.5, 1.5, 2.5,
                # 3.5 y 4.5 cuando la casa efectivamente publica precio.
                if name.casefold() == "total de goles":
                    slider = box.locator('input[type="range"]').first
                    if slider.count():
                        try:
                            slider.focus()
                            slider.press("Home")
                            for _ in range(14):
                                page.wait_for_timeout(55)
                                variant = self._read_detail_box(box)
                                variant["name"] = name
                                line_match = re.search(r"(\d+(?:[.,]\d+)?)", str(variant.get("lineText", "")))
                                if line_match:
                                    value = float(line_match.group(1).replace(",", "."))
                                    if value > 4.5:
                                        break
                                    if value in {0.5, 1.5, 2.5, 3.5, 4.5} and variant.get("buttons"):
                                        output.append(variant)
                                slider.press("ArrowRight")
                        except Exception:
                            pass
            return output
        except Exception as exc:
            progress(f"Detalle de {home} vs {away}: no se pudo leer ({exc}).")
            return []
        finally:
            try:
                if toggle.count():
                    toggle.click(timeout=2500)
                    page.wait_for_timeout(120)
            except Exception:
                pass

    def collect(self, progress: Callable[[str], None] | None = None,
                target_date: date | None = None,
                competitions: list[str] | None = None) -> list[Match]:
        progress = progress or (lambda _msg: None)
        target_date = target_date or date.today()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise TriunfoBetError(
                "Falta Playwright. Ejecuta INSTALAR.bat antes de usar el modo real."
            ) from exc

        self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        competitions = competitions or list(COMPETITION_LABELS)
        progress("Abriendo Triunfobet en modo oculto…")
        with sync_playwright() as pw:
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--enable-webgl",
                "--ignore-gpu-blocklist",
            ]
            try:
                browser = pw.chromium.launch(channel="chrome", headless=self.headless,
                                             args=launch_args)
                progress("Google Chrome iniciado. Esperando la cartelera…")
            except Exception:
                browser = pw.chromium.launch(headless=self.headless, args=launch_args)
                progress("Chrome no estaba disponible; usando Chromium incluido…")
            major = re.match(r"\d+", browser.version or "")
            chrome_major = major.group(0) if major else "131"
            user_agent = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 "
                          "Safari/537.36")
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000}, locale="es-VE",
                timezone_id="America/Caracas", user_agent=user_agent,
                ignore_https_errors=True,
            )
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = context.new_page()
            try:
                base_url = "https://triunfobet.com"
                page.goto(base_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1800)
                self._dismiss_overlays(page)
                progress("Abriendo Apuestas deportivas…")
                try:
                    page.get_by_role("link", name=re.compile("Apuestas Deportivas", re.I)).first.click(timeout=7000)
                except Exception:
                    page.goto(f"{base_url}/altenar#/overview", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5500)
                self._dismiss_overlays(page)

                progress("Seleccionando Fútbol…")
                sports_frame = self._sports_frame(page)
                if sports_frame is not None:
                    clicked = False
                    for selector in ('a[href*="#/sport/66"]', 'button:has-text("Fútbol")'):
                        try:
                            candidate = sports_frame.locator(selector).first
                            if candidate.count() and candidate.is_visible():
                                candidate.click(timeout=5000)
                                page.wait_for_timeout(1800)
                                clicked = True
                                break
                        except Exception:
                            continue
                    if not clicked:
                        try:
                            sports_frame.get_by_text("Fútbol", exact=True).last.click(timeout=5000)
                            clicked = True
                        except Exception:
                            pass

                filter_name, route_id = self._route_for(target_date)
                progress(f"Seleccionando {filter_name.lower()}…")
                sports_frame = self._sports_frame(page)
                selected = False
                if sports_frame is not None:
                    try:
                        option = sports_frame.get_by_text(filter_name, exact=True).first
                        if option.count() and option.is_visible():
                            option.click(timeout=7000)
                            selected = True
                    except Exception:
                        pass
                if not selected:
                    page.goto(f"{base_url}/altenar#/coupon/66/{route_id}",
                              wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(6000)
                self._dismiss_overlays(page)

                sportsbook = None
                for _ in range(30):
                    sportsbook = self._sports_frame(page, require_headers=True)
                    if sportsbook is not None:
                        break
                    page.wait_for_timeout(1000)
                if sportsbook is None:
                    raise TriunfoBetError(
                        "Triunfobet abrió, pero no cargó la lista de ligas. "
                        "Se guardó evidencia en la carpeta diagnostics."
                    )

                headers = sportsbook.locator('div[class*="ChampionshipHeader"]')
                header_texts = headers.all_inner_texts()
                wanted = [text for text in header_texts
                          if self._wanted_header(text, competitions)]
                progress(f"Verificando {len(wanted)} competiciones una por una…")
                payload: list[dict] = []
                league_log: list[dict] = []
                for position, wanted_text in enumerate(wanted, 1):
                    clean_name = wanted_text.split("\n", 1)[0].strip()
                    progress(f"Liga {position}/{len(wanted)}: abriendo {clean_name}…")
                    # React puede reconstruir la lista después de cada apertura;
                    # se busca de nuevo el índice por su texto visible.
                    try:
                        headers = sportsbook.locator('div[class*="ChampionshipHeader"]')
                        current_texts = headers.all_inner_texts()
                        index = current_texts.index(wanted_text)
                        header = headers.nth(index)
                    except Exception:
                        league_log.append({"league": clean_name, "opened": False,
                                           "cards": 0, "error": "cabecera no encontrada"})
                        continue
                    opened = self._open_header(page, header)
                    if not opened:
                        league_log.append({"league": clean_name, "opened": False,
                                           "cards": 0, "error": "no cambió a abierto"})
                        continue
                    page.wait_for_timeout(1200)
                    container = header.locator("xpath=..")
                    cards = container.evaluate(CARD_SCRIPT)
                    card_nodes = container.locator('div[class*="EventBoxContainerBase"]')
                    detail_count = 0
                    for card_index, card_payload in enumerate(cards):
                        try:
                            card_day = datetime.fromisoformat(
                                _kickoff_iso(str(card_payload.get("date", "")))
                            ).date()
                        except ValueError:
                            continue
                        if card_day != target_date or card_payload.get("live") or card_index >= card_nodes.count():
                            continue
                        teams = card_payload.get("teams") or []
                        if len(teams) != 2:
                            continue
                        progress(f"{clean_name}: leyendo mercados de {teams[0]} vs {teams[1]}…")
                        details = self._collect_detail_markets(
                            page, sportsbook, card_nodes.nth(card_index),
                            str(teams[0]), str(teams[1]), progress,
                        )
                        card_payload["detailMarkets"] = details
                        detail_count += len(details)
                    payload.extend(cards)
                    league_log.append({"league": clean_name, "opened": True,
                                       "cards": len(cards), "detail_markets": detail_count})
                    progress(f"{clean_name}: {len(cards)} partido(s) y {detail_count} mercado(s) detallado(s).")
                    try:
                        header.click(timeout=4000)
                        page.wait_for_timeout(200)
                    except Exception:
                        pass

                progress(f"Validando eventos del {target_date.strftime('%d/%m/%Y')}…")
                (self.diagnostics_dir / f"triunfobet-{stamp}.json").write_text(
                    json.dumps({"route": page.url, "leagues": league_log, "cards": payload},
                               ensure_ascii=False, indent=2), encoding="utf-8"
                )
                if not payload:
                    (self.diagnostics_dir / f"triunfobet-{stamp}.html").write_text(
                        page.content(), encoding="utf-8"
                    )
                matches = parse_cards(payload, page.url)
                if not matches:
                    progress("No hay partidos publicados en las competiciones elegidas para esa fecha.")
                    return []
                progress(f"Triunfobet: {len(matches)} partidos leídos.")
                return matches
            except TriunfoBetError:
                try:
                    (self.diagnostics_dir / f"triunfobet-error-{stamp}.html").write_text(
                        page.content(), encoding="utf-8"
                    )
                    page.screenshot(path=str(self.diagnostics_dir / f"triunfobet-error-{stamp}.png"), full_page=True)
                except Exception:
                    pass
                raise
            except Exception as exc:
                try:
                    (self.diagnostics_dir / f"triunfobet-error-{stamp}.html").write_text(
                        page.content(), encoding="utf-8"
                    )
                    page.screenshot(path=str(self.diagnostics_dir / f"triunfobet-error-{stamp}.png"), full_page=True)
                except Exception:
                    pass
                raise TriunfoBetError(f"No se pudo leer Triunfobet: {exc}") from exc
            finally:
                context.close()
                browser.close()

