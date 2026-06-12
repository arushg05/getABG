"""
getABG Performance Metrics Engine
Synthesizes SQLite trade/snapshot data into standardized telemetry report.
Implements all metrics specified in SRS §5.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional
from datetime import datetime


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    return a / b if b != 0 else default


def _safe_round(val: float, ndigits: int = 2) -> float:
    if val is None:
        return 0.0
    if math.isinf(val):
        return 9999.99 if val > 0 else -9999.99
    if math.isnan(val):
        return 0.0
    return round(val, ndigits)


def compute_returns(equity_curve: List[float]) -> np.ndarray:
    """Compute daily returns from equity curve."""
    arr = np.array(equity_curve, dtype=float)
    if len(arr) < 2:
        return np.array([])
    returns = np.diff(arr) / arr[:-1]
    return returns[np.isfinite(returns)]


def cagr(initial: float, final: float, trading_days: int) -> float:
    """Compound Annual Growth Rate."""
    if initial <= 0 or trading_days <= 0 or final <= 0:
        return 0.0
    years = trading_days / 252.0
    return ((final / initial) ** (1.0 / years) - 1.0) * 100


def sharpe_ratio(returns: np.ndarray, risk_free_rate: float = 0.04) -> float:
    """Annualized Sharpe Ratio (daily returns, 252 trading days)."""
    if len(returns) < 2:
        return 0.0
    daily_rf = risk_free_rate / 252
    excess = returns - daily_rf
    std = np.std(excess, ddof=1)
    if std == 0:
        return 0.0
    return float(np.mean(excess) / std * math.sqrt(252))


def sortino_ratio(returns: np.ndarray, risk_free_rate: float = 0.04) -> float:
    """Sortino Ratio using downside deviation."""
    if len(returns) < 2:
        return 0.0
    daily_rf = risk_free_rate / 252
    excess = returns - daily_rf
    downside = np.minimum(0, excess)
    downside_sum_sq = np.sum(downside ** 2)
    if downside_sum_sq == 0:
        return float("inf") if np.mean(excess) > 0 else 0.0
    downside_std = math.sqrt(downside_sum_sq / len(excess))
    return float(np.mean(excess) / downside_std * math.sqrt(252))


def max_drawdown(equity_curve: List[float]) -> Dict[str, Any]:
    """
    Maximum drawdown percentage and peak-to-trough duration.
    Returns: {pct, peak_idx, trough_idx, recovery_idx, duration_days}
    """
    arr = np.array(equity_curve, dtype=float)
    if len(arr) < 2:
        return {"pct": 0.0, "duration_days": 0, "peak_idx": 0, "trough_idx": 0}

    peak = arr[0]
    peak_idx = 0
    max_dd = 0.0
    max_dd_peak = 0
    max_dd_trough = 0

    for i in range(1, len(arr)):
        if arr[i] > peak:
            peak = arr[i]
            peak_idx = i
        dd = (peak - arr[i]) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
            max_dd_peak = peak_idx
            max_dd_trough = i

    return {
        "pct": float(max_dd * 100),
        "peak_idx": int(max_dd_peak),
        "trough_idx": int(max_dd_trough),
        "duration_days": int(max_dd_trough - max_dd_peak),
    }


def profit_factor(trades: List[Dict]) -> float:
    """Gross Profit / Gross Loss."""
    wins = sum(t["Net_PnL"] for t in trades if (t["Net_PnL"] or 0) > 0)
    losses = sum(abs(t["Net_PnL"]) for t in trades if (t["Net_PnL"] or 0) < 0)
    return _safe_div(wins, losses, default=float("inf") if wins > 0 else 0.0)


def win_rate(trades: List[Dict]) -> float:
    """Percentage of profitable trades."""
    closed = [t for t in trades if t.get("Status") == "CLOSED" and t.get("Net_PnL") is not None]
    if not closed:
        return 0.0
    winners = sum(1 for t in closed if t["Net_PnL"] > 0)
    return float(winners / len(closed) * 100)


def time_in_market(snapshots: List[Dict], trades: List[Dict]) -> float:
    """Percentage of total backtest time with at least one open position."""
    if not snapshots:
        return 0.0
    invested = 0
    for snap in snapshots:
        try:
            import json
            positions = json.loads(snap.get("Open_Positions", "[]"))
            if positions:
                invested += 1
        except Exception:
            pass
    return float(invested / len(snapshots) * 100)


def average_trade_duration(trades: List[Dict]) -> float:
    """Average holding period in days for closed trades."""
    durations = []
    for t in trades:
        if t.get("Status") == "CLOSED" and t.get("Entry_Time") and t.get("Exit_Time"):
            try:
                entry = datetime.fromisoformat(t["Entry_Time"][:10])
                exit_ = datetime.fromisoformat(t["Exit_Time"][:10])
                durations.append((exit_ - entry).days)
            except Exception:
                pass
    return float(np.mean(durations)) if durations else 0.0


def build_performance_report(
    run_metadata: Dict,
    snapshots: List[Dict],
    trades: List[Dict],
    events: List[Dict],
) -> Dict[str, Any]:
    """
    Master function: compiles all SQLite data into the standardized
    telemetry report specified in SRS §5 Output Protocol.
    """
    closed_trades = [t for t in trades if t.get("Status") == "CLOSED"]
    initial_capital = float(run_metadata.get("Initial_Capital", 100_000))

    # Build equity curve from snapshots
    equity_curve = [s["Total_Equity_Value"] for s in snapshots]
    if not equity_curve:
        equity_curve = [initial_capital]

    final_equity = equity_curve[-1]
    total_return_pct = _safe_div(final_equity - initial_capital, initial_capital) * 100

    returns = compute_returns(equity_curve)
    dd_info = max_drawdown(equity_curve)
    trading_days = len(snapshots)

    # PnL breakdown
    total_net_pnl = sum(t.get("Net_PnL") or 0 for t in closed_trades)
    gross_wins = sum(t.get("Net_PnL") or 0 for t in closed_trades if (t.get("Net_PnL") or 0) > 0)
    gross_losses = sum(t.get("Net_PnL") or 0 for t in closed_trades if (t.get("Net_PnL") or 0) < 0)

    try:
        import json
        params = json.loads(run_metadata.get("Parameters") or "{}")
    except Exception:
        params = {}
    buy_and_hold_return_pct = params.get("buy_and_hold_return_pct", 0.0)
    total_commission_paid = params.get("total_commission_paid", 0.0)

    return {
        "metadata": {
            "run_id": run_metadata.get("Run_ID"),
            "strategy_name": run_metadata.get("Strategy_Name"),
            "start_date": run_metadata.get("Start_Timestamp", "")[:10],
            "end_date": run_metadata.get("End_Timestamp", "")[:10],
            "status": run_metadata.get("Status"),
            "initial_capital": initial_capital,
            "final_equity": round(final_equity, 2),
            "market_universe": run_metadata.get("Market_Universe"),
        },
        "performance": {
            "total_return_pct": _safe_round(total_return_pct, 3),
            "buy_and_hold_return_pct": _safe_round(buy_and_hold_return_pct, 3),
            "alpha_pct": _safe_round(total_return_pct - buy_and_hold_return_pct, 3),
            "cagr_pct": _safe_round(cagr(initial_capital, final_equity, trading_days), 3),
            "sharpe_ratio": _safe_round(sharpe_ratio(returns), 4),
            "sortino_ratio": _safe_round(sortino_ratio(returns), 4),
            "max_drawdown_pct": _safe_round(dd_info["pct"], 3),
            "max_drawdown_duration_days": dd_info["duration_days"],
            "profit_factor": _safe_round(profit_factor(closed_trades), 4),
            "win_rate_pct": _safe_round(win_rate(closed_trades), 2),
            "total_trades": len(closed_trades),
            "time_in_market_pct": _safe_round(time_in_market(snapshots, closed_trades), 2),
            "avg_trade_duration_days": _safe_round(average_trade_duration(closed_trades), 1),
            "gross_profit": _safe_round(gross_wins, 2),
            "gross_loss": _safe_round(gross_losses, 2),
            "net_pnl": _safe_round(total_net_pnl, 2),
            "total_commission_paid": _safe_round(total_commission_paid, 2),
        },
        "equity_curve": [
            {
                "time": s["Simulation_Time"][:10],
                "equity": round(s["Total_Equity_Value"], 2),
                "cash": round(s["Available_Cash"], 2),
                "margin": round(s["Allocated_Margin"], 2),
            }
            for s in snapshots
        ],
        "trade_log": [
            {
                "trade_id": t["Trade_ID"],
                "ticker": t["Ticker"],
                "direction": t["Direction"],
                "entry_time": t.get("Entry_Time", "")[:10],
                "exit_time": (t.get("Exit_Time") or "")[:10],
                "entry_price": round(t.get("Entry_Price") or 0, 4),
                "exit_price": round(t.get("Exit_Price") or 0, 4),
                "quantity": t.get("Quantity"),
                "slippage_total": round(
                    (t.get("Slippage_In") or 0) + (t.get("Slippage_Out") or 0), 4
                ),
                "commission_total": round(
                    (t.get("Commission_In") or 0) + (t.get("Commission_Out") or 0), 4
                ),
                "net_pnl": round(t.get("Net_PnL") or 0, 2),
                "status": t.get("Status"),
            }
            for t in trades
        ],
        "event_log": [
            {
                "event_id": e["Event_ID"],
                "time": e["Simulation_Time"][:10],
                "type": e["Event_Type"],
                "ticker": e.get("Ticker"),
                "direction": e.get("Direction"),
                "quantity": e.get("Quantity"),
                "price": e.get("Price"),
                "notes": e.get("Notes"),
            }
            for e in events[-200:]  # Last 200 events for dashboard
        ],
    }
