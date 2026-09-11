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
from omnitrade.risk import RiskManager
from omnitrade.storage import Storage
from omnitrade.strategies import get_strategy

log = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self, config: Config):
        self.config = config
        self.storage = Storage(config.db_path)
        self.strategy = get_strategy(config.strategy, config.strategy_params)
        # Faz 4: coin başına strateji override'ı. `config.pair_strategies`'te
        # olmayan pariteler `self.strategy` (varsayılan) kullanmaya devam
        # eder — bkz. run_once()'daki `self.strategies.get(symbol, self.strategy)`.
        self.strategies = {
            symbol: get_strategy(spec["strategy"], spec.get("params", {}))
            for symbol, spec in config.pair_strategies.items()
        }
        self.exchange = ExchangeClient(
            config.exchange.name, config.exchange.api_key, config.exchange.api_secret,
            dry_run=config.dry_run,
        )
        self.notifier = TelegramNotifier(
            config.telegram.token, config.telegram.chat_id, enabled=config.telegram.enabled,
        )
        self.portfolio = (
            Portfolio(
                self.storage, config.dry_run_wallet, risk_config=config.risk,
                fee_pct=config.fee_pct, slippage_pct=config.slippage_pct,
            )
            if config.dry_run else None
        )
        # Canlı modda da aynı risk kurallarıyla pozisyon büyüklüğü hesaplanır.
        self.live_risk = RiskManager(config.risk)
        self._live_open_positions: set[str] = set()

    def run_once(self) -> None:
        last_prices: dict[str, float] = {}
        for symbol in self.config.pairs:
            strategy = self.strategies.get(symbol, self.strategy)
            df = self.exchange.fetch_ohlcv_df(
                symbol, timeframe=self.config.timeframe,
                limit=max(strategy.required_candles() + 10, 100),
            )
            price = float(df["close"].iloc[-1])
            last_prices[symbol] = price

            signal = strategy.generate_signal(df, symbol)
            log.info("%s -> %s (%s)", symbol, signal.action.value, signal.reason)

            if signal.action.value == "hold":
                # Hold sinyalini de kaydet — dashboard'daki "tüm coinler için
                # son sinyal" paneli pozisyon açılmasa da coinin güncel
                # durumunu (ve fiyatını) göstermeli.
                self.storage.log_signal(symbol, signal.action.value, price, signal.reason, executed=False)
                continue

            if self.config.dry_run:
                executed = self.portfolio.apply_signal(signal, price)
            else:
                executed = self._apply_live_signal(signal, price)

            self.storage.log_signal(symbol, signal.action.value, price, signal.reason, executed=executed)

            # Sadece GERÇEKTEN bir işlem olduğunda bildirim gönder. Örn.
            # elinde pozisyon yokken strateji "sell" üretebilir (RSI > 70
            # olduğu her an) — bu durumda apply_signal hiçbir şey yapmaz,
            # dolayısıyla burada da Telegram'a "sell yapıldı" gibi yanıltıcı
            # bir mesaj gitmemeli. Daha önce bu kontrol yoktu (bkz. CHANGELOG).
            if executed:
                self.notifier.trade_alert(signal.action.value, symbol, price, 0.0, signal.reason)

        if self.config.dry_run:
            # Sinyalden bağımsız stop-loss/take-profit kontrolü — bir pozisyon
            # strateji SELL üretmeden de risk limitini aşabilir.
            self.portfolio.check_risk_exits(last_prices)
            self.portfolio.snapshot(last_prices)

        self.storage.beat()

    def _apply_live_signal(self, signal, price: float) -> bool:
        from omnitrade.strategies.base import Action

        if signal.action == Action.BUY and signal.symbol not in self._live_open_positions:
            qty = self._live_order_qty(signal.symbol, price)
            if qty > 0:
                self.exchange.create_market_order(signal.symbol, "buy", qty)
                self.storage.log_trade(signal.symbol, "buy", price, qty, signal.reason, dry_run=False)
                self._live_open_positions.add(signal.symbol)
                return True
        elif signal.action == Action.SELL and signal.symbol in self._live_open_positions:
            qty = self._live_order_qty(signal.symbol, price)
            if qty > 0:
                self.exchange.create_market_order(signal.symbol, "sell", qty)
                self.storage.log_trade(signal.symbol, "sell", price, qty, signal.reason, dry_run=False)
                self._live_open_positions.discard(signal.symbol)
                return True
        return False

    def _live_order_qty(self, symbol: str, price: float) -> float:
        """Risk yönetimini (RiskManager) kullanan canlı emir büyüklüğü hesabı.

        Bilinçli güvenlik freni: sadece `dry_run: false` yetmez — ayrıca
        `live_trading_confirmed: true` de config.yaml'da açıkça set edilmeli.
        Bu, "yanlışlıkla canlıya geçme" riskine karşı ikinci bir bariyer.

        Faz 5: artık `dry_run_wallet` DEĞİL, borsadan çekilen GERÇEK
        `stake_currency` bakiyesi (`exchange.fetch_free_balance`) baz
        alınıyor — önceki implementasyon bilerek sahte bakiyeyi kullanıyordu
        (bkz. CHANGELOG 'Sıradaki fazlar' / Faz 5), bu artık tamamlandı.
        Canlıya geçmeden önce yine de `LIVE_TRADING_CHECKLIST.md`'deki
        adımları uygula.
        """
        if not self.config.live_trading_confirmed:
            raise NotImplementedError(
                "Canlı emir gönderilmeden önce config.yaml'da "
                "`live_trading_confirmed: true` yapman gerekiyor. Bu bilinçli "
                "bir güvenlik freni — önce haftalarca dry-run'da pozitif sonuç "
                "gördüğünden emin ol, sonra bu bayrağı aç."
            )
        balance = self.exchange.fetch_free_balance(self.config.stake_currency)
        stake = self.live_risk.position_stake(balance)
        if stake <= 0:
            return 0.0
        return stake / price

    def run_forever(self) -> None:
        self.notifier.send(f"OmniTrade bot başladı (dry_run={self.config.dry_run})")
        while True:
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001
                log.exception("Döngüde hata: %s", exc)
                self.notifier.system_alert(f"Bot hatası: {exc}")
            time.sleep(self.config.poll_interval_seconds)
