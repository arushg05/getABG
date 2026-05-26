"""
getABG Core Backtest Engine
Implements the Two-Pass Hybrid Execution Architecture from PRD §3.2 and SRS §1.
Pass 1: Vectorized macro-filter across full dataset.
Pass 2: Event-driven micro-simulation with portfolio management.
"""

import os
import uuid
import json
import math
import time
import traceback
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Any

from database.state_db import StateDB
from sandbox.worker import StrategyWorker, validate_action_queue, SandboxViolation
from data.ingestion import get_universe_data
from metrics.performance import build_performance_report

SLIPPAGE_BPS = 5  # 5 basis points default slippage model


class Portfolio:
    """
    Virtual portfolio ledger managed exclusively by the Host engine.
    Tracks cash, open positions, and margin allocation.
    """

    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: Dict[str, dict] = {}  # {ticker: {qty, entry_price, direction, trade_id}}
        self.allocated_margin = 0.0

    def total_equity(self, current_prices: Dict[str, float]) -> float:
        """Mark-to-market total equity."""
        position_value = sum(
            pos["qty"] * current_prices.get(t, pos["entry_price"])
            for t, pos in self.positions.items()
        )
        return self.cash + position_value

    def can_afford(self, price: float, qty: float) -> bool:
        cost = price * qty * (1 + SLIPPAGE_BPS / 10000)
        return self.cash >= cost

    def open_position(self, ticker: str, qty: float, price: float, direction: str, trade_id: int):
        slippage = price * SLIPPAGE_BPS / 10000
        fill_price = price + slippage if direction == "LONG" else price - slippage
        cost = fill_price * qty
        self.cash -= cost
        self.positions[ticker] = {
            "qty": qty,
            "entry_price": fill_price,
            "direction": direction,
            "trade_id": trade_id,
        }
        self.allocated_margin += cost
        return fill_price, slippage

    def close_position(self, ticker: str, price: float) -> Optional[dict]:
        if ticker not in self.positions:
            return None
        pos = self.positions.pop(ticker)
        slippage = price * SLIPPAGE_BPS / 10000
        fill_price = price - slippage  # Pay slippage on exit too
        proceeds = fill_price * pos["qty"]
        self.cash += proceeds
        self.allocated_margin -= pos["entry_price"] * pos["qty"]
        self.allocated_margin = max(0, self.allocated_margin)
        return {**pos, "exit_price": fill_price, "slippage_out": slippage}

    def to_state(self, current_prices: Dict[str, float]) -> dict:
        return {
            "available_cash": round(self.cash, 2),
            "allocated_margin": round(self.allocated_margin, 2),
            "total_equity": round(self.total_equity(current_prices), 2),
            "open_positions": [
                {
                    "ticker": t,
                    "qty": p["qty"],
                    "entry_price": round(p["entry_price"], 4),
                    "direction": p["direction"],
                    "unrealized_pnl": round(
                        (current_prices.get(t, p["entry_price"]) - p["entry_price"]) * p["qty"], 2
                    ),
                }
                for t, p in self.positions.items()
            ],
        }


