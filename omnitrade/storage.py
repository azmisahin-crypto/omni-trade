"""Basit SQLite katmanı: her işlem ve her equity (bakiye) anlık görüntüsü
buraya yazılır. Web dashboard bu tablolardan okur."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,       -- buy / sell
    price REAL NOT NULL,
    qty REAL NOT NULL,
    reason TEXT,
    dry_run INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    balance REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS heartbeat (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    ts REAL NOT NULL
);
"""


class Storage:
    def __init__(self, db_path: str = "data/omnitrade.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        # WAL modu: bot ve web container'ları aynı dosyaya eşzamanlı erişiyor.
        # Varsayılan journal modunda yazma sırasında okuyucular kilitlenebilir;
        # WAL bu durumda okumaya izin verir, "database is locked" hatalarını azaltır.
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def log_trade(
        self, symbol: str, action: str, price: float, qty: float,
        reason: str = "", dry_run: bool = True,
    ) -> None:
        self.conn.execute(
            "INSERT INTO trades (ts, symbol, action, price, qty, reason, dry_run) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (time.time(), symbol, action, price, qty, reason, int(dry_run)),
        )
        self.conn.commit()

    def log_equity(self, balance: float) -> None:
        self.conn.execute(
            "INSERT INTO equity (ts, balance) VALUES (?, ?)", (time.time(), balance)
        )
        self.conn.commit()

    def get_trades(self, limit: int = 200) -> list[dict]:
        cur = self.conn.execute(
            "SELECT ts, symbol, action, price, qty, reason, dry_run "
            "FROM trades ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_equity_curve(self, limit: int = 1000) -> list[dict]:
        cur = self.conn.execute(
            "SELECT ts, balance FROM equity ORDER BY ts ASC LIMIT ?", (limit,)
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def beat(self) -> None:
        """Her başarılı döngü sonunda çağrılır — dışarıdan (healthcheck.py)
        botun canlı olup olmadığını, son ne zaman çalıştığını kontrol etmek için."""
        self.conn.execute(
            "INSERT INTO heartbeat (id, ts) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET ts = excluded.ts",
            (time.time(),),
        )
        self.conn.commit()

    def last_heartbeat(self) -> float | None:
        cur = self.conn.execute("SELECT ts FROM heartbeat WHERE id = 1")
        row = cur.fetchone()
        return row[0] if row else None

    def close(self) -> None:
        self.conn.close()
