"""Config loading: config/config.yaml + .env overrides.

Sırlar (API anahtarları, Telegram token'ı) hiçbir zaman config.yaml içinde
durmaz — sadece .env dosyasından okunur, .env de .gitignore'da.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from omnitrade.risk import RiskConfig

# Faz 10: dashboard'dan coin ekle/çıkar — "BAZ/QUOTE" formatını (ccxt'nin
# beklediği format, örn. "BTC/USDT") doğrulamak için. Borsanın gerçekten bu
# pariteyi destekleyip desteklemediğini kontrol ETMİYORUZ (bu bir ağ isteği
# gerektirir, ve format doğru olsa bile bot ilk mum verisini çekmeye
# çalıştığında zaten anlaşılır bir hata verir) — burada sadece bariz yazım
# hatalarını (boşluk, küçük harf karışıklığı, eksik "/") önlüyoruz.
PAIR_RE = re.compile(r"^[A-Z0-9]{2,15}/[A-Z0-9]{2,15}$")


def normalize_pair(symbol: str) -> str:
    """'btc/usdt' -> 'BTC/USDT'; format geçersizse ValueError fırlatır."""
    sym = (symbol or "").strip().upper()
    if not PAIR_RE.match(sym):
        raise ValueError(
            f"Geçersiz coin formatı: {symbol!r}. Beklenen format 'BAZ/QUOTE', "
            "örn. 'BTC/USDT'."
        )
    return sym


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
    strategy_params: dict = field(default_factory=dict)
    # Faz 4: coin başına farklı strateji/parametre override'ı. Boşsa tüm
    # pariteler `strategy`/`strategy_params`'ı kullanır (eski davranış).
    # Örn: {"ETH/USDT": {"strategy": "RsiStrategy", "params": {"period": 21}}}
    pair_strategies: dict = field(default_factory=dict)
    poll_interval_seconds: int = 60
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    fee_pct: float = 0.001
    slippage_pct: float = 0.0005
    db_path: str = "data/omnitrade.db"
    web_port: int = 8080
    # Faz 3: log seviyesi artık config'ten okunuyor (önceden cli.py'de
    # sabitti). DEBUG/INFO/WARNING/ERROR — geçersiz bir değer verilirse
    # INFO'ya düşülür (bkz. cli.py).
    log_level: str = "INFO"
    # Canlı emirler (dry_run: false) için ek bir bilinçli onay bayrağı.
    # engine.py bunu kontrol eder — sadece dry_run:false yetmez, bkz. README
    # "Canlıya geçmeden önce" bölümü.
    live_trading_confirmed: bool = False
    # Faz 10: `update_pairs()`'ın hangi dosyaya yazacağını bilmesi için —
    # dashboard'dan coin ekle/çıkar isteği geldiğinde config bu yoldan
    # yeniden yazılır. `load_config()` bunu her zaman çağrıldığı yolla set
    # eder; elle `Config()` oluşturulursa (testlerde olduğu gibi) varsayılan
    # değer kullanılır.
    config_path: str = "config/config.yaml"


def load_config(config_path: str = "config/config.yaml", env_path: str = ".env") -> Config:
    _load_dotenv(Path(env_path))

    raw: dict = {}
    p = Path(config_path)
    if p.exists():
        raw = yaml.safe_load(p.read_text()) or {}

    exchange_raw = raw.get("exchange", {})
    telegram_raw = raw.get("telegram", {})
    risk_raw = raw.get("risk", {})

    cfg = Config(
        dry_run=raw.get("dry_run", True),
        dry_run_wallet=float(raw.get("dry_run_wallet", 1000.0)),
        stake_currency=raw.get("stake_currency", "USDT"),
        timeframe=raw.get("timeframe", "1h"),
        pairs=raw.get("pairs", ["BTC/USDT"]),
        strategy=raw.get("strategy", "RsiStrategy"),
        strategy_params=raw.get("strategy_params", {}) or {},
        pair_strategies=raw.get("pair_strategies", {}) or {},
        poll_interval_seconds=int(raw.get("poll_interval_seconds", 60)),
        db_path=raw.get("db_path", "data/omnitrade.db"),
        web_port=int(raw.get("web_port", 8080)),
        log_level=str(raw.get("log_level", "INFO")).upper(),
        fee_pct=float(raw.get("fee_pct", 0.001)),
        slippage_pct=float(raw.get("slippage_pct", 0.0005)),
        live_trading_confirmed=bool(raw.get("live_trading_confirmed", False)),
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
        risk=RiskConfig(
            max_position_pct=float(risk_raw.get("max_position_pct", 0.2)),
            max_open_positions=int(risk_raw.get("max_open_positions", 5)),
            stop_loss_pct=float(risk_raw.get("stop_loss_pct", 0.05)),
            take_profit_pct=(
                float(risk_raw["take_profit_pct"]) if risk_raw.get("take_profit_pct") else None
            ),
            max_daily_loss_pct=float(risk_raw.get("max_daily_loss_pct", 0.1)),
        ),
        config_path=config_path,
    )
    return cfg


def update_pairs(config_path: str, pairs: list) -> None:
    """`config.yaml`'daki `pairs:` bloğunu YERİNDE günceller.

    Faz 10: dashboard'dan coin ekle/çıkar yapılabilsin diye. Bilerek
    `yaml.safe_dump` ile TÜM dosyayı yeniden yazmıyoruz — config.yaml'ın
    her bölümünde elle yazılmış açıklama yorumları var (bkz. dosyanın
    kendisi), tam bir YAML dump bunların hepsini silerdi. Onun yerine sadece
    `pairs:` bloğunu hedefleyen bir metin değişikliği yapıyoruz, dosyanın
    geri kalanı (yorumlar dahil) olduğu gibi kalır.

    Not: Bu fonksiyon SADECE dosyayı günceller — o an ÇALIŞAN bot süreci
    (ayrı bir container/process) bunu otomatik fark etmez, config'i sadece
    başlangıçta okur. Yeni coin'in canlı botta etkili olması için botun
    yeniden başlatılması gerekir (bkz. web/server.py'deki
    `restart_required` alanı ve dashboard'daki uyarı notu).
    """
    path = Path(config_path)
    text = path.read_text() if path.exists() else ""
    new_block = "pairs:\n" + "".join(f"  - {p}\n" for p in pairs)

    pattern = re.compile(r"^pairs:\n(?:[ \t]*-.*\n?)*", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(new_block, text, count=1)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += ("\n" if text else "") + new_block

    path.write_text(text)
