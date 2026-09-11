"""ccxt üzerinden borsa erişimi. `dry_run=True` iken sadece fiyat/mum verisi
çekilir, emir gönderilmez (emirler Portfolio tarafından simüle edilir).
`dry_run=False` + gerçek API anahtarı verildiğinde gerçek emir gönderir —
bunu açmadan önce haftalarca dry-run/backtest sonucun pozitif olsun.
"""
from __future__ import annotations

import logging
import time

import pandas as pd

try:
    import ccxt  # type: ignore
except ImportError:  # ccxt sadece gerçek borsa/canlı veri çekerken gerekli
    ccxt = None

log = logging.getLogger(__name__)


def _with_retry(fn, attempts: int = 3, base_delay: float = 2.0):
    """DNS/ağ anlık kesintileri (Docker Desktop'ta sık görülür) için basit
    retry — 3 denemede de başarısız olursa hatayı normal şekilde yükseltir,
    engine.py zaten bir sonraki döngüde tekrar dener."""
    last_exc = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - ccxt/requests farklı hata tipleri fırlatabilir
            last_exc = exc
            if i < attempts - 1:
                delay = base_delay * (2 ** i)
                log.warning("Ağ hatası (deneme %d/%d), %.0fs sonra tekrar: %s", i + 1, attempts, delay, exc)
                time.sleep(delay)
    raise last_exc


class ExchangeClient:
    def __init__(self, exchange_name: str, api_key: str = "", api_secret: str = "", dry_run: bool = True):
        self.dry_run = dry_run
        self.exchange_name = exchange_name
        self._client = None
        if ccxt is not None:
            exchange_cls = getattr(ccxt, exchange_name)
            self._client = exchange_cls({
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
            })

    def _require_client(self):
        if self._client is None:
            raise RuntimeError(
                "ccxt kurulu değil — `pip install ccxt` ile kur "
                "(gerçek veri/emir olmadan sadece backtest/CSV ile çalışabilirsin)."
            )
        return self._client

    def fetch_ohlcv_df(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> pd.DataFrame:
        client = self._require_client()
        raw = client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df

    def last_price(self, symbol: str) -> float:
        client = self._require_client()
        ticker = client.fetch_ticker(symbol)
        return float(ticker["last"])

    def fetch_free_balance(self, currency: str) -> float:
        """Borsadaki GERÇEK kullanılabilir bakiyeyi çeker (stake_currency,
        örn. USDT). Sadece canlı modda (dry_run=False) anlamlı — dry-run'da
        `dry_run_wallet` config değeri kullanılmaya devam eder.

        Faz 5: `_live_order_qty` artık bunu kullanıyor, önceden
        `dry_run_wallet`'ı baz alıyordu (bkz. CHANGELOG 'Faz 5')."""
        client = self._require_client()
        balance = _with_retry(client.fetch_balance)
        free = balance.get("free", {}) if isinstance(balance, dict) else {}
        return float(free.get(currency, 0.0) or 0.0)

    def create_market_order(self, symbol: str, side: str, qty: float) -> dict:
        """Sadece dry_run=False iken çağrılmalı — gerçek para hareket eder."""
        if self.dry_run:
            raise RuntimeError("dry_run=True iken gerçek emir gönderilmez — Portfolio kullan.")
        client = self._require_client()
        return client.create_order(symbol, "market", side, qty)