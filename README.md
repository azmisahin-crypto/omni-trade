# OmniTrade

Bulduğun/çevirdiğin stratejileri hızlıca deneyip **gerçekten kazandırıyor mu**
görmek için: backtest + dry-run (sahte para) canlı takip + Telegram bildirimi
+ web dashboard. Hepsi tek, düzenli Python projesinde; ağır bağımlılık yok
(dashboard bile stdlib'le çalışıyor, ekstra kurulum gerektirmiyor).

## Nasıl çalışır (mimari)

```
omnitrade/
├── cli.py            # giriş noktası: run / backtest / web
├── config.py          # config.yaml + .env yükleme
├── strategies/         # <-- yeni strateji eklediğin yer
│   ├── base.py          # Strategy taban sınıfı + Signal tipi
│   └── rsi_strategy.py  # örnek strateji (şablon olarak kullan)
├── exchange.py         # ccxt sarmalayıcı (mum verisi + gerçek emir)
├── portfolio.py        # dry-run cüzdanı: sahte al/sat simülasyonu
├── engine.py            # ana döngü: veri çek -> strateji -> uygula -> bildir
├── backtest.py           # CSV'den geçmiş veriyle offline test
├── storage.py             # SQLite: işlem geçmişi + equity eğrisi
├── notifier/telegram.py   # Telegram Bot API bildirimleri
└── web/                    # dashboard (equity grafiği + işlem tablosu)
```

**Aynı strateji kodu** hem backtest'te hem dry-run'da hem canlıda kullanılır —
çevirip yapıştırdığın bir strateji önce backtest'te, sonra dry-run'da haftalarca
gerçek zamanlı veriyle test edilip iyi sonuç veriyorsa canlıya geçirilir.

## Kurulum

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # Telegram token / borsa anahtarların için
```

## 1. Backtest — önce burada test et

```bash
# Geçmiş veri indir (ccxt kurulu olmalı)
python -c "
import ccxt, pandas as pd
ex = ccxt.binance()
raw = ex.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=1000)
pd.DataFrame(raw, columns=['timestamp','open','high','low','close','volume']).to_csv('data/BTCUSDT_1h.csv', index=False)
"

python -m omnitrade.cli backtest --csv data/BTCUSDT_1h.csv --symbol BTC/USDT
# -> [BTC/USDT] 6 işlem | getiri: +4.73% | kazanma oranı: 83.3% | max drawdown: 2.25%
```

## 2. Dry-run — gerçek zamanlı ama sahte para ile

`config/config.yaml`'da `dry_run: true` (varsayılan zaten böyle):

```bash
python -m omnitrade.cli run
```

Her döngüde: fiyat çeker → strateji sinyal üretir → sahte cüzdanla alır/satar →
Telegram'a bildirim atar → SQLite'a loglar. **Gerçek para hiç dokunulmaz.**

## 3. Dashboard — equity eğrini ve işlemlerini izle (motivasyon için)

```bash
python -m omnitrade.cli web
# http://localhost:8080
```

## 4. Telegram bildirimleri

1. Telegram'da @BotFather'a `/newbot` yaz, token'ı al
2. @userinfobot'a mesaj at, kendi `chat_id`'ini öğren
3. `.env`'e `TELEGRAM_TOKEN` ve `TELEGRAM_CHAT_ID` olarak yapıştır
4. `config/config.yaml`'da `telegram.enabled: true` (varsayılan zaten açık)

## 5. Docker ile sunucuda çalıştırma

```bash
docker compose up -d --build
```

`bot` servisi döngüyü, `web` servisi dashboard'u ayrı container'larda
çalıştırır, ikisi de `data/` klasöründeki aynı SQLite dosyasını paylaşır.

## Yeni strateji ekleme

1. `omnitrade/strategies/rsi_strategy.py`'yi kopyala, yeni isim ver
2. `generate_signal(df, symbol)` içine indikatör + al/sat mantığını yaz
   (bulduğun stratejiyi hangi dilde olursa olsun buraya Python'a çevirerek taşı)
3. `omnitrade/strategies/__init__.py`'daki `STRATEGIES` sözlüğüne ekle
4. `config/config.yaml`'da `strategy: <SinifAdi>` yap
5. Önce `backtest`, sonra `dry-run` ile test et

## ⚠️ Canlıya geçmeden önce

- `engine.py` içindeki `_live_order_qty` metodu bilerek boş bırakıldı
  (`NotImplementedError`) — gerçek risk/pozisyon büyüklüğü mantığını sen
  yazana kadar `dry_run: false` yapılamaz. Bu bilinçli bir güvenlik freni.
- Gerçek para öncesi en az birkaç hafta dry-run'da pozitif sonuç görmeden
  canlıya geçme.

## Testler

```bash
python -m unittest discover -s tests -v
```

8 test şu an hazır (strateji sinyalleri, portföy al/sat mantığı, backtest
uçtan uca) — hepsi ağdan bağımsız, saniyeler içinde çalışır.

## Lisans

AGPL-3.0
