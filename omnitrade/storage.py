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

-- Her döngüde üretilen HER sinyal burada tutulur (hold dahil) — trades
-- tablosunun aksine bir pozisyon açılıp açılmadığından bağımsız. Dashboard
-- "pozisyona girilmese bile tüm coinler için sinyal" görünümünü buradan
-- besler. `executed`: bu sinyal gerçekten bir al/sat işlemine yol açtı mı
-- (trades tablosuna da yazıldı mı).
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,       -- buy / sell / hold
    price REAL NOT NULL,
    reason TEXT,
    executed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts ON signals (symbol, ts);

-- Faz 16: dry_run/live_trading_confirmed her değiştiğinde (dashboard'daki
-- "Canlıya Geç"/"Dry-Run'a Dön" uçlarından) buraya bir satır eklenir.
-- Bilinçli olarak sadece INSERT yapan bir yardımcı (`log_mode_change`) ve
-- sadece SELECT yapan bir yardımcı (`get_mode_audit_log`) var — UPDATE/DELETE
-- için Storage'da hiçbir metod yok, yani bu tablo API üzerinden salt-okunur
-- ve izole: denetim izini bir hatanın ya da kötüye kullanımın SİLEMEMESİ
-- amaçlanıyor (bkz. AUDIT_REPORT.md §6.1).
CREATE TABLE IF NOT EXISTS mode_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    username TEXT,
    ip TEXT,
    action TEXT NOT NULL,           -- go_live / go_dry_run
    old_dry_run INTEGER NOT NULL,
    new_dry_run INTEGER NOT NULL,
    old_live_trading_confirmed INTEGER NOT NULL,
    new_live_trading_confirmed INTEGER NOT NULL
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

    def log_signal(
        self, symbol: str, action: str, price: float,
        reason: str = "", executed: bool = False,
    ) -> None:
        """Her döngüde ÜRETİLEN her sinyali kaydeder (hold dahil, pozisyon
        olsun olmasın) — trade gerçekleşmese de coinin son durumu görülebilsin
        diye. Bkz. tablo yorumu (SCHEMA)."""
        self.conn.execute(
            "INSERT INTO signals (ts, symbol, action, price, reason, executed) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), symbol, action, price, reason, int(executed)),
        )
        self.conn.commit()

    def get_latest_signals(self) -> list[dict]:
        """Her sembol için en son üretilen sinyal — coin listesi panelini
        besler (bkz. web dashboard)."""
        cur = self.conn.execute(
            "SELECT s.ts, s.symbol, s.action, s.price, s.reason, s.executed "
            "FROM signals s "
            "INNER JOIN (SELECT symbol, MAX(ts) AS max_ts FROM signals GROUP BY symbol) latest "
            "ON s.symbol = latest.symbol AND s.ts = latest.max_ts "
            "ORDER BY s.symbol ASC"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_signals(self, symbol: str | None = None, limit: int = 500) -> list[dict]:
        """Bir coinin (ya da hepsinin) sinyal geçmişi — coin bazlı grafik için.
        Sonuç zaman artan sırada döner (grafik çizimi için uygun)."""
        if symbol:
            cur = self.conn.execute(
                "SELECT ts, symbol, action, price, reason, executed FROM signals "
                "WHERE symbol = ? ORDER BY ts DESC LIMIT ?",
                (symbol, limit),
            )
        else:
            cur = self.conn.execute(
                "SELECT ts, symbol, action, price, reason, executed FROM signals "
                "ORDER BY ts DESC LIMIT ?",
                (limit,),
            )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        rows.reverse()
        return rows

    def log_mode_change(
        self, action: str, old_dry_run: bool, new_dry_run: bool,
        old_live_trading_confirmed: bool, new_live_trading_confirmed: bool,
        username: str = "", ip: str = "",
    ) -> None:
        """Faz 16: canlı/dry-run geçişini izole, salt-okunur denetim
        kaydına yazar (bkz. SCHEMA'daki `mode_audit_log` yorumu). Bu metod
        SADECE ekler — mevcut bir satırı değiştirmenin/silmenin bir yolu
        yok, bilinçli olarak."""
        self.conn.execute(
            "INSERT INTO mode_audit_log "
            "(ts, username, ip, action, old_dry_run, new_dry_run, "
            " old_live_trading_confirmed, new_live_trading_confirmed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                time.time(), username, ip, action,
                int(old_dry_run), int(new_dry_run),
                int(old_live_trading_confirmed), int(new_live_trading_confirmed),
            ),
        )
        self.conn.commit()

    def get_mode_audit_log(self, limit: int = 100) -> list[dict]:
        """En yeni değişiklik en üstte — dashboard'daki denetim paneli
        için. Salt-okunur: burada UPDATE/DELETE yapan hiçbir metod yok."""
        cur = self.conn.execute(
            "SELECT ts, username, ip, action, old_dry_run, new_dry_run, "
            "old_live_trading_confirmed, new_live_trading_confirmed "
            "FROM mode_audit_log ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_stream_fingerprint(self) -> dict:
        """Faz 17: SSE push modeli için ucuz bir 'durum parmak izi' —
        `trades`/`equity`/`signals`/`mode_audit_log` tablolarının en son
        satır id'si + heartbeat zaman damgası. Web süreci bunu kısa
        aralıklarla (bkz. server.py `_handle_stream`) bir öncekiyle
        karşılaştırır; SADECE değişen anahtar(lar) tarayıcıya push edilir.
        INTEGER PRIMARY KEY sütunları SQLite'ta rowid'nin kendisi olduğundan
        `MAX(id)` burada tam tablo taraması GEREKTİRMEZ — B-tree'nin en sağ
        yaprağına tek adımda gidilir, bu yüzden trades/equity/signals
        tabloları büyüse bile bu sorgu ucuz kalır."""
        cur = self.conn.execute(
            "SELECT "
            "(SELECT MAX(id) FROM trades), "
            "(SELECT MAX(id) FROM equity), "
            "(SELECT MAX(id) FROM signals), "
            "(SELECT MAX(id) FROM mode_audit_log), "
            "(SELECT ts FROM heartbeat WHERE id = 1)"
        )
        trades_id, equity_id, signals_id, audit_id, heartbeat_ts = cur.fetchone()
        return {
            "trades": trades_id,
            "equity": equity_id,
            "signals": signals_id,
            "system": audit_id,
            "heartbeat": heartbeat_ts,
        }

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
