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
    strategy = get_strategy(args.strategy or config.strategy)
    df = load_csv(args.csv)
    result = run_backtest(df, strategy, args.symbol, starting_balance=args.balance)
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

    sub.add_parser("web", help="Web dashboard'u başlat")

    args = parser.parse_args(argv)
    {"run": cmd_run, "backtest": cmd_backtest, "web": cmd_web}[args.command](args)


if __name__ == "__main__":
    main(sys.argv[1:])
