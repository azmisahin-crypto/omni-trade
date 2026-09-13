"""omnitrade/web/server.py için testler.

Önceden bu dosya için hiç test yoktu (stdlib http.server ile elle test
etmek zahmetli görünüp atlanmıştı). Backtest'i dashboard'a taşıyan Faz 6
ile birlikte hem yeni /api/backtest hem de var olan GET endpoint'leri
için temel kapsama ekleniyor — gerçek bir HTTP sunucusu ayrı bir thread'de
ayağa kaldırılıp gerçek istekler atılıyor (mock request/response değil),
çünkü stdlib http.server'ın kendi routing/parsing davranışı da test
edilmiş oluyor.
"""
from __future__ import annotations

import base64
import json
import tempfile
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pandas as pd

from omnitrade.config import Config, WebAuthConfig
from omnitrade.storage import Storage
from omnitrade.web.server import _diff_fingerprint, make_handler


def _wavy_df(n: int = 300, amplitude: float = 10.0, base: float = 100.0) -> pd.DataFrame:
    closes = [base + amplitude * ((i % 40) - 20) / 20 for i in range(n)]
    return pd.DataFrame({
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": [1.0] * n,
    })


class ServerTestBase(unittest.TestCase):
    """Her testte in-memory storage + ThreadingHTTPServer'ı gerçek (rastgele)
    bir portta ayağa kaldırıp testin sonunda düzgünce kapatır."""

    def setUp(self):
        self.storage = Storage(":memory:")
        self.config = Config()
        handler = make_handler(self.storage, self.config)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        # Faz 17: /api/stream testleri uzun ömürlü SSE bağlantıları açıyor;
        # `daemon_threads` olmadan `server_close()` bu thread'in doğal
        # bitişini bekleyip nadir bir yarış durumunda testi asabilir.
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.storage.close()

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _get_json(self, path: str):
        with urlopen(self._url(path), timeout=5) as resp:
            return json.loads(resp.read())

    def _post_json(self, path: str, body: dict | None):
        data = json.dumps(body if body is not None else {}).encode("utf-8")
        req = Request(self._url(path), data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def _read_sse_event(self, resp, timeout=5):
        """Açık bir `/api/stream` bağlantısından bir sonraki gerçek
        `data: ...` olayını okuyup JSON olarak döner; aradaki yorum
        satırlarını (`: heartbeat`) ve boş satırları (olay ayracı) sessizce
        atlar. `resp.readline()` bloklayan bir çağrı olduğundan, sunucu
        taraf test süresi içinde bir olay GÖNDERMEZSE test kendi
        `urlopen(..., timeout=...)` süresi dolunca zaten patlar — sonsuz
        asılı kalma riski yok."""
        while True:
            line = resp.readline()
            if not line:
                raise AssertionError("SSE bağlantısı beklenenden erken kapandı.")
            text = line.decode("utf-8").rstrip("\n")
            if text.startswith("data:"):
                return json.loads(text[len("data:"):].strip())


class TestExistingGetEndpoints(ServerTestBase):
    def test_index_and_app_js_served(self):
        with urlopen(self._url("/"), timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn(b"OmniTrade", resp.read())
        with urlopen(self._url("/app.js"), timeout=5) as resp:
            self.assertEqual(resp.status, 200)

    def test_unknown_path_is_404(self):
        with self.assertRaises(HTTPError) as ctx:
            urlopen(self._url("/does-not-exist"), timeout=5)
        self.assertEqual(ctx.exception.code, 404)

    def test_strategies_endpoint_lists_registered_strategies_with_param_schema(self):
        strategies = self._get_json("/api/strategies")
        names = {s["name"] for s in strategies}
        self.assertEqual(
            names,
            {"RsiStrategy", "MacdStrategy", "BollingerStrategy", "StochasticStrategy", "DonchianStrategy"},
        )
        rsi = next(s for s in strategies if s["name"] == "RsiStrategy")
        param_names = {p["name"] for p in rsi["params"]}
        self.assertEqual(param_names, {"period", "oversold", "overbought"})
        period_param = next(p for p in rsi["params"] if p["name"] == "period")
        self.assertEqual(period_param["default"], 14)

    def test_empty_db_endpoints_return_sane_defaults(self):
        self.assertEqual(self._get_json("/api/trades"), [])
        self.assertEqual(self._get_json("/api/equity"), [])
        self.assertEqual(self._get_json("/api/signals"), [])
        stats = self._get_json("/api/stats")
        self.assertEqual(stats["summary"]["trade_count"], 0)
        self.assertEqual(stats["drawdown_curve"], [])

    def test_signals_and_history_reflect_logged_data(self):
        self.storage.log_signal("BTC/USDT", "hold", 65000.0, reason="RSI=50.0")
        self.storage.log_signal("BTC/USDT", "buy", 64000.0, reason="RSI=28.0")
        latest = self._get_json("/api/signals")
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0]["action"], "buy")  # en son sinyal
        history = self._get_json("/api/signals/history?symbol=BTC%2FUSDT&limit=10")
        self.assertEqual(len(history), 2)


