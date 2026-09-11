"""Örnek strateji: RSI oversold/overbought.

Başka bir dilden/platformdan bulup çevireceğin stratejiler için de şablon:
1. Bu dosyayı kopyala, yeni bir isim ver (örn. `my_strategy.py`)
2. `generate_signal` içine indikatör hesaplarını ve al/sat mantığını yaz
3. `omnitrade/strategies/__init__.py`'daki STRATEGIES sözlüğüne ekle
4. `config/config.yaml`'da `strategy: MyStrategy` yap
"""
from __future__ import annotations

import pandas as pd

from omnitrade.strategies.base import Action, Signal, Strategy


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    # Kenar durum: fiyat tamamen sabitse (avg_gain=0 ve avg_loss=0) RS 0/0
    # belirsizdir. Eskiden bu durumda rs=0 hesaplanıyor, bu da RSI=0 (yanlışlıkla
    # "aşırı satım" -> sahte BUY sinyali) üretiyordu. Doğrusu: hareket yoksa
    # RSI nötr (50) olmalı.
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    result = 100 - (100 / (1 + rs))
    both_zero = (avg_gain == 0) & (avg_loss == 0)
    result = result.where(~both_zero, 50.0)
    # avg_loss=0 ama avg_gain>0 ise gerçek bir aşırı-alım durumu: RSI=100
    only_gain = (avg_loss == 0) & (avg_gain > 0)
    result = result.where(~only_gain, 100.0)
    return result


class RsiStrategy(Strategy):
    name = "RsiStrategy"

    def __init__(self, period: int = 14, oversold: float = 30, overbought: float = 70):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def required_candles(self) -> int:
        return self.period + 5

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        if len(df) < self.required_candles():
            return Signal(Action.HOLD, symbol, reason="yetersiz veri")

        r = rsi(df["close"], self.period)
        last_rsi = r.iloc[-1]

        if last_rsi < self.oversold:
            return Signal(Action.BUY, symbol, reason=f"RSI={last_rsi:.1f} < {self.oversold}")
        if last_rsi > self.overbought:
            return Signal(Action.SELL, symbol, reason=f"RSI={last_rsi:.1f} > {self.overbought}")
        return Signal(Action.HOLD, symbol, reason=f"RSI={last_rsi:.1f}")
