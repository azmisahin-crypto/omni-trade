# OmniTrade Geliştirme Master Planı ve Takip Dosyası

Bu dosya, projenin doğuşundan itibaren her fazın **hangi motivasyonla**, **hangi mimari kararlarla** ve **hangi commit ile** yapıldığını tutan canlı dokümantasyondur.

## Faz Özet Matrisi

| Faz | Konu | Durum | İlgili Commit / Sürüm |
| :-- | :-- | :--: | :-- |
| **0** | Temel Sağlamlaştırma (Risk, Maliyet, WAL) | ✅ Tamamlandı | `db8fdcf` (Örn) |
| **1** | Test Kapsamı Genişletme | ✅ Tamamlandı | ... |
| **1.5** | Backtest/Dry-run Risk Tutarsızlığı | ✅ Tamamlandı | ... |
| **2** | Operasyonel Dayanıklılık (e2-micro) | ✅ Tamamlandı | ... |
| **2.5** | Gerçekleşmeyen İşlem Telegram Bug'ı | ✅ Tamamlandı | ... |
| **3-5** | İzlenebilirlik, Strateji Altyapısı, Canlı | ✅ Tamamlandı | ... |
| **3.6** | Dashboard Sinyal Grafiği Titreme Düzeltmesi | ✅ Tamamlandı | ... |
| **6** | Dashboard'dan Backtest/Walk-forward | ✅ Tamamlandı | ... |
| **7** | MACD ve Bollinger Stratejileri | ✅ Tamamlandı | ... |
| **8** | Otomatik Strateji UI Formu (Introspection) | ✅ Tamamlandı | Bu commit |
| **9** | Çoklu Strateji × Coin Karşılaştırma (Leaderboard) | ✅ Tamamlandı | Bu commit |
| **10** | Coin Listesini UI'dan Ekle/Çıkar | ✅ Tamamlandı | Bu commit |
| **11** | Tek Tıkla Dry-Run Config Uygulama | ✅ Tamamlandı | Bu commit |
| **12** | Görsel / UX Cilası (v1 — yetersiz bulundu) | ⚠️ Revize edilecek | Bkz. Faz 15 |
| **13** | Config Hot-Reload — restart olmadan canlı uygulama | ✅ Tamamlandı | Bu commit |
| **14** | Dashboard Kimlik Doğrulama (HTTP Basic Auth) | ✅ Tamamlandı | Bu commit |
| **15** | Tam Ekran "Kokpit" Yeniden Tasarımı (v2) | ✅ Tamamlandı | Bu commit |
| **16** | Canlı/Dry-run modu + poll aralığı UI'dan | ✅ Tamamlandı | Bu commit |
| **17** | Push Tabanlı Güncellemeler (SSE) | ✅ Tamamlandı | Bu commit |
| **18** | Yeni Stratejiler + Karşılaştırmalı Şablonlar | ✅ Tamamlandı | Bu commit |

## Checkpoint (Faz 12 sonrası) — mimari gözden geçirme + rakip analizi

Faz 12'nin ilk hâli (renk/toast/skeleton cilası) kullanıcı tarafından
yetersiz bulundu: "sadece birkaç tasarım dokunuşu" değil, gerçek bir
mimari + UX gözden geçirmesi isteniyor. Bu bölüm o gözden geçirmenin
bulgularını ve gözden geçirilmiş yol haritasını tutuyor.

### 1) Bugüne kadarki fazların denetimi

Testler (133/133 yeşil) üzerinden doğrulanan sağlam temeller:
- **Sinyal görünürlüğü gerçekten çalışıyor**: `storage.log_signal` HOLD
  dahil her sinyali kaydediyor, `/api/signals` + `/api/signals/history`
  bunu dashboard'a taşıyor (`test_storage.py::TestSignalsStorage`, 5 test).
- **Risk yönetimi** (stop-loss/take-profit/kill-switch/pozisyon limiti)
  hem backtest hem dry-run'da aynı `RiskManager`'ı kullanıyor — tutarlı.
