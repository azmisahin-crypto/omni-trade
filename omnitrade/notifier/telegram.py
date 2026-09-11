"""Telegram bildirimleri. @BotFather'dan token al, botunla konuş, chat_id'ini
@userinfobot ile öğren; ikisini de .env'e koy. Ağır bir SDK'ya gerek yok,
Bot API düz HTTP."""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, enabled: bool = True):
        self.token = token
        self.chat_id = chat_id
        self.enabled = enabled and bool(token) and bool(chat_id)
        if enabled and not self.enabled:
            log.warning("Telegram enabled=true ama token/chat_id eksik — bildirimler kapalı.")

    def send(self, text: str) -> None:
        if not self.enabled:
            log.info("[telegram devre dışı] %s", text)
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            resp = requests.post(url, json={"chat_id": self.chat_id, "text": text}, timeout=10)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.error("Telegram mesajı gönderilemedi: %s", exc)

    def trade_alert(self, action: str, symbol: str, price: float, qty: float, reason: str) -> None:
        emoji = "🟢" if action == "buy" else "🔴"
        self.send(
            f"{emoji} {action.upper()} {symbol}\n"
            f"Fiyat: {price:.4f}  Miktar: {qty:.6f}\n"
            f"Sebep: {reason}"
        )

    def system_alert(self, text: str) -> None:
        """Operasyonel uyarılar (hata, restart, healthcheck) için — trade
        sinyalleriyle karışmasın diye ayrı bir prefix kullanır."""
        self.send(f"⚙️ SYSTEM: {text}")
