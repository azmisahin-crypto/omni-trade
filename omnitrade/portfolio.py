"""Dry-run (kağıt üstü) cüzdan. Gerçek borsaya emir göndermeden al/sat
simüle eder, her işlemi Storage'a loglar — böylece 'gerçekten kazandırıyor
mu' sorusuna backtest'ten bağımsız, gerçek zamanlı veriyle de cevap
alabilirsin, hiç risk almadan.

Komisyon (fee_pct) ve slippage (slippage_pct) backtest.py ile aynı mantıkla
modellenir, böylece backtest ve dry-run sonuçları karşılaştırılabilir kalır.
Risk yönetimi (pozisyon büyüklüğü, stop-loss/take-profit, günlük zarar
kill-switch) RiskManager üzerinden uygulanır — bkz. risk.py.
"""
from __future__ import annotations

from dataclasses import dataclass

from omnitrade.risk import RiskConfig, RiskManager
from omnitrade.storage import Storage
from omnitrade.strategies.base import Action, Signal


@dataclass
class Position:
    symbol: str
    qty: float
    entry_price: float


class Portfolio:
    def __init__(
        self,
        storage: Storage,
        starting_balance: float,
        risk_config: RiskConfig | None = None,
        fee_pct: float = 0.001,
        slippage_pct: float = 0.0005,
    ):
        self.storage = storage
        self.balance = starting_balance
        self.fee_pct = fee_pct
        self.slippage_pct = slippage_pct
        self.risk = RiskManager(risk_config or RiskConfig())
        self.positions: dict[str, Position] = {}

    def equity(self, last_prices: dict[str, float]) -> float:
        total = self.balance
        for sym, pos in self.positions.items():
            total += pos.qty * last_prices.get(sym, pos.entry_price)
        return total

    def _buy_fill_price(self, price: float) -> float:
        # Slippage alışta fiyatı senin aleyhine (biraz daha pahalı) yansıtır
        return price * (1 + self.slippage_pct)

    def _sell_fill_price(self, price: float) -> float:
        # Slippage satışta fiyatı senin aleyhine (biraz daha ucuz) yansıtır
        return price * (1 - self.slippage_pct)

    def apply_signal(self, signal: Signal, price: float) -> tuple[bool, float]:
        """Sinyali uygulamaya çalışır, (gerçekten bir işlem oldu mu, işlem
        miktarı) döner. ÖNEMLİ FIX: önceden sadece bool dönüyordu ve
        engine.py Telegram bildirimine HER ZAMAN qty=0.0 gönderiyordu
        ("Miktar: 0.000000" hatası) — kök neden gerçek miktarın çağırana
        hiç iletilmemesiydi, buradaki hesabın kendisi zaten doğruydu.
        Çağıran taraf (engine.py) `executed`i Telegram bildirimi göndermeden
        önce kontrol etmeli — aksi halde "pozisyon yokken sell sinyali" gibi
        hiçbir şey olmayan durumlarda da yanlışlıkla "işlem yapıldı"
        bildirimi gider (bkz. CHANGELOG)."""
        if signal.action == Action.BUY and signal.symbol not in self.positions:
            if not self.risk.can_open_position(len(self.positions)):
                self.storage.log_trade(
                    signal.symbol, "buy_blocked", price, 0.0,
                    reason=f"risk engeli (kill-switch={self.risk.kill_switch_active}, "
                           f"açık pozisyon={len(self.positions)})",
                    dry_run=True,
                )
                return False, 0.0

            stake = self.risk.position_stake(self.balance)
            if stake <= 0 or stake > self.balance:
                return False, 0.0
            fill_price = self._buy_fill_price(price)
            qty = (stake * (1 - self.fee_pct)) / fill_price
            self.balance -= stake
            self.positions[signal.symbol] = Position(signal.symbol, qty, fill_price)
            self.storage.log_trade(signal.symbol, "buy", fill_price, qty, signal.reason, dry_run=True)
            return True, qty

        elif signal.action == Action.SELL and signal.symbol in self.positions:
            qty = self._close_position(signal.symbol, price, reason=signal.reason)
            return True, qty

        return False, 0.0

    def _close_position(self, symbol: str, price: float, reason: str) -> float:
        pos = self.positions.pop(symbol)
        fill_price = self._sell_fill_price(price)
        proceeds = pos.qty * fill_price * (1 - self.fee_pct)
        self.balance += proceeds
        self.storage.log_trade(symbol, "sell", fill_price, pos.qty, reason, dry_run=True)
        return pos.qty

    def check_risk_exits(self, last_prices: dict[str, float]) -> list[tuple[str, float, float, str]]:
        """Her döngüde stratejiden bağımsız olarak çağrılmalı: açık pozisyonlarda
        stop-loss/take-profit tetiklendiyse pozisyonu zorla kapatır.

        FIX: önceden bu kapanışlar hiçbir yere bildirilmiyordu (Telegram'a
        SESSİZCE gidiyordu) — sadece signal-tabanlı sell'lerde bildirim
        vardı. Artık kapanan (symbol, price, qty, reason) listesi dönüyor,
        engine.py bunun için de trade_alert gönderiyor."""
        closed: list[tuple[str, float, float, str]] = []
        for symbol in list(self.positions.keys()):
            price = last_prices.get(symbol)
            if price is None:
                continue
            pos = self.positions[symbol]
            if self.risk.should_stop_loss(pos.entry_price, price):
                qty = self._close_position(symbol, price, reason="stop-loss tetiklendi")
                closed.append((symbol, price, qty, "stop-loss tetiklendi"))
            elif self.risk.should_take_profit(pos.entry_price, price):
                qty = self._close_position(symbol, price, reason="take-profit tetiklendi")
                closed.append((symbol, price, qty, "take-profit tetiklendi"))
        return closed

    def snapshot(self, last_prices: dict[str, float]) -> None:
        equity = self.equity(last_prices)
        self.risk.update_daily_baseline(equity)
        self.risk.check_kill_switch(equity)
        self.storage.log_equity(equity)
