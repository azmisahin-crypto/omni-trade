import unittest

from omnitrade.stats import compute_drawdown_curve, compute_summary_stats


class TestComputeDrawdownCurve(unittest.TestCase):
    def test_no_drawdown_when_monotonically_increasing(self):
        curve = [{"ts": 1, "balance": 100}, {"ts": 2, "balance": 110}, {"ts": 3, "balance": 120}]
        dd = compute_drawdown_curve(curve)
        self.assertTrue(all(d["drawdown_pct"] == 0 for d in dd))

    def test_drawdown_measured_from_running_peak(self):
        curve = [{"ts": 1, "balance": 100}, {"ts": 2, "balance": 150}, {"ts": 3, "balance": 120}]
        dd = compute_drawdown_curve(curve)
        # peak 150'ye göre 120 -> %20 drawdown
        self.assertAlmostEqual(dd[2]["drawdown_pct"], 20.0)


class TestComputeSummaryStats(unittest.TestCase):
    def test_empty_equity_curve_returns_zeros(self):
        stats = compute_summary_stats(trades=[], equity_curve=[])
        self.assertEqual(stats.total_return_pct, 0.0)
        self.assertEqual(stats.trade_count, 0)

    def test_total_return_from_first_and_last_equity_point(self):
        equity = [{"ts": 1, "balance": 1000}, {"ts": 2, "balance": 1100}]
        stats = compute_summary_stats(trades=[], equity_curve=equity)
        self.assertAlmostEqual(stats.total_return_pct, 10.0)

    def test_win_rate_pairs_buy_then_sell_per_symbol(self):
        trades = [
            {"ts": 1, "symbol": "BTC/USDT", "action": "buy", "price": 100},
            {"ts": 2, "symbol": "BTC/USDT", "action": "sell", "price": 110},  # kazanan
            {"ts": 3, "symbol": "ETH/USDT", "action": "buy", "price": 10},
            {"ts": 4, "symbol": "ETH/USDT", "action": "sell", "price": 9},   # kaybeden
        ]
        equity = [{"ts": 1, "balance": 1000}, {"ts": 4, "balance": 1005}]
        stats = compute_summary_stats(trades, equity)
        self.assertEqual(stats.trade_count, 2)
        self.assertAlmostEqual(stats.win_rate, 0.5)

    def test_blocked_trades_are_ignored_in_win_rate(self):
        trades = [
            {"ts": 1, "symbol": "BTC/USDT", "action": "buy_blocked", "price": 100},
            {"ts": 2, "symbol": "BTC/USDT", "action": "buy", "price": 100},
            {"ts": 3, "symbol": "BTC/USDT", "action": "sell", "price": 105},
        ]
        equity = [{"ts": 1, "balance": 1000}, {"ts": 3, "balance": 1005}]
        stats = compute_summary_stats(trades, equity)
        self.assertEqual(stats.trade_count, 1)
        self.assertAlmostEqual(stats.win_rate, 1.0)

    def test_max_drawdown_reported(self):
        equity = [{"ts": 1, "balance": 100}, {"ts": 2, "balance": 200}, {"ts": 3, "balance": 150}]
        stats = compute_summary_stats(trades=[], equity_curve=equity)
        self.assertAlmostEqual(stats.max_drawdown_pct, 25.0)


if __name__ == "__main__":
    unittest.main()