class TestBacktestEndpoint(ServerTestBase):
    def test_missing_symbol_is_400(self):
        status, body = self._post_json("/api/backtest", {})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_invalid_json_body_is_400(self):
        req = Request(self._url("/api/backtest"), data=b"{not json", method="POST")
        try:
            urlopen(req, timeout=5)
            self.fail("400 bekleniyordu")
        except HTTPError as exc:
            self.assertEqual(exc.code, 400)

    def test_unknown_strategy_is_400(self):
        status, body = self._post_json("/api/backtest", {"symbol": "BTC/USDT", "strategy": "NoSuchStrategy"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    @patch("omnitrade.web.server.ExchangeClient")
    def test_exchange_error_is_502(self, mock_exchange_cls):
        mock_exchange_cls.return_value.fetch_ohlcv_df.side_effect = RuntimeError("ağ hatası")
        status, body = self._post_json("/api/backtest", {"symbol": "BTC/USDT"})
        self.assertEqual(status, 502)
        self.assertIn("error", body)

    @patch("omnitrade.web.server.ExchangeClient")
    def test_single_backtest_default_walk_forward_off(self, mock_exchange_cls):
        # walk_forward=1 -> tek dönem, run_backtest kullanılır (run_walk_forward değil)
        mock_exchange_cls.return_value.fetch_ohlcv_df.return_value = _wavy_df()
        status, body = self._post_json("/api/backtest", {
            "symbol": "BTC/USDT", "walk_forward": 1, "limit": 300,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["symbol"], "BTC/USDT")
        self.assertEqual(body["walk_forward"], 1)
        self.assertEqual(len(body["periods"]), 1)
        self.assertNotIn("avg_return_pct", body)  # tek dönemde özet alanları eklenmez
        period = body["periods"][0]
        self.assertIn("total_return_pct", period)
        self.assertIn("win_rate", period)
        self.assertIn("max_drawdown_pct", period)

    @patch("omnitrade.web.server.ExchangeClient")
    def test_walk_forward_multi_period_summary(self, mock_exchange_cls):
        mock_exchange_cls.return_value.fetch_ohlcv_df.return_value = _wavy_df(n=600)
        status, body = self._post_json("/api/backtest", {
            "symbol": "BTC/USDT", "walk_forward": 4, "limit": 600,
        })
        self.assertEqual(status, 200)
        self.assertEqual(len(body["periods"]), 4)
        self.assertIn("avg_return_pct", body)
        self.assertIn("worst_period_pct", body)
        self.assertIn("best_period_pct", body)
        self.assertLessEqual(body["worst_period_pct"], body["avg_return_pct"])
        self.assertGreaterEqual(body["best_period_pct"], body["avg_return_pct"])

    @patch("omnitrade.web.server.ExchangeClient")
    def test_pair_strategies_override_used_by_default(self, mock_exchange_cls):
        # Faz 4 pair_strategies override'ı backtest endpoint'inde de
        # varsayılan olarak kullanılmalı (canlıda ne çalışıyorsa onu test et).
        self.config.pair_strategies = {"ETH/USDT": {"strategy": "RsiStrategy", "params": {"period": 21}}}
        mock_exchange_cls.return_value.fetch_ohlcv_df.return_value = _wavy_df()
        status, body = self._post_json("/api/backtest", {"symbol": "ETH/USDT", "walk_forward": 1})
        self.assertEqual(status, 200)
        self.assertEqual(body["params"], {"period": 21})

    @patch("omnitrade.web.server.ExchangeClient")
    def test_explicit_params_override_pair_strategies(self, mock_exchange_cls):
        self.config.pair_strategies = {"ETH/USDT": {"strategy": "RsiStrategy", "params": {"period": 21}}}
        mock_exchange_cls.return_value.fetch_ohlcv_df.return_value = _wavy_df()
        status, body = self._post_json("/api/backtest", {
            "symbol": "ETH/USDT", "walk_forward": 1,
            "params": {"period": 9, "oversold": 20, "overbought": 80},
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["params"]["period"], 9)


class TestBacktestBatchEndpoint(ServerTestBase):
    def test_missing_symbols_or_strategies_is_400(self):
        status, body = self._post_json("/api/backtest/batch", {"symbols": ["BTC/USDT"]})
        self.assertEqual(status, 400)
        self.assertIn("error", body)
        status, body = self._post_json("/api/backtest/batch", {"strategies": ["RsiStrategy"]})
        self.assertEqual(status, 400)

    @patch("omnitrade.web.server.ExchangeClient")
    def test_fetches_each_symbol_once_regardless_of_strategy_count(self, mock_exchange_cls):
        mock_exchange_cls.return_value.fetch_ohlcv_df.return_value = _wavy_df()
        status, body = self._post_json("/api/backtest/batch", {
            "symbols": ["BTC/USDT", "ETH/USDT"],
            "strategies": ["RsiStrategy", "MacdStrategy", "BollingerStrategy"],
            "walk_forward": 1,
        })
        self.assertEqual(status, 200)
        # 2 sembol x 3 strateji = 6 satır, ama fetch_ohlcv_df sadece 2 kez
        # çağrılmalı (sembol başına bir kez, kombinasyon başına değil).
        self.assertEqual(mock_exchange_cls.return_value.fetch_ohlcv_df.call_count, 2)
        self.assertEqual(len(body["results"]), 6)

    @patch("omnitrade.web.server.ExchangeClient")
    def test_results_sorted_by_avg_return_descending(self, mock_exchange_cls):
        mock_exchange_cls.return_value.fetch_ohlcv_df.return_value = _wavy_df(n=600)
        status, body = self._post_json("/api/backtest/batch", {
            "symbols": ["BTC/USDT"],
            "strategies": ["RsiStrategy", "MacdStrategy", "BollingerStrategy"],
            "walk_forward": 4,
        })
        self.assertEqual(status, 200)
        returns = [r["avg_return_pct"] for r in body["results"]]
        self.assertEqual(returns, sorted(returns, reverse=True))

    @patch("omnitrade.web.server.ExchangeClient")
    def test_unknown_strategy_in_batch_reports_row_error_not_whole_request_failure(self, mock_exchange_cls):
        mock_exchange_cls.return_value.fetch_ohlcv_df.return_value = _wavy_df()
        status, body = self._post_json("/api/backtest/batch", {
            "symbols": ["BTC/USDT"],
            "strategies": ["RsiStrategy", "NoSuchStrategy"],
            "walk_forward": 1,
        })
        self.assertEqual(status, 200)
        errored = [r for r in body["results"] if r.get("error")]
        self.assertEqual(len(errored), 1)
        self.assertEqual(errored[0]["strategy"], "NoSuchStrategy")

    @patch("omnitrade.web.server.ExchangeClient")
    def test_exchange_error_for_one_symbol_is_502(self, mock_exchange_cls):
        mock_exchange_cls.return_value.fetch_ohlcv_df.side_effect = RuntimeError("ağ hatası")
        status, body = self._post_json("/api/backtest/batch", {
            "symbols": ["BTC/USDT"], "strategies": ["RsiStrategy"],
        })
        self.assertEqual(status, 502)
        self.assertIn("error", body)


class TestConfigPairsEndpoint(ServerTestBase):
    """Faz 10: dashboard'dan coin ekle/çıkar. `Config.config_path` bilerek
    gerçek `config/config.yaml` yerine geçici bir dosyaya işaret edecek
    şekilde ayarlanıyor — testler asıl repo config'ine yazmamalı."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.config_path = Path(self._tmpdir.name) / "config.yaml"
        self.config_path.write_text("dry_run: true\npairs:\n  - BTC/USDT\n  - ETH/USDT\n")
        super().setUp()
        self.config.pairs = ["BTC/USDT", "ETH/USDT"]
        self.config.config_path = str(self.config_path)

    def test_get_returns_current_pairs(self):
        body = self._get_json("/api/config/pairs")
        self.assertEqual(body["pairs"], ["BTC/USDT", "ETH/USDT"])
        self.assertTrue(body["dry_run"])
        self.assertEqual(body["pair_strategies"], {})

    def test_add_valid_pair_updates_memory_and_file(self):
        status, body = self._post_json("/api/config/pairs", {"symbol": "sol/usdt", "action": "add"})
        self.assertEqual(status, 200)
        self.assertEqual(body["pairs"], ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
        # Faz 13: artık restart gerekmiyor, bot değişikliği kendi
        # döngüsünde otomatik fark ediyor (bkz. engine.py hot-reload testleri).
        self.assertFalse(body["restart_required"])
        self.assertEqual(self.config.pairs, ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
        self.assertIn("SOL/USDT", self.config_path.read_text())
        self.assertIn("dry_run: true", self.config_path.read_text())

    def test_add_duplicate_pair_is_400(self):
        status, body = self._post_json("/api/config/pairs", {"symbol": "BTC/USDT", "action": "add"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)
        self.assertEqual(self.config.pairs, ["BTC/USDT", "ETH/USDT"])

    def test_add_invalid_format_is_400(self):
        status, body = self._post_json("/api/config/pairs", {"symbol": "BTCUSDT", "action": "add"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_remove_existing_pair_updates_memory_and_file(self):
        status, body = self._post_json("/api/config/pairs", {"symbol": "ETH/USDT", "action": "remove"})
        self.assertEqual(status, 200)
        self.assertEqual(body["pairs"], ["BTC/USDT"])
        self.assertEqual(self.config.pairs, ["BTC/USDT"])
        self.assertNotIn("ETH/USDT", self.config_path.read_text())

    def test_cannot_remove_last_remaining_pair(self):
        self._post_json("/api/config/pairs", {"symbol": "ETH/USDT", "action": "remove"})
        status, body = self._post_json("/api/config/pairs", {"symbol": "BTC/USDT", "action": "remove"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)
        self.assertEqual(self.config.pairs, ["BTC/USDT"])

    def test_remove_nonexistent_pair_is_400(self):
        status, body = self._post_json("/api/config/pairs", {"symbol": "SOL/USDT", "action": "remove"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_invalid_action_is_400(self):
        status, body = self._post_json("/api/config/pairs", {"symbol": "BTC/USDT", "action": "delete"})
        self.assertEqual(status, 400)

    def test_missing_symbol_is_400(self):
        status, body = self._post_json("/api/config/pairs", {"action": "add"})
        self.assertEqual(status, 400)


class TestConfigPairStrategyEndpoint(ServerTestBase):
    """Faz 11: dashboard'dan tek tıkla dry-run pair_strategies override'ı
    uygula/kaldır. `Config.config_path` yine geçici bir dosyaya işaret
    ediyor — bkz. TestConfigPairsEndpoint'teki aynı gerekçe."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.config_path = Path(self._tmpdir.name) / "config.yaml"
        self.config_path.write_text(
            "dry_run: true\npairs:\n  - BTC/USDT\n  - ETH/USDT\npair_strategies: {}\n"
        )
        super().setUp()
        self.config.dry_run = True
        self.config.pairs = ["BTC/USDT", "ETH/USDT"]
        self.config.pair_strategies = {}
        self.config.config_path = str(self.config_path)

    def test_apply_valid_strategy_updates_memory_and_file(self):
        status, body = self._post_json("/api/config/pair-strategy", {
            "symbol": "eth/usdt", "action": "apply",
            "strategy": "RsiStrategy", "params": {"period": 21},
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["pair_strategies"], {"ETH/USDT": {"strategy": "RsiStrategy", "params": {"period": 21}}})
        self.assertFalse(body["restart_required"])  # Faz 13: otomatik hot-reload
        self.assertEqual(self.config.pair_strategies, {"ETH/USDT": {"strategy": "RsiStrategy", "params": {"period": 21}}})
        text = self.config_path.read_text()
        self.assertIn("ETH/USDT", text)
        self.assertIn("RsiStrategy", text)
        self.assertIn("dry_run: true", text)

    def test_apply_without_params_uses_strategy_defaults(self):
        status, body = self._post_json("/api/config/pair-strategy", {
            "symbol": "BTC/USDT", "action": "apply", "strategy": "MacdStrategy",
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["pair_strategies"]["BTC/USDT"], {"strategy": "MacdStrategy", "params": {}})

    def test_reset_removes_existing_override(self):
        self._post_json("/api/config/pair-strategy", {
            "symbol": "BTC/USDT", "action": "apply", "strategy": "MacdStrategy",
        })
        status, body = self._post_json("/api/config/pair-strategy", {"symbol": "BTC/USDT", "action": "reset"})
        self.assertEqual(status, 200)
        self.assertEqual(body["pair_strategies"], {})
        self.assertEqual(self.config.pair_strategies, {})
        self.assertNotIn("MacdStrategy", self.config_path.read_text())

    def test_reset_without_existing_override_is_400(self):
        status, body = self._post_json("/api/config/pair-strategy", {"symbol": "BTC/USDT", "action": "reset"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_apply_rejected_when_live_trading(self):
        self.config.dry_run = False
        status, body = self._post_json("/api/config/pair-strategy", {
            "symbol": "BTC/USDT", "action": "apply", "strategy": "RsiStrategy",
        })
        self.assertEqual(status, 403)
        self.assertIn("error", body)
        self.assertEqual(self.config.pair_strategies, {})

    def test_apply_unknown_strategy_is_400(self):
        status, body = self._post_json("/api/config/pair-strategy", {
            "symbol": "BTC/USDT", "action": "apply", "strategy": "NoSuchStrategy",
        })
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_apply_invalid_params_is_400(self):
        status, body = self._post_json("/api/config/pair-strategy", {
            "symbol": "BTC/USDT", "action": "apply", "strategy": "RsiStrategy",
            "params": {"not_a_real_param": 1},
        })
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_apply_for_untracked_symbol_is_400(self):
        status, body = self._post_json("/api/config/pair-strategy", {
            "symbol": "SOL/USDT", "action": "apply", "strategy": "RsiStrategy",
        })
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_apply_missing_strategy_is_400(self):
        status, body = self._post_json("/api/config/pair-strategy", {"symbol": "BTC/USDT", "action": "apply"})
        self.assertEqual(status, 400)

    def test_invalid_action_is_400(self):
        status, body = self._post_json("/api/config/pair-strategy", {"symbol": "BTC/USDT", "action": "delete"})
        self.assertEqual(status, 400)


class TestSystemEndpoint(ServerTestBase):
    """Faz 16: /api/system durum uç noktası + poll-interval değişikliği."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.config_path = Path(self._tmpdir.name) / "config.yaml"
        self.config_path.write_text(
            "dry_run: true\npoll_interval_seconds: 60\nlive_trading_confirmed: false\n"
        )
        super().setUp()
        self.config.config_path = str(self.config_path)

    def test_system_status_reflects_file_and_runtime(self):
        body = self._get_json("/api/system")
        self.assertTrue(body["runtime"]["dry_run"])
        self.assertFalse(body["runtime"]["live_trading_confirmed"])
        self.assertTrue(body["config_file"]["dry_run"])
        self.assertFalse(body["restart_required"])
        self.assertFalse(body["web_auth_enabled"])

    def test_update_poll_interval_valid(self):
        status, body = self._post_json("/api/system/poll-interval", {"seconds": 30})
        self.assertEqual(status, 200)
        self.assertEqual(body["poll_interval_seconds"], 30)
        self.assertFalse(body["restart_required"])
        self.assertEqual(self.config.poll_interval_seconds, 30)
        self.assertIn("poll_interval_seconds: 30", self.config_path.read_text())

    def test_update_poll_interval_out_of_range_is_400(self):
        status, body = self._post_json("/api/system/poll-interval", {"seconds": 1})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_update_poll_interval_non_integer_is_400(self):
        status, body = self._post_json("/api/system/poll-interval", {"seconds": "abc"})
        self.assertEqual(status, 400)

    def test_audit_log_empty_by_default(self):
        self.assertEqual(self._get_json("/api/system/audit-log"), [])


class TestLiveModeEndpoint(ServerTestBase):
    """Faz 16: canlı/dry-run geçiş — AUDIT_REPORT.md §6.1 ön koşulları."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.config_path = Path(self._tmpdir.name) / "config.yaml"
        self.config_path.write_text(
            "dry_run: true\nlive_trading_confirmed: false\n"
        )
        super().setUp()
        self.config.config_path = str(self.config_path)
        self.config.dry_run = True
        self.config.live_trading_confirmed = False

    def test_rejected_with_403_when_web_auth_disabled(self):
        # §6.1 madde 1: web_auth kapalıyken bu uç TAMAMEN reddedilir —
        # diğer düşük riskli uçların aksine ("auth kapalıysa serbest" kuralı
        # burada geçerli DEĞİL.
        status, body = self._post_json("/api/system/live-mode", {
            "action": "go_live", "confirm_text": "her ne olursa olsun",
        })
        self.assertEqual(status, 403)
        self.assertIn("error", body)
        self.assertTrue(self.config.dry_run)  # değişiklik olmadı


class TestStreamEndpoint(ServerTestBase):
    """Faz 17: /api/stream (SSE) — sabit 10sn poll yerine push modeli.
    `stream_poll_seconds` testlerde 0.2sn'ye düşürülüyor ki gerçek bir
    değişiklikten sonraki olay birkaç saniye değil, hızlıca gelsin."""

    def setUp(self):
        super().setUp()
        self.config.stream_poll_seconds = 0.2

    def test_first_event_is_connected_with_no_changes(self):
        with urlopen(self._url("/api/stream"), timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/event-stream", resp.headers.get("Content-Type", ""))
            event = self._read_sse_event(resp)
            self.assertEqual(event, {"type": "connected", "changed": []})

    def test_new_trade_triggers_trades_update_event(self):
        with urlopen(self._url("/api/stream"), timeout=5) as resp:
            self._read_sse_event(resp)  # 'connected'
            self.storage.log_trade("BTC/USDT", "buy", 100.0, 1.0, dry_run=True)
            event = self._read_sse_event(resp)
            self.assertEqual(event["type"], "update")
            self.assertEqual(event["changed"], ["trades"])

    def test_new_equity_point_triggers_equity_update_event(self):
        with urlopen(self._url("/api/stream"), timeout=5) as resp:
            self._read_sse_event(resp)
            self.storage.log_equity(1050.0)
            event = self._read_sse_event(resp)
            self.assertEqual(event["changed"], ["equity"])

    def test_new_signal_triggers_signals_update_event(self):
        with urlopen(self._url("/api/stream"), timeout=5) as resp:
            self._read_sse_event(resp)
            self.storage.log_signal("ETH/USDT", "hold", 2000.0, reason="rsi nötr")
            event = self._read_sse_event(resp)
            self.assertEqual(event["changed"], ["signals"])

    def test_mode_change_triggers_system_update_event(self):
        with urlopen(self._url("/api/stream"), timeout=5) as resp:
            self._read_sse_event(resp)
            self.storage.log_mode_change(
                action="go_live", old_dry_run=True, new_dry_run=False,
                old_live_trading_confirmed=False, new_live_trading_confirmed=True,
            )
            event = self._read_sse_event(resp)
            self.assertEqual(event["changed"], ["system"])

    def test_unrelated_reads_do_not_trigger_events(self):
        # Sadece storage'dan OKUMA yapmak (yazma değil) parmak izini
        # değiştirmemeli — bu yüzden ilk 'connected' olayından sonra hiçbir
        # yazma yapılmadıysa bir sonraki gerçek 'data:' olayı gelmemeli.
        # Bunu zamanlamaya bağlı kalmadan doğrulamak için: kısa bir süre
        # bekleyip HİÇBİR yazma yapmadan yeni bir bağlantı daha açıp onun
        # da 'connected' ile başladığını görmek yeterli bir dolaylı kanıt
        # (asıl "sadece değişince gönder" davranışı yukarıdaki testlerde
        # `changed` listesinin HER ZAMAN tam olarak beklenen tek anahtarı
        # içermesiyle zaten doğrulanıyor).
        with urlopen(self._url("/api/stream"), timeout=5) as resp:
            event = self._read_sse_event(resp)
            self.assertEqual(event["changed"], [])


class TestDiffFingerprint(unittest.TestCase):
    """`_diff_fingerprint` — SSE döngüsünden bağımsız, saf fonksiyon testi."""

    def test_no_difference_returns_empty_list(self):
        fp = {"trades": 1, "equity": 2, "signals": 3, "system": None, "heartbeat": 1.0}
        self.assertEqual(_diff_fingerprint(fp, dict(fp)), [])

    def test_single_changed_key_is_detected(self):
        old = {"trades": 1, "equity": 2, "signals": 3, "system": None, "heartbeat": 1.0}
        new = dict(old, trades=2)
        self.assertEqual(_diff_fingerprint(old, new), ["trades"])

    def test_multiple_changed_keys_are_sorted(self):
        old = {"trades": 1, "equity": 2, "signals": 3, "system": None, "heartbeat": 1.0}
        new = dict(old, trades=2, signals=4)
        self.assertEqual(_diff_fingerprint(old, new), ["signals", "trades"])

    def test_none_to_value_is_a_change(self):
        # Boş bir tablodan (MAX(id) -> NULL/None) ilk satır eklendiğinde de
        # bir değişiklik olarak sayılmalı — sunucu ilk açılışta boş bir
        # tabloyu None olarak fingerprint'ler.
        old = {"trades": None, "equity": None, "signals": None, "system": None, "heartbeat": None}
        new = dict(old, trades=1)
        self.assertEqual(_diff_fingerprint(old, new), ["trades"])


class TestLeaderboardTemplatesEndpoint(ServerTestBase):
    """Faz 18: /api/leaderboard/templates — kaydet (upsert)/listele/sil."""

    def test_empty_by_default(self):
        self.assertEqual(self._get_json("/api/leaderboard/templates"), [])

    def test_save_then_list_returns_it(self):
        status, body = self._post_json("/api/leaderboard/templates", {
            "action": "save", "name": "Ana coinler",
            "symbols": ["BTC/USDT", "ETH/USDT"], "strategies": ["RsiStrategy"],
            "candle_limit": 1000, "walk_forward": 4,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["name"], "Ana coinler")
        templates = self._get_json("/api/leaderboard/templates")
        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0]["symbols"], ["BTC/USDT", "ETH/USDT"])

    def test_save_clamps_out_of_range_limits_instead_of_rejecting(self):
        status, body = self._post_json("/api/leaderboard/templates", {
            "action": "save", "name": "Aşırı", "symbols": ["BTC/USDT"],
            "strategies": ["RsiStrategy"], "candle_limit": 999999, "walk_forward": 999,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["candle_limit"], 1500)
        self.assertEqual(body["walk_forward"], 12)

    def test_save_missing_name_is_400(self):
        status, body = self._post_json("/api/leaderboard/templates", {
            "action": "save", "symbols": ["BTC/USDT"], "strategies": ["RsiStrategy"],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_save_empty_symbols_is_400(self):
        status, body = self._post_json("/api/leaderboard/templates", {
            "action": "save", "name": "x", "symbols": [], "strategies": ["RsiStrategy"],
        })
        self.assertEqual(status, 400)

    def test_save_unknown_strategy_is_400(self):
        status, body = self._post_json("/api/leaderboard/templates", {
            "action": "save", "name": "x", "symbols": ["BTC/USDT"], "strategies": ["NopeStrategy"],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_invalid_action_is_400(self):
        status, body = self._post_json("/api/leaderboard/templates", {"action": "update", "name": "x"})
        self.assertEqual(status, 400)

    def test_delete_existing_template(self):
        self._post_json("/api/leaderboard/templates", {
            "action": "save", "name": "Silinecek", "symbols": ["BTC/USDT"],
            "strategies": ["RsiStrategy"],
        })
        status, body = self._post_json("/api/leaderboard/templates", {"action": "delete", "name": "Silinecek"})
        self.assertEqual(status, 200)
        self.assertTrue(body["deleted"])
        self.assertEqual(self._get_json("/api/leaderboard/templates"), [])

    def test_delete_nonexistent_template_is_404(self):
        status, body = self._post_json("/api/leaderboard/templates", {"action": "delete", "name": "yok"})
        self.assertEqual(status, 404)
        self.assertIn("error", body)

    def test_saving_same_name_again_updates(self):
        self._post_json("/api/leaderboard/templates", {
            "action": "save", "name": "Ana coinler", "symbols": ["BTC/USDT"],
            "strategies": ["RsiStrategy"], "candle_limit": 500, "walk_forward": 2,
        })
        self._post_json("/api/leaderboard/templates", {
            "action": "save", "name": "Ana coinler", "symbols": ["BTC/USDT", "SOL/USDT"],
            "strategies": ["MacdStrategy"], "candle_limit": 800, "walk_forward": 3,
        })
        templates = self._get_json("/api/leaderboard/templates")
        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0]["symbols"], ["BTC/USDT", "SOL/USDT"])


class TestLiveModeEndpointWithAuthEnabled(unittest.TestCase):
    """web_auth açıkken go_live/go_dry_run akışı — auth + confirm_text
    doğrulaması ayrı bir test sınıfında, çünkü Config web_auth alanı
    setUp'tan ÖNCE (handler oluşturulmadan önce) ayarlanmalı."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.config_path = Path(self._tmpdir.name) / "config.yaml"
        self.config_path.write_text("dry_run: true\nlive_trading_confirmed: false\n")

        self.storage = Storage(":memory:")
        self.config = Config(
            web_auth=WebAuthConfig(enabled=True, username="admin", password="s3cret"),
            config_path=str(self.config_path),
        )
        handler = make_handler(self.storage, self.config)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.storage.close()

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _auth_header(self) -> dict:
        token = base64.b64encode(b"admin:s3cret").decode()
        return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

    def _post_json(self, path: str, body: dict):
        data = json.dumps(body).encode("utf-8")
        req = Request(self._url(path), data=data, headers=self._auth_header(), method="POST")
        try:
            with urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_invalid_action_is_400(self):
        status, body = self._post_json("/api/system/live-mode", {"action": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_go_live_without_confirm_text_is_400_and_no_change(self):
        status, body = self._post_json("/api/system/live-mode", {"action": "go_live"})
        self.assertEqual(status, 400)
        self.assertIn("required_confirm_text", body)
        self.assertTrue(self.config.dry_run)
        self.assertEqual(self.storage.get_mode_audit_log(), [])

    def test_go_live_with_wrong_confirm_text_is_400(self):
        status, body = self._post_json("/api/system/live-mode", {
            "action": "go_live", "confirm_text": "evet canliya gec",
        })
        self.assertEqual(status, 400)
        self.assertTrue(self.config.dry_run)

    def test_go_live_with_exact_confirm_text_succeeds_and_is_audited(self):
        status, body = self._post_json("/api/system/live-mode", {
            "action": "go_live",
            "confirm_text": "CANLIYA GEÇİYORUM, RİSKİ ANLADIM",
        })
        self.assertEqual(status, 200)
        self.assertFalse(body["dry_run"])
        self.assertTrue(body["live_trading_confirmed"])
        self.assertTrue(body["restart_required"])  # restart-only alan
        self.assertFalse(self.config.dry_run)
        self.assertTrue(self.config.live_trading_confirmed)
        self.assertIn("dry_run: false", self.config_path.read_text())

        log = self.storage.get_mode_audit_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["action"], "go_live")
        self.assertEqual(log[0]["username"], "admin")
        self.assertEqual(log[0]["old_dry_run"], 1)
        self.assertEqual(log[0]["new_dry_run"], 0)

    def test_go_dry_run_requires_no_confirm_text(self):
        # Önce canlıya geç, sonra tek istekle geri dön — ek onay gerekmez.
        self._post_json("/api/system/live-mode", {
            "action": "go_live", "confirm_text": "CANLIYA GEÇİYORUM, RİSKİ ANLADIM",
        })
        status, body = self._post_json("/api/system/live-mode", {"action": "go_dry_run"})
        self.assertEqual(status, 200)
        self.assertTrue(body["dry_run"])
        self.assertFalse(body["live_trading_confirmed"])
        self.assertEqual(len(self.storage.get_mode_audit_log()), 2)


class TestWebAuth(unittest.TestCase):
    """Faz 14: `config.web_auth.enabled` açıkken dashboard HTTP Basic Auth
    ister. Varsayılan (kapalı) davranış diğer tüm testlerde zaten dolaylı
    olarak doğrulanıyor (auth hiç engellemiyor) — burada sadece AÇIK
    olduğu senaryo test ediliyor."""

    def setUp(self):
        self.storage = Storage(":memory:")
        self.config = Config(web_auth=WebAuthConfig(enabled=True, username="admin", password="s3cret"))
        handler = make_handler(self.storage, self.config)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.storage.close()

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _auth_header(self, username: str, password: str) -> dict:
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def test_request_without_credentials_is_401(self):
        with self.assertRaises(HTTPError) as ctx:
            urlopen(self._url("/api/trades"), timeout=5)
        self.assertEqual(ctx.exception.code, 401)
        self.assertIn("WWW-Authenticate", ctx.exception.headers)

    def test_request_with_wrong_credentials_is_401(self):
        req = Request(self._url("/api/trades"), headers=self._auth_header("admin", "yanlis"))
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 401)

    def test_request_with_correct_credentials_succeeds(self):
        req = Request(self._url("/api/trades"), headers=self._auth_header("admin", "s3cret"))
        with urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)

    def test_post_endpoints_also_require_auth(self):
        req = Request(
            self._url("/api/config/pairs"),
            data=json.dumps({"symbol": "SOL/USDT", "action": "add"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 401)

    def test_stream_endpoint_also_requires_auth(self):
        # Faz 17: /api/stream, diğer düşük riskli GET'lerden farklı bir
        # kural İZLEMİYOR — normal `_require_auth()` yoluna tabi. Burada
        # bağlantı kimlik doğrulaması aşamasında (yanıt gövdesi/stream
        # başlamadan) 401 ile reddedildiği için gerçek bir SSE döngüsüne
        # hiç girilmiyor, testin asılı kalma riski yok.
        with self.assertRaises(HTTPError) as ctx:
            urlopen(self._url("/api/stream"), timeout=5)
        self.assertEqual(ctx.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
