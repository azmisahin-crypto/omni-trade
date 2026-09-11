"""Dry-run (kağıt üstü) cüzdan. Gerçek borsaya emir göndermeden al/sat
simüle eder, her işlemi Storage'a loglar — böylece 'gerçekten kazandırıyor
mu' sorusuna backtest'ten bağımsız, gerçek zamanlı veriyle de cevap
alabilirsin, hiç risk almadan.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from omnitrade.storage import Storage
from omnitrade.strategies.base import Action, Signal


@dataclass
class Position:
    symbol: str
    qty: float
    entry_price: float


class Portfolio:
    def __init__(self, storage: Storage, starting_balance: float, stake_fraction: float = 0.2):
        self.storage = storage
        self.balance = starting_balance
        self.stake_fraction = stake_fraction  # her pozisyona bakiyenin ne kadarını ayır
        self.positions: dict[str, Position] = {}

    def equity(self, last_prices: dict[str, float]) -> float:
        total = self.balance
        for sym, pos in self.positions.items():
            total += pos.qty * last_prices.get(sym, pos.entry_price)
        return total

    def apply_signal(self, signal: Signal, price: float) -> None:
        if signal.action == Action.BUY and signal.symbol not in self.positions:
            stake = self.balance * self.stake_fraction
            if stake <= 0:
                return
            qty = stake / price
            self.balance -= stake
            self.positions[signal.symbol] = Position(signal.symbol, qty, price)
            self.storage.log_trade(signal.symbol, "buy", price, qty, signal.reason, dry_run=True)

        elif signal.action == Action.SELL and signal.symbol in self.positions:
            pos = self.positions.pop(signal.symbol)
            proceeds = pos.qty * price
            self.balance += proceeds
            self.storage.log_trade(signal.symbol, "sell", price, pos.qty, signal.reason, dry_run=True)

    def snapshot(self, last_prices: dict[str, float]) -> None:
        self.storage.log_equity(self.equity(last_prices))
