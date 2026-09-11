"""Ana döngü: her `poll_interval_seconds`'ta bir, her pair için mum verisini
çek -> stratejiye sor -> sinyali uygula (dry-run: Portfolio, canlı: gerçek
emir) -> Telegram'a bildir -> equity'yi logla. Backtest de aynı stratejiyi
kullanır (bkz. backtest.py) — tek fark veri kaynağı ve emir uygulaması.
"""
from __future__ import annotations

import logging
import time

from omnitrade.config import Config
from omnitrade.exchange import ExchangeClient
from omnitrade.notifier.telegram import TelegramNotifier
from omnitrade.portfolio import Portfolio
from omnitrade.storage import Storage
from omnitrade.strategies import get_strategy

log = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self, config: Config):
        self.config = config
        self.storage = Storage(config.db_path)
        self.strategy = get_strategy(config.strategy)
        self.exchange = ExchangeClient(
            config.exchange.name, config.exchange.api_key, config.exchange.api_secret,
            dry_run=config.dry_run,
        )
        self.notifier = TelegramNotifier(
            config.telegram.token, config.telegram.chat_id, enabled=config.telegram.enabled,
        )
        self.portfolio = Portfolio(self.storage, config.dry_run_wallet) if config.dry_run else None

    def run_once(self) -> None:
        last_prices: dict[str, float] = {}
        for symbol in self.config.pairs:
            df = self.exchange.fetch_ohlcv_df(
                symbol, timeframe=self.config.timeframe,
                limit=max(self.strategy.required_candles() + 10, 100),
            )
            price = float(df["close"].iloc[-1])
            last_prices[symbol] = price

            signal = self.strategy.generate_signal(df, symbol)
            log.info("%s -> %s (%s)", symbol, signal.action.value, signal.reason)

            if signal.action.value == "hold":
                continue

            if self.config.dry_run:
                self.portfolio.apply_signal(signal, price)
            else:
                qty = self._live_order_qty(symbol, price)
                if qty > 0:
                    self.exchange.create_market_order(symbol, signal.action.value, qty)
                    self.storage.log_trade(symbol, signal.action.value, price, qty, signal.reason, dry_run=False)

            self.notifier.trade_alert(signal.action.value, symbol, price, 0.0, signal.reason)

        if self.config.dry_run:
            self.portfolio.snapshot(last_prices)

    def _live_order_qty(self, symbol: str, price: float) -> float:
        # TODO: canlıya geçerken gerçek risk/pozisyon büyüklüğü mantığı buraya
        raise NotImplementedError("Canlı emir büyüklüğü hesaplaması henüz yazılmadı — önce dry-run'da doğrula.")

    def run_forever(self) -> None:
        self.notifier.send(f"OmniTrade bot başladı (dry_run={self.config.dry_run})")
        while True:
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001
                log.exception("Döngüde hata: %s", exc)
                self.notifier.send(f"⚠️ Bot hatası: {exc}")
            time.sleep(self.config.poll_interval_seconds)
