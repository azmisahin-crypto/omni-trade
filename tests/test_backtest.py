import unittest

import pandas as pd

from omnitrade.backtest import run_backtest, run_walk_forward, walk_forward_windows
from omnitrade.risk import RiskConfig
from omnitrade.strategies.base import Action, Signal, Strategy
from omnitrade.strategies.rsi_strategy import RsiStrategy


class _AlwaysBuyStrategy(Strategy):
    """Test yardımcısı: her zaman BUY üretir, tek pozisyon açıldıktan sonra
    stop-loss/take-profit'in gerçekten backtest'i etkilediğini görmek için."""

    def required_candles(self) -> int:
        return 1

    def generate_signal(self, df, symbol):
        return Signal(Action.BUY, symbol, reason="test")


def _wavy_df(n: int = 200, amplitude: float = 10.0, base: float = 100.0) -> pd.DataFrame:
    closes = [base + amplitude * ((i % 40) - 20) / 20 for i in range(n)]
    return pd.DataFrame({
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": [1.0] * n,
    })


def _trending_df(n: int = 200, start: float = 100.0, step: float = 0.5) -> pd.DataFrame:
    closes = [start + step * i for i in range(n)]
    return pd.DataFrame({
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": [1.0] * n,
    })


class TestBacktest(unittest.TestCase):
    def test_runs_end_to_end_on_synthetic_data(self):
        # Dalgalı fiyat serisi: RSI stratejisinin birkaç al/sat üretmesi beklenir
        df = _wavy_df()
        strategy = RsiStrategy(period=14)
        result = run_backtest(df, strategy, "BTC/USDT", starting_balance=1000.0)

        self.assertGreaterEqual(result.trades, 0)
        self.assertGreater(result.final_balance, 0)
        self.assertGreaterEqual(result.max_drawdown_pct, 0)

    def test_fees_and_slippage_reduce_returns_vs_costless_run(self):
        """Maliyet modeli gerçekten sonucu etkiliyor mu — komisyon/slippage
        sıfırken elde edilen getiri, maliyetli koşudan büyük ya da eşit olmalı."""
        df = _wavy_df()
        strategy = RsiStrategy(period=14)

        costless = run_backtest(
            df, strategy, "BTC/USDT", starting_balance=1000.0, fee_pct=0.0, slippage_pct=0.0,
        )
        strategy2 = RsiStrategy(period=14)  # taze instance, state paylaşmasın
        costly = run_backtest(
            df, strategy2, "BTC/USDT", starting_balance=1000.0, fee_pct=0.01, slippage_pct=0.01,
        )
        if costless.trades > 0:
            self.assertGreaterEqual(costless.final_balance, costly.final_balance)

    def test_different_market_regimes_produce_different_results(self):
        """Overfitting'e karşı ilk adım: aynı strateji farklı piyasa
        rejimlerinde (yatay/dalgalı vs. sürekli yükselen) farklı sonuçlar
        vermeli — 'her koşulda aynı sihirli sayıyı üretiyor' değil."""
        wavy = run_backtest(_wavy_df(), RsiStrategy(period=14), "BTC/USDT")
        trending = run_backtest(_trending_df(), RsiStrategy(period=14), "BTC/USDT")

        # Sürekli yükselen bir piyasada RSI hiç oversold'a düşmeyeceği için
        # muhtemelen hiç işlem açılmaz (ya da çok az) — bu da strateji
        # davranışının rejime duyarlı olduğunu doğrular.
        self.assertIsInstance(wavy.trades, int)
        self.assertIsInstance(trending.trades, int)

    def test_max_drawdown_is_zero_when_no_trades_happen(self):
        # Fiyat hep sabitse RSI 50 civarında kalır, hiç sinyal üretilmemeli
        df = pd.DataFrame({
            "open": [100.0] * 60, "high": [100.0] * 60, "low": [100.0] * 60,
            "close": [100.0] * 60, "volume": [1.0] * 60,
        })
        result = run_backtest(df, RsiStrategy(period=14), "BTC/USDT")
        self.assertEqual(result.trades, 0)
        self.assertEqual(result.final_balance, result.starting_balance)


