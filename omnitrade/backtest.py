"""CSV'den (timestamp,open,high,low,close,volume) geçmiş veriyle backtest.
Aynı Strategy sınıfını kullanır — canlıda kullandığın kodla test ettiğin
kod birebir aynı, farklı davranmaz.

Veri indirmek için (örnek, ccxt kurulu olmalı):
    python -c "
import ccxt, pandas as pd
ex = ccxt.binance()
raw = ex.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=1000)
pd.DataFrame(raw, columns=['timestamp','open','high','low','close','volume']).to_csv('data/BTCUSDT_1h.csv', index=False)
"
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from omnitrade.risk import RiskConfig, RiskManager
from omnitrade.strategies.base import Action, Strategy


@dataclass
class BacktestResult:
    symbol: str
    trades: int
    final_balance: float
    starting_balance: float
    win_rate: float
    max_drawdown_pct: float

    @property
    def total_return_pct(self) -> float:
        return (self.final_balance / self.starting_balance - 1) * 100

    def __str__(self) -> str:
        return (
            f"[{self.symbol}] {self.trades} işlem | "
            f"getiri: {self.total_return_pct:+.2f}% | "
            f"kazanma oranı: {self.win_rate*100:.1f}% | "
            f"max drawdown: {self.max_drawdown_pct:.2f}%"
        )


def run_backtest(
    df: pd.DataFrame, strategy: Strategy, symbol: str,
    starting_balance: float = 1000.0, stake_fraction: float = 0.2, fee_pct: float = 0.001,
    slippage_pct: float = 0.0005, risk_config: RiskConfig | None = None,
) -> BacktestResult:
    """`slippage_pct`: gerçek dünyada emrin, gördüğün fiyattan biraz daha
    kötü dolması (alışta daha pahalı, satışta daha ucuz). Bu modellenmezse
    backtest sonuçları gerçekte elde edeceğinden daha iyimser çıkar —
    özellikle çok işlem yapan/düşük likiditeli stratejilerde önemli.

    `risk_config` verilirse (önerilen: config.yaml'daki `risk` bölümü),
    dry-run Portfolio ile AYNI risk kuralları (stop-loss/take-profit,
    pozisyon büyüklüğü) burada da uygulanır — böylece backtest sonucu
    dry-run'da göreceğinden temelde farklı çıkmaz. Verilmezse eski
    davranışa (`stake_fraction`, risk çıkışı yok) geri düşülür — geriye
    dönük uyumluluk için.
    """
    risk = RiskManager(risk_config) if risk_config is not None else None
    balance = starting_balance
    qty = 0.0
    entry_price = 0.0
    trades = 0
    wins = 0
    equity_curve = [starting_balance]

    min_bars = strategy.required_candles()
    for i in range(min_bars, len(df)):
        window = df.iloc[: i + 1]
        price = float(window["close"].iloc[-1])

        # Risk çıkışları (stop-loss/take-profit) stratejiden ÖNCE kontrol
        # edilir — dry-run Portfolio.check_risk_exits() ile aynı sıralama:
        # bir pozisyon strateji SELL üretmeden de risk limitini aşabilir.
        if risk is not None and qty > 0:
            if risk.should_stop_loss(entry_price, price):
                fill_price = price * (1 - slippage_pct)
                balance += qty * fill_price * (1 - fee_pct)
                if fill_price > entry_price:
                    wins += 1
                qty = 0.0
            elif risk.should_take_profit(entry_price, price):
                fill_price = price * (1 - slippage_pct)
                balance += qty * fill_price * (1 - fee_pct)
                if fill_price > entry_price:
                    wins += 1
                qty = 0.0

        signal = strategy.generate_signal(window, symbol)

        if signal.action == Action.BUY and qty == 0:
            if risk is not None:
                risk.update_daily_baseline(balance)
                if risk.check_kill_switch(balance) or not risk.can_open_position(0):
                    equity_curve.append(balance + qty * price)
                    continue
                stake = risk.position_stake(balance)
            else:
                stake = balance * stake_fraction
            fill_price = price * (1 + slippage_pct)
            qty = (stake * (1 - fee_pct)) / fill_price
            balance -= stake
            entry_price = fill_price
            trades += 1

        elif signal.action == Action.SELL and qty > 0:
            fill_price = price * (1 - slippage_pct)
            proceeds = qty * fill_price * (1 - fee_pct)
            balance += proceeds
            if fill_price > entry_price:
                wins += 1
            qty = 0.0

        equity_curve.append(balance + qty * price)

    # Backtest sonunda açık pozisyon varsa son fiyattan kapat (raporlama için)
    if qty > 0:
        exit_price = float(df["close"].iloc[-1]) * (1 - slippage_pct)
        balance += qty * exit_price * (1 - fee_pct)
        qty = 0.0

    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        peak = max(peak, v)
        dd = (peak - v) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    return BacktestResult(
        symbol=symbol,
        trades=trades,
        final_balance=balance,
        starting_balance=starting_balance,
        win_rate=(wins / trades) if trades else 0.0,
        max_drawdown_pct=max_dd,
    )


def walk_forward_windows(n_rows: int, n_splits: int, min_bars: int) -> list[tuple[int, int]]:
    """Veriyi `n_splits` ardışık, örtüşmeyen test penceresine böler ve her
    pencerenin (start, end) satır aralığını (exclusive end) döndürür.

    Walk-forward'ın amacı: backtest'in TEK bir dönemde (örn. hep yükseliş
    trendinde) iyi görünüp başka bir dönemde (yatay/düşüş) çökmediğini
    görmek — Faz 1'deki "farklı piyasa rejimi" testinden bir adım öteye,
    stratejinin gerçek veri üzerinde zaman içinde tutarlı olup olmadığını
    ölçer. Her pencere kendi başına bağımsız bir backtest koşusu olarak
    çalıştırılır (bkz. `run_walk_forward`) — "train" adımı yok çünkü
    stratejiler burada parametre öğrenmiyor (fit edilmiyor), sadece farklı
    zaman dilimlerinde nasıl davrandığı karşılaştırılıyor.
    """
    if n_splits < 1:
        raise ValueError("n_splits en az 1 olmalı")
    usable = n_rows - min_bars
    if usable <= 0:
        return []
    window_size = usable // n_splits
    if window_size <= 0:
        return []
    windows = []
    for i in range(n_splits):
        start = min_bars + i * window_size
        end = n_rows if i == n_splits - 1 else min_bars + (i + 1) * window_size
        if end - start > 0:
            windows.append((start, end))
    return windows


def run_walk_forward(
    df: pd.DataFrame, strategy: Strategy, symbol: str, n_splits: int = 4,
    starting_balance: float = 1000.0, stake_fraction: float = 0.2, fee_pct: float = 0.001,
    slippage_pct: float = 0.0005, risk_config: RiskConfig | None = None,
) -> list[BacktestResult]:
    """Veriyi `n_splits` ardışık döneme böler, her dönemde bağımsız bir
    `run_backtest` koşar (her dönem kendi `starting_balance`'ıyla başlar,
    böylece bir önceki dönemin sonucu bir sonrakini etkilemez ve dönemler
    doğrudan karşılaştırılabilir kalır). Sonuç listesi kronolojik sıradadır
    — her elemanın `.symbol` alanı "BTC/USDT #1", "BTC/USDT #2" ... şeklinde
    hangi döneme ait olduğunu belirtir.
    """
    min_bars = strategy.required_candles()
    windows = walk_forward_windows(len(df), n_splits, min_bars)
    results = []
    for idx, (start, end) in enumerate(windows, start=1):
        # Her pencereye stratejinin ihtiyaç duyduğu ısınma barlarını da dahil
        # et (window'un ilk barlarında da sinyal üretilebilsin diye), ama
        # sonuçları sadece o pencerenin kendi aralığıyla sınırlı tut.
        warm_start = max(0, start - min_bars)
        window_df = df.iloc[warm_start:end].reset_index(drop=True)
        result = run_backtest(
            window_df, strategy, f"{symbol} #{idx}",
            starting_balance=starting_balance, stake_fraction=stake_fraction,
            fee_pct=fee_pct, slippage_pct=slippage_pct, risk_config=risk_config,
        )
        results.append(result)
    return results


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV'de eksik kolonlar: {missing}")
    return df
