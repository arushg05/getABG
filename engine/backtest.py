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


def _calc_commission(commission_model: dict, price: float, qty: float) -> float:
    """
    Calculate trade commission based on the configured model.

    Models:
      - flat:      fixed dollar amount per trade (e.g. $1.99/trade)
      - per_share: fixed amount per share (e.g. $0.005/share — IB style)
      - pct:       percentage of notional (e.g. 0.1 for 0.1% — Indian market style)
    """
    if not commission_model:
        return 0.0
    model_type = commission_model.get("type", "pct")
    value = float(commission_model.get("value", 0.0))
    if value == 0.0:
        return 0.0
    if model_type == "flat":
        return value
    elif model_type == "per_share":
        return value * qty
    elif model_type == "pct":
        return (value / 100.0) * price * qty
    return 0.0


class Portfolio:
    """
    Virtual portfolio ledger managed exclusively by the Host engine.
    Tracks cash, open positions, margin allocation, and commission paid.
    """

    def __init__(self, initial_capital: float, commission_model: dict = None):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: Dict[str, dict] = {}  # {ticker: {qty, entry_price, direction, trade_id}}
        self.allocated_margin = 0.0
        self.commission_model = commission_model or {}
        self.total_commission_paid = 0.0

    def total_equity(self, current_prices: Dict[str, float]) -> float:
        """Mark-to-market total equity."""
        position_value = sum(
            pos["qty"] * current_prices.get(t, pos["entry_price"])
            for t, pos in self.positions.items()
        )
        return self.cash + position_value

    def can_afford(self, price: float, qty: float) -> bool:
        slippage_cost = price * qty * (SLIPPAGE_BPS / 10000)
        commission = _calc_commission(self.commission_model, price, qty)
        return self.cash >= (price * qty + slippage_cost + commission)

    def open_position(self, ticker: str, qty: float, price: float, direction: str, trade_id: int):
        slippage = price * SLIPPAGE_BPS / 10000
        fill_price = price + slippage if direction == "LONG" else price - slippage
        commission = _calc_commission(self.commission_model, fill_price, qty)
        cost = fill_price * qty + commission
        self.cash -= cost
        self.total_commission_paid += commission
        self.positions[ticker] = {
            "qty": qty,
            "entry_price": fill_price,  # store fill price (with slippage) for accurate PnL
            "direction": direction,
            "trade_id": trade_id,
        }
        self.allocated_margin += fill_price * qty
        return fill_price, slippage, commission

    def close_position(self, ticker: str, price: float) -> Optional[dict]:
        if ticker not in self.positions:
            return None
        pos = self.positions.pop(ticker)
        slippage = price * SLIPPAGE_BPS / 10000
        if pos["direction"] == "SHORT":
            fill_price = price + slippage  # Covering a short costs more
        else:
            fill_price = price - slippage  # Selling a long receives less
        commission = _calc_commission(self.commission_model, fill_price, pos["qty"])
        proceeds = fill_price * pos["qty"] - commission
        self.cash += proceeds
        self.total_commission_paid += commission
        self.allocated_margin -= pos["entry_price"] * pos["qty"]
        self.allocated_margin = max(0, self.allocated_margin)
        return {**pos, "exit_price": fill_price, "slippage_out": slippage, "commission_out": commission}

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
        commission_model: dict = None,
        lot_sizes: dict = None,
        benchmark_ticker: str = "SPY",
    ):
        """
        Args:
            commission_model: dict with 'type' ('flat'|'per_share'|'pct') and 'value'.
                              e.g. {"type": "pct", "value": 0.1} for 0.1% per side.
                              Defaults to no commission.
            lot_sizes: dict mapping ticker -> minimum lot size (int).
                       e.g. {"RELIANCE.NS": 1, "NIFTY": 50}.
                       Tickers not listed default to lot size 1.
        """
        self.strategy_path = strategy_path
        self.tickers = tickers
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.timeout_ms = timeout_ms
        self.verbose = verbose
        self.snapshot_every_n = snapshot_every_n
        self.commission_model = commission_model or {}
        self.lot_sizes = lot_sizes or {}
        self.benchmark_ticker = benchmark_ticker
        self._benchmark_df: Optional[pd.DataFrame] = None

        # Generate run ID
        self.run_id = str(uuid.uuid4())[:12].upper()

        # Setup database
        if db_path is None:
            os.makedirs("runs", exist_ok=True)
            db_path = os.path.join("runs", f"{self.run_id}.db")
        self.db_path = db_path
        self.db = StateDB(db_path)

        self.portfolio = Portfolio(initial_capital, commission_model=self.commission_model)
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

        # Fetch benchmark data (best-effort — failure is non-fatal)
        if self.benchmark_ticker and self.benchmark_ticker not in self.tickers:
            try:
                bmark_data = get_universe_data(
                    [self.benchmark_ticker], self.start_date, self.end_date,
                    verbose=False
                )
                if self.benchmark_ticker in bmark_data:
                    self._benchmark_df = bmark_data[self.benchmark_ticker]
                    self._log(f"  Benchmark: {self.benchmark_ticker} loaded")
            except Exception as e:
                self._log(f"  Benchmark {self.benchmark_ticker} unavailable: {e}")

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

    def _snap_to_lot(self, ticker: str, qty: float) -> float:
        """Round qty down to the nearest valid lot size for the given ticker."""
        lot = self.lot_sizes.get(ticker, 1)
        if lot <= 1:
            return qty
        import math
        snapped = math.floor(qty / lot) * lot
        return float(snapped)

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
                # Snap to lot size before any affordability check
                qty = self._snap_to_lot(ticker, qty)
                if qty <= 0:
                    self.db.log_event(
                        self.run_id, sim_time, "REJECTED_MARGIN",
                        ticker=ticker, direction="LONG", quantity=0, price=price,
                        notes="Quantity rounds to zero after lot-size adjustment"
                    )
                    self._log(f"  [REJECTED] {ticker} BUY — qty rounds to 0 after lot snap")
                    continue

                if not self.portfolio.can_afford(price, qty):
                    self.db.log_event(
                        self.run_id, sim_time, "REJECTED_MARGIN",
                        ticker=ticker, direction="LONG", quantity=qty, price=price,
                        notes="Insufficient funds"
                    )
                    self._log(f"  [REJECTED] {ticker} BUY {qty}@{price:.2f} - insufficient funds")
                    continue

                # Open position — DB stores fill_price (with slippage), not raw price
                fill_price, slippage, commission_in = self.portfolio.open_position(
                    ticker, qty, price, "LONG", trade_id=0  # placeholder; updated below
                )
                trade_id = self.db.open_trade(
                    self.run_id, ticker, "LONG", sim_time, fill_price, qty,
                    slippage_in=slippage, commission_in=commission_in
                )
                # Patch trade_id into the portfolio position
                self.portfolio.positions[ticker]["trade_id"] = trade_id

                self.db.log_event(
                    self.run_id, sim_time, "ORDER_FILLED",
                    ticker=ticker, direction="LONG", quantity=qty,
                    price=fill_price, slippage=slippage,
                    notes=f"Order type: {order_type} | Commission: {commission_in:.4f}"
                )
                self._log(f"  [FILLED] BUY {ticker} {qty}@{fill_price:.4f} (comm: {commission_in:.2f})")

            elif action == "SELL" and ticker not in self.portfolio.positions:
                self.db.log_event(
                    self.run_id, sim_time, "REJECTED_MARGIN",
                    ticker=ticker, notes="SELL rejected — no open position"
                )
                self._log(f"  [REJECTED] SELL {ticker} — no open position to close")

            elif action == "SELL" and ticker in self.portfolio.positions:
                pos_info = self.portfolio.close_position(ticker, price)
                if pos_info:
                    self.db.close_trade(
                        pos_info["trade_id"], sim_time, pos_info["exit_price"],
                        slippage_out=pos_info["slippage_out"],
                        commission_out=pos_info["commission_out"]
                    )
                    self.db.log_event(
                        self.run_id, sim_time, "POSITION_CLOSED",
                        ticker=ticker, direction="LONG",
                        quantity=pos_info["qty"], price=pos_info["exit_price"],
                        slippage=pos_info["slippage_out"],
                        notes=f"Commission: {pos_info['commission_out']:.4f}"
                    )
                    self._log(f"  [CLOSED] {ticker} @{pos_info['exit_price']:.4f} (comm: {pos_info['commission_out']:.2f})")

    def _close_all_positions(self, date: pd.Timestamp, current_prices: Dict[str, float]):
        """Force-close all open positions at end of backtest."""
        sim_time = str(date.date())
        for ticker in list(self.portfolio.positions.keys()):
            price = current_prices.get(ticker)
            if price is not None:
                pos_info = self.portfolio.close_position(ticker, price)
                if pos_info:
                    self.db.close_trade(
                        pos_info["trade_id"], sim_time, pos_info["exit_price"],
                        slippage_out=pos_info["slippage_out"],
                        commission_out=pos_info["commission_out"]
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

        # Register run in database (store commission/lot config in Parameters for record)
        run_params = {}
        if self.commission_model:
            run_params["commission_model"] = self.commission_model
        if self.lot_sizes:
            run_params["lot_sizes"] = self.lot_sizes
        self.db.create_run(
            self.run_id, strategy_name, self.initial_capital, self.tickers,
            parameters=run_params
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
                    if p0 is not None and p1 is not None and p0 > 0:
                        bnh_returns.append((p1 - p0) / p0)
                buy_and_hold_return_pct = (sum(bnh_returns) / len(bnh_returns) * 100) if bnh_returns else 0.0

            # Build benchmark equity curve aligned to trading dates
            benchmark_curve = []
            if self._benchmark_df is not None:
                bdf = self._benchmark_df["Close"].reindex(self._trading_dates, method="ffill").dropna()
                if not bdf.empty:
                    norm = self.initial_capital / float(bdf.iloc[0])
                    benchmark_curve = [
                        {"time": str(d.date()), "equity": round(float(v) * norm, 2)}
                        for d, v in bdf.items()
                    ]

            self.db.finalize_run(self.run_id, "COMPLETED", {
                "buy_and_hold_return_pct": buy_and_hold_return_pct,
                "total_commission_paid": round(self.portfolio.total_commission_paid, 4),
                "benchmark_ticker": self.benchmark_ticker or "",
                "benchmark_curve": benchmark_curve,
            })
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
        self._log(f"Commission   : ${perf['total_commission_paid']:.2f}")

        return report
