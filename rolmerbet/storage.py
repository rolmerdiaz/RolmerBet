from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .domain import Combo, Evaluation, Match


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    matches_count INTEGER NOT NULL DEFAULT 0,
    markets_count INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS matches (
    run_id INTEGER NOT NULL,
    match_id TEXT NOT NULL,
    competition TEXT NOT NULL,
    kickoff_iso TEXT NOT NULL,
    home TEXT NOT NULL,
    away TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (run_id, match_id)
);
CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    match_id TEXT NOT NULL,
    accepted INTEGER NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS combos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    total_odds REAL NOT NULL,
    estimated_probability REAL NOT NULL,
    result TEXT NOT NULL DEFAULT 'Pendiente',
    stake REAL NOT NULL DEFAULT 0,
    profit REAL NOT NULL DEFAULT 0,
    payload TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=20)
        con.row_factory = sqlite3.Row
        return con

    def save_run(self, mode: str, matches: list[Match], evaluations: list[Evaluation], combo: Combo) -> int:
        markets = sum(len(m.quotes) for m in matches)
        with self.connect() as con:
            cur = con.execute(
                "INSERT INTO runs(mode,status,matches_count,markets_count,message) VALUES(?,?,?,?,?)",
                (mode, combo.status, len(matches), markets, combo.message),
            )
            run_id = int(cur.lastrowid)
            con.executemany(
                "INSERT INTO matches(run_id,match_id,competition,kickoff_iso,home,away,payload) VALUES(?,?,?,?,?,?,?)",
                [(run_id, m.match_id, m.competition, m.kickoff_iso, m.home, m.away,
                  json.dumps(m.to_dict(), ensure_ascii=False)) for m in matches],
            )
            con.executemany(
                "INSERT INTO evaluations(run_id,match_id,accepted,payload) VALUES(?,?,?,?)",
                [(run_id, e.match_id, int(e.accepted), json.dumps(e.to_dict(), ensure_ascii=False))
                 for e in evaluations],
            )
            con.execute(
                "INSERT INTO combos(run_id,created_at,status,total_odds,estimated_probability,payload) VALUES(?,?,?,?,?,?)",
                (run_id, combo.created_at, combo.status, combo.total_odds,
                 combo.estimated_probability, json.dumps(combo.to_dict(), ensure_ascii=False)),
            )
            return run_id

    def history(self, limit: int = 100) -> list[dict]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT c.id,c.created_at,c.status,c.total_odds,c.estimated_probability,c.result,c.stake,c.profit,r.mode "
                "FROM combos c JOIN runs r ON r.id=c.run_id ORDER BY c.id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def latest_combo(self) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT payload FROM combos ORDER BY id DESC LIMIT 1").fetchone()
        return json.loads(row["payload"]) if row else None

    def mark_result(self, combo_id: int, result: str, stake: float = 0.0) -> None:
        if result not in {"Pendiente", "Ganada", "Perdida", "Nula"}:
            raise ValueError("Resultado inválido")
        with self.connect() as con:
            row = con.execute("SELECT total_odds FROM combos WHERE id=?", (combo_id,)).fetchone()
            if not row:
                raise KeyError(combo_id)
            odds = float(row["total_odds"])
            profit = stake * (odds - 1.0) if result == "Ganada" else (-stake if result == "Perdida" else 0.0)
            con.execute("UPDATE combos SET result=?,stake=?,profit=? WHERE id=?",
                        (result, stake, profit, combo_id))

