# OmniTrade — Bağımsız Denetim Raporu (Faz 0–15)

**Amaç ve okuyucu:** Bu rapor, OmniTrade projesinde Faz 0'dan Faz 15'e
kadar yapılan tüm çalışmayı, onu üreten asistanın kendisi tarafından
değil, **onu denetleyecek ayrı bir sistem** için yazılmıştır (kullanıcı
tarafından "otonom araştırma • akıl yürütme • red team • sentez • karar
sistemi" olarak tanımlanan bir üst-denetim). Bu yüzden rapor iki şeyi
kasıtlı olarak birlikte yapıyor: (1) ne yapıldığını özetliyor, (2)
**neyin doğrulanmadığını / hangi risklerin bilerek kabul edildiğini**
saklamadan listeliyor. Övgü/pazarlama dili yok; amaç denetlenebilirlik.

**Kapsam:** `git log` — commit `749edf3` (ilk commit) → `ca765a5`
(Faz 15). Tüm sayısal iddialar (test sayısı, dosya sayısı vb.) bu
repodaki gerçek `git`/test çıktılarından alınmıştır, tahmin değildir.

---

## 1) Proje özeti

OmniTrade, kripto para için tek-VM'de self-hosted çalışan bir algoritmik
al-sat botu: `bot` süreci (döngü: veri çek → strateji → sinyal → emir/
dry-run → log) ve `web` süreci (dashboard, aynı SQLite'ı okur/config'i
yazar) iki ayrı container olarak çalışır. ~4.000 satır Python
(`omnitrade/`) + 137 birim test + stdlib-only bir dashboard
(FastAPI/Flask yok, `http.server`).

**Mimari diyagram (metinsel):**

```
[Borsa API (ccxt)] <--> [bot container: TradingEngine]
                              |  (config.yaml mtime izler, Faz 13)
                              v
                    [SQLite (WAL) — data/omnitrade.db]
                              ^
                              |  (okur + config.yaml'ı yazar)
                    [web container: http.server + dashboard]
                              ^
                              |  HTTP (opsiyonel Basic Auth, Faz 14)
                    [Kullanıcı tarayıcısı — SSH tüneli üzerinden]
```

İki süreç arasında **hiçbir doğrudan RPC/IPC kanalı yok** — tek paylaşılan
durum `config.yaml` (dosya) ve `data/omnitrade.db` (SQLite, WAL). Bu
kasıtlı bir mimari seçim: web container'ına bot'u kontrol etme yetkisi
(docker socket vb.) hiçbir fazda verilmedi (bkz. §4).

---

## 2) Faz faz özet (durum tablosu)

| Faz | Konu | Durum | Not |
|---|---|---|---|
| 0 | Risk yönetimi, komisyon/slippage, SQLite WAL | ✅ | Temel |
| 1 / 1.5 | Test kapsamı, backtest-dry_run risk tutarlılığı | ✅ | |
| 2 / 2.5 | Operasyonel dayanıklılık (e2-micro), Telegram bug fix | ✅ | |
| 3–5 | İzlenebilirlik, strateji altyapısı, canlı emir | ✅ | |
| 3.6 | Sinyal grafiği titreme düzeltmesi | ✅ | Kozmetik |
| 6–9 | Dashboard'dan backtest/walk-forward, MACD/Bollinger, strateji introspection, leaderboard | ✅ | |
| 10–11 | UI'dan coin ekle/çıkar, tek tıkla dry-run strateji uygula | ⚠️→✅ | Faz 13'e kadar restart gerektiriyordu |
| 12 | Görsel/UX cilası (v1) | ⚠️ | **Kullanıcı tarafından yetersiz bulundu** — bkz. §6 |
| 13 | Config hot-reload | ✅ | Restart bağımlılığını kapattı |
| 14 | Dashboard HTTP Basic Auth | ✅ | Tek-kullanıcılı, minimal |
| 15 | Tam ekran sekmeli kokpit (v2) | ✅ Doğrulandı | Kullanıcı canlı ortamda onayladı — bkz. §6 |
| 16 | Canlı/dry-run UI kontrolü | ⏳ Planlı — **ön koşullu** | Bkz. §6.1, kodlama başlamadan önce zorunlu |
| 17–18 | SSE/WebSocket, yeni stratejiler | ⏳ Planlı | Kod yazılmadı, sadece PLAN.md'de |

---

## 3) Test kapsamı — gerçek sayılar

`PYTHONPATH=. python -m unittest discover -s tests` → **137 test, 137
geçti** (bu raporun yazıldığı anda, tekrar çalıştırılarak doğrulanmıştır).
Dağılım (dosya bazlı, yaklaşık):

- `test_config.py` — pair/pair_strategy normalize & dosya güncelleme
- `test_engine.py` — sinyal→emir akışı, risk çıkışları, **Faz 13 hot-reload (4 test)**
- `test_server.py` — tüm HTTP endpoint'leri (GET/POST), **Faz 14 auth (4 test)**
- `test_backtest.py`, `test_portfolio.py`, `test_risk.py`, `test_strategy.py`, `test_stats.py`, `test_storage.py`, `test_healthcheck.py` — çekirdek iş mantığı

**Kapsam DIŞI kalanlar (dürüstçe belirtilmeli):**
- **Front-end (`index.html`/`app.js`) için hiçbir otomatik test yok.**
  Doğrulama sadece: (a) statik ID/etiket dengesi kontrolü (bu oturumda
  script ile), (b) `test_server.py::test_index_and_app_js_served`
  (sadece dosyanın 200 döndüğünü ve "OmniTrade" içerdiğini kontrol
  eder — DOM'un veya JS mantığının doğruluğunu DEĞİL).
- **Gerçek bir borsaya karşı hiç çalıştırılmadı.** `ExchangeClient`
  testlerde her zaman mock'lanıyor. "Sinyaller doğru üretiliyor mu"
  iddiası sadece sentetik/deterministik veri üzerinde doğrulanmıştır —
  gerçek piyasa verisiyle canlı/dry-run davranışı bu repo içinden
  BAĞIMSIZ OLARAK doğrulanmamıştır.
- Headless tarayıcı bu ortamda mevcut değildi; Faz 12/15'teki görsel
  değişiklikler bir insan veya headless tarayıcı tarafından **görsel
  olarak** doğrulanmadı, sadece statik/yapısal olarak doğrulandı.
- CI (`.github/workflows/tests.yml`) var ve test suite'i her push'ta
  çalıştırıyor, ama linting/type-checking/security-scanning (bandit,
  mypy, ruff vb.) YOK.

---

## 4) Güvenlik duruşu

**Mevcut önlemler:**
- Sırlar (`EXCHANGE_KEY/SECRET`, `TELEGRAM_TOKEN`, artık `WEB_AUTH_PASSWORD`)
  sadece `.env`'de, `config.yaml`'da asla; `.env` `.gitignore`'da.
- Canlı emir için çift bariyer: `dry_run: false` VE `live_trading_confirmed: true`.
- Risk yönetimi: pozisyon limiti, stop-loss/take-profit, günlük kill-switch.
- Web container'ına ASLA docker/süreç kontrol yetkisi verilmedi (Faz
  10/13/14 boyunca bilinçli olarak korunan karar).
- Faz 14: `web_auth.enabled=true` iken tüm endpoint'ler Basic Auth
  ister, `hmac.compare_digest` ile zamanlama saldırısına karşı korumalı.
- README, dashboard'un sadece `127.0.0.1:8080`'e bağlanıp SSH tüneli
  ile erişilmesini öneriyor (ağ seviyesi savunma).

**AÇIK RİSKLER / bilinçli kabul edilen sınırlamalar (red-team burayı hedeflemeli):**

1. **`web_auth.enabled` varsayılan `false`.** Kurulumu yeni yapan biri
   bunu FARK ETMEZSE dashboard'u kimliksiz bırakabilir. Bu, geriye dönük
   uyumluluk için bilinçli bir tercih — ama gerçek bir risk.
2. **Brute-force koruması yok.** Basic Auth'ta deneme sayısı sınırı,
   IP bazlı kilitleme, ya da gecikme YOK. Şifre güçlüyse önemsiz, ama
   protokol seviyesinde bir savunma yok.
3. **Basic Auth şifresi her istekte açık metin olarak (Base64, şifreleme
   DEĞİL) gönderiliyor.** HTTPS olmadan (örn. SSH tüneli yerine düz HTTP
   ile açığa çıkarsa) şifre ağ üzerinde okunabilir. Rapor SSH tüneli
   varsayımına dayanıyor — bu varsayım BOZULURSA (biri dashboard'u
   `0.0.0.0`'a bind edip HTTPS olmadan açarsa) ciddi bir açık oluşur.
4. **Tek paylaşılan kimlik bilgisi, kullanıcı bazlı değil.** Kim neyi
   ne zaman değiştirdiğine dair bir audit log YOK (config.yaml'a
   `git diff` dışında bir değişiklik geçmişi tutulmuyor).
5. **Hot-reload (Faz 13) dosya sistemine güveniyor.** `config.yaml`
   dosyasına yazma erişimi olan HERHANGİ bir süreç/kullanıcı (web
   container'ı dahil, ya da host'a erişimi olan biri) botun davranışını
   restart'sız değiştirebilir. Bu Faz 13'ün TAM DA amacı olduğundan
   "bug" değil ama blast-radius'u genişleten bir mimari gerçek —
   `config.yaml`'ın dosya izinleri/kim yazabildiği ayrı bir denetim
   konusu, bu repo bunu ZORLAMIYOR.
6. **SQLite dosyası şifresiz.** İşlem geçmişi, equity eğrisi vb. veri
   diskte düz metin (SQLite formatında) duruyor.
7. **Rate limiting / DoS koruması hiçbir endpoint'te yok** — `/api/backtest/batch`
   gibi CPU-ağır bir uç, kimliği doğrulanmış (veya auth kapalıysa herhangi)
   biri tarafından art arda çağrılarak sunucuyu yorabilir.
8. **Bağımlılık güvenlik taraması yok** (Dependabot/pip-audit vb. CI'da yok).

---

## 5) Doğrulanmamış / temkinli okunması gereken iddialar

Bu bölüm bilhassa red-team/denetim sistemi için: aşağıdaki ifadeler
CHANGELOG/PLAN.md'de "yapıldı" olarak geçiyor ama **bağımsız kanıtı bu
repo dışında yoktur**:

- "Faz 13 mimari/rakip araştırması" bölümündeki nitel gözlemler
  (Freqtrade/3Commas/Pionex karşılaştırması) **gerçek web aramasına
  dayanıyor** (bu oturumdaki arama sonuçlarından), ama bu makaleler
  pazarlama/blog içerikleri — sayısal iddiaları (kullanıcı sayıları,
  APR'ler) doğrulanmamış olarak ele alınmalı, PLAN.md bu yüzden
  sonradan güncellenip bu iddiaları tekrarlamaktan kaçındı.
- "133/137 test yeşil" iddiaları her seferinde gerçekten
  `python -m unittest discover` çalıştırılarak doğrulandı (bu raporda
  da tekrar çalıştırıldı) — ama bu sadece **birim test** seviyesinde;
  entegrasyon/uçtan-uca (gerçek borsa, gerçek Telegram, gerçek çoklu
  container Docker ortamı) hiç çalıştırılmadı.
- Faz 12/15'teki "kullanıcı deneyimi iyileşti" iddiası **ölçülmedi** —
  hiçbir kullanılabilirlik testi/metriği yok, sadece kullanıcının
  sözlü geri bildirimine (Faz 12 reddi → Faz 15 revizyonu) dayanıyor.

---

## 6) Faz 12'nin reddi — neden önemli bir sinyal

Faz 12 (ilk görsel/UX cilası), kullanıcı tarafından açıkça yetersiz
bulunup reddedildi ("aşağı kayıyor", "sarı beğenmedim", "kullanışsız").
Bunun kök nedeni **teknik değil süreçseldi**: cilalama, altta yatan
düzen (layout) sorununu (tek uzun scroll) çözmeden yapıldı. Faz 15 bunu
düzelttiği iddiasında.

**Durum güncellemesi (bu rapor ilk yazıldıktan sonra):** Faz 15,
kullanıcı tarafından **canlı ortamda incelenip onaylandı** —
sekmeli düzen, sinyal kartı detay açılımı, Telegram↔dashboard log
senkronizasyonu ve equity/drawdown/walk-forward görselleştirmeleri
"beklentilerle tam uyumlu" olarak doğrulandı. Önceki madde
("Faz 15'in kullanıcı tarafından kabulü hâlâ beklemede") artık
**✅ Başarıyla Doğrulandı** olarak kapatılmıştır. Bu, raporun ilk
halinde §5'te vurgulanan "bağımsız doğrulama eksikliği" boşluklarından
BİRİNİN (front-end'in gerçek kullanıcı tarafından görsel doğrulanması)
kapandığı anlamına gelir — kalan boşluklar (gerçek borsaya karşı hiç
çalıştırılmama, headless tarayıcı/otomatik UI testi eksikliği) hâlâ
geçerlidir, bkz. §3.

Ayrıca §4'te listelenen güvenlik/mimari riskler (özellikle SQLite
şifrelemesi ve mevcut auth yapısı), kullanıcı tarafından şu anki
operasyonel aşama için **"kabul edilebilir teknik borç"** olarak
işaretlenmiştir. **Bu kabul KOŞULLUDUR** — bkz. §6.1, çünkü Faz 16
bu risklerin bir kısmını (özellikle auth zayıflığını) kritik bir
aksiyonla (canlı işleme geçiş) birleştirerek önemli ölçüde büyütüyor.

### 6.1) 🔴 Faz 16 ön koşulu — ZORUNLU, tartışmaya açık değil

Faz 13'te `live_trading_confirmed` alanının **kasıtlı olarak
restart-only** bırakılması bir tasarım hatası değil, kaza veya
kötü niyetli tek-tıkla-canlıya-geçişe karşı bilinçli bir sürtünme
katmanıydı (bkz. §1, §4 madde 5). Faz 16'nın hedefi
("dashboard'dan dry-run/canlı statüsü kontrolü") bu sürtünmeyi
tanım gereği ortadan kaldırıyor. Bunu §4'te listelenen mevcut auth
zayıflıklarıyla (varsayılan kapalı, brute-force koruması yok, tek
paylaşılan kimlik bilgisi, audit log yok) birlikte düşünürsek: sistemin
**en yıkıcı tek aksiyonu** en zayıf korumalı yüzeyden erişilebilir hale
gelir. Bu yüzden aşağıdaki üç şart, Faz 16 kodlaması BAŞLAMADAN ÖNCE
tasarıma dahil edilmiş olmalıdır — öneri değil, **gereksinimdir**:

1. **Zorunlu auth:** `dry_run`/`live_trading_confirmed` durumunu
   değiştiren endpoint, `web_auth.enabled=false` iken **tamamen
   reddedilmelidir** (API seviyesinde, sessizce izin vermek yerine
   açık `403`). Bu, diğer düşük riskli endpoint'lerden (coin ekle/çıkar,
   strateji override — bunlar auth kapalıyken de çalışmaya devam
   edebilir) FARKLI ve daha katı bir kural olmalı.
2. **İkinci teyit adımı:** Tek istekle canlıya geçiş YASAK. Kullanıcı
   şifresini tekrar girmeli veya sabit bir onay metnini (örn.
   `"CANLI'YA GEÇ"`) yazarak göndermelidir; sunucu bu teyidi
   doğrulamadan state'i değiştirmemelidir.
3. **İzole audit log:** Bu state değişikliği, standart
   trade/signal loglarından AYRI bir tabloya/dosyaya — kim (username),
   ne zaman (UTC timestamp), hangi IP, eski→yeni değer — yazılmalıdır.
   Bu log dashboard'da salt-okunur gösterilmeli, API'den silinemez
   olmalıdır.

Faz 16'yı uygulayan geliştirici/model, bu üç maddeyi karşılamayan bir
tasarımı **teslim etmemelidir**; PLAN.md/CHANGELOG.md'ye Faz 16 girişi
eklenirken bu üç maddenin karşılandığının açıkça belirtilmesi
(hangi test dosyasında doğrulandığı dahil) zorunludur.

---

## 7) Mimari zayıflıklar / teknik borç (öncelik sırasıyla)

1. **Tek nokta arıza:** Tek VM, tek SQLite dosyası, yedekleme scripti
   (`scripts/backup_db.sh`) var ama otomatik çalıştığı/geri yükleme
   akışının uçtan uca test edildiği doğrulanmamış (sadece script'in
   kendisi var, bir cron/systemd timer'a bağlandığı ya da restore
   prosedürünün denendiği bu repoda görülmüyor).
2. **Push değil poll:** Dashboard 10 saniyede bir tüm API'leri
   yeniden çekiyor — WebSocket/SSE yok (Faz 17'de planlı, yapılmadı).
3. **Tek strateji ailesi:** RSI/MACD/Bollinger — hepsi klasik teknik
   gösterge tabanlı. ML/AI tabanlı sinyal üretimi yok (kullanıcı zaten
   bunu bilinçli olarak istemedi — "minimal olsun" — ama denetim
   sistemi bunun bir tercih olduğunu, eksiklik değil, bilmeli).
4. **Backtest gerçekçiliği sınırlı:** Sabit `fee_pct`/`slippage_pct` —
   emir defteri derinliği, kısmi dolum, likidite etkisi modellenmiyor.
5. **Hyperparameter arama yok:** Walk-forward var ama grid/hyperopt tarzı
   otomatik parametre optimizasyonu yok (Freqtrade'in Hyperopt'una
   kıyasla bir eksik — bilinçli kapsam dışı bırakıldı, ama not edilmeli).

---

## 8) Red-team için önerilen odak alanları

- `web_auth.enabled=false` varsayılanının gerçek dünyada ne sıklıkla
  atlanacağını / bunun sosyal mühendislik + varsayılan config
  kombinasyonuyla nasıl istismar edilebileceğini değerlendirin.
- `_reload_config_if_changed`'in config.yaml'daki BEKLENMEYEN/kötü
  niyetli bir değeri (örn. çok büyük `max_position_pct`, negatif
  `stop_loss_pct`) çalışırken sessizce kabul edip etmediğini —
  `load_config`'in girdi doğrulamasının reload yolunda da başlangıçtaki
  kadar sıkı olup olmadığını test edin.
- `/api/backtest/batch` gibi CPU-ağır endpoint'lere karşı DoS senaryosu.
- SQLite WAL dosyalarının (`-wal`, `-shm`) yedekleme/taşıma sırasında
  tutarlılığının gerçekten korunup korunmadığı (sadece `.backup` komutu
  kullanıldığı iddia ediliyor, ayrı bir restore testiyle doğrulanmadı).
- Basic Auth + hot-reload kombinasyonunun, "auth olmadan da dosyaya
  host üzerinden yazılabilir" senaryosunu (yani auth'un SADECE HTTP
  yüzeyini koruduğunu, dosya sistemi seviyesini korumadığını) açıkça
  test edin.

---

## 9) Sonuç

Faz 0-15 boyunca üretilen kod, kendi test paketine göre tutarlı ve
(137/137) yeşil. Mimari kararların çoğu (restart yerine hot-reload,
docker kontrolü vermeme, çift bariyerli canlı emir, dry-run/backtest
maliyet tutarlılığı) gerekçeli ve savunulabilir. En büyük gerçek boşluk
**bağımsız/uçtan-uca doğrulama eksikliği**: hiçbir sinyal gerçek
piyasada, hiçbir UI değişikliği gerçek bir tarayıcıda insan tarafından
görülmedi. Bu raporun amacı bu boşluğu gizlemek değil, denetleyen
sisteme açıkça göstermekti.

