from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DIAGNOSTICS_DIR = ROOT / "diagnostics"
ASSETS_DIR = ROOT / "assets"
CONFIG_PATH = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "rolmerbet.db"

DEFAULTS = {
    "triunfobet_url": "https://triunfobet.com",
    "headless": True,
    "demo_mode": True,
    "target_odds_min": 3.0,
    "target_odds_max": 4.0,
    "max_legs": 5,
    "min_leg_probability": 0.68,
    "min_quality": 75,
    "min_edge": 0.02,
    "min_total_probability": 0.22,
    "football_data_token": "",
    "recent_games": 10,
    "theme": "dark",
    "check_updates": True,
    "competitions": [
        "Premier League", "LaLiga", "Serie A", "Bundesliga", "Ligue 1",
        "Champions League", "Europa League", "Carabao Cup", "Coppa Italia",
        "Nations League", "World Cup Qualification", "European Championship Qualification",
    ],
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    ensure_dirs()
    cfg = deepcopy(DEFAULTS)
    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            cfg.update(loaded)
    except (OSError, ValueError):
        pass
    env_token = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()
    if env_token:
        cfg["football_data_token"] = env_token
    return cfg


def save_config(config: dict) -> None:
    ensure_dirs()
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, CONFIG_PATH)

