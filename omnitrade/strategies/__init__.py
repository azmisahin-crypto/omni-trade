from omnitrade.strategies.base import Action, Signal, Strategy
from omnitrade.strategies.rsi_strategy import RsiStrategy
from omnitrade.strategies.macd_strategy import MacdStrategy
from omnitrade.strategies.bollinger_strategy import BollingerStrategy

# Yeni strateji eklediğinde buraya da ekle — config.yaml'daki "strategy"
# adı burada aranıyor.
STRATEGIES = {
    "RsiStrategy": RsiStrategy,
    "MacdStrategy": MacdStrategy,
    "BollingerStrategy": BollingerStrategy,
}


def get_strategy(name: str, params: dict | None = None) -> Strategy:
    if name not in STRATEGIES:
        raise ValueError(
            f"Bilinmeyen strateji: {name!r}. Kayıtlılar: {list(STRATEGIES)}"
        )
    return STRATEGIES[name](**(params or {}))


__all__ = [
    "Action", "Signal", "Strategy", "RsiStrategy", "MacdStrategy",
    "BollingerStrategy", "STRATEGIES", "get_strategy",
]
