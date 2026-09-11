"""Tüm stratejiler bu sınıftan türer. Bulduğun/çevirdiğin bir stratejiyi
eklemek için tek yapman gereken `generate_signal(df)` metodunu yazmak —
motorun geri kalanı (veri çekme, emir simülasyonu, telegram bildirimi,
backtest) bu arayüzle otomatik çalışır.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class Action(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Signal:
    action: Action
    symbol: str
    reason: str = ""
    confidence: float = 1.0  # 0..1, ileride pozisyon büyüklüğü için kullanılabilir


class Strategy:
    """Alt sınıflar en az `generate_signal`'i override eder."""

    name: str = "BaseStrategy"

    def required_candles(self) -> int:
        """Sinyal üretmek için gereken minimum mum sayısı."""
        return 50

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        """`df`: OHLCV DataFrame (kolonlar: open, high, low, close, volume),
        en yeni mum en altta. Bir `Signal` döndürmeli."""
        raise NotImplementedError
