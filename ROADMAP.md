# getABG Production Roadmap — Next 6 Features

> Priority-ordered implementation plan for scaling getABG into a production-grade backtesting platform.

---

## 1. Portfolio-Level Simulation

### Current State
Each ticker runs as a completely independent backtest with its own capital pool. A 3-ticker run with $100k gives each ticker a separate $100k — there is no shared capital, no cross-ticker position sizing, and no aggregate portfolio view.

### What Needs to Change

**Engine (`engine/backtest.py`)**
- Single `Portfolio` instance shared across all tickers in one simulation loop
- Unified trading date index built from the union/intersection of all ticker calendars
- Capital allocated across tickers based on the active position sizing model (see Feature 3)
- `total_equity()` marks all open positions to market simultaneously

**Order Processing**
- Orders across tickers on the same day processed in a deterministic sequence (alphabetical or by signal strength)
- Affordability check references shared cash pool, not per-ticker cash
- `allocated_margin` tracks exposure across the full portfolio

**Performance Report**
- Portfolio-level equity curve (sum of all positions + cash)
- Per-ticker contribution to total PnL (attribution)
- Aggregate metrics: portfolio Sharpe, portfolio drawdown, correlation between ticker sub-curves

### API / UI Changes
- `initial_capital` is now the total portfolio budget
- Results page gets a "Portfolio" tab showing the combined curve alongside per-ticker breakdowns
- Ticker selector in results switches between portfolio view and individual ticker drill-down

### Acceptance Criteria
- Running AAPL + MSFT + GOOGL with $100k allocates a shared pool, not $300k total
- If AAPL consumes 60% of capital, only 40% is available for MSFT/GOOGL signals
- Portfolio equity curve matches manual sum of (cash + all open position values) at every date

---

## 2. Limit / Stop Orders

### Current State
Only `MARKET` orders are supported. All fills happen at the next day's close price with a flat 5 BPS slippage model. This is unrealistic — strategies that use entry/exit levels get filled at prices they never specified.

### Order Types to Add

| Type | Trigger | Fill Logic |
|------|---------|-----------|
| `LIMIT BUY` | Price drops to or below limit price | Fill at limit price (or better) |
| `LIMIT SELL` | Price rises to or at limit price | Fill at limit price (or better) |
| `STOP BUY` | Price rises to or above stop price | Fill at stop price (market-like) |
| `STOP SELL` | Price drops to or below stop price | Fill at stop price (market-like) |
| `STOP_LIMIT` | Stop triggers, then limit executes | Two-stage fill |

### Strategy Contract Change
```python
# New order format
{
    "ticker": "AAPL",
    "action": "BUY",
    "quantity": 10,
    "order_type": "LIMIT",
    "limit_price": 148.50,      # required for LIMIT
    "stop_price": 152.00,       # required for STOP / STOP_LIMIT
    "expire_after_days": 5      # optional GTC — cancel if unfilled after N days
}
```

### Engine Changes (`engine/backtest.py`)
- `_pending_orders` list persists unfilled limit/stop orders across days
- Each day, before processing new signals, check pending orders against `high`/`low` of that day
- A LIMIT BUY fills if `low <= limit_price` on any day after order placement
- A STOP SELL fills if `low <= stop_price` (uses low to model intraday touch)
- GTC orders track days-since-placed and auto-cancel after `expire_after_days`
- Fill price = limit/stop price (not close), with slippage still applied

### DB Changes (`database/state_db.py`)
- Add `Order_Type`, `Limit_Price`, `Stop_Price`, `Placed_Time`, `Expire_After_Days` columns to `Trade_Log`
- New status: `PENDING` (placed but not yet filled), `EXPIRED` (GTC cancelled)

### Acceptance Criteria
- LIMIT BUY at $148.50 does not fill on a day where low=$149.00
- LIMIT BUY at $148.50 fills on a day where low=$147.00 (price touched the level)
- STOP SELL at $145.00 fires on the day price breaches $145 and closes the position
- GTC orders expire after N days if never triggered

