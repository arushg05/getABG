"""
getABG Example Strategy: Dual Moving Average Crossover
------------------------------------------------------
A classic trend-following strategy. Buys when the fast MA crosses above
the slow MA, and sells when it crosses below.

Strategy Contract (SRS §3):
  - Must define a class named `Strategy`
  - Must implement `on_tick(timestamp, market_state, portfolio_state)`
  - Return: list of order dicts or []
  - Each order: {"ticker": str, "action": "BUY"|"SELL", "quantity": float, "order_type": "MARKET"}
"""

class Strategy:
    """Dual Moving Average Crossover Strategy."""

    METADATA = {
        "name": "MA Crossover",
        "description": "Dual Moving Average Crossover (10/30 day). Trend-following.",
        "type": "trend",
    }

    FAST_PERIOD = 10   # Fast MA (10-day)
    SLOW_PERIOD = 30   # Slow MA (30-day)
    POSITION_SIZE_PCT = 0.2  # Risk 20% of portfolio per position

    def on_init(self, params: dict):
        """Called once before the simulation loop."""
        self.tickers = params.get("tickers", [])
        self.initial_capital = params.get("initial_capital", 100_000)
        # Price history buffer for MA calculation
        self._price_history = {t: [] for t in self.tickers}
        self._prev_signal = {t: None for t in self.tickers}

    def _moving_average(self, prices: list, period: int) -> float:
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period

    def on_tick(self, timestamp: str, market_state: dict, portfolio_state: dict) -> list:
        """
        Called at each simulated trading day.
        Returns a list of orders for the host engine to validate and fill.
        """
        orders = []
        cash = portfolio_state["available_cash"]
        total_equity = portfolio_state["total_equity"]
        open_positions = {p["ticker"]: p for p in portfolio_state["open_positions"]}

        for ticker, ohlcv in market_state.items():
            close = ohlcv["close"]

            # Update price history (look-ahead safe: only use current close)
            if ticker not in self._price_history:
                self._price_history[ticker] = []
            self._price_history[ticker].append(close)

            # Compute MAs
            fast_ma = self._moving_average(self._price_history[ticker], self.FAST_PERIOD)
            slow_ma = self._moving_average(self._price_history[ticker], self.SLOW_PERIOD)

            if fast_ma is None or slow_ma is None:
                continue  # Not enough history yet

            # Crossover signal
            current_signal = "BULL" if fast_ma > slow_ma else "BEAR"
            prev_signal = self._prev_signal.get(ticker)

            # Buy signal: fast MA just crossed above slow MA
            if (
                current_signal == "BULL"
                and prev_signal == "BEAR"
                and ticker not in open_positions
            ):
                # Position sizing: use POSITION_SIZE_PCT of total equity
                position_value = total_equity * self.POSITION_SIZE_PCT
                qty = round(position_value / close, 2)
                if qty > 0:
                    orders.append({
                        "ticker": ticker,
                        "action": "BUY",
                        "quantity": qty,
                        "order_type": "MARKET",
                    })

            # Sell signal: fast MA just crossed below slow MA
            elif (
                current_signal == "BEAR"
                and prev_signal == "BULL"
                and ticker in open_positions
            ):
                qty = open_positions[ticker]["qty"]
                orders.append({
                    "ticker": ticker,
                    "action": "SELL",
                    "quantity": qty,
                    "order_type": "MARKET",
                })

            self._prev_signal[ticker] = current_signal

        return orders
