import os
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
    def test_computes_qty_from_real_exchange_balance_when_confirmed(self, mock_exchange_cls):
        """Faz 5: stake artık `dry_run_wallet` DEĞİL, borsadan çekilen
        gerçek bakiyeye (`fetch_free_balance`) göre hesaplanır."""
        from omnitrade.engine import TradingEngine

        config = _make_config(
            self._tmpdir.name,
            live_trading_confirmed=True,
            dry_run_wallet=999999.0,  # bilerek farklı — kullanılmamalı
            stake_currency="USDT",
            risk=RiskConfig(max_position_pct=0.25),
        )
        engine = TradingEngine(config)
        engine.exchange.fetch_free_balance.return_value = 1000.0
        qty = engine._live_order_qty("BTC/USDT", price=100.0)
        # stake = 1000 (gerçek bakiye) * 0.25 = 250, qty = 250 / 100 = 2.5
        self.assertAlmostEqual(qty, 2.5)
        engine.exchange.fetch_free_balance.assert_called_once_with("USDT")

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
        engine.exchange.fetch_free_balance.return_value = 1000.0
        signal = Signal(Action.BUY, "BTC/USDT", reason="test")

        engine._apply_live_signal(signal, price=100.0)

        engine.exchange.create_market_order.assert_called_once()
        self.assertIn("BTC/USDT", engine._live_open_positions)