---

## 3. Position Sizing Models

### Current State
Strategy code manually computes quantity using ad-hoc math like `total_equity * 0.1 / close`. There is no engine-level enforcement, no risk-aware sizing, and no consistency across strategies.

### Models to Implement

**Fixed Fractional**
Invest a fixed percentage of current equity per trade.
```
qty = floor((equity * fraction) / price)
```
Parameter: `fraction` (e.g. 0.1 = 10% per trade)

**Kelly Criterion**
Optimal fraction based on historical win rate and average win/loss ratio.
```
kelly_fraction = win_rate - (1 - win_rate) / (avg_win / avg_loss)
qty = floor((equity * kelly_fraction * kelly_multiplier) / price)
```
Parameters: `kelly_multiplier` (e.g. 0.5 for half-Kelly — safer)

**Volatility-Adjusted (ATR-based)**
Size positions inversely proportional to recent volatility so every trade has equal dollar risk.
```
atr = average(high - low, abs(high - prev_close), abs(low - prev_close)) over 14 days
risk_per_trade = equity * risk_pct          # e.g. 1% of equity at risk
qty = floor(risk_per_trade / (atr_multiplier * atr))
```
Parameters: `risk_pct`, `atr_period`, `atr_multiplier`

**Equal Weight**
Divide capital equally among all tickers in the universe.
```
qty = floor((equity / n_tickers) / price)
```

**Max Concentration Cap**
Hard limit: no single position can exceed X% of portfolio regardless of model output.

### Integration
- `position_sizer` config passed to `BacktestEngine` alongside `commission_model`
- Engine calls `sizer.compute_qty(ticker, price, portfolio_state, market_state)` before affordability check
- Strategy still returns quantity in orders, but engine can override with sized quantity
- UI: dropdown to pick model + model-specific parameter inputs

### Acceptance Criteria
- ATR-based sizing produces smaller quantities for high-volatility tickers
- Kelly fraction correctly clamps to 0 when win rate < loss ratio
- Max concentration cap rejects orders that would exceed the threshold even if cash is available

---

## 4. Monte Carlo Simulation

### What It Is
Takes the sequence of trade returns from a completed backtest and resamples them randomly N times (e.g. 1000 iterations) to produce a distribution of possible outcomes. Answers the question: "Was this result lucky, or is it robust?"

### Why It Matters
A strategy with 30 trades and a 20% return could be great or could be random. Monte Carlo reveals the 5th–95th percentile range of outcomes under different orderings of the same trades.

### Implementation (`engine/monte_carlo.py`)

```python
def run_monte_carlo(
    trade_returns: list[float],   # list of per-trade return %
    initial_capital: float,
    n_iterations: int = 1000,
    confidence_levels: list = [0.05, 0.25, 0.5, 0.75, 0.95],
) -> dict:
    # Resample trade sequence with replacement, compute equity curve per iteration
    # Return percentile bands, median curve, worst/best case
```

**Output**
```json
{
  "median_return_pct": 18.4,
  "p5_return_pct": -12.1,
  "p95_return_pct": 48.2,
  "probability_of_profit_pct": 73.0,
  "median_max_drawdown_pct": 14.2,
  "p95_max_drawdown_pct": 31.7,
  "equity_bands": {
    "p5":    [...],
    "p25":   [...],
    "p50":   [...],
    "p75":   [...],
    "p95":   [...]
  }
}
```

### API Endpoint
`POST /api/runs/{run_id}/monte-carlo`
- Reads trade log from existing completed run
- Runs N iterations server-side (fast — pure numpy)
- Returns percentile bands

### UI Changes
- New tab in ResultsDashboard: "Monte Carlo"
- Fan chart showing equity percentile bands (shaded areas between p5–p95, p25–p75, median line)
- Summary stats: probability of profit, median drawdown, worst-case scenario

### Acceptance Criteria
- 1000 iterations completes in under 2 seconds (numpy vectorized)
- p50 curve closely matches the original backtest curve
- Probability of profit matches ratio of profitable iterations / total iterations

