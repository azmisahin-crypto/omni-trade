"""Stochastic Osilatör (mean-reversion) stratejisi.

RSI'ye benzer bir eşik-tabanlı mean-reversion mantığı (aşırı satım -> BUY,
aşırı alım -> SELL) ama TAMAMEN farklı bir formülle: RSI sadece `close`
serisindeki ardışık kazanç/kayıpların ORANINA bakarken, Stochastic
kapanışın SON N MUM'un high-low ARALIĞI içindeki KONUMUNA bakar. Bu, RSI/
MACD/Bollinger'ın (hepsi sadece `close` kolonunu kullanır) aksine `high`/
`low` kolonlarını da işin içine katan ilk strateji — fitilleri (wick)
görmezden gelmeyen bir sinyal üretir.

%K = 100 * (close - son N mumun en düşüğü) / (son N mumun en yükseği - en düşüğü)
%D = %K'nın d_period'luk basit hareketli ortalaması (gürültüyü azaltmak için)

Diğer stratejiler gibi (bkz. RsiStrategy/MacdStrategy) "durum bazlı" çalışır,
crossover anını ayrıca aramaz — `Portfolio.apply_signal` zaten tekrarlanan
aynı yöndeki sinyali no-op geçtiği için bu güvenlidir.
"""
from __future__ import annotations

import pandas as pd

from omnitrade.strategies.base import Action, Signal, Strategy


def stochastic_oscillator(
    high: pd.Series, low: pd.Series, close: pd.Series,
    k_period: int = 14, d_period: int = 3,
) -> tuple[pd.Series, pd.Series]:
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    denom = highest_high - lowest_low

    # Kenar durum: son N mumda hiç hareket yoksa (highest_high == lowest_low,
    # örn. tamamen yatay/sabit fiyat) 0/0 belirsizdir — RSI'deki "both_zero"
    # ele alışıyla aynı gerekçeyle burada da %K'yı nötr (50) sabitliyoruz,
    # yanlışlıkla 0 (aşırı satım) ya da NaN üretmesin diye.
    percent_k = 100 * (close - lowest_low) / denom.replace(0, float("nan"))
    percent_k = percent_k.where(denom != 0, 50.0)
    percent_d = percent_k.rolling(d_period).mean()
    return percent_k, percent_d


class StochasticStrategy(Strategy):
    name = "StochasticStrategy"

    def __init__(self, k_period: int = 14, d_period: int = 3, oversold: float = 20, overbought: float = 80):
        if oversold >= overbought:
            raise ValueError("oversold, overbought'tan küçük olmalı")
        self.k_period = k_period
        self.d_period = d_period
        self.oversold = oversold
        self.overbought = overbought

    def required_candles(self) -> int:
        return self.k_period + self.d_period + 5

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        if len(df) < self.required_candles():
            return Signal(Action.HOLD, symbol, reason="yetersiz veri")

        _, percent_d = stochastic_oscillator(
            df["high"], df["low"], df["close"], self.k_period, self.d_period
        )
        last_d = percent_d.iloc[-1]

        if pd.isna(last_d):
            return Signal(Action.HOLD, symbol, reason="yetersiz veri")

        if last_d < self.oversold:
            return Signal(Action.BUY, symbol, reason=f"%D={last_d:.1f} < {self.oversold} (aşırı satım)")
        if last_d > self.overbought:
            return Signal(Action.SELL, symbol, reason=f"%D={last_d:.1f} > {self.overbought} (aşırı alım)")
        return Signal(Action.HOLD, symbol, reason=f"%D={last_d:.1f}")
