# CHANGELOG

Bu dosya, OmniTrade üzerinde yapılan geliştirmeleri faz faz takip eder.
Amaç: projeye sonradan bakacak herkesin (bu, gelecekteki sen de olabilir,
başka bir geliştirici de) "ne yapıldı, neden yapıldı, sırada ne var"
sorularına hızlıca cevap bulabilmesi.

Planlanan 6 fazın (0–5) tamamı, aradaki iki düzeltme fazı (1.5, 2.5) ve
Faz 3/4/5 ile birlikte gelen "sinyal görünürlüğü" özelliğiyle birlikte
tamamlandı. Yeni bir faz/özellik planlanırsa buraya aynı formatta
eklenmeli — "Nasıl devam edilir" bölümü en altta.

---

## Faz 0 — Temel sağlamlaştırma ✅ Tamamlandı

**Neden:** Backtest ve dry-run sonuçları gerçekçi değildi (komisyon/slippage
eksikti), risk yönetimi hiç yoktu (tek pozisyon büyüklüğü kuralı vardı,
stop-loss/kill-switch yoktu), ve SQLite iki container tarafından eşzamanlı
kullanılırken kilitlenme riski taşıyordu.

**Değişenler:**

- **`omnitrade/risk.py` (yeni dosya)** — `RiskConfig` + `RiskManager`:
  - `max_position_pct`: bakiyenin en fazla yüzde kaçı tek pozisyona gider
  - `max_open_positions`: aynı anda açık olabilecek pozisyon sayısı sınırı
  - `stop_loss_pct` / `take_profit_pct`: pozisyon bazlı otomatik çıkış
  - `max_daily_loss_pct`: günlük equity kaybı bu eşiği geçerse **kill-switch**
    aktive olur, o gün yeni pozisyon açılmaz (UTC gün sınırında sıfırlanır)

