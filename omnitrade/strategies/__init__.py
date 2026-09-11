from omnitrade.strategies.base import Action, Signal, Strategy
from omnitrade.strategies.rsi_strategy import RsiStrategy

# Yeni strateji eklediğinde buraya da ekle — config.yaml'daki "strategy"
# adı burada aranıyor.
STRATEGIES = {
    "RsiStrategy": RsiStrategy,
}


def get_strategy(name: str) -> Strategy:
    if name not in STRATEGIES:
        raise ValueError(
            f"Bilinmeyen strateji: {name!r}. Kayıtlılar: {list(STRATEGIES)}"
        )
    return STRATEGIES[name]()


__all__ = ["Action", "Signal", "Strategy", "RsiStrategy", "STRATEGIES", "get_strategy"]
