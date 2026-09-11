import unittest

import pandas as pd

from omnitrade.strategies.base import Action
from omnitrade.strategies.rsi_strategy import RsiStrategy


def make_df(closes):
    return pd.DataFrame({
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": [1.0] * len(closes),
    })


class TestRsiStrategy(unittest.TestCase):
    def test_hold_when_not_enough_data(self):
        strat = RsiStrategy(period=14)
        df = make_df([100.0] * 5)
        signal = strat.generate_signal(df, "BTC/USDT")
        self.assertEqual(signal.action, Action.HOLD)

    def test_buy_signal_on_sustained_drop(self):
        strat = RsiStrategy(period=14, oversold=30, overbought=70)
        closes = [100 - i for i in range(30)]  # sürekli düşüş -> düşük RSI
        df = make_df(closes)
        signal = strat.generate_signal(df, "BTC/USDT")
        self.assertEqual(signal.action, Action.BUY)

    def test_sell_signal_on_sustained_rise(self):
        strat = RsiStrategy(period=14, oversold=30, overbought=70)
        closes = [100 + i for i in range(30)]  # sürekli yükseliş -> yüksek RSI
        df = make_df(closes)
        signal = strat.generate_signal(df, "BTC/USDT")
        self.assertEqual(signal.action, Action.SELL)

    def test_flat_price_does_not_produce_false_buy_signal(self):
        """Regresyon testi: fiyat tamamen sabitken avg_gain=0 ve avg_loss=0
        olur (0/0 belirsizliği). Eski implementasyon bunu RSI=0 olarak
        yorumlayıp sahte bir 'aşırı satım' BUY sinyali üretiyordu. RSI
        hareket yokken nötr (50) olmalı, dolayısıyla HOLD dönmeli."""
        strat = RsiStrategy(period=14, oversold=30, overbought=70)
        df = make_df([100.0] * 30)
        signal = strat.generate_signal(df, "BTC/USDT")
        self.assertEqual(signal.action, Action.HOLD)


if __name__ == "__main__":
    unittest.main()
