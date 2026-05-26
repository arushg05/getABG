import { useState, useEffect, useRef } from "react";
import { LineChart, Line, AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
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
  let base = (import.meta.env.VITE_API_URL || "http://localhost:5050/api").replace(/\/+$/, "");
  return base.endsWith("/api") ? base : `${base}/api`;
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
        { trade_id: 1, ticker: "AAPL", direction: "LONG", entry_time: "2022-01-15", exit_time: "2022-02-10", entry_price: 150.0, exit_price: 165.0, quantity: 200, slippage_total: 0.1, net_pnl: 3000.0, status: "CLOSED" },
        { trade_id: 2, ticker: "AAPL", direction: "LONG", entry_time: "2022-03-05", exit_time: "2022-03-25", entry_price: 160.0, exit_price: 155.0, quantity: 200, slippage_total: 0.1, net_pnl: -1000.0, status: "CLOSED" }
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
        { trade_id: 1, ticker: "MSFT", direction: "LONG", entry_time: "2022-01-20", exit_time: "2022-02-15", entry_price: 280.0, exit_price: 310.0, quantity: 100, slippage_total: 0.2, net_pnl: 3000.0, status: "CLOSED" },
        { trade_id: 2, ticker: "MSFT", direction: "LONG", entry_time: "2022-04-10", exit_time: "2022-05-02", entry_price: 290.0, exit_price: 275.0, quantity: 100, slippage_total: 0.2, net_pnl: -1500.0, status: "CLOSED" }
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
      const resp = await authFetch(`${API}/backtest/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code,
          tickers,
          start_date: startDate,
          end_date: endDate,
          initial_capital: capital,
        }),
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



  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <label style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)" }}>
            STRATEGY (This is the template your strategy must follow)
          </label>
          <label style={{
            fontSize: 10, padding: "4px 8px", cursor: "pointer",
            background: "var(--color-background-info)",
            border: "0.5px solid var(--color-border-info)",
            borderRadius: 4,
            color: "var(--color-text-info)",
            fontWeight: 500,
          }}>
            Upload .py File
            <input type="file" accept=".py" style={{ display: "none" }} onChange={(e) => {
              const file = e.target.files[0];
              if (file) {
                if (!file.name.endsWith(".py")) {
                  setError("Please upload a .py file");
                  return;
                }
                const reader = new FileReader();
                reader.onload = (evt) => setCode(evt.target.result);
                reader.readAsText(file);
                setError(null);
              }
            }} />
          </label>
        </div>
        <CodeEditor value={code} onChange={setCode} />
      </div>

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
        <button onClick={useDemo} style={{
          flex: 1,
          padding: "8px 0",
          fontSize: 12,
          borderRadius: "var(--border-radius-md)",
        }}>
          Demo mode
        </button>
      </div>
    </div>
  );
}

function EquityChart({ curve }) {
  const initial = curve[0]?.equity || 100000;
  return (
    <div style={{ width: "100%", height: 180 }}>
      <ResponsiveContainer>
        <AreaChart data={curve} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#378ADD" stopOpacity={0.12} />
              <stop offset="95%" stopColor="#378ADD" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(128,128,128,0.08)" />
          <XAxis dataKey="time" tick={{ fontSize: 10, fill: "#888" }} tickLine={false}
            interval={Math.floor(curve.length / 5)} />
          <YAxis tick={{ fontSize: 10, fill: "#888" }} tickLine={false} axisLine={false}
            tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} width={40} />
          <Tooltip
            formatter={(v) => [`$${v.toLocaleString()}`, "Equity"]}
            labelStyle={{ fontSize: 11 }}
            contentStyle={{ fontSize: 11, borderRadius: 6, border: "0.5px solid var(--color-border-tertiary)", background: "var(--color-background-primary)" }}
          />
          <ReferenceLine y={initial} stroke="#888" strokeDasharray="4 4" strokeWidth={0.5} />
          <Area type="monotone" dataKey="equity" stroke="#378ADD" strokeWidth={1.5}
            fill="url(#eq)" dot={false} />
        </AreaChart>
      </ResponsiveContainer>
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

function ResultsDashboard({ report }) {
  const [selectedTicker, setSelectedTicker] = useState(report.is_multi && report.tickers ? report.tickers[0] : null);
  const [activeTab, setActiveTab] = useState("overview");

  // Resolve sub-report based on ticker selection
  const activeReport = report.is_multi && selectedTicker ? report.results[selectedTicker] : report;
  const { metadata: m, performance: p, equity_curve, trade_log } = activeReport;

  const tabs = ["overview", "trades", "events"];

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
        <Badge type="success">{m.status}</Badge>
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
        <EquityChart curve={equity_curve} />
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
                    <th key={h} style={{ padding: "8px 10px", textAlign: "left", fontWeight: 500, fontSize: 10,
                      color: "var(--color-text-tertiary)" }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {trade_log.map((t, i) => (
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
                    <td style={{ padding: "8px 10px", fontWeight: 500, fontVariantNumeric: "tabular-nums",
                      color: (t.net_pnl || 0) >= 0 ? "var(--color-text-success)" : "var(--color-text-danger)" }}>
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
  const [pollingId, setPollingId] = useState(null);
  const [theme, setTheme] = useState("dark");
  const [showUpgrade, setShowUpgrade] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);

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
          {view === "results" && (
            <button 
              onClick={() => { setView("config"); setReport(null); }} 
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

      {view === "config" && <RunForm onRunStarted={handleRunStarted} onShowUpgrade={() => setShowUpgrade(true)} />}

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