class BacktestEngine:
    """
    The getABG Host Engine.
    Orchestrates data, time loop, sandbox, and state-machine logging.
    """

    def __init__(
        self,
        strategy_path: str,
        tickers: List[str],
        start_date: str,
        end_date: str,
        initial_capital: float = 100_000.0,
        db_path: str = None,
        timeout_ms: int = 5000,
        verbose: bool = True,
        snapshot_every_n: int = 1,
    ):
        self.strategy_path = strategy_path
        self.tickers = tickers
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.timeout_ms = timeout_ms
        self.verbose = verbose
        self.snapshot_every_n = snapshot_every_n

        # Generate run ID
        self.run_id = str(uuid.uuid4())[:12].upper()

        # Setup database
        if db_path is None:
            os.makedirs("runs", exist_ok=True)
            db_path = os.path.join("runs", f"{self.run_id}.db")
        self.db_path = db_path
        self.db = StateDB(db_path)

        self.portfolio = Portfolio(initial_capital)
        self._universe: Dict[str, pd.DataFrame] = {}
        self._aligned: pd.DataFrame = None  # Multi-index aligned OHLCV
        self._trading_dates: pd.DatetimeIndex = None

    # ── Phase 0: Setup ────────────────────────────────────────────────────────

    def _log(self, msg: str):
        if self.verbose:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"  [{ts}] {msg}")

    # ── Phase 1: Data Ingestion ───────────────────────────────────────────────

    def load_data(self):
        self._log("Phase 1 — Data Ingestion")
        self._universe = get_universe_data(
            self.tickers, self.start_date, self.end_date,
            verbose=self.verbose
        )
        if not self._universe:
            raise ValueError("No data loaded for any ticker. Check tickers and date range.")

        # Align all tickers on common trading dates (inner join on Date)
        close_frames = {t: df["Close"].rename(t) for t, df in self._universe.items()}
        self._aligned = pd.concat(close_frames, axis=1).dropna(how="all")
        self._trading_dates = self._aligned.index
        self._log(f"  Loaded {len(self._universe)} tickers, {len(self._trading_dates)} trading days")

    # ── Phase 2: Vectorized Macro-Filter ─────────────────────────────────────

    def _vectorized_filter(self) -> pd.DatetimeIndex:
        """
        Pass 1: High-speed matrix scan to flag "interesting" windows.
        Default filter: days where at least one ticker has >1% price move
        or is within 5% of its 20-day high (breakout potential).
        Strategies with custom macro filters can override this.
        """
        self._log("Phase 2 — Vectorized Macro-Filter")
        close = self._aligned

        # Rolling 20-day high
        rolling_high = close.rolling(20, min_periods=5).max()
        near_high = (close / rolling_high) > 0.95  # within 5% of 20d high

        # 1% daily move
        daily_return = close.pct_change().abs()
        high_vol_day = daily_return > 0.01

        # Flag any date where ANY ticker satisfies either condition
        active_mask = (near_high | high_vol_day).any(axis=1)
        active_dates = self._trading_dates[active_mask]
        self._log(f"  Macro-filter: {len(active_dates)}/{len(self._trading_dates)} active days")
        return active_dates

    # ── Phase 3: Event-Driven Simulation ─────────────────────────────────────

    def _get_market_state(self, date: pd.Timestamp) -> Dict[str, dict]:
        """Build the market state payload for a given date."""
        state = {}
        for ticker, df in self._universe.items():
            if date in df.index:
                row = df.loc[date]
                state[ticker] = {
                    "open": round(float(row.get("Open", row["Close"])), 4),
                    "high": round(float(row.get("High", row["Close"])), 4),
                    "low": round(float(row.get("Low", row["Close"])), 4),
                    "close": round(float(row["Close"]), 4),
                    "volume": int(row.get("Volume", 0) or 0),
                }
        return state

    def _get_current_prices(self, date: pd.Timestamp) -> Dict[str, float]:
        prices = {}
        for ticker, df in self._universe.items():
            if date in df.index:
                prices[ticker] = float(df.loc[date, "Close"])
        return prices

    def _process_orders(
        self,
        action_queue: List[dict],
        date: pd.Timestamp,
        current_prices: Dict[str, float],
    ):
        """Execute validated orders against the portfolio."""
        sim_time = str(date.date())

        for order in action_queue:
            ticker = order["ticker"]
            action = order["action"]
            qty = float(order.get("quantity", 0))
            order_type = order.get("order_type", "MARKET")
            price = current_prices.get(ticker)

            if price is None:
                self.db.log_event(self.run_id, sim_time, "REJECTED_MARGIN",
                                  ticker=ticker, notes="Price not available for ticker")
                continue

            if action == "BUY" and ticker not in self.portfolio.positions:
                if not self.portfolio.can_afford(price, qty):
                    self.db.log_event(
                        self.run_id, sim_time, "REJECTED_MARGIN",
                        ticker=ticker, direction="LONG", quantity=qty, price=price,
                        notes="Insufficient funds"
                    )
                    self._log(f"  [REJECTED] {ticker} BUY {qty}@{price:.2f} - insufficient funds")
                    continue

                # Open position
                trade_id = self.db.open_trade(
                    self.run_id, ticker, "LONG", sim_time, price, qty
                )
                fill_price, slippage = self.portfolio.open_position(
                    ticker, qty, price, "LONG", trade_id
                )
                self.db.log_event(
                    self.run_id, sim_time, "ORDER_FILLED",
                    ticker=ticker, direction="LONG", quantity=qty,
                    price=fill_price, slippage=slippage,
                    notes=f"Order type: {order_type}"
                )
                self._log(f"  [FILLED] BUY {ticker} {qty}@{fill_price:.4f}")

            elif action == "SELL" and ticker in self.portfolio.positions:
                pos_info = self.portfolio.close_position(ticker, price)
                if pos_info:
                    self.db.close_trade(
                        pos_info["trade_id"], sim_time, pos_info["exit_price"],
                        slippage_out=pos_info["slippage_out"]
                    )
                    self.db.log_event(
                        self.run_id, sim_time, "POSITION_CLOSED",
                        ticker=ticker, direction="LONG",
                        quantity=pos_info["qty"], price=pos_info["exit_price"],
                        slippage=pos_info["slippage_out"]
                    )
                    self._log(f"  [CLOSED] {ticker} @{pos_info['exit_price']:.4f}")

    def _close_all_positions(self, date: pd.Timestamp, current_prices: Dict[str, float]):
        """Force-close all open positions at end of backtest."""
        sim_time = str(date.date())
        for ticker in list(self.portfolio.positions.keys()):
            price = current_prices.get(ticker)
            if price:
                pos_info = self.portfolio.close_position(ticker, price)
                if pos_info:
                    self.db.close_trade(
                        pos_info["trade_id"], sim_time, pos_info["exit_price"],
                        slippage_out=pos_info["slippage_out"]
                    )

    # ── Main Orchestrator ─────────────────────────────────────────────────────

    def run(self) -> Dict[str, Any]:
        """
        Execute the full backtest pipeline.
        Returns the standardized telemetry report.
        """
        strategy_name = os.path.basename(self.strategy_path).replace(".py", "")
        self._log(f"=== getABG Backtest Engine ===")
        self._log(f"Run ID: {self.run_id}")
        self._log(f"Strategy: {strategy_name}")
        self._log(f"Universe: {self.tickers}")
        self._log(f"Period: {self.start_date} -> {self.end_date}")
        self._log(f"Capital: ${self.initial_capital:,.2f}")
        print()

        # Register run in database
        self.db.create_run(
            self.run_id, strategy_name, self.initial_capital, self.tickers
        )

        try:
            # Phase 1: Load data
            self.load_data()

            # Phase 2: Vectorized filter
            active_dates = self._vectorized_filter()

            # Phase 3: Event-driven simulation
            self._log("Phase 3 — Event-Driven Micro-Simulation")

            with StrategyWorker(
                self.strategy_path,
                timeout_ms=self.timeout_ms,
                verbose=False
            ) as worker:
                worker.start({"tickers": self.tickers, "initial_capital": self.initial_capital})

                total_dates = len(self._trading_dates)
                for i, date in enumerate(self._trading_dates):
                    sim_time = str(date.date())
                    current_prices = self._get_current_prices(date)
                    market_state = self._get_market_state(date)
                    portfolio_state = self.portfolio.to_state(current_prices)

                    # We always call the worker to keep its history/indicators updated
                    try:
                        response = worker.tick(sim_time, market_state, portfolio_state)
                    except TimeoutError as te:
                        self.db.log_event(self.run_id, sim_time, "TIMEOUT_ERROR",
                                          notes=str(te))
                        self.db.finalize_run(self.run_id, "TIMEOUT")
                        raise

                    if not response.get("heartbeat", False):
                        self.db.log_event(self.run_id, sim_time, "TIMEOUT_ERROR",
                                          notes=response.get("error", "Heartbeat false"))

                    # Only process strategy orders if this date is in active_dates
                    if date in active_dates:
                        action_queue = validate_action_queue(
                            response.get("action_queue", [])
                        )
                        if action_queue:
                            self._process_orders(action_queue, date, current_prices)

                    # Snapshot portfolio every N days
                    if i % self.snapshot_every_n == 0:
                        equity = self.portfolio.total_equity(current_prices)
                        self.db.snapshot_portfolio(
                            self.run_id, sim_time,
                            self.portfolio.cash,
                            self.portfolio.allocated_margin,
                            equity,
                            portfolio_state["open_positions"],
                        )

                    if self.verbose and i % max(1, total_dates // 10) == 0:
                        equity = self.portfolio.total_equity(current_prices)
                        pct = (equity / self.initial_capital - 1) * 100
                        print(f"    [{i+1}/{total_dates}] {sim_time} | Equity: ${equity:,.2f} ({pct:+.1f}%)")

                # Force-close remaining positions on last day
                last_date = self._trading_dates[-1]
                last_prices = self._get_current_prices(last_date)
                self._close_all_positions(last_date, last_prices)

                # Calculate buy and hold returns
                first_date = self._trading_dates[0]
                first_prices = self._get_current_prices(first_date)
                bnh_returns = []
                for ticker in self.tickers:
                    p0 = first_prices.get(ticker)
                    p1 = last_prices.get(ticker)
                    if p0 and p1 and p0 > 0:
                        bnh_returns.append((p1 - p0) / p0)
                buy_and_hold_return_pct = (sum(bnh_returns) / len(bnh_returns) * 100) if bnh_returns else 0.0

            self.db.finalize_run(self.run_id, "COMPLETED", {"buy_and_hold_return_pct": buy_and_hold_return_pct})
            self._log("[OK] Backtest complete. Generating telemetry report...")

        except Exception as e:
            self.db.finalize_run(self.run_id, "FAILED")
            self._log(f"[FAIL] Backtest FAILED: {e}")
            traceback.print_exc()
            raise

        # Compile telemetry report
        run_meta = self.db.get_run(self.run_id)
        snapshots = self.db.get_snapshots(self.run_id)
        trades = self.db.get_trades(self.run_id)
        events = self.db.get_events(self.run_id)
        report = build_performance_report(run_meta, snapshots, trades, events)

        self._log(f"=== Results ===")
        perf = report["performance"]
        self._log(f"Total Return : {perf['total_return_pct']:+.2f}%")
        self._log(f"CAGR         : {perf['cagr_pct']:+.2f}%")
        self._log(f"Sharpe Ratio : {perf['sharpe_ratio']:.3f}")
        self._log(f"Max Drawdown : {perf['max_drawdown_pct']:.2f}%")
        self._log(f"Win Rate     : {perf['win_rate_pct']:.1f}%")
        self._log(f"Total Trades : {perf['total_trades']}")

        return report
