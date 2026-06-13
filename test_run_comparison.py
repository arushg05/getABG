"""Acceptance tests for Feature 5 — Run Comparison (ROADMAP.md §5).

These tests validate the compare endpoint contract via Flask test client.
No real DB files are needed — we mock StateDB at the route level.
"""
import sys
import os
import json
import types
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Must be set before importing server (jwt_utils checks at import time)
os.environ.setdefault("AUTH_SECRET", "test-secret-for-unit-tests-only")

# Stub heavy optional dependencies before importing server
for mod in ("bcrypt", "razorpay"):
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)
        if mod == "bcrypt":
            sys.modules[mod].checkpw = lambda *a: True
            sys.modules[mod].hashpw = lambda p, s: p
            sys.modules[mod].gensalt = lambda: b"salt"
        if mod == "razorpay":
            class _Client:
                def __init__(self, auth=None): pass
            sys.modules[mod].Client = _Client

# Fake dotenv
import importlib
_dotenv = types.ModuleType("dotenv")
_dotenv.load_dotenv = lambda *a, **kw: None
sys.modules["dotenv"] = _dotenv

from api.server import app
from auth.jwt_utils import generate_access_token


def _token(plan="free"):
    return generate_access_token(user_id="1", email="test@test.com", plan=plan)


def _auth(plan="free"):
    return {"Authorization": f"Bearer {_token(plan)}"}


def _fake_report(run_id, strategy="S", ret=10.0, sharpe=1.0, dd=5.0, win=55.0, trades=20, commission=100.0):
    return {
        "metadata": {"run_id": run_id, "strategy_name": strategy, "start_date": "2022-01-01",
                     "end_date": "2023-12-31", "status": "COMPLETED",
                     "initial_capital": 100000, "final_equity": 110000, "market_universe": "AAPL"},
        "performance": {
            "total_return_pct": ret, "sharpe_ratio": sharpe, "max_drawdown_pct": dd,
            "win_rate_pct": win, "total_trades": trades, "total_commission_paid": commission,
            "buy_and_hold_return_pct": 8.0, "alpha_pct": ret - 8.0,
            "cagr_pct": ret * 0.6, "sortino_ratio": sharpe * 1.2, "profit_factor": 1.5,
            "time_in_market_pct": 60.0, "avg_trade_duration_days": 5.0,
            "gross_profit": 5000.0, "gross_loss": -2000.0, "net_pnl": 3000.0,
            "max_drawdown_duration_days": 30,
        },
        "equity_curve": [{"time": "2022-01-03", "equity": 100000, "cash": 100000, "margin": 0},
                         {"time": "2023-12-29", "equity": 110000, "cash": 110000, "margin": 0}],
        "trade_log": [],
        "rolling_metrics": {"windows": [30, 90, 252], "drawdown": [], "by_window": {}},
        "benchmark_ticker": "SPY",
        "benchmark_curve": [],
        "event_log": [],
    }


class TestCompareEndpoint(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def _mock_get_run_data(self, run_ids, reports):
        """Patch the per-run data fetching for the compare endpoint."""
        report_map = {rid: reports[i] for i, rid in enumerate(run_ids)}

        def fake_get_run(run_id):
            r = report_map.get(run_id)
            if r is None:
                return None
            return r

        return patch("api.server._get_compare_run_data", side_effect=fake_get_run)

    # ── AC: up to 5 runs can be compared simultaneously ─────────────────────
    def test_compare_two_runs(self):
        reports = [_fake_report("R1", ret=24.1, sharpe=1.42, dd=12.4, win=58.3, trades=47, commission=842),
                   _fake_report("R2", ret=18.3, sharpe=0.98, dd=8.1, win=62.1, trades=31, commission=612)]
        with self._mock_get_run_data(["R1", "R2"], reports):
            resp = self.client.get("/api/runs/compare?ids=R1,R2", headers=_auth())
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("runs", data)
        self.assertEqual(len(data["runs"]), 2)

    def test_compare_up_to_five_runs(self):
        ids = [f"R{i}" for i in range(1, 6)]
        reports = [_fake_report(rid, ret=float(10 + i)) for i, rid in enumerate(ids)]
        with self._mock_get_run_data(ids, reports):
            resp = self.client.get(f"/api/runs/compare?ids={','.join(ids)}", headers=_auth())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.get_json()["runs"]), 5)

    def test_compare_six_runs_rejected(self):
        ids = [f"R{i}" for i in range(1, 7)]
        resp = self.client.get(f"/api/runs/compare?ids={','.join(ids)}", headers=_auth())
        self.assertEqual(resp.status_code, 400)

    # ── AC: table highlights best value per metric ───────────────────────────
    def test_best_flags_in_response(self):
        reports = [_fake_report("R1", ret=24.1, sharpe=1.42, dd=12.4, win=58.3, trades=47, commission=842),
                   _fake_report("R2", ret=18.3, sharpe=0.98, dd=8.1, win=62.1, trades=31, commission=612)]
        with self._mock_get_run_data(["R1", "R2"], reports):
            resp = self.client.get("/api/runs/compare?ids=R1,R2", headers=_auth())
        data = resp.get_json()
        runs = {r["run_id"]: r for r in data["runs"]}
        # R1 has higher return → best_return
        self.assertTrue(runs["R1"]["best_metrics"]["total_return_pct"])
        self.assertFalse(runs["R2"]["best_metrics"]["total_return_pct"])
        # R2 has lower drawdown (8.1 < 12.4) → best drawdown
        self.assertTrue(runs["R2"]["best_metrics"]["max_drawdown_pct"])
        self.assertFalse(runs["R1"]["best_metrics"]["max_drawdown_pct"])
        # R1 has higher sharpe → best
        self.assertTrue(runs["R1"]["best_metrics"]["sharpe_ratio"])
        self.assertFalse(runs["R2"]["best_metrics"]["sharpe_ratio"])

    # ── AC: overlay chart — equity curves included ───────────────────────────
    def test_equity_curves_returned(self):
        reports = [_fake_report("R1"), _fake_report("R2")]
        with self._mock_get_run_data(["R1", "R2"], reports):
            resp = self.client.get("/api/runs/compare?ids=R1,R2", headers=_auth())
        runs = resp.get_json()["runs"]
        for r in runs:
            self.assertIn("equity_curve", r)
            self.assertGreater(len(r["equity_curve"]), 0)

    # ── AC: missing ids param → 400 ──────────────────────────────────────────
    def test_missing_ids(self):
        resp = self.client.get("/api/runs/compare", headers=_auth())
        self.assertEqual(resp.status_code, 400)

    # ── AC: auth required ────────────────────────────────────────────────────
    def test_requires_auth(self):
        resp = self.client.get("/api/runs/compare?ids=R1,R2")
        self.assertIn(resp.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main(verbosity=2)
