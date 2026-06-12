"""
getABG Walk-Forward Optimization Engine

Splits a date range into N windows of (in-sample training + out-of-sample test).
Runs the strategy on each window and aggregates results.

Why walk-forward?
  A strategy that looks great on a single backtest may be overfit to that period.
  Walk-forward testing reveals whether the strategy generalizes across market regimes
  by measuring out-of-sample performance separately.

Window structure (anchored, non-overlapping OOS):
  |------ IS ------||-- OOS --|
                   |------ IS ------||-- OOS --|
                                    |------ IS ------||-- OOS --|

Parameters:
  n_splits:    Number of windows (default 3)
  oos_ratio:   Fraction of each window that is out-of-sample (default 0.3 = 30%)
"""

import os
import uuid
import json
import tempfile
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import pandas as pd

from engine.backtest import BacktestEngine
from metrics.performance import build_performance_report


def _date_range_windows(
    start: str,
    end: str,
    n_splits: int,
    oos_ratio: float,
) -> List[Dict[str, str]]:
    """
    Divide [start, end] into n_splits windows, each with an in-sample
    and out-of-sample period.

    Returns list of dicts: [{"is_start", "is_end", "oos_start", "oos_end"}, ...]
    """
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    total_days = (end_dt - start_dt).days

    if total_days < n_splits * 60:
        raise ValueError(
            f"Date range too short for {n_splits} windows. "
            f"Need at least {n_splits * 60} days, got {total_days}."
        )

    window_days = total_days // n_splits
    oos_days = max(int(window_days * oos_ratio), 10)
    is_days = window_days - oos_days

    windows = []
    cursor = start_dt
    for i in range(n_splits):
        is_start = cursor
        is_end = is_start + timedelta(days=is_days - 1)
        oos_start = is_end + timedelta(days=1)
        oos_end = oos_start + timedelta(days=oos_days - 1)

        # Last window: extend OOS end to cover remaining days
        if i == n_splits - 1:
            oos_end = end_dt

        if oos_start > end_dt:
            break

        windows.append({
            "is_start":  is_start.strftime("%Y-%m-%d"),
            "is_end":    is_end.strftime("%Y-%m-%d"),
            "oos_start": oos_start.strftime("%Y-%m-%d"),
            "oos_end":   min(oos_end, end_dt).strftime("%Y-%m-%d"),
        })
        cursor = oos_start  # next IS starts where this OOS starts (anchored)

    return windows


def _run_single_window(
    strategy_path: str,
    tickers: List[str],
    start: str,
    end: str,
    initial_capital: float,
    commission_model: dict,
    lot_sizes: dict,
    benchmark_ticker: str,
    timeout_ms: int,
    verbose: bool,
    run_dir: str,
) -> Optional[Dict]:
    """Run one backtest window. Returns performance dict or None on failure."""
    run_id = str(uuid.uuid4())[:8].upper()
    reports = {}
    for ticker in tickers:
        try:
            subrun_id = f"WF_{run_id}_{ticker}"
            db_path = os.path.join(run_dir, f"{subrun_id}.db")
            engine = BacktestEngine(
                strategy_path=strategy_path,
                tickers=[ticker],
                start_date=start,
                end_date=end,
                initial_capital=initial_capital,
                db_path=db_path,
                timeout_ms=timeout_ms,
                verbose=verbose,
                commission_model=commission_model,
                lot_sizes=lot_sizes,
                benchmark_ticker=benchmark_ticker,
            )
            engine.run_id = subrun_id
            report = engine.run()
            reports[ticker] = report
        except Exception as e:
            if verbose:
                print(f"  [WF] Window {start}→{end} failed for {ticker}: {e}")

    if not reports:
        return None

    # Aggregate metrics across tickers (simple average)
    all_perf = [r["performance"] for r in reports.values()]
    keys = ["total_return_pct", "cagr_pct", "sharpe_ratio", "sortino_ratio",
            "max_drawdown_pct", "win_rate_pct", "profit_factor", "total_trades",
            "net_pnl", "total_commission_paid"]
    avg_perf = {}
    for k in keys:
        vals = [p.get(k, 0) for p in all_perf if p.get(k) is not None]
        avg_perf[k] = round(sum(vals) / len(vals), 4) if vals else 0

    # Use equity curve from first ticker
    first_ticker = list(reports.keys())[0]
    equity_curve = reports[first_ticker].get("equity_curve", [])

    return {"performance": avg_perf, "equity_curve": equity_curve}


