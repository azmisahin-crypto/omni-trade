"""Dashboard için özet istatistik hesaplamaları (Faz 3 — İzlenebilirlik).

Bilerek `storage.py`'den ayrı bir modülde: bu fonksiyonlar sadece zaten
çekilmiş `trades`/`equity` listeleri üzerinde saf hesaplama yapar, SQLite'a
dokunmaz — bu da onları DB kurmadan, tek başlarına test etmeyi kolaylaştırır.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SummaryStats:
    total_return_pct: float
    win_rate: float
    max_drawdown_pct: float
    trade_count: int


def compute_drawdown_curve(equity_curve: list[dict]) -> list[dict]:
    """Her equity noktası için o ana kadarki zirveye göre drawdown yüzdesini
    hesaplar. Dashboard'daki drawdown grafiğini besler."""
    result = []
    peak = None
    for point in equity_curve:
        balance = point["balance"]
        peak = balance if peak is None else max(peak, balance)
        dd = (peak - balance) / peak * 100 if peak > 0 else 0.0
        result.append({"ts": point["ts"], "drawdown_pct": dd})
    return result


def compute_summary_stats(trades: list[dict], equity_curve: list[dict]) -> SummaryStats:
    """`trades`: storage.get_trades() ile zaman AZALAN sırada gelir (en yeni
    önce) — burada kronolojik sıraya çeviriyoruz. `buy_blocked` gibi
    gerçekleşmemiş kayıtlar (risk engeli) win-rate hesabına dahil edilmez.
    """
    if not equity_curve:
        return SummaryStats(total_return_pct=0.0, win_rate=0.0, max_drawdown_pct=0.0, trade_count=0)

    starting_balance = equity_curve[0]["balance"]
    final_balance = equity_curve[-1]["balance"]
    total_return_pct = (
        (final_balance / starting_balance - 1) * 100 if starting_balance > 0 else 0.0
    )

    chronological = sorted(trades, key=lambda t: t["ts"])
    open_entry: dict[str, float] = {}
    wins = 0
    closed = 0
    for t in chronological:
        if t["action"] == "buy":
            open_entry[t["symbol"]] = t["price"]
        elif t["action"] == "sell" and t["symbol"] in open_entry:
            entry_price = open_entry.pop(t["symbol"])
            closed += 1
            if t["price"] > entry_price:
                wins += 1

    win_rate = (wins / closed) if closed else 0.0

    drawdown_curve = compute_drawdown_curve(equity_curve)
    max_drawdown_pct = max((d["drawdown_pct"] for d in drawdown_curve), default=0.0)

    return SummaryStats(
        total_return_pct=total_return_pct,
        win_rate=win_rate,
        max_drawdown_pct=max_drawdown_pct,
        trade_count=closed,
    )
