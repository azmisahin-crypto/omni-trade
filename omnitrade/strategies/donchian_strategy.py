"""Donchian Channel breakout (trend-takip) stratejisi.

Klasik "Turtle Trading" sisteminin çekirdeği: kapanış, SON N mumun en
yükseğini (kendisi hariç) yukarı kırarsa BUY (yeni bir yükseliş trendinin
başlangıcı olarak yorumlanır), en düşüğünü aşağı kırarsa SELL. Bu,
BollingerStrategy'nin TAM TERSİ bir felsefe: Bollinger bandın DIŞINA
çıkışı "aşırılık, geri dönecek" (mean-reversion) diye okurken, Donchian
AYNI kırılımı "yeni bir trend başlıyor, takip et" (breakout/momentum)
diye okur — aynı ham olayın iki zıt yorumu, bu yüzden ikisini yan yana
backtest etmek özellikle öğretici.

`shift(1)` ile kanal KASITLI olarak "bu mum HARİÇ önceki N mum"dan
hesaplanır — mumun kendi high/low'u kanala dahil edilseydi, close hiçbir
zaman kendi mumunun high'ını AŞAMAZDI (close <= high her zaman doğru),
yani breakout hiç tetiklenemezdi.
"""
from __future__ import annotations

import pandas as pd

from omnitrade.strategies.base import Action, Signal, Strategy


def donchian_channel(high: pd.Series, low: pd.Series, period: int = 20) -> tuple[pd.Series, pd.Series]:
    upper = high.rolling(period).max().shift(1)
    lower = low.rolling(period).min().shift(1)
    return upper, lower


class DonchianStrategy(Strategy):
    name = "DonchianStrategy"

    def __init__(self, period: int = 20):
        self.period = period

    def required_candles(self) -> int:
        # shift(1) bir mumluk ek gecikme ekliyor, üstüne biraz pay.
        return self.period + 6

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        if len(df) < self.required_candles():
            return Signal(Action.HOLD, symbol, reason="yetersiz veri")

        upper, lower = donchian_channel(df["high"], df["low"], self.period)
        last_close = df["close"].iloc[-1]
        last_upper = upper.iloc[-1]
        last_lower = lower.iloc[-1]

        if pd.isna(last_upper) or pd.isna(last_lower):
            return Signal(Action.HOLD, symbol, reason="yetersiz veri")

        if last_close > last_upper:
            return Signal(
                Action.BUY, symbol,
                reason=f"fiyat={last_close:.4f} > {self.period}mum kanal üstü={last_upper:.4f} (breakout)",
            )
        if last_close < last_lower:
            return Signal(
                Action.SELL, symbol,
                reason=f"fiyat={last_close:.4f} < {self.period}mum kanal altı={last_lower:.4f} (breakdown)",
            )
        return Signal(
            Action.HOLD, symbol,
            reason=f"fiyat={last_close:.4f} kanal içinde ({last_lower:.4f}-{last_upper:.4f})",
        )
