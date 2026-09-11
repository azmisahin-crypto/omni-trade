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


def cmd_run(args: argparse.Namespace) -> None:
    from omnitrade.engine import TradingEngine

    config = load_config(args.config)
    engine = TradingEngine(config)
    engine.run_forever()


def cmd_backtest(args: argparse.Namespace) -> None:
    from omnitrade.backtest import load_csv, run_backtest
    from omnitrade.strategies import get_strategy

    config = load_config(args.config)
    strategy_name = args.strategy or config.strategy
    # --strategy ile config'te olmayan bir strateji seçilirse parametreler
    # boş kalır (strateji kendi defaultlarını kullanır).
    params = config.strategy_params if strategy_name == config.strategy else None
    strategy = get_strategy(strategy_name, params)
    df = load_csv(args.csv)
    risk_config = None if args.no_risk else config.risk
    result = run_backtest(
        df, strategy, args.symbol, starting_balance=args.balance,
        fee_pct=config.fee_pct, slippage_pct=config.slippage_pct,
        risk_config=risk_config,
    )
    print(result)


def cmd_web(args: argparse.Namespace) -> None:
    from omnitrade.web.server import serve

    config = load_config(args.config)
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

    sub.add_parser("web", help="Web dashboard'u başlat")

    args = parser.parse_args(argv)
    {"run": cmd_run, "backtest": cmd_backtest, "web": cmd_web}[args.command](args)


if __name__ == "__main__":
    main(sys.argv[1:])
