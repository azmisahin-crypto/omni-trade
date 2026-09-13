from __future__ import annotations

import inspect

from omnitrade.strategies.base import Action, Signal, Strategy
from omnitrade.strategies.rsi_strategy import RsiStrategy
from omnitrade.strategies.macd_strategy import MacdStrategy
from omnitrade.strategies.bollinger_strategy import BollingerStrategy
from omnitrade.strategies.stochastic_strategy import StochasticStrategy
from omnitrade.strategies.donchian_strategy import DonchianStrategy

# Yeni strateji eklediğinde buraya da ekle — config.yaml'daki "strategy"
# adı burada aranıyor. Dashboard'daki "Strateji Test Et" paneli de bu
# sözlüğü `list_strategies()` üzerinden okuyup dropdown'ı ve parametre
# formunu OTOMATİK kurar — yeni strateji eklerken UI tarafında hiçbir
# şeye dokunman gerekmez, sadece burada kayıt yeterli.
STRATEGIES = {
    "RsiStrategy": RsiStrategy,
    "MacdStrategy": MacdStrategy,
    "BollingerStrategy": BollingerStrategy,
    # Faz 18: high/low kolonlarını kullanan ilk iki strateji (öncekiler
    # sadece close'a bakıyordu) — bkz. her dosyanın kendi docstring'i.
    "StochasticStrategy": StochasticStrategy,
    "DonchianStrategy": DonchianStrategy,
}


def get_strategy(name: str, params: dict | None = None) -> Strategy:
    if name not in STRATEGIES:
        raise ValueError(
            f"Bilinmeyen strateji: {name!r}. Kayıtlılar: {list(STRATEGIES)}"
        )
    return STRATEGIES[name](**(params or {}))


def list_strategies() -> list[dict]:
    """Kayıtlı her strateji için `{name, params: [{name, default}]}` döndürür.

    Parametreler `__init__` imzasından (varsayılan değerleriyle birlikte)
    introspect edilir — yeni bir strateji eklendiğinde (yeni bir .py dosyası
    + STRATEGIES sözlüğüne kayıt) dashboard'daki dropdown ve parametre formu
    hiçbir frontend değişikliği gerekmeden otomatik güncellenir.
    """
    out = []
    for name, cls in STRATEGIES.items():
        sig = inspect.signature(cls.__init__)
        params = []
        for pname, p in sig.parameters.items():
            if pname == "self":
                continue
            default = None if p.default is inspect.Parameter.empty else p.default
            params.append({"name": pname, "default": default})
        out.append({"name": name, "params": params})
    return out


__all__ = [
    "Action", "Signal", "Strategy", "RsiStrategy", "MacdStrategy",
    "BollingerStrategy", "StochasticStrategy", "DonchianStrategy",
    "STRATEGIES", "get_strategy", "list_strategies",
]
