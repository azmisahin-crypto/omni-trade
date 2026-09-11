"""Config loading: config/config.yaml + .env overrides.

Sırlar (API anahtarları, Telegram token'ı) hiçbir zaman config.yaml içinde
durmaz — sadece .env dosyasından okunur, .env de .gitignore'da.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader — python-dotenv'e bağımlı olmamak için."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@dataclass
class ExchangeConfig:
    name: str = "binance"
    api_key: str = ""
    api_secret: str = ""


@dataclass
class TelegramConfig:
    enabled: bool = False
    token: str = ""
    chat_id: str = ""


@dataclass
class Config:
    dry_run: bool = True
    dry_run_wallet: float = 1000.0
    stake_currency: str = "USDT"
    timeframe: str = "1h"
    pairs: list = field(default_factory=lambda: ["BTC/USDT"])
    strategy: str = "RsiStrategy"
    poll_interval_seconds: int = 60
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    db_path: str = "data/omnitrade.db"
    web_port: int = 8080


def load_config(config_path: str = "config/config.yaml", env_path: str = ".env") -> Config:
    _load_dotenv(Path(env_path))

    raw: dict = {}
    p = Path(config_path)
    if p.exists():
        raw = yaml.safe_load(p.read_text()) or {}

    exchange_raw = raw.get("exchange", {})
    telegram_raw = raw.get("telegram", {})

    cfg = Config(
        dry_run=raw.get("dry_run", True),
        dry_run_wallet=float(raw.get("dry_run_wallet", 1000.0)),
        stake_currency=raw.get("stake_currency", "USDT"),
        timeframe=raw.get("timeframe", "1h"),
        pairs=raw.get("pairs", ["BTC/USDT"]),
        strategy=raw.get("strategy", "RsiStrategy"),
        poll_interval_seconds=int(raw.get("poll_interval_seconds", 60)),
        db_path=raw.get("db_path", "data/omnitrade.db"),
        web_port=int(raw.get("web_port", 8080)),
        exchange=ExchangeConfig(
            name=exchange_raw.get("name", "binance"),
            api_key=os.environ.get("EXCHANGE_KEY", exchange_raw.get("api_key", "")),
            api_secret=os.environ.get("EXCHANGE_SECRET", exchange_raw.get("api_secret", "")),
        ),
        telegram=TelegramConfig(
            enabled=telegram_raw.get("enabled", False),
            token=os.environ.get("TELEGRAM_TOKEN", telegram_raw.get("token", "")),
            chat_id=os.environ.get("TELEGRAM_CHAT_ID", telegram_raw.get("chat_id", "")),
        ),
    )
    return cfg
