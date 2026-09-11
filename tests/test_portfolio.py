import tempfile
import unittest
from pathlib import Path

from omnitrade.portfolio import Portfolio
from omnitrade.storage import Storage
from omnitrade.strategies.base import Action, Signal


class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "test.db")
        self.storage = Storage(self.db_path)
        self.portfolio = Portfolio(self.storage, starting_balance=1000.0, stake_fraction=0.5)

    def tearDown(self):
        self.storage.close()
        self.tmpdir.cleanup()

    def test_buy_reduces_cash_and_opens_position(self):
        self.portfolio.apply_signal(Signal(Action.BUY, "BTC/USDT"), price=100.0)
        self.assertIn("BTC/USDT", self.portfolio.positions)
        self.assertAlmostEqual(self.portfolio.balance, 500.0)
        self.assertAlmostEqual(self.portfolio.positions["BTC/USDT"].qty, 5.0)

    def test_sell_closes_position_and_returns_cash(self):
        self.portfolio.apply_signal(Signal(Action.BUY, "BTC/USDT"), price=100.0)
        self.portfolio.apply_signal(Signal(Action.SELL, "BTC/USDT"), price=120.0)
        self.assertNotIn("BTC/USDT", self.portfolio.positions)
        # 500 kaldı + 5 * 120 = 1100 -> kâr etmiş olmalı
        self.assertAlmostEqual(self.portfolio.balance, 1100.0)

    def test_trades_are_logged(self):
        self.portfolio.apply_signal(Signal(Action.BUY, "BTC/USDT", reason="test"), price=100.0)
        trades = self.storage.get_trades()
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["action"], "buy")

    def test_equity_reflects_open_position_value(self):
        self.portfolio.apply_signal(Signal(Action.BUY, "BTC/USDT"), price=100.0)
        equity = self.portfolio.equity({"BTC/USDT": 150.0})
        # 500 nakit + 5 * 150 = 1250
        self.assertAlmostEqual(equity, 1250.0)


if __name__ == "__main__":
    unittest.main()
