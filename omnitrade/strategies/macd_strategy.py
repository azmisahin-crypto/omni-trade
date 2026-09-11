"""MACD (trend-takip) stratejisi.

RSI aşırı-alım/aşırı-satım (mean-reversion) mantığıyla çalışırken, MACD
trend yönünü takip eder: hızlı EMA yavaş EMA'nın üstündeyken BUY, altındayken
SELL. Böylece RSI'nin yakalayamadığı güçlü/uzun trendleri de test edebiliriz.

Not: Diğer stratejiler gibi (bkz. RsiStrategy) bu da "durum bazlı" çalışır,
crossover anını ayrıca tespit etmez — MACD sinyal çizgisinin üstündeyken her
döngüde BUY üretir. Bu güvenlidir çünkü `Portfolio.apply_signal` zaten aynı
sembolde açık pozisyon varken yeni BUY'u, pozisyon yokken SELL'i no-op geçer
(bkz. omnitrade/portfolio.py) — yani tekrarlanan sinyal fazladan işlem
açmaz, sadece trend değiştiğinde gerçek bir aksiyon tetiklenir.
"""
from __future__ import annotations

import pandas as pd

from omnitrade.strategies.base import Action, Signal, Strategy


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple[pd.Series, pd.Series]:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal_period)
    return macd_line, signal_line


class MacdStrategy(Strategy):
    name = "MacdStrategy"

    def __init__(self, fast: int = 12, slow: int = 26, signal_period: int = 9):
        if fast >= slow:
            raise ValueError("fast, slow'dan küçük olmalı")
        self.fast = fast
        self.slow = slow
        self.signal_period = signal_period

    def required_candles(self) -> int:
        # EMA'ların oturması için slow + signal_period kadar mum yeterli
        # olsa da, erken barlardaki gürültüyü azaltmak için biraz pay bırak.
        return self.slow + self.signal_period + 10

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        if len(df) < self.required_candles():
            return Signal(Action.HOLD, symbol, reason="yetersiz veri")

        macd_line, signal_line = macd(df["close"], self.fast, self.slow, self.signal_period)
        last_macd = macd_line.iloc[-1]
        last_signal = signal_line.iloc[-1]

        if pd.isna(last_macd) or pd.isna(last_signal):
            return Signal(Action.HOLD, symbol, reason="yetersiz veri")

        if last_macd > last_signal:
            return Signal(
                Action.BUY, symbol,
                reason=f"MACD={last_macd:.4f} > sinyal={last_signal:.4f}",
            )
        if last_macd < last_signal:
            return Signal(
                Action.SELL, symbol,
                reason=f"MACD={last_macd:.4f} < sinyal={last_signal:.4f}",
            )
        return Signal(Action.HOLD, symbol, reason="MACD sinyal çizgisine eşit")
