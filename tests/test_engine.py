import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from omnitrade.config import Config, ExchangeConfig, TelegramConfig
from omnitrade.risk import RiskConfig


def _make_config(tmp_dir: str, **overrides) -> Config:
    defaults = dict(
        dry_run=True,
        dry_run_wallet=1000.0,
        pairs=["BTC/USDT"],
        strategy="RsiStrategy",
        strategy_params={},
        db_path=str(Path(tmp_dir) / "test.db"),
        exchange=ExchangeConfig(name="binance"),
        telegram=TelegramConfig(enabled=False),
        risk=RiskConfig(max_position_pct=0.2),
        live_trading_confirmed=False,
    )
    defaults.update(overrides)
    return Config(**defaults)


class TestLiveOrderQty(unittest.TestCase):
    """`_live_order_qty` gerçek para hareket eden bir kod yolu — Faz 1'de
    hiç test edilmiyordu, buradaki testler `live_trading_confirmed`
    bayrağının fren görevini gerçekten yaptığını doğrular."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    @patch("omnitrade.engine.ExchangeClient")
    def test_raises_when_live_trading_not_confirmed(self, mock_exchange_cls):
        from omnitrade.engine import TradingEngine

        config = _make_config(self._tmpdir.name, live_trading_confirmed=False)
        engine = TradingEngine(config)
        with self.assertRaises(NotImplementedError):
            engine._live_order_qty("BTC/USDT", 100.0)

    @patch("omnitrade.engine.ExchangeClient")
    def test_computes_qty_from_risk_manager_when_confirmed(self, mock_exchange_cls):
        from omnitrade.engine import TradingEngine

        config = _make_config(
            self._tmpdir.name,
            live_trading_confirmed=True,
            dry_run_wallet=1000.0,
            risk=RiskConfig(max_position_pct=0.25),
        )
        engine = TradingEngine(config)
        qty = engine._live_order_qty("BTC/USDT", price=100.0)
        # stake = 1000 * 0.25 = 250, qty = 250 / 100 = 2.5
        self.assertAlmostEqual(qty, 2.5)

    @patch("omnitrade.engine.ExchangeClient")
    def test_apply_live_signal_does_not_call_exchange_when_not_confirmed(self, mock_exchange_cls):
        """`_apply_live_signal` bir BUY sinyali işlerken, onay yoksa
        NotImplementedError fırlatılmalı ve borsaya emir GÖNDERİLMEMELİ —
        yanlışlıkla canlı emir gitmesin diye bu davranış kritik."""
        from omnitrade.engine import TradingEngine
        from omnitrade.strategies.base import Action, Signal

        config = _make_config(self._tmpdir.name, dry_run=False, live_trading_confirmed=False)
        engine = TradingEngine(config)
        signal = Signal(Action.BUY, "BTC/USDT", reason="test")

        with self.assertRaises(NotImplementedError):
            engine._apply_live_signal(signal, price=100.0)

        engine.exchange.create_market_order.assert_not_called()

    @patch("omnitrade.engine.ExchangeClient")
    def test_apply_live_signal_calls_exchange_when_confirmed(self, mock_exchange_cls):
        from omnitrade.engine import TradingEngine
        from omnitrade.strategies.base import Action, Signal

        config = _make_config(self._tmpdir.name, dry_run=False, live_trading_confirmed=True)
        engine = TradingEngine(config)
        signal = Signal(Action.BUY, "BTC/USDT", reason="test")

        engine._apply_live_signal(signal, price=100.0)

        engine.exchange.create_market_order.assert_called_once()
        self.assertIn("BTC/USDT", engine._live_open_positions)


if __name__ == "__main__":
    unittest.main()