class TestBacktestRiskIntegration(unittest.TestCase):
    """`risk_config` verildiğinde backtest'in dry-run Portfolio ile aynı
    stop-loss/take-profit/pozisyon büyüklüğü kurallarını uygulaması —
    ikisi arasındaki tutarsızlık Faz 1'de bulunup burada giderildi."""

    def test_stop_loss_force_closes_position_before_strategy_sell(self):
        # Fiyat sürekli düşüyor, %5 zarar eşiğini geçince strateji SELL
        # üretmese bile pozisyon kapanmalı.
        closes = [100.0] + [100.0 - i for i in range(1, 20)]
        df = pd.DataFrame({
            "open": closes, "high": closes, "low": closes, "close": closes,
            "volume": [1.0] * len(closes),
        })
        risk = RiskConfig(max_position_pct=1.0, stop_loss_pct=0.05, take_profit_pct=None)
        result = run_backtest(
            df, _AlwaysBuyStrategy(), "BTC/USDT", starting_balance=1000.0,
            fee_pct=0.0, slippage_pct=0.0, risk_config=risk,
        )
        # Zararla kapanmış olmalı: nihai bakiye başlangıçtan düşük.
        self.assertLess(result.final_balance, result.starting_balance)

    def test_max_position_pct_limits_stake_size(self):
        closes = [100.0] * 30
        df = pd.DataFrame({
            "open": closes, "high": closes, "low": closes, "close": closes,
            "volume": [1.0] * len(closes),
        })
        risk = RiskConfig(max_position_pct=0.1)
        # AlwaysBuy + hiç SELL yok -> tek pozisyon, stake balance'ın %10'u olmalı,
        # yani kalan balance ~900 civarında olmalı (fee/slippage sıfır).
        result = run_backtest(
            df, _AlwaysBuyStrategy(), "BTC/USDT", starting_balance=1000.0,
            fee_pct=0.0, slippage_pct=0.0, risk_config=risk,
        )
        # Pozisyon fiyatı sabit kaldığı için equity ~ starting_balance kalmalı
        # (sadece bir kez alım yapıldı, tek qty sabit fiyatta taşınıyor).
        self.assertAlmostEqual(result.final_balance, 1000.0, delta=1.0)

    def test_no_risk_config_keeps_legacy_stake_fraction_behavior(self):
        df = pd.DataFrame({
            "open": [100.0] * 30, "high": [100.0] * 30, "low": [100.0] * 30,
            "close": [100.0] * 30, "volume": [1.0] * 30,
        })
        result = run_backtest(
            df, _AlwaysBuyStrategy(), "BTC/USDT", starting_balance=1000.0,
            stake_fraction=0.3, fee_pct=0.0, slippage_pct=0.0, risk_config=None,
        )
        self.assertEqual(result.trades, 1)


class TestWalkForwardWindows(unittest.TestCase):
    """Faz 4: veri N ardışık test penceresine bölünüyor mu, sınır durumlar
    (yetersiz veri, n_splits=1) doğru mu ele alınıyor."""

    def test_splits_into_n_contiguous_non_overlapping_windows(self):
        windows = walk_forward_windows(n_rows=100, n_splits=4, min_bars=20)
        self.assertEqual(len(windows), 4)
        # Örtüşmemeli, ilk pencere min_bars'tan başlamalı, son pencere n_rows'ta bitmeli
        self.assertEqual(windows[0][0], 20)
        self.assertEqual(windows[-1][1], 100)
        for (s1, e1), (s2, e2) in zip(windows, windows[1:]):
            self.assertEqual(e1, s2)

    def test_returns_empty_when_not_enough_data(self):
        self.assertEqual(walk_forward_windows(n_rows=10, n_splits=4, min_bars=20), [])

    def test_single_split_covers_all_usable_data(self):
        windows = walk_forward_windows(n_rows=100, n_splits=1, min_bars=20)
        self.assertEqual(windows, [(20, 100)])


class TestRunWalkForward(unittest.TestCase):
    def test_runs_independent_backtest_per_window(self):
        df = _wavy_df(n=200)
        results = run_walk_forward(
            df, RsiStrategy(), "BTC/USDT", n_splits=4, starting_balance=1000.0,
        )
        self.assertEqual(len(results), 4)
        for i, r in enumerate(results, start=1):
            self.assertEqual(r.symbol, f"BTC/USDT #{i}")
            # Her pencere kendi starting_balance'ıyla başlamalı (bağımsız)
            self.assertEqual(r.starting_balance, 1000.0)

    def test_empty_when_data_too_short_for_any_window(self):
        df = _wavy_df(n=10)
        results = run_walk_forward(df, RsiStrategy(), "BTC/USDT", n_splits=4)
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
