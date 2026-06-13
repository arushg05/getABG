import { useState, useEffect } from "react";
import { AreaChart, Area, BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import { useAuth } from "./useAuth.jsx";
import UpgradePage from "./UpgradePage";
import CodeEditor from "./CodeEditor.jsx";

const TEMPLATE_CODE = `"""
getABG Example Strategy: Dual Moving Average Crossover
------------------------------------------------------
A classic trend-following strategy. Buys when the fast MA crosses above
the slow MA, and sells when it crosses below.

Strategy Contract (SRS §3):
  - Must define a class named \`Strategy\`
  - Must implement \`on_tick(timestamp, market_state, portfolio_state)\`
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
`

const getApiUrl = () => {
  const env = import.meta.env.VITE_API_URL;
  if (env) {
    let base = env.replace(/\/+$/, "");
    return base.endsWith("/api") ? base : `${base}/api`;
  }
  return "/api";
};
const API = getApiUrl();

const DEMO_REPORT = {
  run_id: "DEMO-RUN-001",
  is_multi: true,
  strategy_name: "ma_crossover",
  start_date: "2022-01-01",
  end_date: "2023-12-31",
  initial_capital: 100000,
  tickers: ["AAPL", "MSFT"],
  results: {
    "AAPL": {
      metadata: {
        run_id: "DEMO-AAPL",
        strategy_name: "ma_crossover",
        start_date: "2022-01-01",
        end_date: "2023-12-31",
        status: "COMPLETED",
        initial_capital: 100000,
        final_equity: 112450.00,
        market_universe: '["AAPL"]',
      },
      performance: {
        total_return_pct: 12.45,
        buy_and_hold_return_pct: 10.0,
        alpha_pct: 2.45,
        cagr_pct: 6.04,
        sharpe_ratio: 0.82,
        sortino_ratio: 1.12,
        max_drawdown_pct: 8.5,
        max_drawdown_duration_days: 35,
        profit_factor: 1.45,
        win_rate_pct: 55.0,
        total_trades: 18,
        time_in_market_pct: 35.5,
        avg_trade_duration_days: 12.5,
        gross_profit: 15450.0,
        gross_loss: -3000.0,
        net_pnl: 12450.00,
        total_commission_paid: 0,
      },
      equity_curve: Array.from({ length: 50 }, (_, i) => {
        const t = i / 49;
        return {
          time: new Date(2022, 0, 1 + Math.floor(i * 14)).toISOString().slice(0, 10),
          equity: Math.round(100000 * (1 + t * 0.1245) + Math.sin(i) * 1500),
          cash: Math.round(100000 * (1 + t * 0.1245) * 0.7),
          margin: Math.round(100000 * (1 + t * 0.1245) * 0.3),
        };
      }),
      trade_log: [
        { trade_id: 1, ticker: "AAPL", direction: "LONG", entry_time: "2022-01-15", exit_time: "2022-02-10", entry_price: 150.0, exit_price: 165.0, quantity: 200, slippage_total: 0.1, commission_total: 0, net_pnl: 3000.0, status: "CLOSED" },
        { trade_id: 2, ticker: "AAPL", direction: "LONG", entry_time: "2022-03-05", exit_time: "2022-03-25", entry_price: 160.0, exit_price: 155.0, quantity: 200, slippage_total: 0.1, commission_total: 0, net_pnl: -1000.0, status: "CLOSED" }
      ],
      event_log: []
    },
    "MSFT": {
      metadata: {
        run_id: "DEMO-MSFT",
        strategy_name: "ma_crossover",
        start_date: "2022-01-01",
        end_date: "2023-12-31",
        status: "COMPLETED",
        initial_capital: 100000,
        final_equity: 124850.32,
        market_universe: '["MSFT"]',
      },
      performance: {
        total_return_pct: 24.85,
        buy_and_hold_return_pct: 15.0,
        alpha_pct: 9.85,
        cagr_pct: 11.72,
        sharpe_ratio: 1.42,
        sortino_ratio: 1.87,
        max_drawdown_pct: 12.3,
        max_drawdown_duration_days: 47,
        profit_factor: 1.91,
        win_rate_pct: 58.3,
        total_trades: 36,
        time_in_market_pct: 41.2,
        avg_trade_duration_days: 18.4,
        gross_profit: 31420.5,
        gross_loss: -16450.2,
        net_pnl: 24850.32,
      },
      equity_curve: Array.from({ length: 50 }, (_, i) => {
        const t = i / 49;
        return {
          time: new Date(2022, 0, 1 + Math.floor(i * 14)).toISOString().slice(0, 10),
          equity: Math.round(100000 * (1 + t * 0.2485) + Math.cos(i) * 2000),
          cash: Math.round(100000 * (1 + t * 0.2485) * 0.6),
          margin: Math.round(100000 * (1 + t * 0.2485) * 0.4),
        };
      }),
      trade_log: [
        { trade_id: 1, ticker: "MSFT", direction: "LONG", entry_time: "2022-01-20", exit_time: "2022-02-15", entry_price: 280.0, exit_price: 310.0, quantity: 100, slippage_total: 0.2, commission_total: 0, net_pnl: 3000.0, status: "CLOSED" },
        { trade_id: 2, ticker: "MSFT", direction: "LONG", entry_time: "2022-04-10", exit_time: "2022-05-02", entry_price: 290.0, exit_price: 275.0, quantity: 100, slippage_total: 0.2, commission_total: 0, net_pnl: -1500.0, status: "CLOSED" }
      ],
      event_log: []
    }
  }
};

const DEFAULT_TICKERS = ["AAPL", "MSFT", "GOOGL"];
const INDIAN_PRESETS = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"];

function StatCard({ label, value, sub, color = "var(--color-text-info)", negative = false }) {
  const numericValue = parseFloat(value);
  let computedColor = color;

  if (negative) {
    if (numericValue < 0) {
      computedColor = "var(--color-text-danger)";
    } else if (numericValue > 0) {
      computedColor = "var(--color-text-success)";
    } else {
      computedColor = "var(--color-text-primary)";
    }
  }

  return (
    <div style={{
      border: "0.5px solid var(--color-border-tertiary)",
      borderRadius: "var(--border-radius-md)",
      padding: "12px 14px",
      display: "flex",
      flexDirection: "column",
      gap: 2,
    }}>
      <span style={{ fontSize: 10, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 500 }}>{label}</span>
      <span style={{
        fontSize: 18,
        fontWeight: 500,
        color: computedColor,
        fontVariantNumeric: "tabular-nums",
      }}>{value}</span>
      {sub && <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>{sub}</span>}
    </div>
  );
}

function Badge({ children, type = "info" }) {
  return (
    <span style={{
      fontSize: 10,
      padding: "1px 6px",
      borderRadius: 4,
      fontWeight: 500,
      background: `var(--color-background-${type})`,
      color: `var(--color-text-${type})`,
      display: "inline-block",
    }}>{children}</span>
  );
}

function TickerTag({ ticker, onRemove }) {
  const isIndian = ticker.endsWith(".NS") || ticker.endsWith(".BO");
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      background: isIndian ? "var(--color-background-warning)" : "var(--color-background-info)",
      color: isIndian ? "var(--color-text-warning)" : "var(--color-text-info)",
      borderRadius: 4, padding: "2px 6px", fontSize: 11, fontWeight: 500,
    }}>
      {ticker}
      {onRemove && (
        <button onClick={() => onRemove(ticker)} style={{
          border: "none", background: "none", cursor: "pointer",
          color: "inherit", padding: 0, lineHeight: 1, fontSize: 11,
        }}>×</button>
      )}
    </span>
  );
}

