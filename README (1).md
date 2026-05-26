# getABG — Quantitative Backtesting Platform

Institutional-grade equity backtesting for US (NASDAQ/NYSE) and Indian (NSE/BSE) markets.

---

## Architecture

```
getABG/
├── engine/
│   └── backtest.py        # Core hybrid execution engine (Two-Pass: vectorized + event-driven)
├── data/
│   └── ingestion.py       # Yahoo Finance fetcher + Parquet-like CSV caching
├── database/
│   └── state_db.py        # SQLite state-machine logger (SRS §2 schema)
├── sandbox/
│   └── worker.py          # Strategy subprocess isolation with timeout enforcement
├── metrics/
│   └── performance.py     # Sharpe, Sortino, CAGR, drawdown, profit factor
├── strategies/
│   ├── ma_crossover.py    # Built-in: Dual MA Crossover (10/30-day)
│   └── rsi_reversion.py   # Built-in: RSI Mean Reversion (period 14)
├── api/
│   └── server.py          # Flask REST API (serves dashboard)
├── dashboard/
│   └── Dashboard.jsx      # React dashboard (recharts, live polling)
├── run_backtest.py        # CLI entrypoint
└── cache/ohlcv/           # Auto-created local data cache
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install flask pandas numpy scipy requests
```

### 2. Run a backtest (CLI)

```bash
cd getabg/

# US equities — MA Crossover
python run_backtest.py \
  --strategy ma_crossover \
  --tickers AAPL MSFT GOOGL NVDA \
  --start 2021-01-01 \
  --end 2023-12-31 \
  --capital 100000

# Indian equities — RSI Reversion
python run_backtest.py \
  --strategy rsi_reversion \
  --tickers RELIANCE.NS TCS.NS INFY.NS HDFCBANK.NS \
  --start 2021-01-01 \
  --end 2023-12-31

# Save report as JSON
python run_backtest.py --strategy ma_crossover --output report.json
```

### 3. Run the API server

```bash
cd getabg/api/
python server.py
# → http://localhost:5050
```

### 4. Use the Dashboard (React)

Copy `dashboard/Dashboard.jsx` into your React app.

```bash
npm install recharts
```

The dashboard connects to `http://localhost:5050/api`.

---

## Writing Your Own Strategy

Create a `.py` file with a class named `Strategy`:

```python
class Strategy:
    
    def on_init(self, params: dict):
        """Called once before simulation. params has 'tickers' and 'initial_capital'."""
        self.tickers = params['tickers']
        self.price_history = {t: [] for t in self.tickers}
    
    def on_tick(self, timestamp: str, market_state: dict, portfolio_state: dict) -> list:
        """
        Called at each simulated trading day.
        
        market_state: {ticker: {open, high, low, close, volume}}
        portfolio_state: {available_cash, total_equity, open_positions: [...]}
        
        Return: list of orders, e.g.:
          [{"ticker": "AAPL", "action": "BUY", "quantity": 10, "order_type": "MARKET"}]
        """
        orders = []
        # ... your logic ...
        return orders
```

Run it:
```bash
python run_backtest.py --strategy strategies/my_strategy.py --tickers AAPL MSFT
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/ping` | Health check |
| GET | `/api/strategies` | List built-in strategies |
| POST | `/api/backtest/run` | Start a backtest (async) |
| GET | `/api/runs` | List all runs |
| GET | `/api/runs/{id}` | Full telemetry report |
| GET | `/api/runs/{id}/status` | Live run status |

### POST /api/backtest/run

```json
{
  "strategy": "ma_crossover",
  "tickers": ["AAPL", "MSFT", "GOOGL"],
  "start_date": "2022-01-01",
  "end_date": "2023-12-31",
  "initial_capital": 100000,
  "timeout_ms": 5000
}
```

---

## Safety & Sandbox Model (SRS §4)

- **Look-ahead prevention**: Strategy only receives market data up to T₀. Future data access results in a hard `LOOKAHEAD_VIOLATION`.
- **Timeout enforcement**: If strategy subprocess exceeds `timeout_ms`, the host terminates it and logs `TIMEOUT_ERROR`.
- **Margin rejection**: Orders exceeding `available_cash` are logged as `REJECTED_MARGIN` and silently skipped — simulation continues.
- **Corporate action normalization**: Prices are automatically split/dividend adjusted before the strategy ever sees them.

---

## Ticker Format Reference

| Market | Suffix | Example |
|--------|--------|---------|
| US (NYSE/NASDAQ) | none | `AAPL`, `MSFT`, `TSLA` |
| NSE India | `.NS` | `RELIANCE.NS`, `TCS.NS` |
| BSE India | `.BO` | `RELIANCE.BO`, `INFY.BO` |

---

## Performance Metrics

| Metric | Description |
|--------|-------------|
| CAGR | Compound Annual Growth Rate |
| Sharpe Ratio | Annualized (252-day), risk-free rate 4% |
| Sortino Ratio | Downside deviation only |
| Max Drawdown | Peak-to-trough % + duration in days |
| Profit Factor | Gross Profit / Gross Loss |
| Win Rate | % of closed trades with positive net PnL |
| Time in Market | % of days with at least one open position |

---

## Database Schema (SQLite)

Each run generates its own `.db` file in `runs/`:

- `Run_Metadata` — strategy, parameters, status
- `Execution_Events` — SIGNAL, ORDER_SENT, ORDER_FILLED, REJECTED_MARGIN, TIMEOUT_ERROR
- `Portfolio_Snapshots` — daily mark-to-market equity
- `Trade_Log` — full round-trip trade records with PnL