- **`omnitrade/portfolio.py`** — yeniden yazıldı:
  - `fee_pct` + `slippage_pct` artık gerçekten uygulanıyor (önceden dry-run'da
    hiç yoktu, sadece backtest'te fee vardı — ikisi tutarsızdı)
  - `RiskManager` entegre edildi: yeni pozisyon açmadan önce
    `can_open_position()` kontrolü, `check_risk_exits()` ile her döngüde
    stop-loss/take-profit taraması
  - **Not:** `Portfolio.__init__` imzası değişti — artık `stake_fraction`
    yerine `risk_config: RiskConfig` alıyor. Bu dosyayı elle çağıran başka
    kod varsa (bu repo dışında) güncellenmesi gerekir.

- **`omnitrade/backtest.py`** — `slippage_pct` parametresi eklendi, artık
  dry-run ile aynı maliyet modelini paylaşıyor, sonuçlar karşılaştırılabilir.

- **`omnitrade/storage.py`**:
  - SQLite `WAL` moduna alındı (`PRAGMA journal_mode=WAL`) — `bot` ve `web`
    container'ları aynı dosyaya eşzamanlı erişirken "database is locked"
    riskini azaltır.
  - `heartbeat` tablosu + `beat()` / `last_heartbeat()` metodları eklendi —
    Faz 2'deki healthcheck script'i bunu kullanacak (henüz script yazılmadı).

- **`omnitrade/config.py` + `config/config.yaml`**:
  - Yeni bölümler: `risk`, `fee_pct`, `slippage_pct`, `strategy_params`,
    `live_trading_confirmed`
  - `strategy_params` sayesinde artık RSI period/oversold/overbought gibi
    parametreler kod değiştirmeden config.yaml'dan ayarlanabiliyor.

- **`omnitrade/engine.py`**:
  - Dry-run döngüsüne `check_risk_exits()` çağrısı eklendi (strateji SELL
    üretmese bile stop-loss/take-profit tetiklenebilsin diye)
  - `storage.beat()` her döngü sonunda çağrılıyor (heartbeat)
  - `_live_order_qty` artık **gerçek bir hesaplama içeriyor** (RiskManager
    üzerinden), ama bilinçli olarak `config.live_trading_confirmed: true`
    olmadan çalışmıyor — orijinaldeki "canlıya kazara geçme" güvenlik freni
    korundu, sadece "hiç yazılmamış" halinden "yazılmış ama açıkça onay
    gerektiren" hale getirildi. **ÖNEMLİ:** şu anki implementasyon
    `dry_run_wallet`'ı baz alıyor, gerçek borsa bakiyesini DEĞİL — canlıya
    geçmeden önce bu kısmın gerçek bakiye çekecek şekilde tamamlanması
    gerekiyor (bkz. kod içi yorum).

- **`omnitrade/notifier/telegram.py`**: `system_alert()` eklendi — trade
  sinyalleri ile operasyonel uyarılar (hata, restart vb.) artık ayrı
  prefix'le (`⚙️ SYSTEM:`) ayrışıyor.

- **`omnitrade/strategies/__init__.py`**: `get_strategy()` artık `params`
  dict'i kabul ediyor, config'ten okunan `strategy_params` buraya akıyor.

- **Bulunan ve düzeltilen bug**: `rsi_strategy.py`'deki RSI hesaplaması,
  fiyat tamamen sabit kaldığında (`avg_gain=0, avg_loss=0`, yani 0/0
  belirsizliği) yanlışlıkla RSI=0 hesaplıyordu — bu da sahte bir "aşırı
  satım, AL" sinyaline yol açıyordu. Doğrusu: hareket yoksa RSI nötr (50)
  olmalı. Bunu `test_flat_price_does_not_produce_false_buy_signal` testi
  yazarken yakaladık (bkz. Faz 1). Şimdi düzeltildi.

## Faz 1 — Test ve doğrulama kapsamını genişletme ✅ Tamamlandı

**Neden:** 8 test vardı ama risk yönetimi, komisyon/slippage, farklı piyasa
rejimleri hiç test edilmiyordu. Backtest'in tek bir sembolde 6 işlemlik
sonucuna güvenmek istatistiksel olarak zayıf.

**Değişenler:**

- **`tests/test_risk.py` (yeni)** — 9 test: pozisyon büyüklüğü hesabı, max
  açık pozisyon limiti, stop-loss/take-profit eşikleri, günlük kill-switch
  aktivasyonu/sıfırlanması.
- **`tests/test_portfolio.py`** — yeniden yazıldı, yeni `Portfolio` API'sine
  uyarlandı + 3 yeni test sınıfı: `TestPortfolioCosts` (komisyon/slippage
  gerçekten balance'a yansıyor mu), `TestPortfolioRisk` (risk kuralları
  Portfolio üzerinden uçtan uca çalışıyor mu).
- **`tests/test_backtest.py`** — 3 yeni test: maliyet modelinin sonucu
  gerçekten düşürdüğünü doğrulama, farklı piyasa rejimlerinde (yatay/dalgalı
  vs. sürekli trend) farklı davranış, sıfır-işlem senaryosu (bu test RSI
  bug'ını yakaladı).
- **`tests/test_strategy.py`** — flat-price regresyon testi eklendi.
- **Toplam: 8 → 29 test, hepsi geçiyor** (ccxt kurulu olmadan da — ağdan
  bağımsız, saniyeler içinde çalışıyor, README'deki iddia hâlâ doğru).

**Yapılmadı (bilerek ertelendi):**
- CI (GitHub Actions) workflow'u henüz eklenmedi.
- `tests/test_config.py` yok — config.py'nin yeni alanları (risk, fee_pct
  vb.) için ayrı bir yükleme testi eklenmeli.
- `tests/test_engine.py` yok — `_live_order_qty` ve `live_trading_confirmed`
  bayrağının davranışı hiç test edilmiyor. Bu risk taşıyan bir kod yolu
  olduğu için önceliklendirilmeli.

## Faz 1.5 — backtest/dry-run risk tutarsızlığı düzeltmesi ✅ Tamamlandı

**Neden:** Kapsamlı gözden geçirme sırasında bulundu: Faz 0'da `Portfolio`
(dry-run) `RiskManager`'ı entegre etti (stop-loss/take-profit/pozisyon
limiti), ama `backtest.py` hâlâ eski `stake_fraction` mantığıyla çalışıyordu
— risk çıkışı hiç simüle edilmiyordu. README "aynı strateji + aynı maliyet
modeli, karşılaştırılabilir sonuç" diyor ama gerçekte sadece komisyon/
slippage ortaktı, risk davranışı değil. Bu, backtest'in dry-run'da
göreceğinden **daha iyimser** sonuç vermesine yol açabiliyordu (stop-loss
backtest'te hiç tetiklenmiyordu).

**Değişenler:**

- **`omnitrade/backtest.py`** — `run_backtest()` artık opsiyonel
  `risk_config: RiskConfig | None` parametresi alıyor. Verilirse: her bar'da
  stop-loss/take-profit kontrolü (stratejiden ÖNCE, dry-run
  `Portfolio.check_risk_exits()` ile aynı sırada), pozisyon büyüklüğü
  `risk.position_stake()` ile, günlük kill-switch kontrolü. Verilmezse
  (`None`, varsayılan) eski `stake_fraction` davranışı korunur — geriye
  dönük uyumlu.
- **`omnitrade/cli.py`** — `backtest` komutu artık config'teki `risk`
  bölümünü otomatik kullanır; eski davranışı istersen `--no-risk` bayrağı.
- **`tests/test_backtest.py`** — `TestBacktestRiskIntegration`: stop-loss'un
  gerçekten pozisyonu kapattığını, `max_position_pct`'in stake'i
  sınırladığını, `risk_config=None` iken eski davranışın değişmediğini
  doğrulayan 3 yeni test. Toplam: 29 → 32 test.

---

## Faz 1 — kalan işler ✅ Tamamlandı

**Neden:** Faz 1'in ilk turunda strateji/portföy/backtest test kapsamı
genişletilmişti ama config yükleme ve canlı-emir güvenlik freni hiç test
edilmiyordu — ikincisi özellikle riskli, çünkü gerçek para hareket eden
kod yolu.

**Değişenler:**

- **`tests/test_config.py` (yeni)** — 7 test: config dosyası yokken
  varsayılanlar, `risk` bölümünün doğru parse edilmesi, `take_profit_pct`
  boş bırakıldığında `None` olması, `fee_pct`/`slippage_pct`/
  `strategy_params`, `live_trading_confirmed`, `.env`'deki sırların
  `config.yaml`'dakini override etmesi, `pairs` listesi.
- **`tests/test_engine.py` (yeni)** — 4 test: `_live_order_qty`
  `live_trading_confirmed: false` iken `NotImplementedError` fırlatıyor mu,
  `true` iken `RiskManager` üzerinden doğru miktarı hesaplıyor mu,
  `_apply_live_signal` onay yokken **borsaya emir göndermiyor mu**
  (`create_market_order` hiç çağrılmamalı — yanlışlıkla canlı emir gitme
  riskine karşı en kritik test), onaylıyken doğru çağrılıyor mu.
- **`.github/workflows/tests.yml` (yeni)** — her push/PR'da Python 3.11 ve
  3.12'de `python -m unittest discover -s tests` çalışır. `ccxt` bilerek
  kurulmuyor (README'deki "ağdan bağımsız" iddiası CI'da da doğrulanmış olur).
- **Toplam: 32 → 43 test.**

---

## Faz 2 — Operasyonel dayanıklılık (e2-micro'ya özel) ✅ Tamamlandı

**Neden:** Bot, e2-micro (1 vCPU/1GB RAM) gibi minik bir VM'de 7/24
çalışacak — bellek/disk sınırları aşılırsa ya sessizce çökebilir ya da
tüm VM'i kilitleyebilir, ve çöktüğünde kimse fark etmeyebilir (Telegram
alert'i olmayan bir kod yolu yok).

**Değişenler:**

- **`docker-compose.yml`** — `bot` için `mem_limit: 300m`, `web` için
  `mem_limit: 150m` (aşılırsa OOM-killed olur, `restart: unless-stopped`
  ile geri döner). Ortak `x-logging` anchor'ı ile `json-file` + `max-size:
  10m` / `max-file: 3` — sınırsız log diski doldurmasın diye.
- **`scripts/setup_swap.sh` (yeni)** — 2GB swap dosyası oluşturur,
  `/etc/fstab`'a ekleyip kalıcı yapar, `vm.swappiness=10` ayarlar (swap'ı
  sadece gerçekten gerektiğinde kullansın).
- **`scripts/healthcheck.py` (yeni)** — `Storage.last_heartbeat()`'i
  okur; `poll_interval_seconds`'in 5 katından (varsayılan, `--stale-
  multiplier` ile değiştirilebilir) daha eskiyse `notifier.system_alert()`
  ile Telegram'a haber verip `docker restart omnitrade-bot` çalıştırır.
  Host'ta (container İÇİNDE DEĞİL) cron ile 5 dakikada bir çalıştırılmak
  üzere tasarlandı — container kendi kendini restart edemeyeceği için.
  4 test (`tests/test_healthcheck.py`): taze heartbeat'te restart
  tetiklenmiyor, eski heartbeat'te tetikleniyor, restart başarısız olursa
  exit code 1 + alert, hiç heartbeat yokken (ilk kurulum) hata verilmiyor.
- **`deploy.sh` (yeni)** — `git pull --ff-only && docker compose up -d
  --build`, ardından son logları ve container durumunu gösterir.
- **README** — yeni "GCP e2-micro üzerinde çalıştırma" bölümü: swap
  kurulumu, firewall (8080 asla dışarı açılmamalı — zaten `127.0.0.1`'e
  bağlı), SSH tüneli ile dashboard erişimi, deploy ve healthcheck cron
  kurulumu adım adım.
- **Toplam: 43 → 47 test.**

---

## Faz 2.5 — kritik bug: gerçekleşmeyen işlem için Telegram bildirimi ✅ Tamamlandı

**Nasıl bulundu:** Kullanıcı, canlıda RSI uzun süre 70 üstünde kalınca art
arda "sell" logları ve Telegram bildirimleri görmüş, ama `data/omnitrade.db`
`trades` tablosunda hiç sell kaydı yoktu. Sebebi: `RsiStrategy`, elde
pozisyon olsun olmasın, RSI > 70 olduğu HER an SELL sinyali üretir —
pozisyon kontrolünü strateji değil `Portfolio`/`_apply_live_signal` yapar.
`Portfolio.apply_signal()` pozisyon yokken SELL'i doğru şekilde yok
sayıyordu (hiç `log_trade` çağırmıyordu — kayıtların boş olması BEKLENEN
davranıştı), **ama** `engine.py`'de `run_once()`, sinyal "hold" olmadığı
sürece `notifier.trade_alert()`'i KOŞULSUZ çağırıyordu — `apply_signal`'ın
gerçekten bir şey yapıp yapmadığına hiç bakmadan. Sonuç: hiçbir işlem
olmamasına rağmen Telegram'a "sell yapıldı" gibi okunan yanıltıcı bir mesaj
gidiyordu. Short pozisyon açılmıyor, borsaya hiçbir emir gitmiyor — sadece
bildirim yanlıştı.

Bu bug Faz 0'dan (`db8fdcf`) beri vardı, bu oturumdaki hiçbir değişiklikle
(Faz 1/1.5/2) `engine.py` değiştirilmediği doğrulandı (`git diff` boş) —
yani "eski versiyon"da da hep oradaydı, muhtemelen RSI daha önce bu kadar
uzun süre pozisyonsuzken 70 üstünde takılı kalmadığı için hiç fark
edilmemişti.

**Değişenler:**

- **`omnitrade/portfolio.py`** — `apply_signal()` artık `bool` döner:
  gerçekten bir buy/sell gerçekleşti mi?
- **`omnitrade/engine.py`** — `_apply_live_signal()` de aynı şekilde `bool`
  döner. `run_once()` artık `notifier.trade_alert()`'i sadece `executed ==
  True` iken çağırıyor.
- **Testler:** `tests/test_portfolio.py` içine `TestApplySignalReturnValue`
  (5 test — özellikle pozisyonsuz SELL'in `False` dönmesi VE hiçbir kayıt
  oluşturmaması), `tests/test_engine.py` içine
  `TestRunOnceOnlyNotifiesOnRealTrade` (2 test — pozisyonsuz SELL sinyalinde
  Telegram'a hiç gitmediğini, gerçek BUY'da gittiğini doğrular).
- **Toplam: 47 → 54 test.**

**Not:** Bu, log mesajının kendisi değil (`"BTC/USDT -> sell (RSI=...)"` —
bu sadece stratejinin ne düşündüğünü gösteriyor, doğru), sadece Telegram
bildirimiydi. Loglardaki "sell" mesajını görmeye devam edeceksin (bu
strateji sinyali, normal) — ama artık gerçek bir işlem olmadan Telegram'a
gitmeyecek.

---

### Faz 3 — İzlenebilirlik, Faz 4 — Strateji altyapısı, Faz 5 — Canlıya geçiş
### + Sinyal görünürlüğü (yeni özellik) ✅ Tamamlandı

**Neden bu üçü birlikte:** Kullanıcı dashboard'da "pozisyona girilmese bile
tüm coinler için long/short sinyalleri görme" istedi. İncelemede bunun
zaten Faz 3 (dashboard) ve Faz 4'ün (çoklu parite) doğal kesişiminde
olduğu görüldü, bu yüzden üçü ve yeni özellik tek oturumda birlikte ele
alındı. Kod tarafı bitti ve 73 test yeşil.

**Yeni: Sinyal görünürlüğü**
- **`omnitrade/storage.py`** — yeni `signals` tablosu: her döngüde
  ÜRETİLEN her sinyali tutar (hold dahil, `trades` tablosunun aksine
  pozisyon açılıp açılmadığından bağımsız). `log_signal()`,
  `get_latest_signals()` (coin başına en son sinyal), `get_signals()`
  (coin bazlı geçmiş, grafik için).
- **`omnitrade/engine.py`** — `run_once()` artık her coin için ürettiği
  sinyali (hold dahil) `storage.log_signal()` ile kaydediyor.
- **`omnitrade/web/server.py`** — yeni endpoint'ler: `/api/signals` (tüm
  coinler için son sinyal), `/api/signals/history?symbol=&limit=`,
  `/api/stats` (özet istatistik + drawdown eğrisi, bkz. Faz 3).
- **`omnitrade/web/static/index.html` + `app.js`** — dashboard'a yeni
  "Tüm Coinler — Son Sinyal" paneli (renkli LONG/SHORT/HOLD rozetli
  kartlar, coine tıklayınca fiyat+sinyal işaretli grafik açılıyor).

**Faz 3 — İzlenebilirlik**
- **`omnitrade/stats.py` (yeni)** — `compute_summary_stats()` (toplam
  getiri, kazanma oranı — `buy_blocked` gibi gerçekleşmemiş kayıtlar hariç,
  max drawdown, kapanan işlem sayısı), `compute_drawdown_curve()`. Testler:
  `tests/test_stats.py`.
- **Dashboard** — Özet istatistik kartları + drawdown grafiği eklendi
  (yukarıdaki dosyalarda, `/api/stats` üzerinden besleniyor).
- **`scripts/backup_db.sh` (yeni)** — `sqlite3 .backup` ile günlük yedek
  (WAL modunda çalıştığı için `cp` yerine bilerek `.backup` kullanıyor).
  README'ye cron örneği eklenmedi — **kalan iş**.
- **`omnitrade/config.py` + `cli.py`** — yeni `log_level` config alanı,
  `cmd_run`/`cmd_web` artık bunu `logging`e uyguluyor (önceden sabit INFO'ydu).

**Faz 4 — Strateji altyapısı**
- **`omnitrade/config.py`** — yeni `pair_strategies` alanı: coin başına
  strateji/parametre override'ı (örn. `{"ETH/USDT": {"strategy": "RsiStrategy",
  "params": {"period": 21}}}`). Boş bırakılan pariteler varsayılan
  `strategy`'i kullanmaya devam eder.
- **`omnitrade/engine.py`** — `self.strategies` dict'i, `run_once()`
  `self.strategies.get(symbol, self.strategy)` ile per-pair strateji
  seçiyor (`required_candles()` de per-pair strateji üzerinden hesaplanıyor).
  **Not:** bu paralellik çalışma zamanında thread/process değil — aynı
  tek-thread döngüde her coin kendi strateji instance'ıyla işleniyor
  (bilinçli tasarım: stdlib-only, basit mimariyi korumak için).
- **`omnitrade/backtest.py`** — `walk_forward_windows()` + `run_walk_forward()`:
  veriyi N ardışık, örtüşmeyen döneme bölüp her birinde bağımsız backtest
  koşuyor (overfitting kontrolü). `cli.py`'de `backtest --walk-forward N`
  bayrağı.
- Testler: `tests/test_engine.py::TestPairStrategies`,
  `tests/test_backtest.py::TestWalkForwardWindows`/`TestRunWalkForward`.

**Faz 5 — Canlıya geçiş hazırlığı**
- **`omnitrade/exchange.py`** — yeni `fetch_free_balance(currency)`:
  borsadan gerçek kullanılabilir bakiyeyi çeker (retry'lı).
- **`omnitrade/engine.py`** — `_live_order_qty` artık `dry_run_wallet`
  DEĞİL, `fetch_free_balance` ile çekilen GERÇEK bakiyeyi kullanıyor —
  önceki implementasyon bilerek sahte bakiyeyi baz alıyordu, bu KRİTİK
  eksik artık tamamlandı.
- **`LIVE_TRADING_CHECKLIST.md` (yeni)** — go/no-go kriterleri: strateji
  doğrulama (walk-forward + min. dry-run süresi), risk parametreleri, API
  anahtar izinleri (withdrawal kapalı!), operasyonel hazırlık, son onay.
- Testler: `tests/test_engine.py::TestLiveOrderQty` güncellendi (artık
  `fetch_free_balance` mock'lanıyor).
- **Toplam: 54 → 73 test.**

**Bu oturumda tamamlanan kalan işler:**
- [x] `README.md` güncellendi: yeni dashboard panelleri (son-sinyal paneli
  + özet istatistik/drawdown), `--walk-forward` kullanımı, `pair_strategies`
  örneği, `log_level`, `backup_db.sh` cron örneği, "Canlıya geçmeden önce"
  bölümü gerçek bakiye entegrasyonunu yansıtacak şekilde güncellendi, test
  sayısı 73'e çekildi.
- [x] `config/config.yaml`'a `pair_strategies` (örnek + varsayılan `{}`) ve
  `log_level: INFO` eklendi.
- [x] Bu bölüm "Faz X ✅ Tamamlandı" formatına çevrildi.
- [x] `scripts/backup_db.sh`, gerçek `sqlite3` CLI'ı bu sandbox'ta
  kurulamadığı (ağ erişimi yok) için python'un `sqlite3.Connection.backup()`
  API'sini saran bir CLI shim üzerinden uçtan uca test edildi: WAL modunda
  dolu bir DB'de `.backup` komutunun gerçekten çalışıp tutarlı bir kopya
  ürettiği (signals/heartbeat tabloları dahil) ve DB henüz yokken script'in
  hatasız (`exit 0`, uyarı mesajıyla) çıktığı doğrulandı. Gerçek `sqlite3`
  CLI kurulu bir ortamda tekrar dumanla test edilmesi yine de önerilir —
  shim sadece script'in ürettiği tek komut kalıbını (`.backup '<dest>'`)
  destekliyor, tam CLI'nin yerini tutmaz.
- [x] `git add -A && git commit` — bu oturumun değişiklikleri commit'lendi
  (bkz. `git log`).

---

## Faz 3.6 — kritik bug: dashboard'da sinyal grafiği her poll'da titriyordu ✅ Tamamlandı

**Nasıl bulundu:** Kullanıcı canlı dashboard'ı (`/mnt` dışı, gerçek VM'de)
inceledi, bir coin kartına tıklayıp altındaki fiyat+sinyal grafiğini
izlerken grafiğin birkaç saniyede bir gözle görülür şekilde titrediğini
fark etti.

**Sebep:** `app.js` her 10 saniyede bir `refreshAll()` ile tüm paneli
polluyor. Equity ve drawdown grafikleri bu poll'da veriyi **yerinde**
güncelliyordu (`chart.data.datasets[0].data = ...; chart.update()`), ama
`selectSymbol()` içindeki sinyal grafiği her çağrıldığında
`signalChart.destroy()` yapıp sıfırdan `new Chart(...)` yaratıyordu — coin
değişmese, hatta veri hiç değişmese bile. Chart.js bir grafiği yok edip
yeniden çizdiğinde kısa bir görsel flaş/titreme oluşur; 10 saniyede bir
tekrarlanınca bu rahatsız edici hale geliyordu.

**Değişen:** `omnitrade/web/static/app.js` — yeni `signalChartSymbol`
değişkeni hangi coinin şu an çizili olduğunu takip ediyor. `selectSymbol()`
aynı coin için tekrar çağrıldığında (poll döngüsü, kullanıcı coin
değiştirmedi) artık grafiği yok etmiyor, sadece `labels`/`data`'yı
güncelleyip `chart.update()` çağırıyor. Kullanıcı gerçekten farklı bir
coine tıkladığında (`signalChartSymbol !== symbol`) hâlâ destroy+recreate
yapılıyor — bu durumda zaten gerekli (eksen/legend'ın yeni veriye göre
yeniden kurulması gerekiyor).

**Not:** Python tarafında değişiklik yok, bu saf bir frontend düzeltmesi;
73 test hâlâ geçiyor. Otomatik JS testi bu projede yok (stdlib-only,
ekstra test altyapısı bilerek eklenmedi) — düzeltme `node --check` ile
sözdizimi açısından ve mantık okuması ile doğrulandı.

---

## Faz 6 — dashboard'dan backtest/walk-forward çalıştırma ✅ Tamamlandı

**Neden:** Kullanıcı canlı dashboard'ı gördükten sonra haklı bir soru
sordu: "veriyi zaten veritabanına kaydediyoruz, backtest için niye hâlâ
terminalde CSV indirip komut yazmam gerekiyor — bunu da UI'dan yapsak
olmaz mı?" Cevap: sinyal tablosundaki veri sadece botun ayakta olduğu
süre kadar geriye gidiyor (walk-forward için yetersiz), asıl ihtiyaç
borsadan geçmiş veri çekip backtest'i **tetiklemenin** terminal
gerektirmemesiydi — veri kaynağı değil, arayüz sorunuydu.

**Değişen:**
- `omnitrade/web/server.py`: yeni `POST /api/backtest` endpoint'i. İstek
  gövdesi `{symbol, timeframe?, limit?, walk_forward?, strategy?,
  params?}`; borsadan `ExchangeClient.fetch_ohlcv_df` ile canlı OHLCV
  çeker, `omnitrade/backtest.py`'deki `run_backtest`/`run_walk_forward`'ı
  (CLI'daki `backtest` komutuyla BİREBİR AYNI kod, kopyalanmadı) çalıştırır.
  Varsayılan strateji/parametre önceliği: istekte açıkça verilen >
  `config.pair_strategies[symbol]` > genel `config.strategy`. Hatalar
  (eksik symbol, geçersiz JSON, bilinmeyen strateji, borsa/ağ hatası,
  yetersiz veri) uygun HTTP status'la (400/502/500) JSON hata mesajı
  döner. `serve()`/`make_handler()` artık `config`'i de alıyor (önceden
  sadece `storage` alıyordu) — backtest için `config.exchange`,
  `config.risk`, `config.fee_pct`/`slippage_pct` gerekiyor.
- `omnitrade/web/static/index.html` + `app.js`: "Strateji Test Et"
  paneli — coin seçimi (sinyal panelindeki coinlerden otomatik dolar),
  mum sayısı, dönem sayısı, opsiyonel RSI parametre override'ları,
  "Çalıştır" butonu; sonuç dönem başına tablo + (çok dönemliyse)
  ortalama/en iyi/en kötü özet kartları olarak gösteriliyor. İstek
  sürerken buton disable edilip durum mesajı gösteriliyor (borsadan veri
  çekmek birkaç saniye sürebilir).
- `tests/test_server.py` (**yeni dosya**): `server.py` için önceden hiç
  test yoktu — gerçek bir `ThreadingHTTPServer`'ı ayrı thread'de rastgele
  bir portta ayağa kaldırıp gerçek HTTP istekleri atan 12 test eklendi.
  Hem yeni backtest endpoint'i (başarılı tek/çoklu dönem, eksik symbol,
  bozuk JSON, bilinmeyen strateji, borsa hatası, `pair_strategies`
  override önceliği) hem de önceden test edilmemiş var olan GET
  endpoint'leri (`/`, `/app.js`, `/api/trades`, `/api/equity`,
  `/api/signals`, `/api/signals/history`, `/api/stats`, 404) kapsandı.
  Borsa çağrıları `omnitrade.web.server.ExchangeClient`
  mock'lanarak test ediliyor, gerçek ağ/API anahtarı gerekmiyor.
- **Toplam: 73 → 85 test.**

**Kasıtlı olarak yapılMAYAN:** strateji parametrelerini dashboard'dan
kaydedip canlı config'i değiştirmek (yani "backtest sonucu iyiyse tek
tıkla canlıya uygula"). Bu bilinçli bir sınır: backtest sonucunu görüp
config.yaml'ı elle güncellemek, yanlışlıkla/aceleyle canlı stratejiyi
değiştirmeye karşı bir sürtünme katmanı olarak kalsın istendi. İleride
istenirse ayrı bir onay adımıyla eklenebilir.

---

## Faz 7 — MACD ve Bollinger Bantları stratejileri eklendi ✅ Tamamlandı

**Neden:** Faz 6'daki dashboard'dan backtest/walk-forward özelliği ile
altyapı (backtest, walk-forward, dry-run, risk yönetimi, sinyal görünürlüğü)
tamamlandı, ama gerçekten test edilecek tek strateji `RsiStrategy` idi.
Kullanıcının asıl hedefi — "en düşük parayla en iyi stratejiyi hızlıca
test edip kazandırıyor mu görmek" — birden fazla, birbirinden farklı
mantıkla çalışan stratejiye ihtiyaç duyuyor; tek stratejiyle karşılaştırma
yapılamaz.

**Değişen:**
- `omnitrade/strategies/macd_strategy.py` (**yeni dosya**) — `MacdStrategy`:
  trend-takip mantığı (RSI/Bollinger'ın aksine mean-reversion değil).
  Hızlı EMA(12) yavaş EMA(26)'nın üstündeyken BUY, altındayken SELL.
  Durum bazlı çalışır (RSI ile aynı desen) — `Portfolio.apply_signal`
  zaten açık pozisyon varken tekrar BUY'u, pozisyon yokken SELL'i no-op
  geçtiği için tekrarlanan sinyal fazladan işlem açmaz.
- `omnitrade/strategies/bollinger_strategy.py` (**yeni dosya**) —
  `BollingerStrategy`: RSI'ye ek ikinci bir mean-reversion referansı,
  farklı istatistiksel temelle (hareketli ortalama ± N std sapma).
  Fiyat alt bandın altına inince BUY, üst bandın üstüne çıkınca SELL.
- `omnitrade/strategies/__init__.py`: her iki strateji `STRATEGIES`
  sözlüğüne eklendi — `config.yaml`'da `strategy: MacdStrategy` veya
  `strategy: BollingerStrategy` yazarak ya da `pair_strategies` ile coin
  bazında seçilebilirler; dashboard'daki "Strateji Test Et" panelinden de
  `strategy` alanına isim yazılarak backtest'te denenebilirler.
- `tests/test_strategy.py`: her iki strateji için RSI testleriyle aynı
  desende testler (yetersiz veri → HOLD, sürdürülen trend/bant ihlali →
  doğru sinyal, geçersiz parametre → hata). **Toplam: 85 → 93 test.**

**Kasıtlı olarak yapılMAYAN:** Çoklu strateji/coin sonuçlarını tek ekranda
karşılaştıran bir "leaderboard" paneli — mevcut backtest paneli tek
strateji×coin kombinasyonunu tek seferde çalıştırıyor. Üç strateji ×
birkaç coin manuel denendikten sonra bu gerçekten sık kullanılan bir
akışsa, sıradaki mantıklı adım budur.

---

## Faz 8 — dashboard'daki strateji formu artık backend'den otomatik kuruluyor ✅ Tamamlandı

**Neden:** Faz 7'de `MacdStrategy` ve `BollingerStrategy` eklendi ama
dashboard'daki "Strateji Test Et" formu hâlâ sadece RSI'ye özel 3 alan
(periyot/aşırı satım/aşırı alım) gösteriyordu — yeni stratejiler API
üzerinden (`POST /api/backtest` body'sinde `strategy`+`params`) test
edilebiliyordu ama UI'dan değil. Kullanıcının sorduğu asıl soru buydu:
"stratejileri tek tek eklerken UI'ı da elle mi güncelleyeceğiz, yoksa
otomatik mi gelsin?" Cevap: strateji **mantığı** (indikatör hesabı) kod
olarak kalmalı — bu zaten az kod (~50-70 satır), UI'dan yazılabilir bir
şey değil ve öyle olsa test edilebilirliği azaltır. Ama strateji
**seçimi ve parametre formu** tamamen otomatik olmalı.

**Değişen:**
- `omnitrade/strategies/__init__.py`: yeni `list_strategies()` — her
  kayıtlı stratejinin adını ve `__init__` imzasından introspect edilen
  parametre/varsayılan listesini döndürür. Yeni strateji eklerken tek
  gereken hâlâ `STRATEGIES` sözlüğüne kayıt; frontend'e hiç dokunulmaz.
- `omnitrade/web/server.py`: yeni `GET /api/strategies` endpoint'i,
  `list_strategies()`'i JSON olarak döner.
- `omnitrade/web/static/index.html` + `app.js`: RSI'ye özel 3 hardcoded
  input kaldırıldı. Yerine: sayfa açılışında `/api/strategies` çekilip
  bir strateji dropdown'ı kuruluyor; dropdown değiştiğinde o stratejinin
  parametre alanları (`btParams` container'ı) otomatik render ediliyor.
  "— canlı ayar —" seçiliyse (varsayılan) hiç strateji/params
  gönderilmiyor, önceki davranış (o coin için canlıda çalışan
  strateji/parametreler kullanılır) korunuyor.
- `tests/test_server.py` + `tests/test_strategy.py`: `/api/strategies`
  endpoint'i ve `list_strategies()` için testler. **Toplam: 93 → 95 test.**

**Kasıtlı olarak yapılMAYAN:** Parametre tipleri hâlâ hepsi `number`
varsayılıyor (şu ana kadarki tüm stratejiler sayısal parametre alıyor).
İleride string/bool parametre alan bir strateji eklenirse `list_strategies()`
her parametrenin tipini de döndürecek şekilde genişletilmeli — şimdiden
yapmak spekülatif olurdu.

---

## Faz 9 — çoklu strateji × coin karşılaştırma (leaderboard) ✅ Tamamlandı

**Neden:** Faz 7-8 ile 3 strateji (RSI/MACD/Bollinger) ve bunları UI'dan
otomatik seçebilme geldi, ama "hangisi bu coinde daha iyi" sorusunu
cevaplamak için hâlâ her kombinasyonu tek tek `/api/backtest`'e sokup
sonuçları elle karşılaştırmak gerekiyordu. Hedef "en düşük parayla en
iyi stratejiyi hızlıca bulmak" olduğuna göre, karşılaştırmanın kendisi
de tek işlemlik olmalıydı.

**Değişen:**
- `omnitrade/web/server.py`: yeni `POST /api/backtest/batch` endpoint'i.
  Gövde: `{symbols: [...], strategies: [...], timeframe?, limit?,
  walk_forward?}`. Her sembol için OHLCV verisi **bir kez** çekilir
  (kombinasyon sayısı kadar değil — borsaya gereksiz tekrar istek
  atılmaz), sonra her strateji o veri üzerinde kendi varsayılan
  parametreleriyle çalıştırılır (canlı config'i etkilemez, tek amaç
  kaba/hızlı bir "genel olarak hangisi iyi" sinyali). Sonuçlar ortalama
  getiriye göre azalan sırada döner. Bir kombinasyonda hata olursa
  (bilinmeyen strateji, yetersiz veri) tüm istek değil sadece o satır
  `error` alanıyla işaretlenir — 6 kombinasyondan 1'i patlarsa diğer 5'i
  kaybetmeyelim diye.
- `omnitrade/web/static/index.html` + `app.js`: yeni "Karşılaştırma
  (Leaderboard)" paneli — coin ve strateji çoklu-seçim kutuları
  (varsayılan: hepsi seçili), mum sayısı/dönem sayısı, "Karşılaştır"
  butonu. Sonuç tablosu zaten sıralı geldiği için frontend'de ayrıca
  sıralama yapılmıyor, sadece render ediliyor.
- `tests/test_server.py`: `TestBacktestBatchEndpoint` — eksik
  symbols/strategies → 400, sembol başına tek fetch (mock call_count
  ile doğrulanıyor), sıralamanın doğruluğu, kombinasyon bazlı hata
  izolasyonu, borsa hatası → 502. **Toplam: 95 → 100 test.**

**Kasıtlı olarak yapılMAYAN:** Leaderboard'daki sonuçları tek tıkla
`pair_strategies`'e (canlı config) yazma — bu hâlâ Faz 11'in işi,
burada sadece keşif/karşılaştırma var.

---

## Faz 10 — dashboard'dan coin ekle/çıkar ✅ Tamamlandı

**Neden:** Faz 6-9 ile backtest/walk-forward/leaderboard tamamen UI'dan
yapılabilir hale geldi, ama hangi coinlerin botun izlediği listede
(`config.yaml`'daki `pairs`) olduğunu değiştirmek hâlâ SSH'lanıp dosyayı
elle düzenlemeyi gerektiriyordu — "en düşük parayla en iyi stratejiyi
hızlıca test etmek" hedefine göre bu gereksiz bir sürtünmeydi, özellikle
leaderboard'da denenmemiş yeni bir coin görmek isteyince.

**Değişen:**
- **`omnitrade/config.py`**:
  - `normalize_pair(symbol)` — `"btc/usdt"` gibi girdileri `"BTC/USDT"`'ye
    çevirir, format (`BAZ/QUOTE`) geçersizse `ValueError` fırlatır. Borsanın
    gerçekten bu pariteyi listelediğini KONTROL ETMEZ (ağ isteği
    gerektirir) — sadece bariz yazım hatalarını yakalar.
  - `update_pairs(config_path, pairs)` — `config.yaml`'daki `pairs:`
    bloğunu YERİNDE (regex ile) değiştirir, dosyanın geri kalanındaki
    yorumları/bölümleri korur. Bilerek `yaml.safe_dump` ile tüm dosyayı
    yeniden yazMAdık — bu, config.yaml'daki tüm açıklama yorumlarını
    silerdi.
  - `Config` artık `config_path` alanı taşıyor (`load_config()` tarafından
    set edilir) — `update_pairs()`'ın hangi dosyaya yazacağını bilmesi için.
- **`omnitrade/web/server.py`**: yeni `GET /api/config/pairs` (mevcut
  listeyi döner) ve `POST /api/config/pairs` (`{"symbol", "action":
  "add"|"remove"}`) endpoint'leri. Kurallar: aynı coin iki kez eklenemez,
  son coin silinemez (en az 1 parite kalmalı), geçersiz format/aksiyon
  400 döner. Başarılı yanıt her zaman `restart_required: true` +
  kullanıcıya gösterilecek bir mesaj içerir.
- **`omnitrade/web/static/index.html` + `app.js`**: yeni "Coin Yönetimi"
  paneli — mevcut coinler çip/rozet olarak listelenir (her birinde ×
  butonu), altında yeni coin eklemek için input + buton. İşlem sonrası
  durum mesajı (başarı ya da hata) gösterilir.
- Testler: `tests/test_config.py::TestNormalizePair` +
  `TestUpdatePairs` (9 test), `tests/test_server.py::TestConfigPairsEndpoint`
  (9 test, gerçek HTTP istekleriyle — GET, add/remove başarı, format/
  duplicate/son-coin/bilinmeyen-aksiyon hata yolları, in-memory config'in
  ve dosyanın gerçekten güncellendiğinin doğrulanması).
  **Toplam: 100 → 116 test.**

**Kasıtlı olarak yapılMAYAN:** Bu isteğin çalışan `bot` container'ını
canlı olarak (otomatik restart ile) etkilemesi. `config.yaml` sadece
BAŞLANGIÇTA okunuyor (`engine.py`'de `TradingEngine.__init__`), bu yüzden
web container'ı dosyayı güncelledikten sonra `bot`'un bunu görmesi için
yeniden başlatılması gerekiyor. Otomatik restart (docker socket'i web
container'ına bağlamak) teknik olarak mümkün ama web'e (dış dünyaya en
yakın, en az güvenilir yüzey) container kontrol yetkisi vermek —
sırf bu rahatlık için — orantısız bir risk artışı olurdu. Panel bu
kısıtı `restart_required` mesajıyla açıkça gösteriyor, sessizce
gizlemiyor.

## Nasıl devam edilir

1. `git log --oneline` ile commit geçmişini oku — her commit bir fazı
   temsil ediyor, mesajları neyin neden yapıldığını anlatıyor.
2. `PYTHONPATH=. python -m unittest discover -s tests -v` ile testlerin
   hâlâ geçtiğini doğrulayarak başla.
3. Faz 0-10 (+ düzeltme fazları 1.5/2.5/3.6) tamamlandı — güncel durum ve
   sıradaki fazlar için `PLAN.md`'deki özet matrise bak. Yeni bir iş varsa
   (kullanıcı isteği, bulunan bug, yeni faz), önce burada "neden" yazan
   bir bölüm taslağı aç, sonra uygula — kod değil dokümantasyon önce
   planlanmalı ki gerekçe kaybolmasın.
4. Her iş sonunda bu dosyaya yeni bir bölüm ekle — "Faz X ✅ Tamamlandı"
   veya "<konu> — ✅ Tamamlandı" formatında + değişen dosyalar + neden.
