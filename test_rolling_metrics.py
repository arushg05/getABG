"""Acceptance tests for Feature 6 — Rolling Metrics (ROADMAP.md §6)."""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from metrics.performance import compute_rolling_metrics, sharpe_ratio, compute_returns


def _curve(values):
    """Build an equity curve from a list of equity values."""
    return [{"time": f"2022-01-{i+1:02d}", "equity": v} for i, v in enumerate(values)]


# ── AC: Gracefully handles windows longer than available data (null early) ──
curve = _curve([100, 101, 102, 103, 104])
rm = compute_rolling_metrics(curve, {"sharpe": 3, "volatility": 3, "return": 3})
assert rm["sharpe"][0]["value"] is None, "first point has no trailing window"
assert rm["sharpe"][1]["value"] is None, "second point still short of window=3"
assert rm["sharpe"][2]["value"] is not None, "third point completes window=3"
print("[PASS] Null returned for dates without enough trailing data")

# Window longer than the entire series → all None
rm_long = compute_rolling_metrics(curve, {"sharpe": 50, "volatility": 50, "return": 50})
assert all(p["value"] is None for p in rm_long["sharpe"]), "window > data → all null"
print("[PASS] Window longer than available data yields all-null series")

# ── AC: Rolling Sharpe uses correct annualization (matches sqrt(252) func) ──
# The rolling value at the final point must equal sharpe_ratio() over that window,
# which is annualized with sqrt(252). Equality proves correct annualization.
import numpy as np
np.random.seed(0)
vals = list(100 + np.cumsum(np.random.randn(40)))
c2 = _curve(vals)
W = 20
rm2 = compute_rolling_metrics(c2, {"sharpe": W, "volatility": W, "return": W})
expected = round(sharpe_ratio(compute_returns(vals[-W:])), 4)
assert abs(rm2["sharpe"][-1]["value"] - expected) < 1e-9, \
    f"rolling sharpe {rm2['sharpe'][-1]['value']} != windowed sharpe {expected}"
print("[PASS] Rolling Sharpe annualization matches sqrt(252) reference")

# ── AC: Running drawdown is window-independent and peak-to-current ──
# Rises to 120 (peak), falls to 90 → drawdown = (90-120)/120 = -25%
dd_curve = _curve([100, 110, 120, 100, 90])
rmd = compute_rolling_metrics(dd_curve)
dd = rmd["drawdown"]
assert dd[0]["value"] == 0.0, "first point: no drawdown"
assert dd[2]["value"] == 0.0, "at the peak: no drawdown"
assert abs(dd[4]["value"] - (-25.0)) < 1e-6, f"trough drawdown should be -25%, got {dd[4]['value']}"
assert all(p["value"] <= 0.0 for p in dd), "drawdown is always <= 0"
print("[PASS] Running drawdown tracks peak-to-current correctly")

# ── AC: Window return is simple % across the trailing window ──
ret_curve = _curve([100, 105, 110, 121])
rmr = compute_rolling_metrics(ret_curve, {"sharpe": 2, "volatility": 2, "return": 2})
# at index 3: base = equity[2] = 110, current = 121 → +10%
assert abs(rmr["return"][3]["value"] - 10.0) < 1e-6, f"expected +10%, got {rmr['return'][3]['value']}"
print("[PASS] Rolling window return computed correctly")

# ── Empty input must not crash ──
assert compute_rolling_metrics([])["sharpe"] == []
print("[PASS] Empty equity curve handled gracefully")

print("\nAll rolling-metrics acceptance tests passed.")
