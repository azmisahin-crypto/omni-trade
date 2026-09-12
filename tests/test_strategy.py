import unittest

import pandas as pd

from omnitrade.strategies.base import Action
from omnitrade.strategies.rsi_strategy import RsiStrategy
from omnitrade.strategies.macd_strategy import MacdStrategy
from omnitrade.strategies.bollinger_strategy import BollingerStrategy
from omnitrade.strategies import list_strategies


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


class TestMacdStrategy(unittest.TestCase):
    def test_hold_when_not_enough_data(self):
        strat = MacdStrategy()
        df = make_df([100.0] * 10)
        signal = strat.generate_signal(df, "BTC/USDT")
        self.assertEqual(signal.action, Action.HOLD)

    def test_invalid_periods_raise(self):
        with self.assertRaises(ValueError):
            MacdStrategy(fast=26, slow=12)

    def test_buy_signal_on_sustained_uptrend(self):
        strat = MacdStrategy(fast=12, slow=26, signal_period=9)
        closes = [100 + i * 0.5 for i in range(60)]  # sürekli yükseliş
        df = make_df(closes)
        signal = strat.generate_signal(df, "BTC/USDT")
        self.assertEqual(signal.action, Action.BUY)

    def test_sell_signal_on_sustained_downtrend(self):
        strat = MacdStrategy(fast=12, slow=26, signal_period=9)
        closes = [100 - i * 0.5 for i in range(60)]  # sürekli düşüş
        df = make_df(closes)
        signal = strat.generate_signal(df, "BTC/USDT")
        self.assertEqual(signal.action, Action.SELL)


class TestBollingerStrategy(unittest.TestCase):
    def test_hold_when_not_enough_data(self):
        strat = BollingerStrategy(period=20)
        df = make_df([100.0] * 5)
        signal = strat.generate_signal(df, "BTC/USDT")
        self.assertEqual(signal.action, Action.HOLD)

    def test_hold_when_price_inside_bands(self):
        strat = BollingerStrategy(period=20, num_std=2.0)
        df = make_df([100.0] * 30)  # sabit fiyat -> std=0 -> bantlar ortalamada
        signal = strat.generate_signal(df, "BTC/USDT")
        self.assertEqual(signal.action, Action.HOLD)

    def test_buy_signal_when_price_drops_below_lower_band(self):
        strat = BollingerStrategy(period=20, num_std=2.0)
        closes = [100.0] * 25 + [80.0]  # ani düşüş -> alt bandın altına iner
        df = make_df(closes)
        signal = strat.generate_signal(df, "BTC/USDT")
        self.assertEqual(signal.action, Action.BUY)

    def test_sell_signal_when_price_rises_above_upper_band(self):
        strat = BollingerStrategy(period=20, num_std=2.0)
        closes = [100.0] * 25 + [120.0]  # ani yükseliş -> üst bandın üstüne çıkar
        df = make_df(closes)
        signal = strat.generate_signal(df, "BTC/USDT")
        self.assertEqual(signal.action, Action.SELL)


class TestListStrategies(unittest.TestCase):
    def test_returns_every_registered_strategy_with_defaults(self):
        schemas = list_strategies()
        by_name = {s["name"]: s for s in schemas}
        self.assertIn("RsiStrategy", by_name)
        self.assertIn("MacdStrategy", by_name)
        self.assertIn("BollingerStrategy", by_name)

        rsi_params = {p["name"]: p["default"] for p in by_name["RsiStrategy"]["params"]}
        self.assertEqual(rsi_params, {"period": 14, "oversold": 30, "overbought": 70})


if __name__ == "__main__":
    unittest.main()
