"""Bollinger Bantları mean-reversion stratejisi.

RSI'ye benzer bir mean-reversion mantığı ama farklı bir istatistiksel temelle:
fiyat, hareketli ortalamanın `num_std` standart sapma altına inince BUY,
üstüne çıkınca SELL üretir. RSI ile aynı coin'de yan yana backtest edip
hangisinin o coin'in volatilite karakterine daha uygun olduğunu görmek için
iyi bir ikinci mean-reversion referansı.
"""
from __future__ import annotations

import pandas as pd

from omnitrade.strategies.base import Action, Signal, Strategy


def bollinger_bands(
    series: pd.Series, period: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return lower, middle, upper


class BollingerStrategy(Strategy):
    name = "BollingerStrategy"

    def __init__(self, period: int = 20, num_std: float = 2.0):
        self.period = period
        self.num_std = num_std

    def required_candles(self) -> int:
        return self.period + 5

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        if len(df) < self.required_candles():
            return Signal(Action.HOLD, symbol, reason="yetersiz veri")

        lower, middle, upper = bollinger_bands(df["close"], self.period, self.num_std)
        last_close = df["close"].iloc[-1]
        last_lower = lower.iloc[-1]
        last_upper = upper.iloc[-1]

        if pd.isna(last_lower) or pd.isna(last_upper):
            return Signal(Action.HOLD, symbol, reason="yetersiz veri")

        if last_close < last_lower:
            return Signal(
                Action.BUY, symbol,
                reason=f"fiyat={last_close:.4f} < alt bant={last_lower:.4f}",
            )
        if last_close > last_upper:
            return Signal(
                Action.SELL, symbol,
                reason=f"fiyat={last_close:.4f} > üst bant={last_upper:.4f}",
            )
        return Signal(
            Action.HOLD, symbol,
            reason=f"fiyat={last_close:.4f} bantlar içinde ({last_lower:.4f}-{last_upper:.4f})",
        )
