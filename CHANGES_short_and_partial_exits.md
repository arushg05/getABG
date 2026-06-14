# Engine Changes: Short Selling & Partial Exits

**Status:** Proposed / design spec — not yet applied to the engine.
**Targets:** `engine/backtest.py` (`Portfolio`, order loop), `sandbox/worker.py` (`validate_action_queue`), strategy contract.
**Motivation:** Enable (1) short positions for bearish signals and (2) partial scale-outs, so the tiered "Variation C" exit can reduce the profit-capture gap (currently ~25–32% of MFE realized).

---

## 1. Order schema (the contract change)

Today the engine recognizes two actions and is long-only:

- `BUY` when flat → open LONG; `BUY` when holding → ignored
- `SELL` when flat → **rejected**; `SELL` when holding → close the **entire** position (order `quantity` is ignored)

We add two explicit actions and make `SELL`/`COVER` quantity-aware. Explicit actions keep existing long-only strategies **100% backward compatible** (a stray `SELL` while flat is still rejected, not silently turned into a short).

| Action | Flat | Long held | Short held |
|--------|------|-----------|------------|
| `BUY`   | open LONG | reject (no pyramiding) | reject |
| `SELL`  | reject | reduce/close LONG by `quantity` | reject |
| `SHORT` | open SHORT | reject | reject (no pyramiding) |
| `COVER` | reject | reject | reduce/close SHORT by `quantity` |

A reduce order with `quantity >= position qty` closes the position fully; with `quantity < position qty` it scales out and leaves the remainder open.

`sandbox/worker.py` → `validate_action_queue()`: extend the allowed set from `("BUY","SELL")` to `("BUY","SELL","SHORT","COVER")`. Everything else in that validator stays the same.

---

## 2. Short selling

### Accounting model (simple, symmetric with the existing long convention)

The current long convention is: open subtracts cost from cash, and `total_equity` adds `qty * current_price`; at the open bar equity is unchanged. Shorts mirror this exactly:

- **Open short:** `cash += fill_price * qty - commission`; reserve `allocated_margin += fill_price * qty`. Fill is `price - SLIPPAGE` (already in `open_position`).
- **Equity:** a SHORT position contributes **`- qty * current_price`** (a liability), so `total_equity = cash + Σ(long qty·px) − Σ(short qty·px)`. At the open bar equity ≈ unchanged; as price falls, equity rises. Correct.
- **Cover:** fill is `price + SLIPPAGE`; `cash -= fill_price * qty + commission`; release `allocated_margin`. Realized PnL = `(entry_fill − cover_fill) * qty − commissions`.
- **Unrealized PnL** (`to_state`): for SHORT use **`(entry − current) * qty`** (sign flips vs long).

This is a cash-collateral model: **no borrow fees, no margin interest, no hard-to-borrow constraint.** Buying-power check for a short: require `cash >= fill_price * qty` (100% reserve) — or implement Reg-T 50% if you want leverage. State the choice; default to 100% reserve for conservatism.

### Code touch-points in `engine/backtest.py`

- `Portfolio.open_position(...)` already takes `direction` and sets the SHORT fill price, **but its cash math is long-only** (`cash -= cost`). Add a SHORT branch: `cash += fill*qty - commission`.
- `Portfolio.close_position(...)` already handles the SHORT cover fill price, **but `cash += proceeds` is long-only**. Add a SHORT branch for the cover cash math above.
- `Portfolio.total_equity(...)` — subtract `qty*price` for SHORT positions instead of adding.
- `Portfolio.to_state(...)` — flip the `unrealized_pnl` sign for SHORT.
- **Order loop** (the `if action == ...` block): add the `SHORT` (open) and `COVER` (close/reduce) branches per the table above; add an affordability/margin check for `SHORT` mirroring `can_afford`.
- `_close_all_positions(...)` (end-of-backtest force close): already pops every position — confirm it uses the direction-aware `close_position`, which it does. The `direction` hardcoded as `"LONG"` in the `POSITION_CLOSED` event log should read `pos["direction"]`.

---

## 3. Partial exits

### Behavior

`SELL` / `COVER` with `quantity < held` closes only that slice and keeps the rest open. This lets a strategy bank a portion at momentum exhaustion and trail the runner.

### Code touch-points

- `Portfolio.close_position(ticker, price, qty=None)` — add a `qty` parameter. Compute `close_qty = min(qty or pos["qty"], pos["qty"])`. Realize PnL on `close_qty`; release `allocated_margin` proportionally. If `close_qty < pos["qty"]`: **decrement** `pos["qty"]` and leave the position open; else pop it as today.
- **Trade log:** emit a **separate `Trade_Log` row per scale-out**, copying the original `entry_time`/`entry_price` but recording the closed `qty` and its own `exit_time`/`exit_price`. A 50/50 scale-out therefore produces two closed-trade rows. `db.open_trade` / `db.close_trade` may need a partial-close path (e.g. `close_trade(trade_id, ..., qty=close_qty)` that splits the row) — simplest is to register a child trade for each closed slice.
- Lot sizing: route the partial `quantity` through `_snap_to_lot` like entries do, so a 50% slice still respects lot size.

### Metrics impact (important)

Per-trade stats now count **scale-outs as trades**, so trade count rises and win-rate/avg-trade shift. When comparing against the current report, compare on **portfolio return / capture ratio / give-back**, not raw trade count. Document this in the report so it isn't misread.

---

## 4. Strategy-side usage (`strategies/momentum_screener.py`)

The existing class already tracks indicators and positions. With the new contract it can do:

```python
# SHORT entry (bearish): score <= -6 AND close < 200 EMA  -> {"action": "SHORT", "quantity": q}
# scale out half a LONG at exhaustion:
#   {"ticker": t, "action": "SELL", "quantity": round(held * 0.5, 2), "order_type": "MARKET"}
# trail the runner: SELL remaining when close < (highest_high_since_entry - 3*ATR)
# mirror for shorts with COVER + (lowest_low_since_entry + 3*ATR)
```

The strategy reads `direction` from `portfolio_state["open_positions"]` to know whether it holds a long or a short, and tracks `highest_high_since_entry` / `lowest_low_since_entry` per ticker for the chandelier trail.

---

## 5. Validation checklist (write these before trusting results)

- **Backward compat:** `ma_crossover` and the current `momentum_screener` (long-only, full-qty SELL) produce **identical** results to pre-change. This is the regression gate.
- **Short PnL sign:** a hand-built series that falls after a `SHORT` shows a profit; one that rises shows a loss of the right magnitude (net of 5bps slippage).
- **Equity continuity:** total_equity is ~unchanged on the bar a short is opened.
- **Partial close:** after a 50% scale-out, remaining `qty` is exactly half (post lot-snap), position still open, and the two trade rows' PnL sums to the single-exit equivalent.
- **No pyramiding:** `BUY` while long and `SHORT` while short are rejected and logged.
- **Margin/affordability:** a `SHORT` larger than buying power is rejected, not filled into negative cash.

---

## 6. Open questions / assumptions

- **Borrow cost:** model assumes zero. Real shorts on names like ASTS/RKLB can carry high borrow — add a daily borrow-fee accrual later if needed.
- **Buying power:** default 100% cash reserve per short (no leverage). Switch to Reg-T 50% if you want the long+short book to use more capital.
- **Partial-exit trade accounting:** each slice = its own trade row (chosen for clean per-slice stats). Alternative is one trade row with a weighted-average exit — simpler log, but hides the scale-out behavior.
