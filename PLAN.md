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
| **16** | Canlı/Dry-run modu + poll aralığı UI'dan | ⏳ Planlandı | - |
| **17** | Push Tabanlı Güncellemeler (SSE/WebSocket) | ⏳ Planlandı | - |
| **18** | Yeni Stratejiler + Karşılaştırmalı Şablonlar | ⏳ Planlandı | - |

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