"""
getABG AI Strategy Generator
Uses the Anthropic API to convert plain-English strategy descriptions into
valid getABG Strategy Python code.
"""

import os
import re

try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

SYSTEM_PROMPT = """You are an expert quantitative trading strategy developer for the getABG backtesting platform.

Your job is to convert a trader's plain-English strategy description into a valid Python Strategy class.

## STRICT CONTRACT — the code you generate MUST follow this exactly:

```python
class Strategy:
    def on_init(self, params: dict):
        # Called once before simulation. Set up state here.
        self.tickers = params.get("tickers", [])
        self.initial_capital = params.get("initial_capital", 100_000)
        # initialize any indicators, price history, signals, etc.

    def on_tick(self, timestamp: str, market_state: dict, portfolio_state: dict) -> list:
        # Called every trading day. Return a list of orders or [].
        # market_state: {ticker: {"open", "high", "low", "close", "volume"}}
        # portfolio_state: {"available_cash", "total_equity", "open_positions": [{"ticker", "qty", "entry_price", "unrealized_pnl"}]}
        orders = []
        # ... your logic ...
        return orders
```

## ORDER FORMAT — each order in the returned list must be:
```python
{"ticker": "AAPL", "action": "BUY", "quantity": 10.0, "order_type": "MARKET"}
# action: "BUY" or "SELL" only
# quantity: positive float (number of shares/units)
# order_type: always "MARKET" (LIMIT/STOP not yet supported)
```

## RULES:
- Do NOT import os, sys, subprocess, socket, requests, urllib, pathlib, open, eval, exec
- You MAY import: math, statistics, collections, datetime, random, numpy as np
- Keep price history in self._price_history = {ticker: []} and append each tick's close
- Always check `if len(prices) < required_period: continue` before computing indicators
- Never access future data (only use data up to and including current timestamp)
- Position sizing: use `portfolio_state["total_equity"] * fraction / close` for share count
- Only BUY if ticker not already in open_positions; only SELL if it is
- Round quantities to 2 decimal places with round(qty, 2)
- Add a METADATA dict with name, description, type (trend/mean_reversion/momentum/etc.)

## OUTPUT FORMAT:
- Return ONLY the Python code — no markdown fences, no explanation
- Start directly with the class definition or any allowed imports
- The code must be syntactically valid Python 3

## COMMON INDICATORS you can implement from scratch:
- SMA: sum(prices[-n:]) / n
- EMA: use a rolling multiplier: ema = alpha * price + (1 - alpha) * prev_ema
- RSI: compare avg gains vs avg losses over N periods
- Bollinger Bands: SMA ± (k * std of last N closes)
- ATR: average of (high-low, abs(high-prev_close), abs(low-prev_close)) over N bars
"""


def generate_strategy(description: str, model: str = "claude-haiku-4-5-20251001") -> dict:
    """
    Generate a Strategy class from a plain-English description.

    Returns:
        {"code": str, "error": None}  on success
        {"code": None, "error": str}  on failure
    """
    # Temporarily disabled
    return {"code": None, "error": "AI Strategy Generation is temporarily disabled."}

    if not _ANTHROPIC_AVAILABLE:
        return {"code": None, "error": "anthropic package not installed. Run: pip install anthropic"}

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"code": None, "error": "ANTHROPIC_API_KEY not set in environment"}

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Generate a getABG Strategy class for the following strategy:\n\n{description}",
                }
            ],
        )
        code = message.content[0].text.strip()

        # Strip markdown fences if the model included them despite instructions
        code = re.sub(r"^```python\s*", "", code)
        code = re.sub(r"^```\s*", "", code)
        code = re.sub(r"\s*```$", "", code)
        code = code.strip()

        # Basic sanity check
        if "class Strategy" not in code:
            return {"code": None, "error": "Model did not return a valid Strategy class. Try rephrasing your description."}

        return {"code": code, "error": None}

    except Exception as e:
        return {"code": None, "error": f"Generation failed: {str(e)}"}
