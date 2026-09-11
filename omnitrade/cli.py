"""Kullanım:
    python -m omnitrade.cli run            # dry-run veya canlı döngüyü başlat (config'e göre)
    python -m omnitrade.cli backtest --csv data/BTCUSDT_1h.csv --symbol BTC/USDT
    python -m omnitrade.cli web            # dashboard'u başlat (http://localhost:8080)
"""
from __future__ import annotations

import argparse
import logging
import sys

from omnitrade.config import load_config


def _apply_log_level(config) -> None:
    """Faz 3: log seviyesi artık config.yaml'daki `log_level`'dan okunuyor
    (önceden `logging.basicConfig` her zaman INFO'ya sabitti). Geçersiz bir
    değer verilirse sessizce INFO'ya düşülür."""
    level = getattr(logging, config.log_level, None)
    if not isinstance(level, int):
        logging.warning("Geçersiz log_level=%r, INFO kullanılıyor.", config.log_level)
        level = logging.INFO
    logging.getLogger().setLevel(level)


def cmd_run(args: argparse.Namespace) -> None:
    from omnitrade.engine import TradingEngine

    config = load_config(args.config)
    _apply_log_level(config)
    engine = TradingEngine(config)
    engine.run_forever()


def cmd_backtest(args: argparse.Namespace) -> None:
    from omnitrade.backtest import load_csv, run_backtest, run_walk_forward
    from omnitrade.strategies import get_strategy

    config = load_config(args.config)
    strategy_name = args.strategy or config.strategy
    # --strategy ile config'te olmayan bir strateji seçilirse parametreler
    # boş kalır (strateji kendi defaultlarını kullanır).
    params = config.strategy_params if strategy_name == config.strategy else None
    strategy = get_strategy(strategy_name, params)
    df = load_csv(args.csv)
    risk_config = None if args.no_risk else config.risk

    if args.walk_forward and args.walk_forward > 1:
        results = run_walk_forward(
            df, strategy, args.symbol, n_splits=args.walk_forward,
            starting_balance=args.balance, fee_pct=config.fee_pct,
            slippage_pct=config.slippage_pct, risk_config=risk_config,
        )
        if not results:
            print("Walk-forward için yeterli veri yok (n_splits'i azalt ya da daha fazla mum indir).")
            return
        for r in results:
            print(r)
        returns = [r.total_return_pct for r in results]
        print(
            f"--- {len(results)} dönem özeti: ortalama getiri "
            f"{sum(returns)/len(returns):+.2f}% | en kötü dönem "
            f"{min(returns):+.2f}% | en iyi dönem {max(returns):+.2f}% ---"
        )
    else:
        result = run_backtest(
            df, strategy, args.symbol, starting_balance=args.balance,
            fee_pct=config.fee_pct, slippage_pct=config.slippage_pct,
            risk_config=risk_config,
        )
        print(result)


def cmd_web(args: argparse.Namespace) -> None:
    from omnitrade.web.server import serve

    config = load_config(args.config)
    _apply_log_level(config)
    serve(config)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(prog="omnitrade")
    parser.add_argument("--config", default="config/config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="Bot döngüsünü başlat (dry-run/canlı, config'e göre)")

    bt = sub.add_parser("backtest", help="Geçmiş CSV veriyle strateji test et")
    bt.add_argument("--csv", required=True)
    bt.add_argument("--symbol", default="BTC/USDT")
    bt.add_argument("--strategy", default=None)
    bt.add_argument("--balance", type=float, default=1000.0)
    bt.add_argument(
        "--no-risk", action="store_true",
        help="config.yaml'daki risk kurallarını (stop-loss/take-profit/pozisyon "
             "limiti) uygulama, eski basit stake_fraction davranışını kullan.",
    )
    bt.add_argument(
        "--walk-forward", type=int, default=None, metavar="N",
        help="Veriyi N ardışık döneme bölüp her birinde bağımsız backtest çalıştır "
             "(overfitting kontrolü — strateji tek bir dönemde şans eseri mi iyi "
             "çıkıyor, yoksa zaman içinde tutarlı mı görmek için). N>=2 gerekir.",
    )

    sub.add_parser("web", help="Web dashboard'u başlat")

    args = parser.parse_args(argv)
    {"run": cmd_run, "backtest": cmd_backtest, "web": cmd_web}[args.command](args)


if __name__ == "__main__":
    main(sys.argv[1:])