def run_walk_forward(
    strategy_path: str,
    tickers: List[str],
    start_date: str,
    end_date: str,
    initial_capital: float = 100_000.0,
    n_splits: int = 3,
    oos_ratio: float = 0.3,
    commission_model: dict = None,
    lot_sizes: dict = None,
    benchmark_ticker: str = "SPY",
    timeout_ms: int = 5000,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Run a walk-forward optimization and return aggregated results.

    Returns:
    {
      "windows": [
        {
          "window": 1,
          "is_start", "is_end", "oos_start", "oos_end",
          "in_sample":     {performance dict},
          "out_of_sample": {performance dict},
        }, ...
      ],
      "summary": {
        "avg_oos_sharpe", "avg_oos_return", "avg_oos_drawdown",
        "consistency_score",   # % of OOS windows that are profitable
        "oos_equity_curve",    # combined OOS equity curve
      },
      "n_splits": int,
      "oos_ratio": float,
    }
    """
    windows = _date_range_windows(start_date, end_date, n_splits, oos_ratio)

    # Temp dir for this walk-forward run's DB files (auto-cleaned)
    run_dir = tempfile.mkdtemp(prefix="getabg_wf_")

    results = []
    combined_oos_curve = []
    oos_equity_start = initial_capital

    for i, w in enumerate(windows):
        if verbose:
            print(f"\n[WF] Window {i+1}/{len(windows)}: IS={w['is_start']}→{w['is_end']}  OOS={w['oos_start']}→{w['oos_end']}")

        # In-sample run
        is_result = _run_single_window(
            strategy_path, tickers,
            w["is_start"], w["is_end"],
            initial_capital, commission_model or {}, lot_sizes or {},
            benchmark_ticker, timeout_ms, verbose, run_dir,
        )

        # Out-of-sample run (same strategy, no re-training — tests generalization)
        oos_result = _run_single_window(
            strategy_path, tickers,
            w["oos_start"], w["oos_end"],
            initial_capital, commission_model or {}, lot_sizes or {},
            benchmark_ticker, timeout_ms, verbose, run_dir,
        )

        # Build continuous OOS equity curve scaled from previous endpoint
        if oos_result and oos_result.get("equity_curve"):
            curve = oos_result["equity_curve"]
            if curve:
                scale = oos_equity_start / initial_capital
                for point in curve:
                    combined_oos_curve.append({
                        "time": point["time"],
                        "equity": round(point["equity"] * scale, 2),
                    })
                last_equity = curve[-1]["equity"]
                oos_equity_start = last_equity * scale

        results.append({
            "window": i + 1,
            "is_start":  w["is_start"],
            "is_end":    w["is_end"],
            "oos_start": w["oos_start"],
            "oos_end":   w["oos_end"],
            "in_sample":     is_result["performance"] if is_result else None,
            "out_of_sample": oos_result["performance"] if oos_result else None,
        })

    # Summary stats across all OOS windows
    oos_perfs = [r["out_of_sample"] for r in results if r["out_of_sample"]]

    def _avg(key):
        vals = [p[key] for p in oos_perfs if p.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else 0

    profitable_windows = sum(1 for p in oos_perfs if p.get("total_return_pct", 0) > 0)
    consistency_score = round(profitable_windows / len(oos_perfs) * 100, 1) if oos_perfs else 0

    summary = {
        "avg_oos_return_pct":   _avg("total_return_pct"),
        "avg_oos_sharpe":       _avg("sharpe_ratio"),
        "avg_oos_sortino":      _avg("sortino_ratio"),
        "avg_oos_drawdown_pct": _avg("max_drawdown_pct"),
        "avg_oos_win_rate_pct": _avg("win_rate_pct"),
        "consistency_score_pct": consistency_score,
        "profitable_windows":   profitable_windows,
        "total_windows":        len(oos_perfs),
        "oos_equity_curve":     combined_oos_curve,
    }

    return {
        "n_splits": n_splits,
        "oos_ratio": oos_ratio,
        "tickers": tickers,
        "start_date": start_date,
        "end_date": end_date,
        "windows": results,
        "summary": summary,
    }
