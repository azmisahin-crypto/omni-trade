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

Backtest artık `config.yaml`'daki `risk` bölümünü (stop-loss/take-profit/
pozisyon limiti) dry-run ile aynı şekilde uygular, sonuçlar gerçekten
karşılaştırılabilir olsun diye. Eski basit davranış için `--no-risk`.

### Walk-forward — overfitting kontrolü

Bir stratejinin tek bir dönemde iyi çıkması şans eseri olabilir. Veriyi N
ardışık, örtüşmeyen döneme bölüp her birinde bağımsız backtest çalıştırmak
için:

```bash
python -m omnitrade.cli backtest --csv data/BTCUSDT_1h.csv --symbol BTC/USDT --walk-forward 4
# -> her dönem için ayrı sonuç satırı, ardından
# --- 4 dönem özeti: ortalama getiri +2.10% | en kötü dönem -1.40% | en iyi dönem +5.80% ---
```

Strateji dönemler arasında tutarlı sonuç veriyorsa (hepsi pozitif ya da
en azından aynı yönde), tek dönemlik backtest'e göre daha güvenilir bir
sinyal. `N>=2` olmalı ve yeterli veri yoksa uyarı verip çıkar.

**Alternatif — terminale hiç dokunmadan:** dashboard'daki "Strateji Test
Et" panelinden aynı walk-forward'ı çalıştırabilirsin (bkz. aşağıdaki
Dashboard bölümü) — CSV indirmen gerekmez, borsadan canlı veri çeker.

## 2. Dry-run — gerçek zamanlı ama sahte para ile

`config/config.yaml`'da `dry_run: true` (varsayılan zaten böyle):

```bash
python -m omnitrade.cli run
```

Her döngüde: fiyat çeker → strateji sinyal üretir → sahte cüzdanla alır/satar →
Telegram'a bildirim atar → SQLite'a loglar (üretilen her sinyal `hold` dahil
`signals` tablosuna, gerçekleşen işlemler ayrıca `trades` tablosuna).
**Gerçek para hiç dokunulmaz.**

Log ayrıntısını `config.yaml`'daki `log_level` ile ayarlayabilirsin
(`DEBUG`/`INFO`/`WARNING`/`ERROR`, varsayılan `INFO`) — hem `run` hem `web`
komutu bunu kullanır.

## 3. Dashboard — equity eğrini ve işlemlerini izle (motivasyon için)

```bash
python -m omnitrade.cli web
# http://localhost:8080
```

Dashboard artık şunları da gösterir:

- **Tüm coinler — son sinyal paneli**: `pairs`'teki her coin için, pozisyon
  açılmış olsun olmasın, en son üretilen sinyal (LONG/SHORT/HOLD rozetli
  kart). Strateji her döngüde bir sinyal üretir ama `Portfolio` bunu
  pozisyon kurallarına göre uygulayıp uygulamamaya karar verir — bu panel
  "strateji ne düşünüyor"yu, gerçekte işlem açılıp açılmadığından bağımsız
  gösterir. Bir karta tıklayınca o coin için fiyat + sinyal işaretli grafik
  açılır (`/api/signals/history?symbol=...`).
- **Özet istatistik kartları + drawdown grafiği**: toplam getiri, kazanma
  oranı, kapanan işlem sayısı, max drawdown (`/api/stats`,
  `omnitrade/stats.py`). Kazanma oranı hesabı `buy_blocked` gibi
  gerçekleşmemiş kayıtları hariç tutar.
- **Strateji Test Et (Backtest / Walk-Forward)**: coin seç, mum sayısı ve
  dönem sayısını gir, "Çalıştır"a bas — terminale hiç dokunmadan borsadan
  canlı geçmiş veri çekip walk-forward backtest çalıştırır ve sonucu
  (dönem başına getiri/kazanma oranı/max drawdown + ortalama/en iyi/en
  kötü dönem) tabloda gösterir. Varsayılan olarak o coin için o an canlıda
  çalışan strateji/parametreleri kullanır (`pair_strategies` override'ı
  dahil); RSI periyodu/eşiklerini formdan değiştirip deneme yapabilirsin,
  bu canlı config'i **etkilemez** — sadece o tek isteğe özel. Aynı mantığı
  `omnitrade/backtest.py` sağlıyor (CLI'daki `backtest` komutuyla birebir
  aynı kod), sadece tetikleme yolu artık `POST /api/backtest`. Borsadan
  veri çekmek birkaç saniye sürebilir; bu sırada dashboard'un normal
  yenilenmesi bloklanmaz (`ThreadingHTTPServer`).

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
Her iki servis de küçük VM'lerde (bkz. aşağıdaki e2-micro bölümü) OOM'u
önlemek için `mem_limit`e sahip, loglar da diski doldurmasın diye
döndürülüyor (`max-size: 10m`, `max-file: 3`).

### GCP e2-micro (1 vCPU, 1GB RAM) üzerinde çalıştırma

