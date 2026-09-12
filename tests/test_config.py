import os
import tempfile
import unittest
from pathlib import Path

from omnitrade.config import load_config, normalize_pair, update_pair_strategies, update_pairs


class TestLoadConfig(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp = Path(self._tmpdir.name)

    def _write(self, name: str, content: str) -> str:
        path = self.tmp / name
        path.write_text(content)
        return str(path)

    def test_defaults_when_config_file_missing(self):
        cfg = load_config(
            config_path=str(self.tmp / "does_not_exist.yaml"),
            env_path=str(self.tmp / "does_not_exist.env"),
        )
        self.assertTrue(cfg.dry_run)
        self.assertEqual(cfg.dry_run_wallet, 1000.0)
        self.assertEqual(cfg.strategy, "RsiStrategy")
        self.assertEqual(cfg.pairs, ["BTC/USDT"])
        self.assertFalse(cfg.live_trading_confirmed)

    def test_risk_section_is_parsed(self):
        config_path = self._write(
            "config.yaml",
            """
risk:
  max_position_pct: 0.1
  max_open_positions: 3
  stop_loss_pct: 0.02
  take_profit_pct: 0.08
  max_daily_loss_pct: 0.05
""",
        )
        cfg = load_config(config_path=config_path, env_path=str(self.tmp / "no.env"))
        self.assertEqual(cfg.risk.max_position_pct, 0.1)
        self.assertEqual(cfg.risk.max_open_positions, 3)
        self.assertEqual(cfg.risk.stop_loss_pct, 0.02)
        self.assertEqual(cfg.risk.take_profit_pct, 0.08)
        self.assertEqual(cfg.risk.max_daily_loss_pct, 0.05)

    def test_take_profit_pct_none_when_blank(self):
        config_path = self._write(
            "config.yaml",
            """
risk:
  take_profit_pct:
""",
        )
        cfg = load_config(config_path=config_path, env_path=str(self.tmp / "no.env"))
        self.assertIsNone(cfg.risk.take_profit_pct)

    def test_fee_and_slippage_and_strategy_params_are_parsed(self):
        config_path = self._write(
            "config.yaml",
            """
fee_pct: 0.002
slippage_pct: 0.001
strategy: RsiStrategy
strategy_params:
  period: 21
  oversold: 25
  overbought: 75
""",
        )
        cfg = load_config(config_path=config_path, env_path=str(self.tmp / "no.env"))
        self.assertEqual(cfg.fee_pct, 0.002)
        self.assertEqual(cfg.slippage_pct, 0.001)
        self.assertEqual(cfg.strategy_params, {"period": 21, "oversold": 25, "overbought": 75})

    def test_live_trading_confirmed_defaults_false_and_can_be_enabled(self):
        config_path = self._write("config.yaml", "live_trading_confirmed: true\n")
        cfg = load_config(config_path=config_path, env_path=str(self.tmp / "no.env"))
        self.assertTrue(cfg.live_trading_confirmed)

    def test_env_overrides_take_precedence_over_yaml_secrets(self):
        # Sırlar (token/api key) .env'den okunur, config.yaml'da olsa bile
        # .env'deki değer öncelikli olmalı (config.py'nin belgelenen davranışı).
        config_path = self._write(
            "config.yaml",
            """
telegram:
  enabled: true
  token: yaml-token
  chat_id: yaml-chat
exchange:
  name: binance
  api_key: yaml-key
  api_secret: yaml-secret
""",
        )
        env_path = self._write(
            ".env",
            "TELEGRAM_TOKEN=env-token\nTELEGRAM_CHAT_ID=env-chat\n"
            "EXCHANGE_KEY=env-key\nEXCHANGE_SECRET=env-secret\n",
        )
        for var in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "EXCHANGE_KEY", "EXCHANGE_SECRET"):
            os.environ.pop(var, None)
        self.addCleanup(lambda: [os.environ.pop(v, None) for v in (
            "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "EXCHANGE_KEY", "EXCHANGE_SECRET")])

        cfg = load_config(config_path=config_path, env_path=env_path)
        self.assertEqual(cfg.telegram.token, "env-token")
        self.assertEqual(cfg.telegram.chat_id, "env-chat")
        self.assertEqual(cfg.exchange.api_key, "env-key")
        self.assertEqual(cfg.exchange.api_secret, "env-secret")

    def test_pairs_list_is_parsed(self):
        config_path = self._write("config.yaml", "pairs:\n  - BTC/USDT\n  - ETH/USDT\n")
        cfg = load_config(config_path=config_path, env_path=str(self.tmp / "no.env"))
        self.assertEqual(cfg.pairs, ["BTC/USDT", "ETH/USDT"])

    def test_config_path_is_recorded_on_the_config_object(self):
        config_path = self._write("config.yaml", "pairs:\n  - BTC/USDT\n")
        cfg = load_config(config_path=config_path, env_path=str(self.tmp / "no.env"))
        self.assertEqual(cfg.config_path, config_path)


class TestNormalizePair(unittest.TestCase):
    def test_valid_pair_is_uppercased(self):
        self.assertEqual(normalize_pair("btc/usdt"), "BTC/USDT")
        self.assertEqual(normalize_pair("  SOL/USDT  "), "SOL/USDT")

    def test_missing_slash_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_pair("BTCUSDT")

    def test_empty_or_garbage_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_pair("")
        with self.assertRaises(ValueError):
            normalize_pair("BTC/USD/T")
        with self.assertRaises(ValueError):
            normalize_pair("B/USDT")  # baz tarafı çok kısa


class TestUpdatePairs(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp = Path(self._tmpdir.name)

    def test_replaces_pairs_block_and_preserves_rest_of_file(self):
        config_path = self.tmp / "config.yaml"
        config_path.write_text(
            "dry_run: true\n"
            "\n"
            "pairs:\n"
            "  - BTC/USDT\n"
            "  - ETH/USDT\n"
            "\n"
            "strategy: RsiStrategy  # bir yorum\n"
        )
        update_pairs(str(config_path), ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
        text = config_path.read_text()
        self.assertIn("dry_run: true", text)
        self.assertIn("strategy: RsiStrategy  # bir yorum", text)
        self.assertIn("pairs:\n  - BTC/USDT\n  - ETH/USDT\n  - SOL/USDT\n", text)

        cfg = load_config(config_path=str(config_path), env_path=str(self.tmp / "no.env"))
        self.assertEqual(cfg.pairs, ["BTC/USDT", "ETH/USDT", "SOL/USDT"])

    def test_removing_a_pair_updates_the_block(self):
        config_path = self.tmp / "config.yaml"
        config_path.write_text("pairs:\n  - BTC/USDT\n  - ETH/USDT\n  - SOL/USDT\n")
        update_pairs(str(config_path), ["BTC/USDT", "SOL/USDT"])
        cfg = load_config(config_path=str(config_path), env_path=str(self.tmp / "no.env"))
        self.assertEqual(cfg.pairs, ["BTC/USDT", "SOL/USDT"])

    def test_appends_pairs_block_when_missing_from_file(self):
        config_path = self.tmp / "config.yaml"
        config_path.write_text("dry_run: true\n")
        update_pairs(str(config_path), ["BTC/USDT"])
        cfg = load_config(config_path=str(config_path), env_path=str(self.tmp / "no.env"))
        self.assertEqual(cfg.pairs, ["BTC/USDT"])
        self.assertIn("dry_run: true", config_path.read_text())


class TestUpdatePairStrategies(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp = Path(self._tmpdir.name)

    def test_replaces_empty_dict_block_and_preserves_comments_above(self):
        config_path = self.tmp / "config.yaml"
        config_path.write_text(
            "# Örnek (varsayılan olarak devre dışı, kopyala/aç):\n"
            "# pair_strategies:\n"
            "#   ETH/USDT:\n"
            "#     strategy: RsiStrategy\n"
            "pair_strategies: {}\n"
            "\n"
            "fee_pct: 0.001\n"
        )
        update_pair_strategies(str(config_path), {
            "ETH/USDT": {"strategy": "RsiStrategy", "params": {"period": 21}},
        })
        text = config_path.read_text()
        self.assertIn("# Örnek (varsayılan olarak devre dışı, kopyala/aç):", text)
        self.assertIn("fee_pct: 0.001", text)
        self.assertIn("pair_strategies:\n  ETH/USDT:\n    strategy: RsiStrategy\n    params:\n      period: 21\n", text)

        cfg = load_config(config_path=str(config_path), env_path=str(self.tmp / "no.env"))
        self.assertEqual(cfg.pair_strategies, {"ETH/USDT": {"strategy": "RsiStrategy", "params": {"period": 21}}})

    def test_replaces_nested_block_back_to_empty_dict(self):
        config_path = self.tmp / "config.yaml"
        config_path.write_text(
            "pair_strategies:\n"
            "  ETH/USDT:\n"
            "    strategy: RsiStrategy\n"
            "    params:\n"
            "      period: 21\n"
            "\n"
            "fee_pct: 0.001\n"
        )
        update_pair_strategies(str(config_path), {})
        text = config_path.read_text()
        self.assertIn("pair_strategies: {}\n", text)
        self.assertIn("fee_pct: 0.001", text)
        self.assertNotIn("ETH/USDT", text)

    def test_appends_block_when_missing_from_file(self):
        config_path = self.tmp / "config.yaml"
        config_path.write_text("dry_run: true\n")
        update_pair_strategies(str(config_path), {"BTC/USDT": {"strategy": "MacdStrategy", "params": {}}})
        cfg = load_config(config_path=str(config_path), env_path=str(self.tmp / "no.env"))
        self.assertEqual(cfg.pair_strategies, {"BTC/USDT": {"strategy": "MacdStrategy", "params": {}}})
        self.assertIn("dry_run: true", config_path.read_text())


if __name__ == "__main__":
    unittest.main()
