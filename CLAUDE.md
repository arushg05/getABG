# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Behavioral guidelines to reduce common LLM coding mistakes.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

## Project: getABG — Quantitative Backtesting Platform

### Commands

**Backend (Flask API):**
```bash
# Install Python dependencies
pip install -r requirements.txt

# Run API server locally (port 5050)
cd api && python server.py
# Or from project root:
python -m api.server

# Run a backtest from CLI
python run_backtest.py --strategy ma_crossover --tickers AAPL MSFT --start 2022-01-01 --end 2023-12-31
python run_backtest.py --strategy strategies/rsi_reversion.py --tickers RELIANCE.NS TCS.NS

# Production: gunicorn (Render deployment)
gunicorn api.server:app
```

**Frontend (React + Vite):**
```bash
cd dashboard
npm install
npm run dev      # Dev server at http://localhost:5173 (proxies /api to :5050)
npm run build    # Builds to dashboard/dist/ (Flask serves this in prod)
npm run lint
```

**Auth utilities:**
```bash
python manage_users.py   # CLI for user management
python test_auth.py      # Auth integration tests
```

### Architecture

**Two-Pass Hybrid Backtest Engine** (`engine/backtest.py`):
- Pass 1 (vectorized): NumPy/Pandas matrix scan to flag "active" days (>1% move or near 20-day high). Skips processing on quiet days.
- Pass 2 (event-driven): Day-by-day simulation calling `strategy.on_tick()` for every trading date but only processing orders on active days.
- Each backtest run creates a per-ticker SQLite DB at `api/runs/{RUN_ID}_{TICKER}.db`. A `_master.db` acts as a registry.
- `BacktestEngine(commission_model, lot_sizes, benchmark_ticker)`: commission_model `{type: flat|per_share|pct, value: float}` is applied on every fill; lot_sizes `{TICKER: int}` enforces minimum order sizes; benchmark_ticker (default `SPY`) fetches a buy-and-hold curve for comparison.
- Slippage: flat 5 BPS applied to every fill price; commission is on top of slippage.

**Strategy Sandbox** (`sandbox/worker.py`):
- User strategy code runs in an isolated subprocess communicating via JSON over stdin/stdout.
- The host engine (BacktestEngine) never shares its data structures with the guest subprocess.
- Look-ahead prevention: strategy only receives data up to current `timestamp`.
- Timeout enforced per tick via subprocess termination.

**Data Pipeline** (`data/ingestion.py`):
- Fetches OHLCV from Yahoo Finance (`yfinance`). Results cached as Parquet in `cache/ohlcv/` (CSV fallback when `pyarrow` unavailable), keyed by ticker symbol (not date range). New data is merged into the existing file rather than replacing it.
- Recent data (within last 7 days) has a TTL and is re-fetched; historical data is cached forever.
- Indian tickers use `.NS` (NSE) or `.BO` (BSE) suffix.

**Flask API** (`api/server.py`):
- Runs on port 5050. In production, Flask itself serves the built React SPA from `dashboard/dist/`.
- Backtests execute asynchronously in daemon threads; status is polled via `/api/runs/{id}/status`.
- `_active_runs` dict holds in-flight run state (auto-pruned after 10 minutes).
- CORS allowlist is explicit; credentials (httpOnly cookies) flow on auth endpoints only.
- `GET /api/runs/compare?ids=RUN1,RUN2,...` — returns performance summaries for up to 5 runs with per-metric best-value flags; no new DB work, reads existing run DBs.
- `POST /api/admin/upgrade` and `GET /api/admin/users` — admin-key-protected endpoints for manual tier management.
- `POST /api/backtest/run` accepts optional `commission_model`, `lot_sizes`, `benchmark_ticker` fields.

**Auth** (`auth/`):
- JWT access tokens (short-lived) + rotating refresh tokens, stored as httpOnly cookies.
- `auth/user_db.py`: SQLite-backed user store (`api/users.db`) with daily backtest usage counters.
- `auth/middleware.py`: `@require_auth` and `@require_verified` decorators for Flask routes.
- Freemium: free tier = 3 backtests/day; Pro tier (paid via Razorpay) = unlimited + walk-forward.

**Walk-Forward Optimization** (`engine/walk_forward.py`):
- Pro-only feature. Splits date range into N train/test folds and runs the strategy on each OOS window.
- Runs synchronously (blocks the request); no background thread.