---

## 5. Run Comparison UI

### What It Is
A side-by-side table and overlay chart letting users compare multiple completed backtest runs. Essential for A/B testing strategy variants (e.g. RSI(14) vs RSI(21), different commission settings, different date ranges).

### UI Layout

**Comparison Table**
| Metric | Run A | Run B | Run C |
|--------|-------|-------|-------|
| Total Return | +24.1% | +18.3% | +31.2% |
| Sharpe Ratio | 1.42 | 0.98 | 1.71 |
| Max Drawdown | -12.4% | -8.1% | -19.3% |
| Win Rate | 58.3% | 62.1% | 54.7% |
| Total Trades | 47 | 31 | 63 |
| Commission Paid | $842 | $612 | $1,104 |

Cells highlighted green/red relative to the best/worst value in each row.

**Overlay Chart**
All selected runs' equity curves plotted on one chart, each a different colour. Normalized to the same starting capital so they're directly comparable.

### Implementation

**Backend**
- `GET /api/runs/compare?ids=RUN1,RUN2,RUN3` — fetches and returns performance dicts for all requested runs
- No new DB work needed — reads from existing per-run DBs

**Frontend (`Dashboard.jsx`)**
- "Compare" checkbox on each row in the run history list
- "Compare Selected" button appears when 2+ runs are checked
- New view: `ComparisonView` component with table + overlay `EquityChart` accepting array of curves

### Acceptance Criteria
- Up to 5 runs can be compared simultaneously
- Table highlights the best value in each metric row
- Overlay chart renders all curves with a colour legend
- Comparison view has its own "Download CSV" that exports all runs side-by-side

---

## 6. Rolling Metrics Chart

### What It Is
Instead of single full-period numbers (e.g. "Sharpe: 1.42"), show how key metrics evolved over time as rolling windows. Reveals whether a strategy is consistently good or had one lucky streak.

### Metrics to Roll

| Metric | Window | Why Useful |
|--------|--------|-----------|
| Sharpe Ratio | 90-day, 252-day | Is risk-adjusted return stable across regimes? |
| Drawdown | Running (cumulative) | When was the worst period? |
| Win Rate | 30-trade rolling | Is the strategy improving or degrading? |
| Volatility | 30-day | When was the strategy most/least volatile? |
| Return | 30-day | Shows momentum in strategy performance |

### Implementation (`metrics/performance.py`)

```python
def compute_rolling_metrics(
    equity_curve: list[dict],   # [{time, equity}, ...]
    windows: dict = {"sharpe": 252, "volatility": 30, "return": 30},
) -> dict:
    # Returns {metric_name: [{time, value}, ...]} for each rolling metric
```

All computed from the existing equity curve — no new DB columns needed.

### UI Changes (`Dashboard.jsx`)
- New tab in ResultsDashboard: "Rolling Analytics"
- Row of small sparkline charts (one per metric), each with a window selector (30d / 90d / 252d)
- Red/green background shading when metric is below/above threshold (e.g. Sharpe < 0 = red)
- Tooltip on hover shows exact value + date

### Acceptance Criteria
- Rolling Sharpe uses correct annualization (sqrt(252) for daily)
- Window selector updates all charts simultaneously
- Charts clearly show regime changes (e.g. strategy worked in 2021 but not 2022)
- Gracefully handles windows longer than available data (returns null for early dates)

---

## Implementation Order

```
Month 1:  Feature 5 (Run Comparison)   — low backend effort, high daily utility
          Feature 6 (Rolling Metrics)  — pure computation, no schema changes

Month 2:  Feature 3 (Position Sizing)  — self-contained, adds pro-tier value
          Feature 4 (Monte Carlo)      — new engine file, new UI tab

Month 3:  Feature 2 (Limit/Stop Orders) — deep engine change, needs thorough testing
          Feature 1 (Portfolio Sim)     — largest refactor, touches everything
```
