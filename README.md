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

- `engine.py` içindeki `_live_order_qty` artık `RiskManager` üzerinden gerçek
  bir hesaplama yapıyor, ama `config.yaml`'da `live_trading_confirmed: true`
  set etmeden çalışmaz — `dry_run: false` yapmak TEK BAŞINA yeterli değil,
  bu ikinci bir bilinçli onay adımı. Ayrıca şu anki implementasyon gerçek
  borsa bakiyeni değil `dry_run_wallet` değerini baz alıyor — canlıya
  geçmeden önce bunu gerçek bakiye çekecek şekilde tamamlamalısın (kod
  içindeki yorumda detay var).
- `risk:` bölümünde `max_position_pct`, `max_open_positions`,
  `stop_loss_pct`, `take_profit_pct`, `max_daily_loss_pct` ayarlarını
  ihtiyacına göre gözden geçir — varsayılanlar güvenli tarafta ama körü
  körüne güvenme.
- Gerçek para öncesi en az birkaç hafta dry-run'da pozitif sonuç görmeden
  canlıya geçme, tercihen farklı piyasa koşullarında (yükseliş/düşüş/yatay).
- Detaylı yol haritası ve gerekçeler için `CHANGELOG.md`'ye bak.

## Testler

```bash
python -m unittest discover -s tests -v
```

29 test şu an hazır (strateji sinyalleri, risk yönetimi, portföy al/sat
mantığı + komisyon/slippage, backtest uçtan uca ve farklı piyasa rejimleri)
— hepsi ağdan bağımsız, saniyeler içinde çalışır.

## Geliştirme geçmişi

Projede yapılan geliştirmeler faz faz `CHANGELOG.md` dosyasında
belgeleniyor — her fazın neden yapıldığı, hangi dosyaların değiştiği ve
sırada ne olduğu orada.

## Lisans

AGPL-3.0