**Performance Metrics** (`metrics/performance.py`):
- `build_performance_report()` synthesizes SQLite data into the full telemetry report (equity curve, trade log, event log, rolling metrics, benchmark curve).
- `compute_rolling_metrics(equity_curve, windows)` — returns rolling Sharpe, volatility, return (%), and running drawdown series for configurable trailing windows (30/90/252 days). Included in every performance report under `rolling_metrics.by_window`.
- Report includes `buy_and_hold_return_pct`, `alpha_pct`, `benchmark_ticker`, `benchmark_curve` from the engine run.

**AI Strategy Generator** (`api/strategy_generator.py`):
- Calls Anthropic API (`claude-haiku-4-5-20251001` by default) to generate a Strategy class from plain English. Currently disabled (returns a stub error).
- Requires `ANTHROPIC_API_KEY` env var.

**React Dashboard** (`dashboard/src/`):
- `App.jsx` → routes between `AuthPage`, `Dashboard`, `UpgradePage`.
- `Dashboard.jsx` → main trading UI: code editor, run controls, results charts (recharts), walk-forward panel, comparison view, rolling analytics tab.
- Key Dashboard components: `EquityChart` (with benchmark overlay + trade markers), `RollingAnalytics` / `RollingSparkline` (rolling metrics with window selector), `ComparisonView` (side-by-side table + normalized overlay chart for up to 5 runs), `RunHistory` (with compare checkboxes), `TradeBarChart`.
- Export: `downloadCSV()` and `downloadPDF()` (uses jsPDF) available from results view.
- AI panel in UI for strategy generation (wired to `/api/strategy/generate`; backend still returns stub error).
- `useAuth.jsx` → auth context hook (polls `/api/auth/me`, handles token refresh).
- Vite dev proxy forwards `/api/*` to Flask at port 5050.

### Key Environment Variables (`.env`)

| Variable | Purpose |
|---|---|
| `AUTH_SECRET` | JWT signing secret |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | Payment integration |
| `RAZORPAY_WEBHOOK_SECRET` | Webhook signature verification |
| `RAZORPAY_PLAN_AMOUNT` | Pro plan price in paise (default 1599 INR) |
| `ANTHROPIC_API_KEY` | AI strategy generation |
| `ADMIN_API_KEY` | Admin endpoints (`/api/admin/*`) |
| `FRONTEND_URL` | Added to CORS allowlist in production |
| `FLASK_ENV` | Set to `production` to enable secure cookies + `SameSite=None` |

### Writing a Custom Strategy

Strategies must define a class named `Strategy` with exactly two methods:

```python
class Strategy:
    # Optional — surfaced in the UI
    METADATA = {"name": "...", "description": "...", "type": "trend|momentum|..."}

    def on_init(self, params: dict):
        self.tickers = params['tickers']

    def on_tick(self, timestamp: str, market_state: dict, portfolio_state: dict) -> list:
        # market_state: {ticker: {open, high, low, close, volume}}
        # portfolio_state: {available_cash, total_equity, open_positions: [...]}
        return [{"ticker": "AAPL", "action": "BUY", "quantity": 10, "order_type": "MARKET"}]
```

Allowed imports in strategy code: `math`, `statistics`, `collections`, `datetime`, `random`, `numpy`. OS/network imports are blocked by the sandbox AST checker.

Bundled strategies: `strategies/ma_crossover.py` (dual MA trend), `strategies/rsi_reversion.py`, `strategies/bbsar.py`, `strategies/momentum_screener.py` (MACD/RSI/EMA additive score, two exit variants).

### Database Layout

Each run: `api/runs/{RUN_ID}_{TICKER}.db` with tables `Run_Metadata`, `Execution_Events`, `Portfolio_Snapshots`, `Trade_Log`. Auth: `api/users.db` with `Users`, `Backtest_Usage`, `Refresh_Tokens`.

### ROADMAP Status (as of 2026-06-13)

Features from `ROADMAP.md` — implemented vs pending:

| # | Feature | Status |
|---|---------|--------|
| 5 | Run Comparison UI | **Done** — `/api/runs/compare`, `ComparisonView`, `test_run_comparison.py` |
| 6 | Rolling Metrics Chart | **Done** — `compute_rolling_metrics()`, `RollingAnalytics` tab, `test_rolling_metrics.py` |
| 3 | Position Sizing Models | Pending |
| 4 | Monte Carlo Simulation | Pending |
| 2 | Limit / Stop Orders | Pending |
| 1 | Portfolio-Level Simulation | Pending |