class TestPairStrategies(unittest.TestCase):
    """Faz 4: `pair_strategies` ile coin başına farklı strateji/parametre
    tanımlanabilmeli, tanımlanmayan pariteler varsayılan `strategy`'i
    kullanmaya devam etmeli."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    @patch("omnitrade.engine.ExchangeClient")
    def test_pair_without_override_uses_default_strategy(self, mock_exchange_cls):
        from omnitrade.engine import TradingEngine
        from omnitrade.strategies.rsi_strategy import RsiStrategy

        config = _make_config(
            self._tmpdir.name,
            pairs=["BTC/USDT", "ETH/USDT"],
            pair_strategies={"ETH/USDT": {"strategy": "RsiStrategy", "params": {"period": 21}}},
        )
        engine = TradingEngine(config)

        self.assertNotIn("BTC/USDT", engine.strategies)  # override yok -> varsayılan kullanılır
        self.assertIsInstance(engine.strategies["ETH/USDT"], RsiStrategy)
        self.assertEqual(engine.strategies["ETH/USDT"].period, 21)
        self.assertEqual(engine.strategy.period, 14)  # default RsiStrategy param

    @patch("omnitrade.engine.ExchangeClient")
    def test_run_once_uses_per_pair_strategy(self, mock_exchange_cls):
        from omnitrade.engine import TradingEngine
        from omnitrade.strategies.base import Action

        config = _make_config(
            self._tmpdir.name, dry_run=True, pairs=["BTC/USDT", "ETH/USDT"],
        )
        engine = TradingEngine(config)
        engine.strategy = _StubStrategy(Action.HOLD)
        engine.strategies = {"ETH/USDT": _StubStrategy(Action.BUY)}
        mock_exchange_cls.return_value.fetch_ohlcv_df.return_value = _flat_df()

        engine.run_once()

        latest = {s["symbol"]: s["action"] for s in engine.storage.get_latest_signals()}
        self.assertEqual(latest["BTC/USDT"], "hold")
        self.assertEqual(latest["ETH/USDT"], "buy")


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
        # Regresyon testi: Telegram "Miktar: 0.000000" bugu — trade_alert
        # önceden qty parametresini HER ZAMAN sabit 0.0 alıyordu (bkz.
        # portfolio.apply_signal'in artık qty de döndürmesi / engine.py fix).
        _, _, _, sent_qty, _ = mock_alert.call_args.args
        self.assertGreater(sent_qty, 0.0)


class TestConfigHotReload(unittest.TestCase):
    """Faz 13: config.yaml diskte değişince bot artık YENİDEN
    BAŞLATILMADAN, çalışırken bunu fark edip uyguluyor (bkz.
    engine.py::_reload_config_if_changed). Önceden (Faz 10/11) dashboard
    sadece dosyayı güncelliyordu, botun bunu görmesi için container'ın
    elle yeniden başlatılması gerekiyordu — bu testler o sürtünmenin artık
    olmadığını doğruluyor."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.config_path = str(Path(self._tmpdir.name) / "config.yaml")
        self.db_path = str(Path(self._tmpdir.name) / "test.db")
        self._write_yaml(pairs=["BTC/USDT"])

    def _write_yaml(self, **overrides) -> None:
        """Minimal ama gerçek bir config.yaml yazar (`load_config` ile
        okunacak) — mtime'ın gerçekten ilerlediğinden emin olmak için
        dosyayı yazdıktan sonra mtime'ı bilinçli olarak ileri alıyoruz;
        aksi halde bazı dosya sistemlerinin saniye altı çözünürlüğü testi
        (yanlışlıkla "değişmedi" sanıp) kırılgan yapabilirdi.
        """
        raw = {
            "dry_run": overrides.get("dry_run", True),
            "dry_run_wallet": 1000.0,
            "pairs": overrides.get("pairs", ["BTC/USDT"]),
            "strategy": overrides.get("strategy", "RsiStrategy"),
            "strategy_params": overrides.get("strategy_params", {}),
            "pair_strategies": overrides.get("pair_strategies", {}),
            "db_path": self.db_path,
            "risk": overrides.get("risk", {}),
        }
        import yaml
        Path(self.config_path).write_text(yaml.safe_dump(raw))
        self._bump_mtime()

    def _bump_mtime(self) -> None:
        current = Path(self.config_path).stat().st_mtime
        future = current + 5
        os.utime(self.config_path, (future, future))

    def _make_engine(self, **overrides):
        from omnitrade.engine import TradingEngine
        config = _make_config(self._tmpdir.name, config_path=self.config_path, **overrides)
        return TradingEngine(config)

    @patch("omnitrade.engine.ExchangeClient")
    def test_new_pair_added_to_file_is_picked_up_without_restart(self, mock_exchange_cls):
        engine = self._make_engine(pairs=["BTC/USDT"])
        mock_exchange_cls.return_value.fetch_ohlcv_df.return_value = _flat_df()

        engine.run_once()  # ilk çağrı: sadece referans mtime'ı kullanır, değişiklik yok
        self.assertEqual(engine.config.pairs, ["BTC/USDT"])

        self._write_yaml(pairs=["BTC/USDT", "ETH/USDT"])
        engine.run_once()

        self.assertEqual(engine.config.pairs, ["BTC/USDT", "ETH/USDT"])
        latest_symbols = {s["symbol"] for s in engine.storage.get_latest_signals()}
        self.assertIn("ETH/USDT", latest_symbols)  # yeni coin gerçekten döngüye dahil oldu

    @patch("omnitrade.engine.ExchangeClient")
    def test_pair_strategy_override_hot_reloads(self, mock_exchange_cls):
        from omnitrade.strategies.rsi_strategy import RsiStrategy

        engine = self._make_engine(pairs=["BTC/USDT", "ETH/USDT"])
        mock_exchange_cls.return_value.fetch_ohlcv_df.return_value = _flat_df()
        engine.run_once()
        self.assertNotIn("ETH/USDT", engine.strategies)

        self._write_yaml(
            pairs=["BTC/USDT", "ETH/USDT"],
            pair_strategies={"ETH/USDT": {"strategy": "RsiStrategy", "params": {"period": 21}}},
        )
        engine.run_once()

        self.assertIsInstance(engine.strategies["ETH/USDT"], RsiStrategy)
        self.assertEqual(engine.strategies["ETH/USDT"].period, 21)

    @patch("omnitrade.engine.ExchangeClient")
    def test_restart_only_field_change_is_not_applied_but_warns(self, mock_exchange_cls):
        engine = self._make_engine(pairs=["BTC/USDT"], dry_run=True)
        mock_exchange_cls.return_value.fetch_ohlcv_df.return_value = _flat_df()
        engine.run_once()

        self._write_yaml(pairs=["BTC/USDT"], dry_run=False)
        with patch.object(engine.notifier, "system_alert") as mock_alert:
            engine.run_once()

        # dry_run restart-only bir alan: dosyada değişse de çalışan
        # nesnede uygulanmaz (Portfolio hâlâ mevcut olmalı) — sadece uyarı verilir.
        self.assertTrue(engine.config.dry_run)
        self.assertIsNotNone(engine.portfolio)
        # dry_run gerçekten uygulanmadı diye bir uyarı verilmiş olmalı
        # (aynı reload'da başka hot-reloadable alan yoksa tek çağrı olurdu;
        # burada sadece uyarının GERÇEKTEN gittiğini doğruluyoruz).
        warning_calls = [c for c in mock_alert.call_args_list if "dry_run" in c.args[0]]
        self.assertEqual(len(warning_calls), 1)

    @patch("omnitrade.engine.ExchangeClient")
    def test_kill_switch_state_survives_reload(self, mock_exchange_cls):
        """RiskManager'ın kill-switch/günlük başlangıç equity durumu, config
        reload sırasında nesne YENİDEN YARATILMADIĞI için korunmalı —
        aksi halde alakasız bir config değişikliği (örn. yeni coin) aktif
        bir kill-switch'i yanlışlıkla sıfırlayıp yeni pozisyon açılmasına
        izin verebilirdi."""
        engine = self._make_engine(pairs=["BTC/USDT"])
        mock_exchange_cls.return_value.fetch_ohlcv_df.return_value = _flat_df()
        engine.run_once()

        engine.portfolio.risk.update_daily_baseline(1000.0)
        engine.portfolio.risk.check_kill_switch(current_equity=1.0)  # %99+ kayıp -> kill-switch
        self.assertTrue(engine.portfolio.risk.kill_switch_active)

        self._write_yaml(pairs=["BTC/USDT", "ETH/USDT"])
        engine.run_once()

        self.assertTrue(engine.portfolio.risk.kill_switch_active)  # korunmuş olmalı


def _flat_df() -> pd.DataFrame:
    closes = [100.0] * 30
    return pd.DataFrame({
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": [1.0] * len(closes),
    })


class _StubStrategy:
    name = "StubStrategy"

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
