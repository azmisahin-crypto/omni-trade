"""Risk yönetimi: pozisyon büyüklüğü sınırlama, stop-loss/take-profit ve
günlük zarar kill-switch. Hem dry-run Portfolio hem de (ileride) canlı emir
büyüklüğü hesaplaması bu modülü kullanır — böylece backtest/dry-run/canlı
arasında risk davranışı da tutarlı olur, sadece strateji sinyali değil.

Kill-switch mantığı: gün içinde başlangıç equity'sine göre `max_daily_loss_pct`
kadar kayıp oluşursa, o gün için yeni pozisyon açılmaz (mevcut pozisyonlar
stop-loss/take-profit kurallarıyla yönetilmeye devam eder). Gün değişince
(UTC gün sınırı) otomatik sıfırlanır.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class RiskConfig:
    # Bir pozisyona ayrılacak bakiyenin oranı (0.2 = bakiyenin %20'si)
    max_position_pct: float = 0.2
    # Aynı anda açık olabilecek maksimum pozisyon sayısı
    max_open_positions: int = 5
    # Bir pozisyonda izin verilen maksimum zarar (giriş fiyatına göre, 0.05 = %5)
    stop_loss_pct: float = 0.05
    # Bir pozisyonda hedeflenen kâr (giriş fiyatına göre, None = kapalı)
    take_profit_pct: float | None = None
    # Günlük toplam zarar bu oranı aşarsa yeni pozisyon açılmaz (0.1 = %10)
    max_daily_loss_pct: float = 0.1


def _day_bucket(ts: float | None = None) -> int:
    """UTC gün numarası — kill-switch'in günlük sıfırlanması için."""
    return int((ts if ts is not None else time.time()) // 86400)


class RiskManager:
    """Stateful: gün içi başlangıç equity'sini ve kill-switch durumunu takip eder.
    Engine/Portfolio her equity snapshot'ında `update_daily_baseline` çağırmalı,
    yeni pozisyon açmadan önce `can_open_position` kontrol edilmeli.
    """

    def __init__(self, config: RiskConfig):
        self.config = config
        self._day_start_equity: float | None = None
        self._current_day: int | None = None
        self._kill_switch_active = False

    def update_daily_baseline(self, equity: float, ts: float | None = None) -> None:
        day = _day_bucket(ts)
        if self._current_day != day:
            self._current_day = day
            self._day_start_equity = equity
            self._kill_switch_active = False

    def check_kill_switch(self, current_equity: float) -> bool:
        """Günlük zarar limitini kontrol eder, aşıldıysa kill-switch'i aktive eder.
        True dönerse: yeni pozisyon açılmamalı."""
        if self._day_start_equity and self._day_start_equity > 0:
            loss_pct = (self._day_start_equity - current_equity) / self._day_start_equity
            if loss_pct >= self.config.max_daily_loss_pct:
                self._kill_switch_active = True
        return self._kill_switch_active

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch_active

    def can_open_position(self, open_position_count: int) -> bool:
        if self._kill_switch_active:
            return False
        if open_position_count >= self.config.max_open_positions:
            return False
        return True

    def position_stake(self, balance: float) -> float:
        return balance * self.config.max_position_pct

    def should_stop_loss(self, entry_price: float, current_price: float) -> bool:
        if self.config.stop_loss_pct <= 0:
            return False
        loss_pct = (entry_price - current_price) / entry_price
        return loss_pct >= self.config.stop_loss_pct

    def should_take_profit(self, entry_price: float, current_price: float) -> bool:
        if not self.config.take_profit_pct:
            return False
        gain_pct = (current_price - entry_price) / entry_price
        return gain_pct >= self.config.take_profit_pct
