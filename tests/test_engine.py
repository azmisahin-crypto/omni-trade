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


class TestRunOnceOnlyNotifiesOnRealTrade(unittest.TestCase):
    """Bug düzeltmesi: RsiStrategy pozisyondan bağımsız olarak RSI>70 iken
    her zaman SELL üretir. Elde pozisyon yokken bu sinyal hiçbir işlem
    yapmaz — ama düzeltmeden önce run_once yine de Telegram'a "sell"
    bildirimi gönderiyordu. Bu test, gerçek işlem olmadan bildirim
    gitmediğini doğrular."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    @patch("omnitrade.engine.ExchangeClient")
    def test_sell_signal_without_position_sends_no_telegram_alert(self, mock_exchange_cls):
        from omnitrade.engine import TradingEngine
        from omnitrade.strategies.base import Action, Signal

        config = _make_config(self._tmpdir.name, dry_run=True)
        engine = TradingEngine(config)
        engine.strategy = _StubStrategy(Action.SELL)  # her zaman SELL üretir
        mock_exchange_cls.return_value.fetch_ohlcv_df.return_value = _flat_df()

        with patch.object(engine.notifier, "trade_alert") as mock_alert:
            engine.run_once()

        mock_alert.assert_not_called()
        self.assertEqual(engine.storage.get_trades(limit=10), [])

    @patch("omnitrade.engine.ExchangeClient")
    def test_buy_signal_sends_telegram_alert(self, mock_exchange_cls):
        from omnitrade.engine import TradingEngine
        from omnitrade.strategies.base import Action

        config = _make_config(self._tmpdir.name, dry_run=True)
        engine = TradingEngine(config)
        engine.strategy = _StubStrategy(Action.BUY)
        mock_exchange_cls.return_value.fetch_ohlcv_df.return_value = _flat_df()

        with patch.object(engine.notifier, "trade_alert") as mock_alert:
            engine.run_once()

        mock_alert.assert_called_once()


def _flat_df() -> pd.DataFrame:
    closes = [100.0] * 30
    return pd.DataFrame({
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": [1.0] * len(closes),
    })


class _StubStrategy:
    def __init__(self, action):
        from omnitrade.strategies.base import Signal
        self._action = action
        self._Signal = Signal

    def required_candles(self) -> int:
        return 1

    def generate_signal(self, df, symbol):
        return self._Signal(self._action, symbol, reason="stub")


if __name__ == "__main__":
    unittest.main()
