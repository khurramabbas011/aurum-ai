# ═══════════════════════════════════════════════════════════
# AURUM AI · learning/memory.py
# Persistent trade memory (SQLite). Every signal and every
# closed trade is recorded with full feature context so the
# learning layer can study what actually works.
# ═══════════════════════════════════════════════════════════

import json
import os
import sqlite3
import threading

import config
from core.models import ClosedTrade
from core.utils import get_logger, gmt_now

log = get_logger("memory")


class Memory:
    def __init__(self, db_path: str = None):
        self.path = db_path or config.DB_PATH
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.Lock()
        self.cx = sqlite3.connect(self.path, check_same_thread=False)
        self.cx.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        with self._lock:
            self.cx.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket INTEGER, side TEXT, setup TEXT, timeframe TEXT,
                entry REAL, exit REAL, sl REAL, lots REAL,
                pnl_usd REAL, pnl_r REAL, result TEXT,
                open_time TEXT, close_time TEXT,
                bias TEXT, session TEXT, features TEXT, reason TEXT
            );
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT, side TEXT, setup TEXT, timeframe TEXT,
                taken INTEGER, edge_score REAL, features TEXT
            );
            CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT);
            """)
            self.cx.commit()

    # ---------- writes ----------
    def log_signal(self, sig, taken: bool):
        with self._lock:
            self.cx.execute(
                "INSERT INTO signals(ts,side,setup,timeframe,taken,edge_score,features)"
                " VALUES(?,?,?,?,?,?,?)",
                (gmt_now().isoformat(), sig.side.value, sig.setup.value,
                 sig.timeframe, int(taken), sig.edge_score,
                 json.dumps(sig.features, default=str)))
            self.cx.commit()

    def log_trade(self, t: ClosedTrade):
        row = t.to_row()
        cols = ("ticket", "side", "setup", "timeframe", "entry", "exit", "sl",
                "lots", "pnl_usd", "pnl_r", "result", "open_time",
                "close_time", "bias", "session", "features", "reason")
        with self._lock:
            self.cx.execute(
                f"INSERT INTO trades({','.join(cols)}) "
                f"VALUES({','.join('?' * len(cols))})",
                tuple(row[c] for c in cols))
            self.cx.commit()
        log.info("trade logged: %s %s %s r=%.2f", t.setup, t.side, t.result,
                 t.pnl_r)

    # ---------- reads ----------
    def closed_trades(self, limit: int = 1000) -> list[dict]:
        with self._lock:
            rows = self.cx.execute(
                "SELECT * FROM trades ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows][::-1]

    def count_trades(self) -> int:
        with self._lock:
            return self.cx.execute("SELECT COUNT(*) c FROM trades").fetchone()["c"]

    def get_state(self, k, default=None):
        with self._lock:
            r = self.cx.execute("SELECT v FROM state WHERE k=?", (k,)).fetchone()
        return r["v"] if r else default

    def set_state(self, k, v):
        with self._lock:
            self.cx.execute(
                "INSERT INTO state(k,v) VALUES(?,?) "
                "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))
            self.cx.commit()

    def close(self):
        with self._lock:
            self.cx.close()
