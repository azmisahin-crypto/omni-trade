"""Ana döngü: her `poll_interval_seconds`'ta bir, her pair için mum verisini
çek -> stratejiye sor -> sinyali uygula (dry-run: Portfolio, canlı: gerçek
emir) -> Telegram'a bildir -> equity'yi logla. Backtest de aynı stratejiyi
kullanır (bkz. backtest.py) — tek fark veri kaynağı ve emir uygulaması.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from omnitrade.config import Config, load_config
from omnitrade.exchange import ExchangeClient
from omnitrade.notifier.telegram import TelegramNotifier
from omnitrade.portfolio import Portfolio
from omnitrade.risk import RiskManager
from omnitrade.storage import Storage
from omnitrade.strategies import get_strategy

log = logging.getLogger(__name__)

# Faz 13: hot-reload edilebilen alanlar. Dashboard bu alanları zaten
# `update_pairs`/`update_pair_strategies` ile dosyaya yazıyordu (Faz 10/11)
# — eskiden botun bunu fark etmesi için CONTAINER YENİDEN BAŞLATILMASI
# gerekiyordu. Artık bot her döngüde config.yaml'ın mtime'ını kontrol
# ediyor, değiştiyse burada listelenen alanları çalışırken günceller.
#
# Bilinçli olarak DIŞARIDA bırakılanlar (hâlâ restart gerektirir):
# dry_run, exchange.*, db_path, web_port, live_trading_confirmed.
# Bunların hepsi ya süreç/bağlantı kurulumunu değiştirir (exchange client,
# storage dosyası, HTTP portu) ya da "canlı paraya geçiş" gibi bilinçli bir
# insan onayı gerektirir (bkz. README "Canlıya geçmeden önce"). Bu ikisini
# çalışırken sessizce değiştirmek şaşırtıcı ve riskli olurdu; bunun yerine
# değişiklik algılanırsa log/Telegram uyarısı verilir (bkz. _reload_config_if_changed).
_RESTART_ONLY_FIELDS = ("dry_run", "db_path", "web_port", "live_trading_confirmed")


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

        # Faz 13: config.yaml'ın mtime'ını baz alıyoruz. İlk değer burada
        # (henüz hiçbir döngü çalışmadan) sabitleniyor ki run_once()'daki
        # ilk kontrol "değişiklik var" sanıp gereksiz bir reload denemesi
        # yapmasın — sadece dosya GERÇEKTEN bu ilk andan SONRA değişirse
        # reload tetiklenir.
        self._config_mtime = self._stat_mtime(config.config_path)

    @staticmethod
    def _stat_mtime(path: str) -> float | None:
        try:
            return Path(path).stat().st_mtime
        except OSError:
            return None

    def _reload_config_if_changed(self) -> None:
        """config.yaml diskte değiştiyse (dashboard'daki coin ekle/çıkar ya da
        "backtest sonucunu uygula" panelleri bunu yapar — bkz. web/server.py)
        botu YENİDEN BAŞLATMADAN, çalışırken günceller.

        Önceden (Faz 10/11) bu paneller sadece dosyayı güncelliyordu; botun
        yeni ayarı fark etmesi için container'ın elle yeniden başlatılması
        gerekiyordu. Bu, "her şey dashboard'dan yönetilebilmeli" hedefiyle
        çelişen tek gerçek sürtünme noktasıydı — burada kapatılıyor.

        Stateful nesneler (RiskManager: kill-switch/günlük zarar takibi,
        Portfolio: bakiye/pozisyonlar) kasıtlı olarak YENİDEN
        OLUŞTURULMUYOR, sadece ayarları (`*.config`/`fee_pct` vb.) güncelleniyor
        — aksi halde örn. aktif bir kill-switch, config'teki alakasız bir
        satır değiştiğinde (örn. yeni coin eklenince) sıfırlanıp yeniden
        pozisyon açılmasına izin verebilirdi.
        """
        mtime = self._stat_mtime(self.config.config_path)
        if mtime is None or mtime == self._config_mtime:
            return
        self._config_mtime = mtime

        try:
            fresh = load_config(self.config.config_path)
        except Exception as exc:  # noqa: BLE001
            log.exception("config.yaml yeniden yüklenirken hata, mevcut ayarlarla devam ediliyor: %s", exc)
            return

        restart_needed = [
            field for field in _RESTART_ONLY_FIELDS
            if getattr(fresh, field) != getattr(self.config, field)
        ]
        if (fresh.exchange.name, fresh.exchange.api_key, fresh.exchange.api_secret) != (
            self.config.exchange.name, self.config.exchange.api_key, self.config.exchange.api_secret,
        ):
            restart_needed.append("exchange")
        if restart_needed:
            msg = (
                f"config.yaml'da {', '.join(restart_needed)} değişti ama bu alanlar "
                "çalışırken uygulanamaz (bkz. engine.py _RESTART_ONLY_FIELDS) — "
                "etkili olması için container'ın yeniden başlatılması gerekiyor."
            )
            log.warning(msg)
            self.notifier.system_alert(msg)

        added = sorted(set(fresh.pairs) - set(self.config.pairs))
        removed = sorted(set(self.config.pairs) - set(fresh.pairs))

        self.config.pairs = fresh.pairs
        self.config.pair_strategies = fresh.pair_strategies
        self.config.strategy = fresh.strategy
        self.config.strategy_params = fresh.strategy_params
        self.config.poll_interval_seconds = fresh.poll_interval_seconds
        self.config.fee_pct = fresh.fee_pct
        self.config.slippage_pct = fresh.slippage_pct
        self.config.risk = fresh.risk
        self.config.telegram = fresh.telegram

        self.strategy = get_strategy(fresh.strategy, fresh.strategy_params)
        self.strategies = {
            symbol: get_strategy(spec["strategy"], spec.get("params", {}))
            for symbol, spec in fresh.pair_strategies.items()
        }
        # RiskManager'ı yeniden yaratmak yerine sadece config'ini değiştir —
        # kill-switch/günlük başlangıç equity durumu (bkz. risk.py) korunur.
        self.live_risk.config = fresh.risk
        if self.portfolio is not None:
            self.portfolio.risk.config = fresh.risk
            self.portfolio.fee_pct = fresh.fee_pct
            self.portfolio.slippage_pct = fresh.slippage_pct

        summary = "config.yaml değişikliği canlı olarak uygulandı."
        if added:
            summary += f" Eklenen coin: {', '.join(added)}."
        if removed:
            summary += f" Çıkarılan coin: {', '.join(removed)}."
        log.info(summary)
        self.notifier.system_alert(summary)

    def run_once(self) -> None:
        self._reload_config_if_changed()
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
                # durumunu (ve fiyatını) göstermeli. `strategy=strategy.name`
                # eklendi: dashboard artık bu sinyali hangi stratejinin
                # ürettiğini gösterebiliyor (bkz. storage.py migration).
                self.storage.log_signal(
                    symbol, signal.action.value, price, signal.reason,
                    executed=False, strategy=strategy.name,
                )
                continue

            if self.config.dry_run:
                executed, qty = self.portfolio.apply_signal(signal, price)
            else:
                executed, qty = self._apply_live_signal(signal, price)

            self.storage.log_signal(
                symbol, signal.action.value, price, signal.reason,
                executed=executed, strategy=strategy.name,
            )

            # Sadece GERÇEKTEN bir işlem olduğunda bildirim gönder. Örn.
            # elinde pozisyon yokken strateji "sell" üretebilir (RSI > 70
            # olduğu her an) — bu durumda apply_signal hiçbir şey yapmaz,
            # dolayısıyla burada da Telegram'a "sell yapıldı" gibi yanıltıcı
            # bir mesaj gitmemeli. Daha önce bu kontrol yoktu (bkz. CHANGELOG).
            # FIX: qty artık apply_signal/_apply_live_signal'dan gerçek
            # değeriyle geliyor — önceden burada sabit 0.0 gönderiliyordu,
            # bu yüzden Telegram'da "Miktar: 0.000000" görünüyordu.
            if executed:
                self.notifier.trade_alert(signal.action.value, symbol, price, qty, signal.reason)

        if self.config.dry_run:
            # Sinyalden bağımsız stop-loss/take-profit kontrolü — bir pozisyon
            # strateji SELL üretmeden de risk limitini aşabilir.
            # FIX: bu kapanışlar önceden hiçbir yere bildirilmiyordu (sessizce
            # oluyordu) — artık her zorunlu kapanış için de Telegram'a gidiyor.
            for closed_symbol, closed_price, closed_qty, closed_reason in self.portfolio.check_risk_exits(last_prices):
                self.notifier.trade_alert("sell", closed_symbol, closed_price, closed_qty, closed_reason)
            self.portfolio.snapshot(last_prices)

        self.storage.beat()

    def _apply_live_signal(self, signal, price: float) -> tuple[bool, float]:
        from omnitrade.strategies.base import Action

        if signal.action == Action.BUY and signal.symbol not in self._live_open_positions:
            qty = self._live_order_qty(signal.symbol, price)
            if qty > 0:
                self.exchange.create_market_order(signal.symbol, "buy", qty)
                self.storage.log_trade(signal.symbol, "buy", price, qty, signal.reason, dry_run=False)
                self._live_open_positions.add(signal.symbol)
                return True, qty
        elif signal.action == Action.SELL and signal.symbol in self._live_open_positions:
            qty = self._live_order_qty(signal.symbol, price)
            if qty > 0:
                self.exchange.create_market_order(signal.symbol, "sell", qty)
                self.storage.log_trade(signal.symbol, "sell", price, qty, signal.reason, dry_run=False)
                self._live_open_positions.discard(signal.symbol)
                return True, qty
        return False, 0.0

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
