# Canlıya Geçiş Checklist (Faz 5)

Bu dosya, `dry_run: false` + `live_trading_confirmed: true` yapıp GERÇEK
parayla işlem yapmadan önce gözden geçirilmesi gereken go/no-go
kriterlerini listeler. Amaç: "hızlıca deneyip gördük" değil, bilinçli bir
karar vermek — buradaki maddelerin çoğu geri dönüşü olmayan (para kaybı)
riskler içeriyor.

**Kural: aşağıdaki maddelerden BİRİ bile "hayır" ise canlıya geçme.**

## 1. Strateji doğrulaması

- [ ] Backtest, en az birkaç farklı piyasa rejiminde (yükseliş / düşüş /
      yatay) test edildi — tek bir dönemde iyi görünüp başka dönemde
      çökmediği doğrulandı. `python -m omnitrade.cli backtest --walk-forward N`
      ile kontrol et (bkz. README).
- [ ] Dry-run'da **en az birkaç hafta** (tercihen 4+) kesintisiz çalıştı.
- [ ] Dry-run sonucu **pozitif** getiri veriyor (`/api/stats`'taki
      `total_return_pct` veya dashboard'daki "Toplam Getiri" kartı).
- [ ] Max drawdown, kabul edebileceğin bir seviyenin altında kaldı
      (dashboard'daki drawdown grafiği / `max_drawdown_pct`).
- [ ] Kazanma oranı (`win_rate`) ve işlem sayısı, sonucun şans eseri
      olmadığına ikna edecek kadar (çok az işlemle — örn. 3-5 işlem — yüksek
      win rate anlamlı değildir).

## 2. Risk parametreleri

- [ ] `config.yaml`'daki `risk:` bölümü (`max_position_pct`,
      `max_open_positions`, `stop_loss_pct`, `take_profit_pct`,
      `max_daily_loss_pct`) gerçek risk toleransına göre GÖZDEN GEÇİRİLDİ —
      varsayılanlar güvenli tarafta ama körü körüne güvenilmemeli.
- [ ] `dry_run_wallet` yerine gerçek borsa bakiyesi kullanıldığında
      (`fetch_free_balance`, Faz 5'te eklendi) pozisyon büyüklüğünün makul
      olduğu doğrulandı (küçük bir tutarla, örn. borsanın izin verdiği
      minimum emirle, ilk canlı işlemi gözlemleyerek).

## 3. Borsa / API anahtarı

- [ ] API anahtarının izinleri **sadece trade (spot trading)** ile sınırlı —
      **withdrawal (para çekme) izni KAPALI**. Bu, anahtar sızarsa/çalınırsa
      olabilecek en kötü senaryoyu (fonların çekilmesi) engeller.
- [ ] IP whitelist (borsanın destekliyorsa) sadece botun çalıştığı VM'in
      IP'sine ayarlandı.
- [ ] `.env` dosyası `.gitignore`'da, yanlışlıkla commit edilmediği
      doğrulandı (`git status` / `git log -- .env` boş dönmeli).
- [ ] Küçük bir gerçek bakiye ile başlanacak — "tüm sermaye" değil, kaybını
      göze alabileceğin bir tutar.

## 4. Operasyonel hazırlık

- [ ] Telegram bildirimleri (`telegram.enabled: true`) canlıda da çalışıyor
      ve test edildi.
- [ ] Healthcheck cron kurulu (`scripts/healthcheck.py`, bkz. README) — bot
      çökerse fark edilsin.
- [ ] Günlük DB yedeği kurulu (`scripts/backup_db.sh`, bkz. README).
- [ ] `docker-compose.yml`'daki `mem_limit`/log rotasyonu VM boyutuna uygun.

## 5. Son onay

- [ ] `config.yaml`'da `dry_run: false` VE `live_trading_confirmed: true`
      bilinçli olarak, yukarıdaki tüm maddeler işaretlendikten SONRA
      set edildi.
- [ ] İlk canlı işlemler yakından izlenecek (dashboard + Telegram) —
      "kur, unut" değil.

---

Bu checklist tamamlandıktan sonra bile: piyasa koşulları geçmiş verilerden
farklı davranabilir, borsa API'leri arıza yapabilir, ağ kesintileri
olabilir. Hiçbir checklist riski sıfıra indirmez — sadece bilinen,
önlenebilir hataları elemeyi amaçlar.
