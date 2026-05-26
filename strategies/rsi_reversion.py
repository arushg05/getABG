"""
getABG Example Strategy: RSI Mean Reversion
-------------------------------------------
Buys when RSI drops below 30 (oversold) and sells when RSI rises above 70 (overbought).
A classic contrarian approach suited for range-bound markets.
"""

class Strategy:
    METADATA = {
        "name": "RSI Mean Reversion",
        "description": "RSI 14-period. Buys <30 (oversold), sells >70 (overbought).",
        "type": "mean_reversion",
    }

    RSI_PERIOD = 14
    OVERSOLD = 30
    OVERBOUGHT = 70
    POSITION_SIZE_PCT = 0.15

    def on_init(self, params: dict):
        self.tickers = params.get("tickers", [])
        self._price_history = {t: [] for t in self.tickers}

    def _rsi(self, prices: list, period: int) -> float:
        if len(prices) <= period:
            return None
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        recent = deltas[-period:]
        gains = [d for d in recent if d > 0]
        losses = [abs(d) for d in recent if d < 0]
        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 1e-10
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def on_tick(self, timestamp: str, market_state: dict, portfolio_state: dict) -> list:
        orders = []
        total_equity = portfolio_state["total_equity"]
        open_positions = {p["ticker"]: p for p in portfolio_state["open_positions"]}

        for ticker, ohlcv in market_state.items():
            close = ohlcv["close"]
            if ticker not in self._price_history:
                self._price_history[ticker] = []
            self._price_history[ticker].append(close)

            rsi = self._rsi(self._price_history[ticker], self.RSI_PERIOD)
            if rsi is None:
                continue

            if rsi < self.OVERSOLD and ticker not in open_positions:
                qty = round((total_equity * self.POSITION_SIZE_PCT) / close, 2)
                if qty > 0:
                    orders.append({"ticker": ticker, "action": "BUY", "quantity": qty, "order_type": "MARKET"})

            elif rsi > self.OVERBOUGHT and ticker in open_positions:
                orders.append({"ticker": ticker, "action": "SELL",
                               "quantity": open_positions[ticker]["qty"], "order_type": "MARKET"})
        return orders
