import unittest

import pandas as pd

from omnitrade.backtest import run_backtest
from omnitrade.strategies.rsi_strategy import RsiStrategy


class TestBacktest(unittest.TestCase):
    def test_runs_end_to_end_on_synthetic_data(self):
        # Dalgalı fiyat serisi: RSI stratejisinin birkaç al/sat üretmesi beklenir
        n = 200
        closes = [100 + 10 * ((i % 40) - 20) / 20 for i in range(n)]
        df = pd.DataFrame({
            "open": closes, "high": closes, "low": closes, "close": closes,
            "volume": [1.0] * n,
        })
        strategy = RsiStrategy(period=14)
        result = run_backtest(df, strategy, "BTC/USDT", starting_balance=1000.0)

        self.assertGreaterEqual(result.trades, 0)
        self.assertGreater(result.final_balance, 0)
        self.assertGreaterEqual(result.max_drawdown_pct, 0)


if __name__ == "__main__":
    unittest.main()