1. **Swap kur** (Docker + Python botu 1GB RAM'de dar olabilir):
   ```bash
   sudo bash scripts/setup_swap.sh   # 2GB swap dosyası, kalıcı (fstab)
   ```
2. **Firewall**: `8080` portunu dışarı hiç açma — `docker-compose.yml`
   dashboard'u zaten sadece `127.0.0.1:8080`'e bağlıyor. GCP'de VPC
   firewall kuralında da yalnızca SSH (22) inbound açık olsun, 8080'i
   hiç eklemene gerek yok.
3. **Dashboard'a erişim**: SSH tüneli ile local makinenden bağlan, VM'de
   port dışarı açmadan:
   ```bash
   ssh -L 8080:localhost:8080 kullanici@vm-ip
   # sonra local tarayıcıda http://localhost:8080
   ```
4. **Deploy**:
   ```bash
   git clone <repo-url> && cd omni-trade
   cp .env.example .env   # token/anahtarları doldur
   bash deploy.sh          # git pull + docker compose up -d --build
   ```
   Sonraki güncellemelerde de sadece `bash deploy.sh` yeterli.
5. **Healthcheck (opsiyonel ama önerilir)**: bot çökerse/takılırsa
   Telegram'a haber verip container'ı otomatik restart eder — host'ta
   (container içinde değil) cron'a ekle:
   ```bash
   crontab -e
   # aşağıdaki satırı ekle:
   */5 * * * * cd /path/to/omni-trade && python3 scripts/healthcheck.py >> data/healthcheck.log 2>&1
   ```
6. **Günlük yedek (önerilir)**: `scripts/backup_db.sh`, `sqlite3 .backup`
   kullanır (WAL modunda çalıştığı için doğrudan `cp`'den daha güvenli —
   yazma sırasında yarım/bozuk kopya riski taşımaz). Cron'a ekle:
   ```bash
   crontab -e
   # her gün 03:00'te yedek al, 14 günden eski yedekleri temizle:
   0 3 * * * cd /path/to/omni-trade && bash scripts/backup_db.sh >> data/backup.log 2>&1
   5 3 * * * find /path/to/omni-trade/data/backups -name 'omnitrade_*.db' -mtime +14 -delete
   ```

## Yeni strateji ekleme

1. `omnitrade/strategies/rsi_strategy.py`'yi kopyala, yeni isim ver
2. `generate_signal(df, symbol)` içine indikatör + al/sat mantığını yaz
   (bulduğun stratejiyi hangi dilde olursa olsun buraya Python'a çevirerek taşı)
3. `omnitrade/strategies/__init__.py`'daki `STRATEGIES` sözlüğüne ekle
4. `config/config.yaml`'da `strategy: <SinifAdi>` yap
5. Önce `backtest`, sonra `dry-run` ile test et

### Coin başına farklı strateji/parametre (`pair_strategies`)

Her coin aynı stratejiyi ya da aynı parametreleri kullanmak zorunda değil.
`config.yaml`'da `strategy`/`strategy_params` genel varsayılanı belirler;
`pair_strategies` ile belirli bir coin için bunu override edebilirsin,
listelenmeyen coinler varsayılanı kullanmaya devam eder:

```yaml
pair_strategies:
  ETH/USDT:
    strategy: RsiStrategy
    params:
      period: 21          # BTC için 14, ETH için daha yavaş/az gürültülü
      oversold: 25
      overbought: 75
```

Not: bu paralellik thread/process bazlı değil — tek döngüde her coin kendi
strateji örneğiyle sırayla işlenir (stdlib-only, basit mimariyi korumak
için bilinçli bir tasarım tercihi).

## ⚠️ Canlıya geçmeden önce

- `engine.py` içindeki `_live_order_qty` artık `RiskManager` **ve** gerçek
  borsa bakiyesi (`exchange.fetch_free_balance`) üzerinden hesaplama
  yapıyor — önceki sürümde bilerek sahte `dry_run_wallet` baz alınıyordu,
  bu artık tamamlandı. Yine de `config.yaml`'da `live_trading_confirmed:
  true` set etmeden çalışmaz — `dry_run: false` yapmak TEK BAŞINA yeterli
  değil, bu ikinci bir bilinçli onay adımı.
- `risk:` bölümünde `max_position_pct`, `max_open_positions`,
  `stop_loss_pct`, `take_profit_pct`, `max_daily_loss_pct` ayarlarını
  ihtiyacına göre gözden geçir — varsayılanlar güvenli tarafta ama körü
  körüne güvenme.
- Stratejini `--walk-forward` ile birden fazla dönemde doğrula (yukarıya
  bak) — tek dönemlik iyi sonuç yetmez.
- Gerçek para öncesi en az birkaç hafta dry-run'da pozitif sonuç görmeden
  canlıya geçme, tercihen farklı piyasa koşullarında (yükseliş/düşüş/yatay).
- Borsa API anahtarında **withdrawal (para çekme) izni kapalı** olsun —
  sadece trade izni yeterli.
- Ayrıntılı go/no-go kontrol listesi için `LIVE_TRADING_CHECKLIST.md`'ye,
  gerekçeler için `CHANGELOG.md`'ye bak.

## Testler

```bash
python -m unittest discover -s tests -v
```

85 test şu an hazır (strateji sinyalleri, risk yönetimi, portföy al/sat
mantığı + komisyon/slippage, backtest uçtan uca + risk entegrasyonu +
walk-forward, config yükleme, canlı-emir güvenlik freni (gerçek bakiye
dahil), healthcheck script'i, sinyal loglama, özet istatistik/drawdown,
coin başına strateji override, dashboard HTTP endpoint'leri — backtest
dahil) — hepsi ağdan bağımsız (borsa çağrıları mock'lanır), saniyeler
içinde çalışır. CI'da (`.github/workflows/tests.yml`) her push/PR'da
otomatik çalışır.

## Geliştirme geçmişi

Projede yapılan geliştirmeler faz faz `CHANGELOG.md` dosyasında
belgeleniyor — her fazın neden yapıldığı, hangi dosyaların değiştiği ve
sırada ne olduğu orada.

## Lisans

AGPL-3.0
