# CHANGELOG

Bu dosya, OmniTrade üzerinde yapılan geliştirmeleri faz faz takip eder.
Amaç: projeye sonradan bakacak herkesin (bu, gelecekteki sen de olabilir,
başka bir geliştirici de) "ne yapıldı, neden yapıldı, sırada ne var"
sorularına hızlıca cevap bulabilmesi.

Planın tamamı 6 fazdan oluşuyor. Bu dosyanın en altındaki "Sıradaki fazlar"
bölümü, henüz uygulanmamış işleri detaylı biçimde listeler.

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

---

## Sıradaki fazlar (henüz uygulanmadı)

### Faz 1 — kalan işler
- [ ] `tests/test_config.py`: yeni config alanlarının (risk, fee_pct,
      strategy_params, live_trading_confirmed) doğru yüklendiğini test et.
- [ ] `tests/test_engine.py`: `_live_order_qty`'nin `live_trading_confirmed`
      false/true durumlarında doğru davrandığını test et.
- [ ] `.github/workflows/tests.yml`: her push/PR'da `python -m unittest
      discover -s tests` otomatik çalışsın. `ccxt` gerekmediği için CI
      hızlı olur.

### Faz 2 — Operasyonel dayanıklılık (e2-micro'ya özel)
- [ ] `docker-compose.yml`'e `mem_limit` (örn. bot: 300m, web: 150m) ve
      `logging.driver: json-file` + `max-size`/`max-file` ekle (disk
      dolmasın diye).
- [ ] `scripts/setup_swap.sh`: 2GB swap oluşturma script'i.
- [ ] `scripts/healthcheck.py`: `Storage.last_heartbeat()`'i okuyup
      `poll_interval_seconds`'in birkaç katından eskiyse
      `notifier.system_alert()` ile Telegram'a haber verip container'ı
      restart eden basit bir script. Cron ile 5 dakikada bir çalıştırılabilir.
- [ ] `deploy.sh`: `git pull && docker compose up -d --build` — tek
      komutla deploy.
- [ ] README'ye e2-micro deployment bölümü ekle (SSH tünel ile dashboard
      erişimi, firewall kuralları, swap kurulumu sırası).

### Faz 3 — İzlenebilirlik
- [ ] Dashboard'a (`web/static/`) drawdown grafiği ve basit özet istatistik
      (toplam getiri, kazanma oranı) ekle — şu an sadece equity eğrisi ve
      işlem tablosu var.
- [ ] `scripts/backup_db.sh`: `sqlite3 .backup` ile günlük yedek + cron
      örneği (README'de).
- [ ] Log formatını yapılandır (şu an sadece `logging.basicConfig` var,
      seviye config'ten okunmuyor).

### Faz 4 — Strateji altyapısı
- [x] `strategy_params` config'ten okunuyor (Faz 0'da yapıldı).
- [ ] Aynı anda birden fazla strateji/pariteyi paralel çalıştırma desteği
      (şu an tek strateji tüm pariteler için kullanılıyor — `config.pairs`
      listesi zaten var ama hepsi aynı stratejiyi kullanıyor).
- [ ] Walk-forward test desteği: `backtest.py`'ye zaman bazlı train/test
      split ekle (overfitting kontrolü için Faz 1'deki "farklı rejim"
      testinden bir adım öteye).

### Faz 5 — Canlıya geçiş hazırlığı
- [ ] `_live_order_qty` içindeki `dry_run_wallet` yerine gerçek borsa
      bakiyesini çekecek implementasyonu tamamla (bkz. `engine.py` içi
      yorum — bu KRİTİK, canlıya geçmeden önce mutlaka yapılmalı).
- [ ] `LIVE_TRADING_CHECKLIST.md`: go/no-go kriterlerini listeleyen bir
      doküman (min. dry-run süresi, min. işlem sayısı, API anahtar izin
      kontrolü, vb.)
- [ ] API anahtar izinleri: sadece trade, withdrawal kapalı — bunu
      doğrulayan bir manuel checklist maddesi.

---

## Nasıl devam edilir

1. `git log --oneline` ile commit geçmişini oku — her commit bir fazı
   temsil ediyor, mesajları neyin neden yapıldığını anlatıyor.
2. `PYTHONPATH=. python -m unittest discover -s tests -v` ile testlerin
   hâlâ geçtiğini doğrulayarak başla.
3. Yukarıdaki "Sıradaki fazlar" listesinden bir madde seç, üstündeki
   fazın CHANGELOG girdisini oku (neden yapıldığını anlamak için), sonra
   uygula.
4. Her faz sonunda bu dosyaya yeni bir bölüm ekle — "Faz X — Tamamlandı"
   + değişen dosyalar + neden.
