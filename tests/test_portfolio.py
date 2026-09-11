import tempfile
import unittest
from pathlib import Path

from omnitrade.portfolio import Portfolio
from omnitrade.risk import RiskConfig
from omnitrade.storage import Storage
from omnitrade.strategies.base import Action, Signal


class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "test.db")
        self.storage = Storage(self.db_path)
        # fee/slippage sıfırlanmış: bu testlerde saf pozisyon mantığını izole ediyoruz.
        # Komisyon/slippage davranışı test_portfolio_costs.py'de ayrıca test ediliyor.
        risk = RiskConfig(max_position_pct=0.5, max_open_positions=5, stop_loss_pct=0.0)
        self.portfolio = Portfolio(
            self.storage, starting_balance=1000.0, risk_config=risk,
            fee_pct=0.0, slippage_pct=0.0,
        )

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


class TestPortfolioCosts(unittest.TestCase):
    """Komisyon ve slippage'ın gerçekten balance/qty'e yansıdığını doğrular."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "test.db")
        self.storage = Storage(self.db_path)
        risk = RiskConfig(max_position_pct=0.5, stop_loss_pct=0.0)
        self.portfolio = Portfolio(
            self.storage, starting_balance=1000.0, risk_config=risk,
            fee_pct=0.01, slippage_pct=0.01,
        )

    def tearDown(self):
        self.storage.close()
        self.tmpdir.cleanup()

    def test_buy_applies_slippage_and_fee(self):
        # stake = 500, fill_price = 100 * 1.01 = 101, qty = (500*0.99)/101
        self.portfolio.apply_signal(Signal(Action.BUY, "BTC/USDT"), price=100.0)
        pos = self.portfolio.positions["BTC/USDT"]
        self.assertAlmostEqual(pos.entry_price, 101.0)
        expected_qty = (500 * 0.99) / 101.0
        self.assertAlmostEqual(pos.qty, expected_qty)

    def test_sell_applies_slippage_and_fee_and_reduces_proceeds(self):
        self.portfolio.apply_signal(Signal(Action.BUY, "BTC/USDT"), price=100.0)
        qty = self.portfolio.positions["BTC/USDT"].qty
        self.portfolio.apply_signal(Signal(Action.SELL, "BTC/USDT"), price=100.0)
        # satış fill fiyatı 100 * 0.99 = 99, komisyon %1 daha düşer
        expected_proceeds = qty * 99.0 * 0.99
        self.assertAlmostEqual(self.portfolio.balance, 500.0 + expected_proceeds)


class TestPortfolioRisk(unittest.TestCase):
    """Risk yönetimi: max açık pozisyon, stop-loss/take-profit, günlük kill-switch."""

    def _make_portfolio(self, risk: RiskConfig, balance: float = 1000.0) -> Portfolio:
        storage = Storage(self.db_path)
        self.addCleanup(storage.close)
        return Portfolio(storage, starting_balance=balance, risk_config=risk, fee_pct=0.0, slippage_pct=0.0)

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_max_open_positions_blocks_new_buy(self):
        risk = RiskConfig(max_position_pct=0.1, max_open_positions=1, stop_loss_pct=0.0)
        p = self._make_portfolio(risk)
        p.apply_signal(Signal(Action.BUY, "BTC/USDT"), price=100.0)
        p.apply_signal(Signal(Action.BUY, "ETH/USDT"), price=100.0)
        self.assertNotIn("ETH/USDT", p.positions)
        self.assertIn("BTC/USDT", p.positions)

    def test_stop_loss_force_closes_position(self):
        risk = RiskConfig(max_position_pct=0.5, stop_loss_pct=0.05)
        p = self._make_portfolio(risk)
        p.apply_signal(Signal(Action.BUY, "BTC/USDT"), price=100.0)
        # fiyat %6 düştü -> stop-loss (%5) tetiklenmeli
        p.check_risk_exits({"BTC/USDT": 94.0})
        self.assertNotIn("BTC/USDT", p.positions)

    def test_take_profit_force_closes_position(self):
        risk = RiskConfig(max_position_pct=0.5, stop_loss_pct=0.0, take_profit_pct=0.1)
        p = self._make_portfolio(risk)
        p.apply_signal(Signal(Action.BUY, "BTC/USDT"), price=100.0)
        p.check_risk_exits({"BTC/USDT": 111.0})
        self.assertNotIn("BTC/USDT", p.positions)

    def test_no_exit_when_within_thresholds(self):
        risk = RiskConfig(max_position_pct=0.5, stop_loss_pct=0.05, take_profit_pct=0.1)
        p = self._make_portfolio(risk)
        p.apply_signal(Signal(Action.BUY, "BTC/USDT"), price=100.0)
        p.check_risk_exits({"BTC/USDT": 103.0})
        self.assertIn("BTC/USDT", p.positions)

    def test_daily_kill_switch_blocks_new_positions(self):
        risk = RiskConfig(max_position_pct=0.5, stop_loss_pct=0.0, max_daily_loss_pct=0.1)
        p = self._make_portfolio(risk, balance=1000.0)
        # Günlük baseline'ı elle 1000 olarak ayarla, sonra equity'yi %15 düşür
        p.risk.update_daily_baseline(1000.0, ts=0)
        p.risk.check_kill_switch(850.0)
        self.assertTrue(p.risk.kill_switch_active)

        p.apply_signal(Signal(Action.BUY, "BTC/USDT"), price=100.0)
        self.assertNotIn("BTC/USDT", p.positions)


class TestApplySignalReturnValue(unittest.TestCase):
    """Bug düzeltmesi: apply_signal artık gerçekten bir işlem olup
    olmadığını (bool) döndürüyor — engine.py bunu Telegram bildirimi
    göndermeden önce kontrol ediyor. Öncesinde pozisyon yokken gelen bir
    SELL sinyali hiçbir şey yapmıyordu AMA yine de "işlem yapıldı"
    bildirimi gidiyordu (bkz. CHANGELOG)."""

    def _make_portfolio(self, balance: float = 1000.0) -> Portfolio:
        storage = Storage(":memory:")
        return Portfolio(storage, balance, risk_config=RiskConfig(max_position_pct=0.5))

    def test_sell_without_open_position_returns_false_and_does_not_log(self):
        p = self._make_portfolio()
        executed = p.apply_signal(Signal(Action.SELL, "BTC/USDT", reason="RSI>70"), price=100.0)
        self.assertFalse(executed)
        self.assertEqual(p.storage.get_trades(limit=10), [])

    def test_successful_buy_returns_true(self):
        p = self._make_portfolio()
        executed = p.apply_signal(Signal(Action.BUY, "BTC/USDT"), price=100.0)
        self.assertTrue(executed)

    def test_successful_sell_returns_true(self):
        p = self._make_portfolio()
        p.apply_signal(Signal(Action.BUY, "BTC/USDT"), price=100.0)
        executed = p.apply_signal(Signal(Action.SELL, "BTC/USDT"), price=110.0)
        self.assertTrue(executed)

    def test_buy_when_already_holding_returns_false(self):
        p = self._make_portfolio()
        p.apply_signal(Signal(Action.BUY, "BTC/USDT"), price=100.0)
        executed = p.apply_signal(Signal(Action.BUY, "BTC/USDT"), price=105.0)
        self.assertFalse(executed)

    def test_blocked_buy_by_risk_engine_returns_false(self):
        risk = RiskConfig(max_position_pct=0.5, max_open_positions=0)
        p = Portfolio(Storage(":memory:"), 1000.0, risk_config=risk)
        executed = p.apply_signal(Signal(Action.BUY, "BTC/USDT"), price=100.0)
        self.assertFalse(executed)


if __name__ == "__main__":
    unittest.main()