function RunForm({ onRunStarted, onShowUpgrade }) {
  const { user, authFetch, isPro, refreshUser } = useAuth();
  const [code, setCode] = useState(TEMPLATE_CODE);
  const [tickers, setTickers] = useState(DEFAULT_TICKERS);
  const [tickerInput, setTickerInput] = useState("");
  const [startDate, setStartDate] = useState("2022-01-01");
  const [endDate, setEndDate] = useState("2023-12-31");
  const [capital, setCapital] = useState(100000);
  const [commissionType, setCommissionType] = useState("pct");
  const [commissionValue, setCommissionValue] = useState("");
  const [lotSizes, setLotSizes] = useState({});
  const [benchmarkTicker, setBenchmarkTicker] = useState("SPY");
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState(null);
  const [showAiPanel, setShowAiPanel] = useState(false);
  const [wfLoading, setWfLoading] = useState(false);
  const [wfResult, setWfResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const usageToday = user?.usage_today || 0;
  const dailyLimit = user?.daily_limit;
  const isQuotaExhausted = !isPro && dailyLimit != null && usageToday >= dailyLimit;



  const addTicker = (t) => {
    const sym = t.trim().toUpperCase();
    if (sym && !tickers.includes(sym)) setTickers([...tickers, sym]);
    setTickerInput("");
  };

  const useDemo = () => {
    onRunStarted(DEMO_REPORT, true);
  };

  const handleRun = async () => {
    if (!tickers.length || !code) return;
    setLoading(true);
    setError(null);
    try {
      const commVal = parseFloat(commissionValue);
      const body = {
        code,
        tickers,
        start_date: startDate,
        end_date: endDate,
        initial_capital: capital,
        commission_model: commVal > 0 ? { type: commissionType, value: commVal } : {},
        lot_sizes: Object.keys(lotSizes).length > 0 ? lotSizes : {},
        benchmark_ticker: benchmarkTicker || "SPY",
      };
      const resp = await authFetch(`${API}/backtest/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (data.code === "QUOTA_EXCEEDED") {
        setError(data.error);
        return;
      }
      if (data.error) throw new Error(data.error);
      // Refresh user to update usage count
      refreshUser();
      onRunStarted(data.run_id, false);
    } catch (e) {
      setError(`API unavailable. ${e.message}. Use Demo Mode to preview.`);
    } finally {
      setLoading(false);
    }
  };



  const handleGenerate = async () => {
    if (!aiPrompt.trim()) return;
    setAiLoading(true);
    setAiError(null);
    try {
      const resp = await authFetch(`${API}/strategy/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description: aiPrompt }),
      });
      const data = await resp.json();
      if (data.error) throw new Error(data.error);
      setCode(data.code);
      setShowAiPanel(false);
      setAiPrompt("");
    } catch (e) {
      setAiError(e.message);
    } finally {
      setAiLoading(false);
    }
  };

  const handleWalkForward = async () => {
    if (!tickers.length || !code) return;
    setWfLoading(true);
    setWfResult(null);
    setError(null);
    try {
      const commVal = parseFloat(commissionValue);
      const resp = await authFetch(`${API}/backtest/walk-forward`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code, tickers,
          start_date: startDate, end_date: endDate,
          initial_capital: capital,
          commission_model: commVal > 0 ? { type: commissionType, value: commVal } : {},
          lot_sizes: Object.keys(lotSizes).length > 0 ? lotSizes : {},
          benchmark_ticker: benchmarkTicker || "SPY",
          n_splits: 3, oos_ratio: 0.3,
        }),
      });
      const data = await resp.json();
      if (data.error) throw new Error(data.error);
      setWfResult(data);
    } catch (e) {
      setError(`Walk-forward failed: ${e.message}`);
    } finally {
      setWfLoading(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <label style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)" }}>
            STRATEGY (This is the template your strategy must follow)
          </label>
          <div style={{ display: "flex", gap: 6 }}>
            <button
              onClick={() => setShowAiPanel(v => !v)}
              style={{
                fontSize: 10, padding: "4px 8px", cursor: "pointer",
                background: showAiPanel ? "var(--color-background-info)" : "transparent",
                border: "0.5px solid var(--color-border-info)",
                borderRadius: 4, color: "var(--color-text-info)", fontWeight: 500,
              }}
            >✨ Generate with AI</button>
            <label style={{
              fontSize: 10, padding: "4px 8px", cursor: "pointer",
              background: "transparent",
              border: "0.5px solid var(--color-border-tertiary)",
              borderRadius: 4, color: "var(--color-text-secondary)", fontWeight: 500,
            }}>
              Upload .py
              <input type="file" accept=".py" style={{ display: "none" }} onChange={(e) => {
                const file = e.target.files[0];
                if (file) {
                  if (!file.name.endsWith(".py")) { setError("Please upload a .py file"); return; }
                  const reader = new FileReader();
                  reader.onload = (evt) => setCode(evt.target.result);
                  reader.readAsText(file);
                  setError(null);
                }
              }} />
            </label>
          </div>
        </div>
        <CodeEditor value={code} onChange={setCode} />
      </div>

      {/* ── AI Strategy Generator Panel ───────────────────────────── */}
      {showAiPanel && (
        <div style={{
          border: "0.5px solid var(--color-border-info)",
          borderRadius: "var(--border-radius-md)",
          padding: "12px 14px",
          background: "var(--color-background-secondary)",
          display: "flex", flexDirection: "column", gap: 8,
        }}>
          <div style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-info)" }}>
            ✨ Describe your strategy in plain English
          </div>
          <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", lineHeight: 1.5 }}>
            Examples: "Buy when RSI drops below 30, sell when it crosses above 60" · "Momentum strategy: buy top 20% performers from last month" · "Mean reversion on Bollinger Band breakouts"
          </div>
          <textarea
            value={aiPrompt}
            onChange={e => setAiPrompt(e.target.value)}
            placeholder="e.g. Buy when the 10-day RSI goes below 30 and the price is above the 50-day moving average. Sell when RSI crosses above 70."
            rows={3}
            style={{ fontSize: 12, padding: "8px 10px", resize: "vertical", lineHeight: 1.5 }}
          />
          {aiError && (
            <div style={{ fontSize: 11, color: "var(--color-text-danger)", padding: "4px 0" }}>{aiError}</div>
          )}
          <div style={{ display: "flex", gap: 6 }}>
            <button
              onClick={handleGenerate}
              disabled={aiLoading || !aiPrompt.trim()}
              style={{
                flex: 2, padding: "7px 0", fontSize: 12,
                background: "var(--color-background-info)",
                color: "var(--color-text-info)",
                border: "0.5px solid var(--color-border-info)",
                borderRadius: "var(--border-radius-md)",
                cursor: aiLoading ? "wait" : "pointer",
                opacity: aiLoading ? 0.7 : 1,
                fontWeight: 500,
              }}
            >{aiLoading ? "Generating…" : "Generate strategy code"}</button>
            <button onClick={() => setShowAiPanel(false)} style={{ flex: 1, padding: "7px 0", fontSize: 12 }}>Cancel</button>
          </div>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <label style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)" }}>TICKER UNIVERSE</label>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 4 }}>
          {tickers.map(t => <TickerTag key={t} ticker={t} onRemove={tk => setTickers(tickers.filter(x => x !== tk))} />)}
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <input
            value={tickerInput}
            onChange={e => setTickerInput(e.target.value.toUpperCase())}
            onKeyDown={e => e.key === "Enter" && addTicker(tickerInput)}
            placeholder="Add ticker (e.g. AAPL, RELIANCE.NS)"
            style={{ flex: 1, fontSize: 12, padding: "6px 10px" }}
          />
          <button onClick={() => addTicker(tickerInput)} style={{ padding: "0 10px" }}>+</button>
        </div>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
          <span style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>Presets:</span>
          {INDIAN_PRESETS.map(t => (
            <button key={t} onClick={() => addTicker(t)} style={{
              fontSize: 10, padding: "1px 6px",
              background: "var(--color-background-warning)",
              color: "var(--color-text-warning)",
              border: "0.5px solid var(--color-border-warning)",
              borderRadius: 4,
            }}>{t}</button>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)" }}>START DATE</label>
          <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} style={{ fontSize: 12, padding: "6px 10px" }} />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)" }}>END DATE</label>
          <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} style={{ fontSize: 12, padding: "6px 10px" }} />
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <label style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)" }}>
          INITIAL CAPITAL: ${capital.toLocaleString()}
        </label>
        <input
          type="range" min="10000" max="1000000" step="10000"
          value={capital} onChange={e => setCapital(Number(e.target.value))}
          style={{ padding: 0 }}
        />
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--color-text-tertiary)" }}>
          <span>$10K</span><span>$1M</span>
        </div>
      </div>

      {/* ── Commission Model ─────────────────────────────────────── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <label style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)" }}>
          COMMISSION MODEL
        </label>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <select
            value={commissionType}
            onChange={e => setCommissionType(e.target.value)}
            style={{ fontSize: 12, padding: "6px 8px", flex: "0 0 auto", width: 120 }}
          >
            <option value="pct">% of trade</option>
            <option value="flat">Flat $/trade</option>
            <option value="per_share">$/share</option>
          </select>
          <input
            type="number"
            min="0"
            step={commissionType === "pct" ? "0.01" : "0.001"}
            value={commissionValue}
            onChange={e => setCommissionValue(e.target.value)}
            placeholder={commissionType === "pct" ? "e.g. 0.1 (for 0.1%)" : commissionType === "flat" ? "e.g. 1.99" : "e.g. 0.005"}
            style={{ flex: 1, fontSize: 12, padding: "6px 10px" }}
          />
        </div>
        {commissionValue > 0 && (
          <div style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>
            {commissionType === "pct" && `${commissionValue}% of notional per side (e.g. STT-style)`}
            {commissionType === "flat" && `$${commissionValue} flat fee per trade`}
            {commissionType === "per_share" && `$${commissionValue} per share traded`}
          </div>
        )}
      </div>

      {/* ── Lot Sizes ────────────────────────────────────────────── */}
      {tickers.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <label style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)" }}>
            LOT SIZES <span style={{ fontWeight: 400, color: "var(--color-text-tertiary)" }}>(leave blank for 1)</span>
          </label>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 6 }}>
            {tickers.map(t => (
              <div key={t} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{
                  fontSize: 10, fontWeight: 500, minWidth: 60,
                  color: t.endsWith(".NS") || t.endsWith(".BO") ? "var(--color-text-warning)" : "var(--color-text-info)",
                }}>{t}</span>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={lotSizes[t] || ""}
                  onChange={e => {
                    const v = parseInt(e.target.value);
                    setLotSizes(prev => {
                      const next = { ...prev };
                      if (v > 1) next[t] = v;
                      else delete next[t];
                      return next;
                    });
                  }}
                  placeholder="1"
                  style={{ width: "100%", fontSize: 12, padding: "5px 8px" }}
                />
              </div>
            ))}
          </div>
          <div style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>
            Orders will be rounded down to the nearest lot. Use 50 for NSE F&O, 1 for equities.
          </div>
        </div>
      )}

      {error && (
        <div style={{
          background: "var(--color-background-danger)",
          color: "var(--color-text-danger)",
          borderRadius: "var(--border-radius-md)",
          padding: "8px 10px",
          fontSize: 12,
        }}>{error}</div>
      )}

      {/* Quota Banner */}
      {!isPro && dailyLimit != null && (
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "8px 12px",
          borderRadius: "var(--border-radius-md)",
          border: `0.5px solid ${isQuotaExhausted ? "var(--color-border-warning)" : "var(--color-border-tertiary)"}`,
          background: isQuotaExhausted ? "var(--color-background-warning)" : "var(--color-background-secondary)",
          fontSize: 12,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{
              display: "flex",
              gap: 3,
            }}>
              {[...Array(dailyLimit)].map((_, i) => (
                <div key={i} style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: i < usageToday
                    ? (isQuotaExhausted ? "var(--color-text-warning)" : "var(--color-text-info)")
                    : "var(--color-border-tertiary)",
                  transition: "background 0.3s ease",
                }} />
              ))}
            </div>
            <span style={{
              color: isQuotaExhausted ? "var(--color-text-warning)" : "var(--color-text-secondary)",
              fontWeight: 500,
            }}>
              {usageToday}/{dailyLimit} backtests used today
            </span>
          </div>
          {isQuotaExhausted && (
            <button
              onClick={onShowUpgrade}
              style={{
                fontSize: 11,
                fontWeight: 600,
                padding: "3px 10px",
                borderRadius: 4,
                border: "none",
                background: "linear-gradient(135deg, #38BDF8, #818CF8)",
                color: "#fff",
                cursor: "pointer",
              }}
            >
              Upgrade →
            </button>
          )}
        </div>
      )}

      {/* ── Benchmark Ticker ────────────────────────────────────── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <label style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)" }}>
          BENCHMARK TICKER
        </label>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            value={benchmarkTicker}
            onChange={e => setBenchmarkTicker(e.target.value.toUpperCase())}
            placeholder="SPY"
            style={{ flex: 1, padding: "6px 10px", fontSize: 12 }}
          />
          <span style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>
            Use ^NSEI for NIFTY50 · ^GSPC for S&amp;P 500
          </span>
        </div>
      </div>

      {/* ── Walk-Forward Results ─────────────────────────────────── */}
      {wfResult && (
        <div style={{
          border: "0.5px solid var(--color-border-tertiary)",
          borderRadius: "var(--border-radius-md)",
          padding: "12px 14px",
          background: "var(--color-background-secondary)",
          display: "flex", flexDirection: "column", gap: 10,
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-primary)" }}>
            Walk-Forward Results — {wfResult.n_splits} windows · {Math.round(wfResult.oos_ratio * 100)}% OOS
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
            {[
              ["Avg OOS Return", `${wfResult.summary.avg_oos_return_pct > 0 ? "+" : ""}${wfResult.summary.avg_oos_return_pct}%`],
              ["Avg OOS Sharpe", wfResult.summary.avg_oos_sharpe],
              ["Avg Drawdown", `${wfResult.summary.avg_oos_drawdown_pct}%`],
              ["Win Rate", `${wfResult.summary.avg_oos_win_rate_pct}%`],
              ["Consistency", `${wfResult.summary.consistency_score_pct}%`],
              ["Profitable", `${wfResult.summary.profitable_windows}/${wfResult.summary.total_windows}`],
            ].map(([label, val]) => (
              <div key={label} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <div style={{ fontSize: 9, color: "var(--color-text-tertiary)", textTransform: "uppercase" }}>{label}</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-primary)" }}>{val}</div>
              </div>
            ))}
          </div>
          <table style={{ fontSize: 11, borderCollapse: "collapse", width: "100%" }}>
            <thead>
              <tr style={{ color: "var(--color-text-tertiary)" }}>
                {["Win", "OOS Period", "Return", "Sharpe", "MaxDD"].map(h => (
                  <th key={h} style={{ textAlign: "left", padding: "3px 6px", fontWeight: 500, borderBottom: "0.5px solid var(--color-border-tertiary)" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {wfResult.windows.map(w => {
                const p = w.out_of_sample;
                return (
                  <tr key={w.window}>
                    <td style={{ padding: "3px 6px", color: "var(--color-text-secondary)" }}>{w.window}</td>
                    <td style={{ padding: "3px 6px", color: "var(--color-text-secondary)" }}>{w.oos_start} → {w.oos_end}</td>
                    <td style={{ padding: "3px 6px", color: p?.total_return_pct >= 0 ? "var(--color-text-success)" : "var(--color-text-danger)", fontWeight: 600 }}>{p ? `${p.total_return_pct > 0 ? "+" : ""}${p.total_return_pct}%` : "—"}</td>
                    <td style={{ padding: "3px 6px" }}>{p ? p.sharpe_ratio : "—"}</td>
                    <td style={{ padding: "3px 6px", color: "var(--color-text-danger)" }}>{p ? `${p.max_drawdown_pct}%` : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
        <button onClick={handleRun} disabled={loading || !tickers.length || isQuotaExhausted} style={{
          flex: 2,
          padding: "8px 0",
          background: isQuotaExhausted ? "var(--color-background-secondary)" : "var(--color-background-info)",
          color: isQuotaExhausted ? "var(--color-text-tertiary)" : "var(--color-text-info)",
          border: `0.5px solid ${isQuotaExhausted ? "var(--color-border-tertiary)" : "var(--color-border-info)"}`,
          borderRadius: "var(--border-radius-md)",
          fontSize: 13, fontWeight: 500,
          cursor: loading ? "wait" : (isQuotaExhausted ? "not-allowed" : "pointer"),
          opacity: loading ? 0.7 : 1,
        }}>
          {loading ? "Launching backtest…" : (isQuotaExhausted ? "Daily limit reached" : "Run backtest")}
        </button>
        <button
          onClick={handleWalkForward}
          disabled={wfLoading || !tickers.length || !code}
          title="Pro feature: walk-forward optimization"
          style={{
            flex: 1,
            padding: "8px 0",
            fontSize: 12,
            borderRadius: "var(--border-radius-md)",
            opacity: wfLoading ? 0.7 : 1,
            cursor: wfLoading ? "wait" : "pointer",
          }}
        >{wfLoading ? "Running WF…" : "Walk-forward"}</button>
        <button onClick={useDemo} style={{
          flex: 1,
          padding: "8px 0",
          fontSize: 12,
          borderRadius: "var(--border-radius-md)",
        }}>
          Demo
        </button>
      </div>
    </div>
  );
}

function EquityChart({ curve, benchmarkCurve = [], benchmarkTicker = "SPY", trades = [] }) {
  const initial = curve[0]?.equity || 100000;

  // Merge equity + benchmark by time key for combined chart
  const benchMap = {};
  (benchmarkCurve || []).forEach(b => { benchMap[b.time] = b.equity; });

  // Build drawdown series — running peak minus current equity
  const merged = curve.reduce((acc, pt) => {
    const prevPeak = acc.length > 0 ? acc[acc.length - 1].peak : initial;
    const currPeak = Math.max(prevPeak, pt.equity);
    const drawdown = currPeak > 0 ? ((pt.equity - currPeak) / currPeak) * initial : 0; // scaled to $ for same axis
    acc.push({ ...pt, benchmark: benchMap[pt.time] ?? null, drawdown: Math.min(0, drawdown), peak: currPeak });
    return acc;
  }, []);

  // Build buy/sell marker sets from trades
  const buyTimes = new Set((trades || []).filter(t => t.action !== "SELL").map(t => t.entry_time));
  const sellTimes = new Set((trades || []).map(t => t.exit_time).filter(Boolean));

  return (
    <div style={{ width: "100%", height: 220 }}>
      <ResponsiveContainer>
        <AreaChart data={merged} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#378ADD" stopOpacity={0.12} />
              <stop offset="95%" stopColor="#378ADD" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="dd" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#EF4444" stopOpacity={0.18} />
              <stop offset="95%" stopColor="#EF4444" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(128,128,128,0.08)" />
          <XAxis dataKey="time" tick={{ fontSize: 10, fill: "#888" }} tickLine={false}
            interval={Math.floor(merged.length / 5)} />
          <YAxis tick={{ fontSize: 10, fill: "#888" }} tickLine={false} axisLine={false}
            tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} width={42} />
          <Tooltip
            formatter={(v, name) => {
              if (name === "equity") return [`$${Number(v).toLocaleString()}`, "Strategy"];
              if (name === "benchmark") return [`$${Number(v).toLocaleString()}`, benchmarkTicker];
              if (name === "drawdown") return [`$${Number(v).toLocaleString()}`, "Drawdown"];
              return [v, name];
            }}
            labelStyle={{ fontSize: 11 }}
            contentStyle={{ fontSize: 11, borderRadius: 6, border: "0.5px solid var(--color-border-tertiary)", background: "var(--color-background-primary)" }}
          />
          <ReferenceLine y={initial} stroke="#888" strokeDasharray="4 4" strokeWidth={0.5} />

          {/* Drawdown shading — fills red below the equity curve toward the running peak */}
          <Area type="monotone" dataKey="drawdown" stroke="none" fill="url(#dd)" dot={false} legendType="none" />

          {/* Strategy equity curve */}
          <Area type="monotone" dataKey="equity" stroke="#378ADD" strokeWidth={1.5}
            fill="url(#eq)" dot={false} />

          {/* Benchmark overlay — dashed line, no fill */}
          {benchmarkCurve && benchmarkCurve.length > 0 && (
            <Area type="monotone" dataKey="benchmark" stroke="#F59E0B" strokeWidth={1}
              strokeDasharray="4 2" fill="none" dot={false} />
          )}

          {/* Buy/sell markers via reference lines */}
          {merged.filter(pt => buyTimes.has(pt.time)).map(pt => (
            <ReferenceLine key={`buy-${pt.time}`} x={pt.time} stroke="#22C55E" strokeWidth={1} strokeDasharray="2 4" />
          ))}
          {merged.filter(pt => sellTimes.has(pt.time)).map(pt => (
            <ReferenceLine key={`sell-${pt.time}`} x={pt.time} stroke="#EF4444" strokeWidth={1} strokeDasharray="2 4" />
          ))}
        </AreaChart>
      </ResponsiveContainer>
      {/* Legend */}
      <div style={{ display: "flex", gap: 12, marginTop: 6, fontSize: 10, color: "var(--color-text-tertiary)", paddingLeft: 4 }}>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 16, height: 2, background: "#378ADD", display: "inline-block" }} /> Strategy
        </span>
        {benchmarkCurve && benchmarkCurve.length > 0 && (
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span style={{ width: 16, height: 2, background: "#F59E0B", borderTop: "2px dashed #F59E0B", display: "inline-block" }} /> {benchmarkTicker}
          </span>
        )}
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 8, height: 8, background: "rgba(239,68,68,0.3)", display: "inline-block" }} /> Drawdown
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 2, height: 10, background: "#22C55E", display: "inline-block" }} /> Entry
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 2, height: 10, background: "#EF4444", display: "inline-block" }} /> Exit
        </span>
      </div>
    </div>
  );
}

function TradeBarChart({ trades }) {
  const data = trades.map(t => ({
    label: `${t.ticker} #${t.trade_id}`,
    pnl: Math.round(t.net_pnl || 0),
  }));
  return (
    <div style={{ width: "100%", height: 140 }}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(128,128,128,0.08)" />
          <XAxis dataKey="label" tick={{ fontSize: 9, fill: "#888" }} tickLine={false} />
          <YAxis tick={{ fontSize: 10, fill: "#888" }} tickLine={false} axisLine={false}
            tickFormatter={v => `$${v}`} width={40} />
          <Tooltip formatter={(v) => [`$${v.toFixed(0)}`, "Net PnL"]}
            contentStyle={{ fontSize: 11, borderRadius: 6, border: "0.5px solid var(--color-border-tertiary)", background: "var(--color-background-primary)" }} />
          <ReferenceLine y={0} stroke="#888" strokeWidth={0.5} />
          <Bar dataKey="pnl" radius={[2, 2, 0, 0]}
            fill="#378ADD"
            label={false}
            isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function downloadCSV(m, p, trade_log, equity_curve) {
  const rows = [];

  // ── Section 1: Performance Summary ──
  rows.push(["=== PERFORMANCE SUMMARY ==="]);
  rows.push(["Run ID", m.run_id]);
  rows.push(["Strategy", m.strategy_name]);
  rows.push(["Period", `${m.start_date} → ${m.end_date}`]);
  rows.push(["Initial Capital", m.initial_capital]);
  rows.push(["Final Equity", m.final_equity]);
  rows.push([]);
  rows.push(["Metric", "Value"]);
  const metrics = [
    ["Total Return (%)", p.total_return_pct],
    ["Buy & Hold Return (%)", p.buy_and_hold_return_pct],
    ["Alpha (%)", p.alpha_pct],
    ["CAGR (%)", p.cagr_pct],
    ["Sharpe Ratio", p.sharpe_ratio],
    ["Sortino Ratio", p.sortino_ratio],
    ["Max Drawdown (%)", p.max_drawdown_pct],
    ["Max Drawdown Duration (days)", p.max_drawdown_duration_days],
    ["Win Rate (%)", p.win_rate_pct],
    ["Profit Factor", p.profit_factor],
    ["Total Trades", p.total_trades],
    ["Gross Profit", p.gross_profit],
    ["Gross Loss", p.gross_loss],
    ["Net PnL", p.net_pnl],
    ["Commission Paid", p.total_commission_paid],
    ["Time in Market (%)", p.time_in_market_pct],
    ["Avg Trade Duration (days)", p.avg_trade_duration_days],
  ];
  metrics.forEach(([k, v]) => rows.push([k, v ?? ""]));
  rows.push([]);

  // ── Section 2: Trade Log ──
  rows.push(["=== TRADE LOG ==="]);
  rows.push(["Trade ID", "Ticker", "Direction", "Entry Date", "Exit Date", "Entry Price", "Exit Price", "Quantity", "Slippage", "Commission", "Net PnL", "Status"]);
  (trade_log || []).forEach(t => rows.push([
    t.trade_id, t.ticker, t.direction,
    t.entry_time, t.exit_time,
    t.entry_price, t.exit_price, t.quantity,
    t.slippage_total ?? "", t.commission_total ?? "",
    t.net_pnl, t.status,
  ]));
  rows.push([]);

  // ── Section 3: Equity Curve ──
  rows.push(["=== EQUITY CURVE ==="]);
  rows.push(["Date", "Equity", "Cash"]);
  (equity_curve || []).forEach(pt => rows.push([pt.time, pt.equity, pt.cash]));

  const csv = rows.map(r => r.map(v => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `getABG_${m.run_id}_${m.start_date}_${m.end_date}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

async function downloadPDF(m, p, trade_log) {
  // Lazy-load jsPDF from CDN
  if (!window.jspdf) {
    await new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js";
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ unit: "mm", format: "a4" });
  const W = doc.internal.pageSize.getWidth();
  let y = 18;

  const line = (text, x, size = 10, style = "normal", color = [30, 30, 30]) => {
    doc.setFontSize(size);
    doc.setFont("helvetica", style);
    doc.setTextColor(...color);
    doc.text(text, x, y);
  };
  const rule = (thick = false) => {
    doc.setDrawColor(200, 200, 200);
    doc.setLineWidth(thick ? 0.5 : 0.2);
    doc.line(14, y, W - 14, y);
    y += 4;
  };
  const newPage = () => { doc.addPage(); y = 18; };
  const checkPage = (need = 10) => { if (y + need > 275) newPage(); };

  // Header
  doc.setFillColor(15, 23, 42);
  doc.rect(0, 0, W, 14, "F");
  doc.setFontSize(13); doc.setFont("helvetica", "bold"); doc.setTextColor(255, 255, 255);
  doc.text("getABG Backtest Report", 14, 9);
  doc.setFontSize(8); doc.setFont("helvetica", "normal");
  doc.text(`Run ID: ${m.run_id}   ·   Generated: ${new Date().toLocaleDateString()}`, W - 14, 9, { align: "right" });
  y = 22;

  // Strategy info
  line(`${m.strategy_name.replace("_", " ")}  ·  ${m.start_date} → ${m.end_date}`, 14, 11, "bold");
  y += 6;
  line(`Initial Capital: $${Number(m.initial_capital).toLocaleString()}   →   Final Equity: $${Number(m.final_equity).toLocaleString()}`, 14, 9, "normal", [80, 80, 80]);
  y += 7;
  rule(true);

  // Performance grid
  line("Performance Summary", 14, 11, "bold"); y += 6;
  const cols = [[14, 75], [75, 135], [135, W - 14]];
  const perfRows = [
    [["Total Return", `${p.total_return_pct > 0 ? "+" : ""}${p.total_return_pct}%`], ["Buy & Hold", `${p.buy_and_hold_return_pct > 0 ? "+" : ""}${p.buy_and_hold_return_pct}%`], ["Alpha", `${p.alpha_pct > 0 ? "+" : ""}${p.alpha_pct}%`]],
    [["CAGR", `${p.cagr_pct}%`], ["Sharpe Ratio", String(p.sharpe_ratio)], ["Sortino Ratio", String(p.sortino_ratio)]],
    [["Max Drawdown", `${p.max_drawdown_pct}%`], ["Win Rate", `${p.win_rate_pct}%`], ["Profit Factor", String(p.profit_factor)]],
    [["Total Trades", String(p.total_trades)], ["Net PnL", `$${Number(p.net_pnl).toLocaleString()}`], ["Commission", `$${Number(p.total_commission_paid || 0).toLocaleString()}`]],
  ];
  perfRows.forEach(row => {
    row.forEach(([label, val], i) => {
      doc.setFontSize(8); doc.setFont("helvetica", "normal"); doc.setTextColor(120, 120, 120);
      doc.text(label.toUpperCase(), cols[i][0], y);
      doc.setFontSize(11); doc.setFont("helvetica", "bold"); doc.setTextColor(30, 30, 30);
      doc.text(val, cols[i][0], y + 5);
    });
    y += 13;
  });
  rule();

  // Trade log
  line("Trade Log", 14, 11, "bold"); y += 6;
  const tHeaders = ["#", "Ticker", "Dir", "Entry", "Exit", "Entry $", "Exit $", "Qty", "PnL"];
  const tWidths =  [8,   18,      12,    22,      22,      18,       18,      12,    20];
  let x = 14;
  tHeaders.forEach((h, i) => {
    doc.setFontSize(7.5); doc.setFont("helvetica", "bold"); doc.setTextColor(80, 80, 80);
    doc.text(h, x, y);
    x += tWidths[i];
  });
  y += 1.5; rule();

  (trade_log || []).slice(0, 60).forEach((t, idx) => {
    checkPage(7);
    if (idx % 2 === 0) {
      doc.setFillColor(248, 249, 250);
      doc.rect(14, y - 3.5, W - 28, 6, "F");
    }
    const cells = [
      String(t.trade_id), t.ticker, t.direction,
      t.entry_time, t.exit_time || "—",
      `$${t.entry_price}`, `$${t.exit_price || "—"}`,
      String(t.quantity),
      `$${Number(t.net_pnl).toFixed(2)}`,
    ];
    x = 14;
    const pnlColor = t.net_pnl >= 0 ? [22, 163, 74] : [220, 38, 38];
    cells.forEach((val, i) => {
      const color = i === 8 ? pnlColor : [30, 30, 30];
      doc.setFontSize(7.5); doc.setFont("helvetica", "normal"); doc.setTextColor(...color);
      doc.text(val, x, y);
      x += tWidths[i];
    });
    y += 6;
  });
  if ((trade_log || []).length > 60) {
    y += 2;
    doc.setFontSize(8); doc.setTextColor(120, 120, 120);
    doc.text(`… and ${trade_log.length - 60} more trades. Download CSV for the full log.`, 14, y);
    y += 6;
  }

  // Footer
  const pages = doc.internal.getNumberOfPages();
  for (let i = 1; i <= pages; i++) {
    doc.setPage(i);
    doc.setFontSize(7); doc.setTextColor(160, 160, 160); doc.setFont("helvetica", "normal");
    doc.text(`getABG · Page ${i} of ${pages}`, W / 2, 290, { align: "center" });
  }

  doc.save(`getABG_${m.run_id}_${m.start_date}_${m.end_date}.pdf`);
}

function RollingSparkline({ title, data, unit = "", threshold = 0, higherIsBetter = true, decimals = 2 }) {
  const points = (data || []).filter(d => d && d.value !== null && d.value !== undefined);
  const latest = points.length ? points[points.length - 1].value : null;
  const good = latest === null ? null : (higherIsBetter ? latest >= threshold : latest <= threshold);
  const accent = good === null ? "var(--color-text-tertiary)" : good ? "#22C55E" : "#EF4444";
  const tint = good === null ? "transparent" : good ? "rgba(34,197,94,0.05)" : "rgba(239,68,68,0.05)";
  const gid = `rs-${title.replace(/\s+/g, "")}`;

  return (
    <div style={{
      border: "0.5px solid var(--color-border-tertiary)",
      borderRadius: "var(--border-radius-md)",
      padding: "10px 12px",
      background: tint,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
        <span style={{ fontSize: 10, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 500 }}>{title}</span>
        <span style={{ fontSize: 13, fontWeight: 600, color: accent, fontVariantNumeric: "tabular-nums" }}>
          {latest === null ? "—" : `${latest.toFixed(decimals)}${unit}`}
        </span>
      </div>
      <div style={{ width: "100%", height: 56 }}>
        {points.length >= 2 ? (
          <ResponsiveContainer>
            <AreaChart data={points} margin={{ top: 2, right: 2, left: 2, bottom: 0 }}>
              <defs>
                <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={accent} stopOpacity={0.25} />
                  <stop offset="95%" stopColor={accent} stopOpacity={0} />
                </linearGradient>
              </defs>
              <Tooltip
                contentStyle={{ background: "var(--color-background-secondary)", border: "0.5px solid var(--color-border-tertiary)", borderRadius: 6, fontSize: 11 }}
                labelStyle={{ color: "var(--color-text-tertiary)" }}
                formatter={(v) => [`${Number(v).toFixed(decimals)}${unit}`, title]}
              />
              <ReferenceLine y={threshold} stroke="rgba(128,128,128,0.35)" strokeDasharray="2 2" />
              <Area type="monotone" dataKey="value" stroke={accent} strokeWidth={1.4} fill={`url(#${gid})`} dot={false} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", fontSize: 10, color: "var(--color-text-tertiary)" }}>
            Not enough data for this window
          </div>
        )}
      </div>
    </div>
  );
}

function RollingAnalytics({ rolling }) {
  const [win, setWin] = useState("90");

  if (!rolling || !rolling.by_window || !rolling.by_window[win]) {
    return (
      <div style={{ border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-lg)", padding: "12px 14px", fontSize: 11, color: "var(--color-text-secondary)" }}>
        Rolling analytics are computed from the equity curve of a completed run. Run a backtest to populate this view.
      </div>
    );
  }

  const w = rolling.by_window[win];
  const windows = rolling.windows || [30, 90, 252];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>WINDOW:</span>
        {windows.map(ws => (
          <button
            key={ws}
            onClick={() => setWin(String(ws))}
            style={{
              background: win === String(ws) ? "var(--color-background-info)" : "transparent",
              color: win === String(ws) ? "var(--color-text-info)" : "var(--color-text-secondary)",
              border: `0.5px solid ${win === String(ws) ? "var(--color-border-info)" : "var(--color-border-tertiary)"}`,
              borderRadius: 4, padding: "3px 10px", fontSize: 11,
              fontWeight: win === String(ws) ? 600 : 400, cursor: "pointer",
            }}
          >{ws}d</button>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 10 }}>
        <RollingSparkline title={`Sharpe (${win}d)`} data={w.sharpe} threshold={0} higherIsBetter decimals={2} />
        <RollingSparkline title={`Volatility (${win}d)`} data={w.volatility} unit="%" threshold={0} higherIsBetter={false} decimals={1} />
        <RollingSparkline title={`Return (${win}d)`} data={w.return} unit="%" threshold={0} higherIsBetter decimals={1} />
        <RollingSparkline title="Drawdown (running)" data={rolling.drawdown} unit="%" threshold={0} higherIsBetter decimals={1} />
      </div>

      <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", lineHeight: 1.5 }}>
        Trailing-window metrics reveal regime changes — consistent performance vs. a single lucky streak.
        Sharpe is annualized (√252). Drawdown is the running peak-to-current decline and ignores the window selector.
      </div>
    </div>
  );
}

// ── Compare palette ───────────────────────────────────────────────────────────
const COMPARE_COLORS = ["#378ADD", "#F59E0B", "#22C55E", "#A78BFA", "#F472B6"];

const COMPARE_METRIC_ROWS = [
  { key: "total_return_pct", label: "Total Return", fmt: v => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`, higherBetter: true },
  { key: "sharpe_ratio", label: "Sharpe Ratio", fmt: v => v.toFixed(3), higherBetter: true },
  { key: "max_drawdown_pct", label: "Max Drawdown", fmt: v => `-${v.toFixed(2)}%`, higherBetter: false },
  { key: "win_rate_pct", label: "Win Rate", fmt: v => `${v.toFixed(1)}%`, higherBetter: true },
  { key: "total_trades", label: "Total Trades", fmt: v => String(v), higherBetter: null },
  { key: "total_commission_paid", label: "Commission Paid", fmt: v => `$${v.toFixed(0)}`, higherBetter: false },
];

function downloadComparisonCSV(runs) {
  const rows = [];
  rows.push(["Metric", ...runs.map(r => r.run_id)]);
  rows.push(["Strategy", ...runs.map(r => r.strategy_name)]);
  rows.push(["Period", ...runs.map(r => `${r.start_date} → ${r.end_date}`)]);
  rows.push([]);
  COMPARE_METRIC_ROWS.forEach(({ key, label }) => {
    rows.push([label, ...runs.map(r => r.performance[key] ?? "")]);
  });
  const csv = rows.map(r => r.map(v => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `getABG_comparison_${runs.map(r => r.run_id).join("-")}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// Normalise all equity curves to the same starting capital so they're comparable
function normaliseEquityCurve(curve, targetCapital = 100000) {
  if (!curve || curve.length === 0) return [];
  const base = curve[0].equity || targetCapital;
  return curve.map(pt => ({ ...pt, equity: (pt.equity / base) * targetCapital }));
}

function ComparisonView({ runs, onClose }) {
  // Build overlay data: merge all equity curves by index position (not date)
  const maxLen = Math.max(...runs.map(r => (r.equity_curve || []).length));
  const normCurves = runs.map(r => normaliseEquityCurve(r.equity_curve || []));

  const overlayData = Array.from({ length: maxLen }, (_, i) => {
    const pt = { time: normCurves[0]?.[i]?.time || String(i) };
    runs.forEach((r, ri) => {
      pt[r.run_id] = normCurves[ri][i]?.equity ?? null;
    });
    return pt;
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 500 }}>Run Comparison</div>
          <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 1 }}>
            {runs.length} runs · equity curves normalised to $100k starting capital
          </div>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button
            onClick={() => downloadComparisonCSV(runs)}
            style={{
              fontSize: 11, padding: "3px 10px",
              borderRadius: "var(--border-radius-md)",
              border: "0.5px solid var(--color-border-tertiary)",
              background: "var(--color-background-secondary)",
              color: "var(--color-text-secondary)",
              cursor: "pointer",
            }}
          >⬇ CSV</button>
          <button
            onClick={onClose}
            style={{
              fontSize: 11, padding: "3px 10px",
              borderRadius: "var(--border-radius-md)",
              border: "0.5px solid var(--color-border-tertiary)",
              background: "transparent",
              color: "var(--color-text-secondary)",
              cursor: "pointer",
            }}
          >✕ Close</button>
        </div>
      </div>

      {/* Metrics table */}
      <div style={{ border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-lg)", overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
          <thead>
            <tr style={{ background: "var(--color-background-secondary)" }}>
              <th style={{ padding: "8px 12px", textAlign: "left", fontWeight: 500, color: "var(--color-text-tertiary)", fontSize: 10, letterSpacing: "0.05em" }}>METRIC</th>
              {runs.map((r, i) => (
                <th key={r.run_id} style={{ padding: "8px 12px", textAlign: "right", fontWeight: 500, color: COMPARE_COLORS[i], fontSize: 10 }}>
                  <div style={{ fontSize: 10, fontWeight: 600 }}>{r.run_id.slice(0, 8)}</div>
                  <div style={{ fontSize: 9, color: "var(--color-text-tertiary)", fontWeight: 400, marginTop: 1 }}>{r.strategy_name}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {COMPARE_METRIC_ROWS.map(({ key, label, fmt, higherBetter }, rowIdx) => (
              <tr key={key} style={{ borderTop: "0.5px solid var(--color-border-tertiary)", background: rowIdx % 2 === 0 ? "transparent" : "var(--color-background-secondary)" }}>
                <td style={{ padding: "7px 12px", color: "var(--color-text-secondary)", fontWeight: 400 }}>{label}</td>
                {runs.map((r) => {
                  const val = r.performance?.[key];
                  const isBest = higherBetter !== null && r.best_metrics?.[key];
                  return (
                    <td key={r.run_id} style={{
                      padding: "7px 12px",
                      textAlign: "right",
                      fontWeight: isBest ? 600 : 400,
                      color: isBest ? "#22C55E" : "var(--color-text-primary)",
                      fontVariantNumeric: "tabular-nums",
                    }}>
                      {val != null ? fmt(val) : "—"}
                      {isBest && <span style={{ marginLeft: 4, fontSize: 9, color: "#22C55E" }}>▲</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Overlay equity chart */}
      <div style={{ border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-lg)", padding: "12px 14px" }}>
        <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 10 }}>Equity Curve Overlay (normalised)</div>
        <div style={{ width: "100%", height: 220 }}>
          <ResponsiveContainer>
            <LineChart data={overlayData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(128,128,128,0.08)" />
              <XAxis dataKey="time" tick={{ fontSize: 9, fill: "#888" }} tickLine={false}
                interval={Math.floor(overlayData.length / 5)} />
              <YAxis tick={{ fontSize: 10, fill: "#888" }} tickLine={false} axisLine={false}
                tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} width={42} />
              <Tooltip
                formatter={(v, name) => [`$${Number(v).toLocaleString()}`, name]}
                labelStyle={{ fontSize: 11 }}
                contentStyle={{ fontSize: 11, borderRadius: 6, border: "0.5px solid var(--color-border-tertiary)", background: "var(--color-background-primary)" }}
              />
              <ReferenceLine y={100000} stroke="#888" strokeDasharray="4 4" strokeWidth={0.5} />
              {runs.map((r, i) => (
                <Line key={r.run_id} type="monotone" dataKey={r.run_id}
                  stroke={COMPARE_COLORS[i]} strokeWidth={1.5}
                  dot={false} connectNulls isAnimationActive={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
        {/* Legend */}
        <div style={{ display: "flex", gap: 12, marginTop: 6, fontSize: 10, color: "var(--color-text-tertiary)", flexWrap: "wrap" }}>
          {runs.map((r, i) => (
            <span key={r.run_id} style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ width: 16, height: 2, background: COMPARE_COLORS[i], display: "inline-block" }} />
              {r.run_id.slice(0, 8)} · {r.strategy_name}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── RunHistory — list of past runs with compare checkboxes ────────────────────
function RunHistory({ onViewRun, onCompare }) {
  const { authFetch } = useAuth();
  const [runs, setRuns] = useState(null); // null = loading, [] = loaded empty
  const [selected, setSelected] = useState(new Set());

  useEffect(() => {
    let cancelled = false;
    authFetch(`${API}/runs`)
      .then(r => r.json())
      .then(d => { if (!cancelled) setRuns(d.runs || []); })
      .catch(() => { if (!cancelled) setRuns([]); });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggle = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < 5) next.add(id);
      return next;
    });
  };

  if (runs === null) return <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", padding: "12px 0" }}>Loading run history…</div>;
  if (!runs.length) return <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", padding: "12px 0" }}>No completed runs yet. Run a backtest above.</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)" }}>
          RUN HISTORY ({runs.length})
        </span>
        {selected.size >= 2 && (
          <button
            onClick={() => onCompare(Array.from(selected))}
            style={{
              fontSize: 10, padding: "4px 10px", cursor: "pointer",
              background: "var(--color-background-info)",
              border: "0.5px solid var(--color-border-info)",
              borderRadius: 4, color: "var(--color-text-info)", fontWeight: 600,
            }}
          >Compare Selected ({selected.size})</button>
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {runs.map(r => (
          <div
            key={r.run_id}
            style={{
              display: "flex", alignItems: "center", gap: 8,
              border: "0.5px solid var(--color-border-tertiary)",
              borderRadius: "var(--border-radius-md)",
              padding: "7px 10px",
              background: selected.has(r.run_id) ? "var(--color-background-info)" : "transparent",
              cursor: "pointer",
            }}
            onClick={() => toggle(r.run_id)}
          >
            <input
              type="checkbox"
              checked={selected.has(r.run_id)}
              onChange={() => toggle(r.run_id)}
              onClick={e => e.stopPropagation()}
              style={{ cursor: "pointer", flexShrink: 0 }}
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 11, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {r.strategy_name} · {(r.market_universe || []).join(", ")}
              </div>
              <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginTop: 1 }}>
                {r.start_date} → {r.end_date} · {r.run_id.slice(0, 8)}
              </div>
            </div>
            <button
              onClick={e => { e.stopPropagation(); onViewRun(r.run_id); }}
              style={{
                fontSize: 10, padding: "3px 8px", cursor: "pointer",
                background: "transparent",
                border: "0.5px solid var(--color-border-tertiary)",
                borderRadius: 4, color: "var(--color-text-secondary)", flexShrink: 0,
              }}
            >View</button>
          </div>
        ))}
      </div>
      {selected.size > 0 && selected.size < 2 && (
        <div style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>Select at least 2 runs to compare.</div>
      )}
    </div>
  );
}

function ResultsDashboard({ report }) {
  const [selectedTicker, setSelectedTicker] = useState(report.is_multi && report.tickers ? report.tickers[0] : null);
  const [activeTab, setActiveTab] = useState("overview");
  const [pdfLoading, setPdfLoading] = useState(false);

  // Resolve sub-report based on ticker selection
  const activeReport = report.is_multi && selectedTicker ? report.results[selectedTicker] : report;
  const { metadata: m, performance: p, equity_curve, trade_log } = activeReport;

  const tabs = ["overview", "rolling", "trades", "events"];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {/* Ticker Selector Header */}
      {report.is_multi && (
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          borderBottom: "0.5px solid var(--color-border-tertiary)",
          paddingBottom: 10,
        }}>
          <span style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-tertiary)" }}>TICKERS:</span>
          <div style={{ display: "flex", gap: 4 }}>
            {report.tickers.map(t => (
              <button
                key={t}
                onClick={() => setSelectedTicker(t)}
                style={{
                  background: selectedTicker === t ? "var(--color-background-info)" : "transparent",
                  color: selectedTicker === t ? "var(--color-text-info)" : "var(--color-text-secondary)",
                  border: `0.5px solid ${selectedTicker === t ? "var(--color-border-info)" : "transparent"}`,
                  borderRadius: 4,
                  padding: "3px 8px",
                  fontSize: 11,
                  fontWeight: selectedTicker === t ? 600 : 400,
                  cursor: "pointer"
                }}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      )}

      <div style={{
        padding: "10px 0",
        borderBottom: "0.5px solid var(--color-border-tertiary)",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
      }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 500 }}>{m.strategy_name.replace("_", " ")}</div>
          <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 1 }}>
            {m.start_date} → {m.end_date} · ID: {m.run_id}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Badge type="success">{m.status}</Badge>
          <button
            onClick={() => downloadCSV(m, p, trade_log, equity_curve)}
            title="Download metrics + trades as CSV"
            style={{
              fontSize: 11, padding: "3px 10px",
              borderRadius: "var(--border-radius-md)",
              border: "0.5px solid var(--color-border-tertiary)",
              background: "var(--color-background-secondary)",
              color: "var(--color-text-secondary)",
              cursor: "pointer",
              display: "flex", alignItems: "center", gap: 4,
            }}
          >⬇ CSV</button>
          <button
            onClick={async () => {
              setPdfLoading(true);
              try { await downloadPDF(m, p, trade_log); }
              finally { setPdfLoading(false); }
            }}
            title="Download formatted PDF report"
            style={{
              fontSize: 11, padding: "3px 10px",
              borderRadius: "var(--border-radius-md)",
              border: "0.5px solid var(--color-border-info)",
              background: "var(--color-background-info)",
              color: "var(--color-text-info)",
              cursor: pdfLoading ? "wait" : "pointer",
              display: "flex", alignItems: "center", gap: 4,
              opacity: pdfLoading ? 0.7 : 1,
            }}
          >{pdfLoading ? "Generating…" : "⬇ PDF"}</button>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 8 }}>
        <StatCard label="Total Return" value={`${p.total_return_pct > 0 ? "+" : ""}${p.total_return_pct.toFixed(2)}%`} negative />
        <StatCard label="Buy & Hold" value={`${p.buy_and_hold_return_pct > 0 ? "+" : ""}${p.buy_and_hold_return_pct.toFixed(2)}%`} negative />
        <StatCard label="Alpha" value={`${p.alpha_pct > 0 ? "+" : ""}${p.alpha_pct.toFixed(2)}%`} negative />
        <StatCard label="CAGR" value={`${p.cagr_pct > 0 ? "+" : ""}${p.cagr_pct.toFixed(2)}%`} negative />
        <StatCard label="Sharpe Ratio" value={p.sharpe_ratio.toFixed(3)} color={p.sharpe_ratio > 1 ? "var(--color-text-success)" : "var(--color-text-warning)"} />
        <StatCard label="Sortino Ratio" value={p.sortino_ratio.toFixed(3)} color={p.sortino_ratio > 1.5 ? "var(--color-text-success)" : "var(--color-text-warning)"} />
        <StatCard label="Max Drawdown" value={`-${p.max_drawdown_pct.toFixed(2)}%`} color="var(--color-text-danger)" />
        <StatCard label="Win Rate" value={`${p.win_rate_pct.toFixed(1)}%`} sub={`${p.total_trades} trades`} />
        <StatCard label="Profit Factor" value={p.profit_factor.toFixed(3)} color={p.profit_factor > 1.5 ? "var(--color-text-success)" : "var(--color-text-warning)"} />
        <StatCard label="Time in Market" value={`${p.time_in_market_pct.toFixed(1)}%`} sub={`avg ${p.avg_trade_duration_days}d hold`} />
      </div>

      <div style={{
        border: "0.5px solid var(--color-border-tertiary)",
        borderRadius: "var(--border-radius-lg)",
        padding: "12px 14px",
      }}>
        <div style={{ display: "flex", justify: "space-between", marginBottom: 10, fontSize: 12 }}>
          <span style={{ fontWeight: 500 }}>Equity Growth Curve</span>
          <span style={{ color: "var(--color-text-tertiary)", marginLeft: "auto" }}>
            Start: ${m.initial_capital.toLocaleString()} → End: <strong>${m.final_equity.toLocaleString()}</strong>
          </span>
        </div>
        <EquityChart
          curve={equity_curve}
          benchmarkCurve={activeReport.benchmark_curve}
          benchmarkTicker={activeReport.benchmark_ticker || "SPY"}
          trades={trade_log}
        />
      </div>

      <div style={{ display: "flex", gap: 4, borderBottom: "0.5px solid var(--color-border-tertiary)" }}>
        {tabs.map(tab => (
          <button key={tab} onClick={() => setActiveTab(tab)} style={{
            background: "none", border: "none", borderBottom: activeTab === tab ? "1.5px solid var(--color-text-info)" : "1.5px solid transparent",
            color: activeTab === tab ? "var(--color-text-primary)" : "var(--color-text-secondary)",
            padding: "4px 8px", cursor: "pointer", fontSize: 12, fontWeight: activeTab === tab ? 500 : 400,
            marginBottom: -1,
            borderRadius: 0,
          }}>{tab.charAt(0).toUpperCase() + tab.slice(1)}</button>
        ))}
      </div>

      {activeTab === "overview" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{
            border: "0.5px solid var(--color-border-tertiary)",
            borderRadius: "var(--border-radius-lg)",
            padding: "12px 14px",
          }}>
            <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 10 }}>Net PnL per trade</div>
            <TradeBarChart trades={trade_log.slice(0, 16)} />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <div style={{ border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-md)", padding: "10px 12px" }}>
              <div style={{ fontSize: 10, fontWeight: 500, color: "var(--color-text-tertiary)", marginBottom: 6 }}>CAPITAL DETAILS</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {[
                  ["Gross Profit", `+$${p.gross_profit.toLocaleString()}`, "success"],
                  ["Gross Loss", `$${p.gross_loss.toLocaleString()}`, "danger"],
                  ["Commission Paid", p.total_commission_paid > 0 ? `-$${p.total_commission_paid.toFixed(2)}` : "$0.00", p.total_commission_paid > 0 ? "danger" : "tertiary"],
                  ["Net PnL", `${p.net_pnl >= 0 ? "+" : ""}$${p.net_pnl.toLocaleString()}`, p.net_pnl >= 0 ? "success" : "danger"],
                ].map(([label, val, type]) => (
                  <div key={label} style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
                    <span style={{ color: "var(--color-text-secondary)" }}>{label}</span>
                    <span style={{ color: `var(--color-text-${type})`, fontWeight: 500, fontVariantNumeric: "tabular-nums" }}>{val}</span>
                  </div>
                ))}
              </div>
            </div>
            <div style={{ border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-md)", padding: "10px 12px" }}>
              <div style={{ fontSize: 10, fontWeight: 500, color: "var(--color-text-tertiary)", marginBottom: 6 }}>DRAWDOWN DETAILS</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {[
                  ["Max Drawdown", `-${p.max_drawdown_pct.toFixed(2)}%`],
                  ["Drawdown Duration", `${p.max_drawdown_duration_days} days`],
                  ["Initial Capital", `$${m.initial_capital.toLocaleString()}`],
                  ["Final Equity", `$${m.final_equity.toLocaleString()}`],
                ].map(([label, val]) => (
                  <div key={label} style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
                    <span style={{ color: "var(--color-text-secondary)" }}>{label}</span>
                    <span style={{ fontWeight: 500, fontVariantNumeric: "tabular-nums" }}>{val}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {activeTab === "trades" && (
        <div style={{
          border: "0.5px solid var(--color-border-tertiary)",
          borderRadius: "var(--border-radius-lg)",
          overflow: "hidden",
        }}>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
              <thead>
                <tr style={{ background: "var(--color-background-secondary)", borderBottom: "0.5px solid var(--color-border-tertiary)" }}>
                  {["#", "Ticker", "Dir", "Entry", "Exit", "Qty", "Entry $", "Exit $", "Net PnL", "Status"].map(h => (
                    <th key={h} style={{
                      padding: "8px 10px", textAlign: "left", fontWeight: 500, fontSize: 10,
                      color: "var(--color-text-tertiary)"
                    }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {trade_log.map((t) => (
                  <tr key={t.trade_id} style={{ borderBottom: "0.5px solid var(--color-border-tertiary)" }}>
                    <td style={{ padding: "8px 10px", color: "var(--color-text-tertiary)" }}>{t.trade_id}</td>
                    <td style={{ padding: "8px 10px", fontWeight: 500 }}>
                      <TickerTag ticker={t.ticker} />
                    </td>
                    <td style={{ padding: "8px 10px" }}><Badge type="info">{t.direction}</Badge></td>
                    <td style={{ padding: "8px 10px", fontVariantNumeric: "tabular-nums" }}>{t.entry_time}</td>
                    <td style={{ padding: "8px 10px", fontVariantNumeric: "tabular-nums", color: "var(--color-text-tertiary)" }}>{t.exit_time || "—"}</td>
                    <td style={{ padding: "8px 10px", fontVariantNumeric: "tabular-nums" }}>{t.quantity}</td>
                    <td style={{ padding: "8px 10px", fontVariantNumeric: "tabular-nums" }}>${t.entry_price?.toFixed(2)}</td>
                    <td style={{ padding: "8px 10px", fontVariantNumeric: "tabular-nums" }}>${t.exit_price?.toFixed(2) || "—"}</td>
                    <td style={{
                      padding: "8px 10px", fontWeight: 500, fontVariantNumeric: "tabular-nums",
                      color: (t.net_pnl || 0) >= 0 ? "var(--color-text-success)" : "var(--color-text-danger)"
                    }}>
                      {(t.net_pnl || 0) >= 0 ? "+" : ""}${(t.net_pnl || 0).toFixed(2)}
                    </td>
                    <td style={{ padding: "8px 10px" }}>
                      <Badge type={t.status === "CLOSED" ? "success" : "warning"}>{t.status}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activeTab === "rolling" && (
        <RollingAnalytics rolling={activeReport.rolling_metrics} />
      )}

      {activeTab === "events" && (
        <div style={{ border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-lg)", padding: "12px 14px" }}>
          <div style={{ fontSize: 11, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
            Event log is populated from the SQLite state machine during a live run. Connect the API server at{" "}
            <code style={{ fontSize: 11 }}>localhost:5050</code> to see real-time execution events.
          </div>
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
            {[
              "SIGNAL", "ORDER_SENT", "ORDER_FILLED", "STOP_LOSS",
              "REJECTED_MARGIN", "TIMEOUT_ERROR", "POSITION_CLOSED"
            ].map(e => (
              <div key={e} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Badge type={e.includes("ERROR") || e.includes("REJECTED") ? "danger" : e === "ORDER_FILLED" ? "success" : "info"}>{e}</Badge>
                <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
                  {e === "SIGNAL" && "Macro-filter flagged an active window"}
                  {e === "ORDER_SENT" && "Strategy returned an order intent"}
                  {e === "ORDER_FILLED" && "Host engine filled order with slippage"}
                  {e === "STOP_LOSS" && "Stop-loss threshold triggered"}
                  {e === "REJECTED_MARGIN" && "Insufficient funds — order rejected"}
                  {e === "TIMEOUT_ERROR" && "Strategy subprocess timed out"}
                  {e === "POSITION_CLOSED" && "Position liquidated by engine"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Dashboard() {
  const { user, logout, isPro, authFetch } = useAuth();
  const [view, setView] = useState("config");
  const [report, setReport] = useState(null);
  const [compareRuns, setCompareRuns] = useState(null); // [{run_id, performance, equity_curve, best_metrics, ...}]
  const [compareLoading, setCompareLoading] = useState(false);
  const [pollingId, setPollingId] = useState(null);
  const [theme, setTheme] = useState("dark");
  const [showUpgrade, setShowUpgrade] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);

  const handleCompare = async (runIds) => {
    setCompareLoading(true);
    try {
      const resp = await authFetch(`${API}/runs/compare?ids=${runIds.join(",")}`);
      const data = await resp.json();
      if (data.error) { alert(data.error); return; }
      setCompareRuns(data.runs);
      setView("compare");
    } catch (e) {
      alert(`Compare failed: ${e.message}`);
    } finally {
      setCompareLoading(false);
    }
  };

  const handleViewRun = async (runId) => {
    try {
      const r = await authFetch(`${API}/runs/${runId}`);
      const fullReport = await r.json();
      if (fullReport.error) { alert(fullReport.error); return; }
      setReport(fullReport);
      setView("results");
    } catch (e) {
      alert(`Failed to load run: ${e.message}`);
    }
  };

  useEffect(() => {
    if (theme === "light") {
      document.body.classList.add("light");
    } else {
      document.body.classList.remove("light");
    }
  }, [theme]);

  const handleRunStarted = (data, isDemo) => {
    if (isDemo) {
      setReport(data);
      setView("results");
      return;
    }
    setPollingId(data);
    setView("polling");
    const interval = setInterval(async () => {
      try {
        const resp = await authFetch(`${API}/runs/${data}/status`);
        const status = await resp.json();
        if (status.status === "COMPLETED" || status.status === "FAILED") {
          clearInterval(interval);
          if (status.status === "COMPLETED") {
            const r = await authFetch(`${API}/runs/${data}`);
            const fullReport = await r.json();
            setReport(fullReport);
            setView("results");
          } else {
            alert(`Backtest failed: ${status.error || 'Check server logs'}`);
            setView("config");
          }
        }
      } catch (e) {
        clearInterval(interval);
        alert(`Polling failed: ${e.message}`);
        setView("config");
      }
    }, 2000);
  };

  return (
    <div style={{ padding: "2rem 1.5rem", maxWidth: 680, margin: "0 auto" }}>
      <h2 aria-hidden className="sr-only">getABG Quantitative Backtesting Platform</h2>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 16, fontWeight: 500, letterSpacing: "-0.01em" }}>getABG</span>
            <Badge type="info">Quant Platform</Badge>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {/* Plan badge */}
          {isPro ? (
            <span style={{
              fontSize: 9,
              fontWeight: 600,
              padding: "2px 8px",
              borderRadius: 20,
              background: "linear-gradient(135deg, rgba(56,189,248,0.15), rgba(129,140,248,0.15))",
              color: "var(--color-text-info)",
              border: "0.5px solid rgba(56,189,248,0.3)",
              letterSpacing: "0.06em",
            }}>
              PRO
            </span>
          ) : (
            <button
              onClick={() => setShowUpgrade(true)}
              style={{
                fontSize: 9,
                fontWeight: 600,
                padding: "2px 8px",
                borderRadius: 20,
                background: "transparent",
                color: "var(--color-text-tertiary)",
                border: "0.5px solid var(--color-border-tertiary)",
                cursor: "pointer",
                letterSpacing: "0.06em",
                transition: "all 0.2s",
              }}
            >
              FREE ↑
            </button>
          )}

          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            style={{
              fontSize: 10,
              padding: "4px 8px",
              borderRadius: 4,
              cursor: "pointer",
              background: "transparent",
              border: "0.5px solid var(--color-border-tertiary)"
            }}
          >
            {theme === "dark" ? "LIGHT" : "DARK"}
          </button>
          {(view === "results" || view === "compare") && (
            <button
              onClick={() => { setView("config"); setReport(null); setCompareRuns(null); }}
              style={{
                fontSize: 10,
                padding: "4px 8px",
                borderRadius: 4,
                cursor: "pointer",
                background: "transparent",
                border: "0.5px solid var(--color-border-tertiary)"
              }}
            >
              NEW RUN
            </button>
          )}

          {/* User menu */}
          <div style={{ position: "relative" }}>
            <button
              onClick={() => setShowUserMenu(!showUserMenu)}
              style={{
                fontSize: 10,
                padding: "4px 8px",
                borderRadius: 4,
                cursor: "pointer",
                background: "transparent",
                border: "0.5px solid var(--color-border-tertiary)",
                display: "flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              <span style={{
                width: 16,
                height: 16,
                borderRadius: "50%",
                background: "linear-gradient(135deg, #38BDF8, #818CF8)",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 8,
                fontWeight: 700,
                color: "#fff",
              }}>
                {(user?.email || "?")[0].toUpperCase()}
              </span>
              <span style={{ fontSize: 10, maxWidth: 80, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {user?.email?.split("@")[0] || "User"}
              </span>
            </button>

            {showUserMenu && (
              <div
                style={{
                  position: "absolute",
                  top: "calc(100% + 6px)",
                  right: 0,
                  minWidth: 180,
                  background: "var(--color-background-secondary)",
                  border: "0.5px solid var(--color-border-tertiary)",
                  borderRadius: "var(--border-radius-md)",
                  padding: "8px 0",
                  boxShadow: "0 8px 24px rgba(0,0,0,0.3)",
                  zIndex: 100,
                }}
              >
                <div style={{ padding: "6px 14px", borderBottom: "0.5px solid var(--color-border-tertiary)" }}>
                  <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 2 }}>{user?.email}</div>
                  <div style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>
                    {isPro ? "Pro Plan" : "Free Plan"}
                  </div>
                </div>
                {!isPro && (
                  <button
                    onClick={() => { setShowUserMenu(false); setShowUpgrade(true); }}
                    style={{
                      width: "100%",
                      padding: "8px 14px",
                      fontSize: 11,
                      textAlign: "left",
                      background: "none",
                      border: "none",
                      color: "var(--color-text-info)",
                      cursor: "pointer",
                      fontWeight: 500,
                      borderRadius: 0,
                    }}
                  >
                    ⚡ Upgrade to Pro
                  </button>
                )}
                <button
                  onClick={() => { setShowUserMenu(false); logout(); }}
                  style={{
                    width: "100%",
                    padding: "8px 14px",
                    fontSize: 11,
                    textAlign: "left",
                    background: "none",
                    border: "none",
                    color: "var(--color-text-danger)",
                    cursor: "pointer",
                    borderRadius: 0,
                  }}
                >
                  Sign Out
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {view === "config" && (
        <>
          <RunForm onRunStarted={handleRunStarted} onShowUpgrade={() => setShowUpgrade(true)} />
          <div style={{ marginTop: 24, borderTop: "0.5px solid var(--color-border-tertiary)", paddingTop: 16 }}>
            <RunHistory onViewRun={handleViewRun} onCompare={handleCompare} />
            {compareLoading && (
              <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 8 }}>Loading comparison…</div>
            )}
          </div>
        </>
      )}

      {view === "compare" && compareRuns && (
        <ComparisonView runs={compareRuns} onClose={() => { setView("config"); setCompareRuns(null); }} />
      )}

      {view === "polling" && (
        <div style={{ textAlign: "center", padding: "40px 0" }}>
          <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 6 }}>Backtest in progress…</div>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 20 }}>
            Run <code>{pollingId}</code> is executing tickers separately.
          </div>
          <div style={{
            display: "flex", gap: 6, justifyContent: "center", alignItems: "center",
            color: "var(--color-text-tertiary)", fontSize: 11,
          }}>
            {["Fetch Data", "Macro filter", "Micro Sim", "Performance"].map((s, i) => (
              <span key={s} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                {i > 0 && <span>→</span>}
                <span>{s}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {view === "results" && report && <ResultsDashboard report={report} />}

      {showUpgrade && (
        <UpgradePage onClose={() => setShowUpgrade(false)} />
      )}
    </div>
  );
}