- **Strateji introspection'ı** (Faz 8) gerçekten iyi bir mimari karar:
  yeni strateji eklemek `STRATEGIES` sözlüğüne kayıt + dataclass param
  tanımından ibaret, UI formu otomatik kuruluyor. Rakiplerin çoğu (3Commas,
  Cryptohopper) bunu kapalı kaynak bir "marketplace" ile çözüyor; bizimki
  daha basit ama tamamen şeffaf.

Bulunan gerçek zayıflıklar:
- **Restart bağımlılığı** (Faz 10/11'in bilerek bıraktığı tek sürtünme):
  dashboard sadece `config.yaml`'ı yazıyordu, botun bunu görmesi için
  elle restart gerekiyordu. → **Faz 13'te kapatıldı** (aşağıda detay).
- **Kimlik doğrulama yok**: dashboard'a ağ erişimi olan HERKES coin
  ekleyip/çıkarabilir, backtest çalıştırabilir, strateji override
  uygulayabilir. "Her şey dashboard'dan yönetilebilsin" hedefiyle
  ilerledikçe bu, kontrol yüzeyini büyüten gerçek bir güvenlik açığı —
  Faz 14 bunu ele alıyor.
- **Tek uzun sayfa, gerçek bir "kokpit" değil**: kullanıcı geri
  bildiriminin özü de bu — sekiz kart alt alta, sürekli scroll,
  "tam ekranda her şeyi görebilmeli" isteği karşılanmıyor. Faz 12 v1
  bunu sadece nav/toast ile yamadı, gerçek çözüm (sekmeli/panelli tek
  ekran düzeni) Faz 15'te yapılacak.
- **10sn polling**: çalışıyor ama modern rakiplerin çoğu (3Commas,
  Gainium) push/websocket kullanıyor — daha "canlı" hissettiriyor.
- **Canlı/dry-run geçişi hâlâ tamamen elle**: bilerek böyle bırakılmıştı
  (Faz 11), bu doğru bir karar olarak kalıyor — ama en azından *hangi
  modda olduğunu ve geçiş adımlarını* dashboard'da çok daha görünür
  kılmak (LIVE_TRADING_CHECKLIST.md'yi UI'a taşımak) mümkün — Faz 16.

### 2) Rakip/trend analizi (Eylül 2026 itibarıyla, web araştırması)

Kaynaklar: Freqtrade/FreqUI resmi dokümantasyonu ve GitHub release
notları, Gainium'un Freqtrade incelemesi, altFINS'in 2026 bot
karşılaştırması, ve 3Commas/Pionex/Cryptohopper karşılaştıran birkaç
bağımsız blog yazısı (web araması ile doğrulandı — bkz. konuşma geçmişi).
Bunlar pazarlama/blog içerikleri olduğundan sayısal iddialar (kullanıcı
sayısı, APR vb.) burada tekrarlanmıyor; sadece mimari/UX örüntüleri
(aşağıda) alınıyor.

- **Piyasa haritası**: uçta no-code/cloud platformlar (3Commas, Pionex,
  Cryptohopper, Bitsgap — temiz arayüz, DCA/grid odaklı, kapalı kaynak),
  diğer uçta kod-öncelikli açık kaynak botlar (Freqtrade, Hummingbot,
  Gainium Community Edition) var. **En büyük trend: self-hosting** —
  kullanıcılar API anahtarlarını ve verilerini kendi sunucusunda tutmak
  istiyor; bunu erken benimseyen açık kaynak projeler (Gainium, Freqtrade,
  Hummingbot) büyüyor. OmniTrade zaten bu kategoride (kendi VM'inde,
  kendi SQLite'ında) — bu, bilinçli olarak korunması gereken bir
  konumlandırma, "cloud SaaS'a" kaymak doğru yön değil.
- **Freqtrade (en yakın mimari akran) bile config değişikliğinde
  BOTU YENİDEN BAŞLATIYOR** (`/reload_config` komutu "bot durur,
  config'i yeniden yükler, yeniden başlar" şeklinde çalışıyor) — yani
  "restart" kavramının kendisi tuhaf değil, tuhaf olan bunun İNSANIN
  SSH'lanıp elle yapması gerekmesiydi. Freqtrade'de bile bu bot
  SÜRECİNİN kendi içinde, bir komuta cevaben, otomatik oluyor. Faz 13
  tam olarak bunu yapıyor: insan müdahalesi olmadan, sürecin kendi
  döngüsünde.
- **AI/otomasyon her yerde** (Gainium Telegram AI Agent, Freqtrade
  FreqAI, Cryptohopper Algorithm Intelligence) ama kullanıcının isteği
  net: "minimal olsun ama en iyisi olsun", "hiç düşünmeden kullanmalıyız"
  — yani buradan çıkarılacak ders AI entegrasyonu eklemek değil,
  **temel deneyimi (kurulum, izleme, kontrol) sürtünmesiz yapmak.**
  Bu, kapsamı bilinçli olarak dar tutmayı destekliyor.

### 3) Gözden geçirilmiş yol haritası ve öncelik sırası

Sıra bilinçli: önce mimari/güvenlik temelleri (13, 14), sonra büyük
görsel yeniden tasarım (15 — böylece yeniden tasarım, hâlâ değişecek
alt yapı üzerine değil, oturmuş bir temel üzerine yapılır), sonra
UI'dan daha fazla kontrol (16), sonra his/performans (17), en son yeni
özellik/strateji genişlemesi (18) — kullanıcının "önce temel, sonra
parlaklık, sonra yeni özellik" sıralamasıyla uyumlu.

Detaylı "neden" + "değişen dosyalar" kayıtları her zamanki gibi
CHANGELOG.md'ye faz faz ekleniyor; buradaki matris ve checkpoint sadece
güncel durumun özeti.

## Faz 16 sonrası not — AUDIT_REPORT.md §6.1 ön koşulları nasıl karşılandı

Faz 15'in ardından eklenen bağımsız denetim raporu, Faz 16'yı (canlı/
dry-run + poll aralığı UI'dan) teslim etmeden ÖNCE üç ön koşul koymuştu:

1. **`web_auth` kapalıyken 403**: `POST /api/system/live-mode`, diğer
   düşük riskli uçların aksine ("auth kapalıysa herkese serbest" genel
   kuralına TABİ DEĞİL) — `config.web_auth.enabled == False` iken her
   zaman 403 döner, kimlik bilgisi gönderilse bile.
2. **İkinci onay adımı**: `go_live` isteği gövdede `confirm_text`
   alanında sabit bir metni ("CANLIYA GEÇİYORUM, RİSKİ ANLADIM") birebir
   içermek zorunda; eksik/yanlışsa 400 döner ve HİÇBİR ŞEY değişmez
   (config.yaml'a yazılmaz, audit log'a yazılmaz). `go_dry_run` bu adımı
   gerektirmez — kill-switch mantığıyla tutarlı, riski azaltan işlem
   sürtünmesiz olmalı.
3. **İzole, salt-okunur denetim kaydı**: yeni `mode_audit_log` SQLite
   tablosu (`storage.py`) — `Storage` sınıfında bu tabloyu güncelleyen ya
   da silen HİÇBİR metod yok, sadece `log_mode_change` (ekle) ve
   `get_mode_audit_log` (oku) var. Dashboard'daki "Sistem & Mod"
   sekmesinde görünür (kim/ne zaman/hangi IP/eski→yeni değer).

Ayrıca, `dry_run`/`live_trading_confirmed` hâlâ restart-only alanlar
olduğundan (bkz. `engine.py` `_RESTART_ONLY_FIELDS` — bu Faz 16 ile
DEĞİŞMEDİ, bilinçli olarak), uç nokta config.yaml'ı günceller ama yanıtı
her zaman `restart_required: true` döner ve bunu açıkça belirtir —
"tek tıkla anında canlıya geçiş" gibi yanıltıcı bir izlenim vermez.
`poll_interval_seconds` ise zaten hot-reload edilebilir bir alan olduğu
için (Faz 13) o uç (`/api/system/poll-interval`) sürtünmesiz, restart
gerektirmez.

137 → 156 test (19 yeni: `TestUpdateScalar`, `TestModeAuditLog`,
`TestSystemEndpoint`, `TestLiveModeEndpoint`,
`TestLiveModeEndpointWithAuthEnabled`).

## Faz 17 sonrası not — neden SSE, neden bot'a dokunulmadı

AUDIT_REPORT.md §6.1 gibi Faz 17'ye özel bir ZORUNLU ön koşul listesi
yoktu (o bölüm sadece Faz 16'nın gerçek-para riskine özeldi) — ama
raporun §1'inde vurgulanan mimari karar ("bot↔web arasında doğrudan bir
RPC/IPC kanalı yok, tek paylaşılan durum config.yaml + SQLite") bu
faz için de bağlayıcı bir kısıt olarak alındı: SSE akışı bot'tan bir
bildirim ALMIYOR, sadece web sürecinin zaten okuduğu SQLite'ı kendi
içinde kısa aralıkla yoklayıp DEĞİŞİKLİK varsa tarayıcıya haber veriyor.
"Poll" kavramı ortadan kalkmadı, sadece ağ üzerinden (tarayıcı↔web,
pahalı/gecikmeli) yerine yerel diskte (web↔SQLite, ucuz) yapılıyor hale
geldi — bu, Faz 13'ün "insan restart etmesin, süreç kendi döngüsünde
fark etsin" felsefesiyle de tutarlı bir seçim.

WebSocket yerine SSE seçildi çünkü ihtiyaç tek yönlü ("bir şey değişti,
çek" bildirimi) — projenin "stdlib-only, FastAPI/Flask yok" mimari
tercihiyle (bkz. `server.py` modül docstring'i) SSE, `http.server`
üzerinde ek bir kütüphane ya da elle WebSocket handshake/frame'leme
yazmadan doğal biçimde çalışıyor.

Ayrıntılı "neden" + "değişen dosyalar" kaydı her zamanki gibi
`CHANGELOG.md`'ye eklendi; buradaki not sadece kısa bir özet.

## Faz 18 sonrası not — iki yeni strateji + leaderboard şablonları

PLAN.md'deki Faz 18 iki ayrı parçadan oluşuyordu, ikisi de bağımsız
ama birbirini tamamlıyor:

1. **Yeni stratejiler**: `StochasticStrategy` ve `DonchianStrategy` —
   ikisi de ilk kez `high`/`low` kolonlarını kullanan stratejiler
   (RSI/MACD/Bollinger sadece `close`'a bakıyordu). Bilinçli olarak
   ZIT felsefeli bir çift seçildi (Stochastic mean-reversion, Donchian
   breakout/trend-takip) — aynı ham high/low verisini iki farklı
   yorumla ele alıp yan yana backtest etmek öğretici olsun diye (bkz.
   `donchian_strategy.py` docstring'i). `STRATEGIES` sözlüğüne
   eklendikleri an dashboard'daki strateji dropdown'ı/parametre formu
   VE leaderboard paneli otomatik güncellendi — Faz 8'in introspection
   mekanizması sayesinde frontend'e HİÇBİR dokunuş gerekmedi.
2. **Leaderboard şablonları**: Faz 9'daki karşılaştırma panelinde her
   seferinde aynı coin/strateji kombinasyonunu elle yeniden seçmek
   yerine, bir seçimi isimle kaydedip (`leaderboard_templates` tablosu,
   upsert) tek tıkla geri yükleme. Bilinçli olarak DAR tutuldu: şablonlar
   sadece bir UI kısayolu, botun canlı `strategy`/`pair_strategies`
   davranışını ETKİLEMİYOR — bu yüzden Faz 16/17'deki gibi bir auth/
   audit-log zorunluluğu yok (gerçek para riski taşımıyor).

Testler: `TestStochasticStrategy`, `TestDonchianStrategy`,
`TestLeaderboardTemplates` (storage), `TestLeaderboardTemplatesEndpoint`
(server) — 167 → 191 test, hepsi yeşil.