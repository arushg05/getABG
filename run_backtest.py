#!/usr/bin/env python3
import os
import sys
import argparse
import json

# Add current directory to path so packages can be resolved
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.backtest import BacktestEngine

def main():
    parser = argparse.ArgumentParser(description="getABG CLI Backtest Runner")
    parser.add_argument("--strategy", type=str, default="ma_crossover",
                        help="Strategy name (e.g. ma_crossover, rsi_reversion) or path to a custom .py file")
    parser.add_argument("--tickers", nargs="+", default=["AAPL", "MSFT", "GOOGL"],
                        help="Space-separated list of symbols (e.g., AAPL MSFT RELIANCE.NS)")
    parser.add_argument("--start", type=str, default="2022-01-01",
                        help="Start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, default="2023-12-31",
                        help="End date YYYY-MM-DD")
    parser.add_argument("--capital", type=float, default=100000.0,
                        help="Initial capital in base currency")
    parser.add_argument("--output", type=str, default=None,
                        help="Path to JSON file to save the telemetry report")

    args = parser.parse_args()

    # Resolve strategy path
    strategy_key = args.strategy
    strategies_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "strategies"))
    built_in = {
        "ma_crossover": os.path.join(strategies_dir, "ma_crossover.py"),
        "rsi_reversion": os.path.join(strategies_dir, "rsi_reversion.py"),
        "bbsar": os.path.join(strategies_dir, "bbsar.py"),
    }
    strategy_path = built_in.get(strategy_key, strategy_key)

    if not os.path.exists(strategy_path):
        print(f"Error: Strategy not found: {strategy_key} (resolved to {strategy_path})", file=sys.stderr)
        sys.exit(1)

    reports = {}
    for ticker in args.tickers:
        print(f"\nRunning backtest for {ticker}...")
        engine = BacktestEngine(
            strategy_path=strategy_path,
            tickers=[ticker],
            start_date=args.start,
            end_date=args.end,
            initial_capital=args.capital,
            verbose=True
        )
        try:
            report = engine.run()
            reports[ticker] = report
        except Exception as e:
            print(f"Backtest failed for {ticker}: {e}", file=sys.stderr)

    if not reports:
        print("All backtest executions failed.", file=sys.stderr)
        sys.exit(1)

    # Save output report
    if len(args.tickers) == 1:
        final_report = list(reports.values())[0]
    else:
        # Take metadata from first one
        first_ticker = list(reports.keys())[0]
        meta = reports[first_ticker]["metadata"]
        final_report = {
            "run_id": meta.get("run_id"),
            "is_multi": True,
            "strategy_name": meta.get("strategy_name"),
            "start_date": meta.get("start_date"),
            "end_date": meta.get("end_date"),
            "initial_capital": meta.get("initial_capital"),
            "tickers": list(reports.keys()),
            "results": reports
        }

    if args.output:
        try:
            with open(args.output, "w") as f:
                json.dump(final_report, f, indent=2)
            print(f"\nReport saved to {args.output}")
        except Exception as e:
            print(f"Failed to save report to {args.output}: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
