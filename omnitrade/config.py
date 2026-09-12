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
class WebAuthConfig:
    """Faz 14: dashboard'a HTTP Basic Auth.

    `enabled` config.yaml'da (sır değil, sadece açık/kapalı). `username`
    da config.yaml'da durabilir (kullanıcı adı bir sır sayılmaz). `password`
    ise diğer tüm sırlar gibi (bkz. modül docstring'i) SADECE .env'den
    (`WEB_AUTH_PASSWORD`) okunur — asla config.yaml'a yazılmaz/yazılmamalı.

    Varsayılan `enabled: False` — geriye dönük uyumluluk için (mevcut
    kurulumlar aniden dashboard'dan kilitlenmesin). README ve
    LIVE_TRADING_CHECKLIST.md, dashboard dış dünyaya açılıyorsa bunun
    açılmasını önerir.
    """
    enabled: bool = False
    username: str = "admin"
    password: str = ""


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
    web_auth: WebAuthConfig = field(default_factory=WebAuthConfig)


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
        web_auth=WebAuthConfig(
            enabled=bool(raw.get("web_auth", {}).get("enabled", False)),
            username=raw.get("web_auth", {}).get("username", "admin"),
            password=os.environ.get("WEB_AUTH_PASSWORD", ""),
        ),
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

    Not: Bu fonksiyon SADECE dosyayı günceller — botu bu fonksiyondan
    çağırarak DOĞRUDAN uyarmıyoruz. Faz 13'ten beri çalışan bot süreci
    (ayrı bir container/process) `config.yaml`'ın mtime'ını kendi
    döngüsünde kontrol edip değişikliği otomatik uyguluyor (bkz.
    engine.py `_reload_config_if_changed`) — restart gerekmiyor.
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


def _yaml_key_block(key: str, value: dict) -> str:
    """`key:` başlığı altına, 2 boşluk girintiyle, `value` dict'ini YAML
    olarak render eder. Boş dict için tek satırlık `key: {}` döner —
    config.yaml'daki mevcut kullanımla (bkz. `pair_strategies: {}`)
    tutarlı olsun diye.
    """
    if not value:
        return f"{key}: {{}}\n"
    dumped = yaml.safe_dump(value, default_flow_style=False, sort_keys=False, allow_unicode=True)
    indented = "\n".join(("  " + line if line else line) for line in dumped.splitlines())
    return f"{key}:\n{indented}\n"


def update_pair_strategies(config_path: str, pair_strategies: dict) -> None:
    """`config.yaml`'daki `pair_strategies:` bloğunu YERİNDE günceller.

    Faz 11: "tek tıkla dry-run config uygulama" — backtest panelinde iyi
    sonuç veren bir strateji/parametre kombinasyonunu bir coin için
    `pair_strategies` override'ı olarak kaydetmek artık dashboard'dan
    yapılabiliyor. `update_pairs()` ile aynı gerekçeyle (yorumları koru)
    metin tabanlı, sadece `pair_strategies:` bloğunu hedefleyen bir
    değişiklik yapılıyor — tüm dosyayı `yaml.safe_dump` ile yeniden
    yazmak, bu anahtarın ÜSTÜNDEKİ örnek/açıklama yorumlarını silerdi
    (o yorumlar bu bloğun DIŞINDA kaldığı için etkilenmiyor).

    Aynı restart kısıtı burada da geçerli: dosya güncellenir, ama çalışan
    bot süreci config'i yeniden okumadığı için (bkz. `update_pairs`)
    değişikliğin etkili olması için yeniden başlatma gerekir.
    """
    path = Path(config_path)
    text = path.read_text() if path.exists() else ""
    new_block = _yaml_key_block("pair_strategies", pair_strategies)

    pattern = re.compile(r"^pair_strategies:.*\n(?:[ \t]+.*\n?)*", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(new_block, text, count=1)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += ("\n" if text else "") + new_block

    path.write_text(text)
