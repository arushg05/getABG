"""
getABG REST API Server
Flask-based API layer serving the React dashboard.
Endpoints for running backtests, fetching results, managing runs,
user authentication, and Razorpay payment integration.
"""

import os
import sys
import json
import uuid
import hmac
import hashlib
import threading
import traceback
import time
from collections import defaultdict
from functools import wraps
from datetime import datetime, timezone
from typing import Dict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Load .env before anything else
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from flask import Flask, request, jsonify, Response, g, make_response
from flask import send_from_directory

import bcrypt
import razorpay

from database.state_db import StateDB
from engine.backtest import BacktestEngine
from metrics.performance import build_performance_report
try:
    from api.strategy_generator import generate_strategy  # when run via gunicorn from project root
except ImportError:
    from strategy_generator import generate_strategy      # when run directly from api/
from engine.walk_forward import run_walk_forward


from auth.user_db import UserDB
from auth.jwt_utils import (
    generate_access_token,
    decode_access_token,
    generate_refresh_token,
    verify_refresh_token_hash,
    is_refresh_token_expired,
    ACCESS_TOKEN_EXPIRY_MINUTES,
)
from auth.middleware import require_auth, require_verified

app = Flask(__name__, static_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dashboard", "dist")), static_url_path="")

RUNS_DIR = os.path.join(os.path.dirname(__file__), "runs")
os.makedirs(RUNS_DIR, exist_ok=True)

MASTER_DB = StateDB(os.path.join(RUNS_DIR, "_master.db"))

# ── User database ────────────────────────────────────────────────────────────
USER_DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")
user_db = UserDB(USER_DB_PATH)

# ── Razorpay client ──────────────────────────────────────────────────────────
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_xxxx")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "xxxx")
RAZORPAY_PLAN_AMOUNT = int(os.environ.get("RAZORPAY_PLAN_AMOUNT", "159900"))  # paise

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# ── Freemium config ──────────────────────────────────────────────────────────
FREE_DAILY_BACKTEST_LIMIT = 3



# In-memory run status tracker
_active_runs: Dict[str, dict] = {}
_run_lock = threading.Lock()


def _get_run_db(run_id: str) -> StateDB:
    db_path = os.path.join(RUNS_DIR, f"{run_id}.db")
    return StateDB(db_path)


def _today_utc() -> str:
    """Current UTC date as YYYY-MM-DD."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── CORS ──────────────────────────────────────────────────────────────────────

ALLOWED_ORIGINS = [
    "http://localhost:5173",   # Vite dev server
    "http://localhost:5050",   # Production / Flask-served
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5050",
]

frontend_url = os.environ.get("FRONTEND_URL")
if frontend_url:
    ALLOWED_ORIGINS.append(frontend_url.rstrip("/"))

def cors(response):
    origin = request.headers.get("Origin", "")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
    # If origin not in allowlist, do NOT set Access-Control-Allow-Origin.
    # The browser will block the cross-origin request.

    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, DELETE"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


@app.after_request
def after_request(response):
    return cors(response)


# ── Cookie Helpers ────────────────────────────────────────────────────────────

def _set_auth_cookies(response, access_token: str, refresh_token: str, refresh_token_id: str):
    """Set httpOnly secure cookies for access and refresh tokens."""
    is_prod = os.environ.get("FLASK_ENV") == "production"
    samesite_policy = "None" if is_prod else "Lax"

    response.set_cookie(
        "access_token",
        access_token,
        httponly=True,
        secure=is_prod,
        samesite=samesite_policy,
        max_age=ACCESS_TOKEN_EXPIRY_MINUTES * 60,
        path="/",
    )
    response.set_cookie(
        "refresh_token",
        refresh_token,
        httponly=True,
        secure=is_prod,
        samesite=samesite_policy,
        max_age=30 * 24 * 3600,  # 30 days
        path="/api/auth",  # Only sent to auth endpoints
    )
    response.set_cookie(
        "refresh_token_id",
        refresh_token_id,
        httponly=True,
        secure=is_prod,
        samesite=samesite_policy,
        max_age=30 * 24 * 3600,
        path="/api/auth",
    )
    return response


def _clear_auth_cookies(response):
    """Clear all auth cookies."""
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/auth")
    response.delete_cookie("refresh_token_id", path="/api/auth")
    return response


@app.route("/api/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "version": "1.0.0", "engine": "getABG"})


# ── Rate Limiting ─────────────────────────────────────────────────────────────

_login_attempts = defaultdict(list)  # ip -> [timestamps]
LOGIN_RATE_LIMIT = 5   # max attempts per window
LOGIN_RATE_WINDOW = 300  # 5 minutes


def rate_limit_auth(f):
    """Rate-limit decorator for auth endpoints to prevent brute-force attacks."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == "OPTIONS":
            return f(*args, **kwargs)
        ip = request.remote_addr or "unknown"
        now = time.time()
        _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < LOGIN_RATE_WINDOW]
        if len(_login_attempts[ip]) >= LOGIN_RATE_LIMIT:
            return jsonify({
                "error": "Too many attempts. Please try again later.",
                "code": "RATE_LIMITED",
            }), 429
        _login_attempts[ip].append(now)
        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════════════════════════════════════════
# AUTH ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/auth/register", methods=["POST", "OPTIONS"])
@rate_limit_auth
def register():
    """Register a new user with email + password."""
    if request.method == "OPTIONS":
        return jsonify({}), 200

    data = request.json or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password", "")

    if not email or "@" not in email:
        return jsonify({"error": "Valid email is required"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    # Check if user already exists
    existing = user_db.get_user_by_email(email)
    if existing:
        return jsonify({"error": "An account with this email already exists"}), 409

    # Hash password and create user
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    try:
        user_id = user_db.create_user(email, password_hash)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409

    # Generate tokens
    access_token = generate_access_token(user_id, email, "free")
    token_id, raw_refresh, token_hash, expires_at = generate_refresh_token()
    user_db.store_refresh_token(token_id, user_id, token_hash, expires_at)

    # TODO: Send verification email in background (Resend/SMTP)
    # For now, users get instant access; sensitive actions gated by @require_verified

    resp = make_response(jsonify({
        "user_id": user_id,
        "email": email,
        "plan": "free",
        "verified": False,
        "message": "Account created successfully. A verification email will be sent shortly.",
    }), 201)

    return _set_auth_cookies(resp, access_token, raw_refresh, token_id)


@app.route("/api/auth/login", methods=["POST", "OPTIONS"])
@rate_limit_auth
def login():
    """Authenticate with email + password."""
    if request.method == "OPTIONS":
        return jsonify({}), 200

    data = request.json or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    user = user_db.get_user_by_email(email)
    if not user:
        return jsonify({"error": "Invalid email or password"}), 401

    if not bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        return jsonify({"error": "Invalid email or password"}), 401

    # Generate tokens
    access_token = generate_access_token(user["user_id"], email, user["plan"])
    token_id, raw_refresh, token_hash, expires_at = generate_refresh_token()
    user_db.store_refresh_token(token_id, user["user_id"], token_hash, expires_at)

    resp = make_response(jsonify({
        "user_id": user["user_id"],
        "email": email,
        "plan": user["plan"],
        "verified": bool(user["verified"]),
    }))

    return _set_auth_cookies(resp, access_token, raw_refresh, token_id)


@app.route("/api/auth/logout", methods=["POST", "OPTIONS"])
def logout():
    """Log out — revoke refresh token and clear cookies."""
    if request.method == "OPTIONS":
        return jsonify({}), 200

    token_id = request.cookies.get("refresh_token_id")
    if token_id:
        user_db.revoke_refresh_token(token_id)

    resp = make_response(jsonify({"message": "Logged out"}))
    return _clear_auth_cookies(resp)


@app.route("/api/auth/refresh", methods=["POST", "OPTIONS"])
def refresh():
    """Rotate access + refresh tokens using the refresh token cookie."""
    if request.method == "OPTIONS":
        return jsonify({}), 200

    token_id = request.cookies.get("refresh_token_id")
    raw_refresh = request.cookies.get("refresh_token")

    if not token_id or not raw_refresh:
        resp = make_response(jsonify({"error": "No refresh token", "code": "NO_REFRESH_TOKEN"}), 401)
        return _clear_auth_cookies(resp)

    stored = user_db.get_refresh_token(token_id)
    if not stored:
        resp = make_response(jsonify({"error": "Invalid refresh token", "code": "INVALID_REFRESH"}), 401)
        return _clear_auth_cookies(resp)

    if not verify_refresh_token_hash(raw_refresh, stored["token_hash"]):
        # Possible token theft — revoke all tokens for this user
        user_db.revoke_all_user_tokens(stored["user_id"])
        resp = make_response(jsonify({"error": "Token mismatch — all sessions revoked", "code": "TOKEN_THEFT"}), 401)
        return _clear_auth_cookies(resp)

    if is_refresh_token_expired(stored["expires_at"]):
        user_db.revoke_refresh_token(token_id)
        resp = make_response(jsonify({"error": "Refresh token expired", "code": "REFRESH_EXPIRED"}), 401)
        return _clear_auth_cookies(resp)

    # Revoke old token and issue new pair (rotation)
    user_db.revoke_refresh_token(token_id)

    user = user_db.get_user_by_id(stored["user_id"])
    if not user:
        resp = make_response(jsonify({"error": "User not found"}), 401)
        return _clear_auth_cookies(resp)

    new_access = generate_access_token(user["user_id"], user["email"], user["plan"])
    new_token_id, new_raw, new_hash, new_expires = generate_refresh_token()
    user_db.store_refresh_token(new_token_id, user["user_id"], new_hash, new_expires)

    resp = make_response(jsonify({
        "user_id": user["user_id"],
        "email": user["email"],
        "plan": user["plan"],
        "verified": bool(user["verified"]),
    }))

    return _set_auth_cookies(resp, new_access, new_raw, new_token_id)


@app.route("/api/auth/me", methods=["GET"])
@require_auth
def me():
    """Get current user info + today's usage."""
    user = user_db.get_user_by_id(g.user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    usage_today = user_db.get_daily_usage(g.user_id, _today_utc())

    return jsonify({
        "user_id": user["user_id"],
        "email": user["email"],
        "plan": user["plan"],
        "verified": bool(user["verified"]),
        "usage_today": usage_today,
        "daily_limit": FREE_DAILY_BACKTEST_LIMIT if user["plan"] == "free" else None,
    })


# ══════════════════════════════════════════════════════════════════════════════
# PAYMENT ENDPOINTS (Razorpay)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/payments/create-order", methods=["POST", "OPTIONS"])
@require_auth
def create_payment_order():
    """Create a Razorpay order for the Pro plan upgrade."""
    if request.method == "OPTIONS":
        return jsonify({}), 200

    # Only verified users can purchase
    user = user_db.get_user_by_id(g.user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    if user["plan"] == "pro":
        return jsonify({"error": "Already on Pro plan"}), 400

    try:
        order = razorpay_client.order.create({
            "amount": RAZORPAY_PLAN_AMOUNT,
            "currency": "INR",
            "receipt": f"getabg_{g.user_id[:8]}_{_today_utc()}",
            "notes": {
                "user_id": g.user_id,
                "email": g.email,
                "plan": "pro",
            },
        })
        return jsonify({
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "key_id": RAZORPAY_KEY_ID,
        })
    except Exception as e:
        return jsonify({"error": f"Failed to create order: {str(e)}"}), 500


@app.route("/api/payments/verify", methods=["POST", "OPTIONS"])
@require_auth
def verify_payment():
    """
    Verify a Razorpay payment after checkout completion.
    Client sends: razorpay_order_id, razorpay_payment_id, razorpay_signature
    """
    if request.method == "OPTIONS":
        return jsonify({}), 200

    data = request.json or {}
    order_id = data.get("razorpay_order_id")
    payment_id = data.get("razorpay_payment_id")
    signature = data.get("razorpay_signature")

    if not all([order_id, payment_id, signature]):
        return jsonify({"error": "Missing payment verification fields"}), 400

    # Verify signature
    try:
        razorpay_client.utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        })
    except razorpay.errors.SignatureVerificationError:
        return jsonify({"error": "Payment signature verification failed"}), 400

    # Upgrade user to Pro
    user_db.set_plan(g.user_id, "pro", subscription_id=payment_id)

    # Issue new access token with updated plan
    user = user_db.get_user_by_id(g.user_id)
    new_access = generate_access_token(user["user_id"], user["email"], "pro")

    resp = make_response(jsonify({
        "message": "Payment verified! You're now on the Pro plan.",
        "plan": "pro",
    }))

    is_prod = os.environ.get("FLASK_ENV") == "production"
    samesite_policy = "None" if is_prod else "Lax"

    resp.set_cookie(
        "access_token",
        new_access,
        httponly=True,
        secure=is_prod,
        samesite=samesite_policy,
        max_age=ACCESS_TOKEN_EXPIRY_MINUTES * 60,
        path="/",
    )

    return resp


@app.route("/api/payments/webhook", methods=["POST"])
def razorpay_webhook():
    """
    Razorpay webhook for async payment events.
    Verifies webhook signature and upgrades user on successful payment.
    """
    webhook_secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET")
    if not webhook_secret:
        print("[getABG] WARNING: RAZORPAY_WEBHOOK_SECRET not configured. Rejecting webhook.")
        return jsonify({"error": "Webhook secret not configured"}), 500

    webhook_signature = request.headers.get("X-Razorpay-Signature", "")
    webhook_body = request.get_data(as_text=True)

    # Verify webhook signature
    expected = hmac.new(  # noqa: deprecated but safe here; key/msg/digestmod are all provided
        webhook_secret.encode("utf-8"),
        webhook_body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, webhook_signature):
        return jsonify({"error": "Invalid webhook signature"}), 400

    payload = request.json or {}
    event = payload.get("event", "")

    if event == "payment.captured":
        payment = payload.get("payload", {}).get("payment", {}).get("entity", {})
        notes = payment.get("notes", {})
        user_id = notes.get("user_id")

        if user_id:
            # Validate user exists and payment amount matches expected plan amount
            user = user_db.get_user_by_id(user_id)
            if not user:
                print(f"[getABG] Webhook: Unknown user_id '{user_id}' in payment notes. Ignoring.")
            elif user["plan"] == "pro":
                print(f"[getABG] Webhook: User {user_id} already on Pro. Ignoring duplicate.")
            elif payment.get("amount") != RAZORPAY_PLAN_AMOUNT:
                print(f"[getABG] Webhook: Payment amount mismatch for user {user_id}: "
                      f"expected {RAZORPAY_PLAN_AMOUNT}, got {payment.get('amount')}. Ignoring.")
            else:
                user_db.set_plan(user_id, "pro", subscription_id=payment.get("id"))
                print(f"[getABG] Webhook: User {user_id} upgraded to Pro via payment {payment.get('id')}")

    return jsonify({"status": "ok"}), 200


# ── Admin endpoints (secure) ──────────────────────────────────────────────────
@app.route("/api/admin/upgrade", methods=["POST", "OPTIONS"])
def admin_upgrade():
    """Admin API to set a user's plan. Protect with ADMIN_API_KEY env var."""
    if request.method == "OPTIONS":
        return jsonify({}), 200

    admin_key = os.environ.get("ADMIN_API_KEY")
    provided = request.headers.get("X-Admin-Token") or request.args.get("admin_token")
    if not admin_key or not provided or not hmac.compare_digest(admin_key, provided):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json or {}
    email = (data.get("email") or "").strip().lower()
    user_id = data.get("user_id")
    plan = data.get("plan", "pro")
    subscription_id = data.get("subscription_id")

    if not email and not user_id:
        return jsonify({"error": "email or user_id is required"}), 400

    if email:
        user = user_db.get_user_by_email(email)
        if not user:
            return jsonify({"error": "User not found"}), 404
        user_id = user["user_id"]

    user_db.set_plan(user_id, plan, subscription_id)
    return jsonify({"message": f"User {user_id} upgraded to {plan}"}), 200


@app.route("/api/admin/users", methods=["GET", "OPTIONS"])
def admin_list_users():
    """Admin API to list all users. Uses ADMIN_API_KEY for protection."""
    if request.method == "OPTIONS":
        return jsonify({}), 200

    admin_key = os.environ.get("ADMIN_API_KEY")
    provided = request.headers.get("X-Admin-Token") or request.args.get("admin_token")
    if not admin_key or not provided or not hmac.compare_digest(admin_key, provided):
        return jsonify({"error": "Unauthorized"}), 401

    users = user_db._fetch_all(
        "SELECT user_id, email, plan, verified, created_at FROM Users ORDER BY created_at DESC"
    )
    for u in users:
        u["verified"] = bool(u["verified"])

    return jsonify({"users": users}), 200


# ══════════════════════════════════════════════════════════════════════════════
# RUN MANAGEMENT (unchanged logic, now with auth context)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/runs", methods=["GET"])
@require_auth
def list_runs():
    """List all backtest runs from master registry."""
    try:
        # Group database files by parent run ID
        groups = {}
        for fname in os.listdir(RUNS_DIR):
            if not fname.endswith(".db") or fname.startswith("_"):
                continue
            name = fname.replace(".db", "")
            if "_" in name:
                parts = name.split("_")
                parent_id = parts[0]
                ticker = parts[1]
                groups.setdefault(parent_id, []).append((ticker, name))
            else:
                groups.setdefault(name, []).append((None, name))

        runs = []
        for parent_id, db_files in groups.items():
            first_ticker, first_db_name = db_files[0]
            db = _get_run_db(first_db_name)
            run = db.get_run(first_db_name)
            if run:
                tickers = []
                for t, db_name in db_files:
                    if t:
                        tickers.append(t)
                    else:
                        try:
                            tickers.extend(json.loads(run["Market_Universe"]))
                        except Exception:
                            if run["Market_Universe"]:
                                tickers.append(run["Market_Universe"])
                
                status = "COMPLETED"
                for t, db_name in db_files:
                    sub_db = _get_run_db(db_name)
                    sub_run = sub_db.get_run(db_name)
                    if sub_run and sub_run["Status"] != "COMPLETED":
                        status = sub_run["Status"]

                runs.append({
                    "run_id": parent_id,
                    "strategy_name": run["Strategy_Name"],
                    "status": status,
                    "start_date": run["Start_Timestamp"][:10] if run["Start_Timestamp"] else None,
                    "end_date": run["End_Timestamp"][:10] if run["End_Timestamp"] else None,
                    "initial_capital": run["Initial_Capital"],
                    "market_universe": list(set(tickers)),
                })
        runs.sort(key=lambda r: r.get("start_date") or "", reverse=True)
        return jsonify({"runs": runs, "count": len(runs)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _get_compare_run_data(run_id: str):
    """Return the performance report for one run_id, or None if not found.
    Handles both single-ticker and multi-ticker (aggregated first ticker) runs."""
    subruns = [
        fname.replace(".db", "")
        for fname in os.listdir(RUNS_DIR)
        if fname.startswith(f"{run_id}_") and fname.endswith(".db")
    ]
    if subruns:
        subrun_id = subruns[0]
        db = _get_run_db(subrun_id)
        run_meta = db.get_run(subrun_id)
        if not run_meta:
            return None
        snapshots = db.get_snapshots(subrun_id)
        trades = db.get_trades(subrun_id)
        events = db.get_events(subrun_id)
        return build_performance_report(run_meta, snapshots, trades, events)

    db = _get_run_db(run_id)
    run_meta = db.get_run(run_id)
    if not run_meta:
        return None
    snapshots = db.get_snapshots(run_id)
    trades = db.get_trades(run_id)
    events = db.get_events(run_id)
    return build_performance_report(run_meta, snapshots, trades, events)


_COMPARE_METRICS = [
    ("total_return_pct", True),    # higher is better
    ("sharpe_ratio", True),
    ("max_drawdown_pct", False),   # lower (less negative) is better
    ("win_rate_pct", True),
    ("total_trades", None),        # neutral — no best/worst highlight
    ("total_commission_paid", False),
]


@app.route("/api/runs/compare", methods=["GET", "OPTIONS"])
@require_auth
def compare_runs():
    """Return performance summaries + equity curves for up to 5 runs."""
    if request.method == "OPTIONS":
        return jsonify({}), 200
    try:
        ids_param = request.args.get("ids", "").strip()
        if not ids_param:
            return jsonify({"error": "ids query parameter is required"}), 400
        run_ids = [rid.strip() for rid in ids_param.split(",") if rid.strip()]
        if len(run_ids) < 2:
            return jsonify({"error": "At least 2 run IDs are required"}), 400
        if len(run_ids) > 5:
            return jsonify({"error": "At most 5 runs can be compared"}), 400

        results = []
        for rid in run_ids:
            report = _get_compare_run_data(rid)
            if report is None:
                return jsonify({"error": f"Run {rid} not found"}), 404
            results.append((rid, report))

        # Compute best-value flags per metric
        def _best_flags(metric, higher_is_better):
            vals = [(rid, r["performance"].get(metric)) for rid, r in results]
            vals = [(rid, v) for rid, v in vals if v is not None]
            if not vals:
                return {}
            best_rid = max(vals, key=lambda x: x[1])[0] if higher_is_better else min(vals, key=lambda x: x[1])[0]
            return {rid: (rid == best_rid) for rid, _ in vals}

        best_by_metric = {}
        for metric, higher_is_better in _COMPARE_METRICS:
            if higher_is_better is None:
                continue
            best_by_metric[metric] = _best_flags(metric, higher_is_better)

        runs_out = []
        for rid, report in results:
            p = report["performance"]
            best_metrics = {metric: best_by_metric.get(metric, {}).get(rid, False)
                            for metric, _ in _COMPARE_METRICS if _ is not None}
            runs_out.append({
                "run_id": rid,
                "strategy_name": report["metadata"].get("strategy_name", ""),
                "start_date": report["metadata"].get("start_date", ""),
                "end_date": report["metadata"].get("end_date", ""),
                "initial_capital": report["metadata"].get("initial_capital", 100000),
                "performance": {k: p.get(k) for k, _ in _COMPARE_METRICS},
                "best_metrics": best_metrics,
                "equity_curve": report.get("equity_curve", []),
            })

        return jsonify({"runs": runs_out, "count": len(runs_out)})
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/runs/<run_id>", methods=["GET"])
@require_auth
def get_run(run_id: str):
    """Get full telemetry report for a specific run."""
    try:
        subruns = []
        for fname in os.listdir(RUNS_DIR):
            if fname.startswith(f"{run_id}_") and fname.endswith(".db"):
                subruns.append(fname.replace(".db", ""))
        
        if not subruns:
            db = _get_run_db(run_id)
            run_meta = db.get_run(run_id)
            if not run_meta:
                return jsonify({"error": f"Run {run_id} not found"}), 404

            snapshots = db.get_snapshots(run_id)
            trades = db.get_trades(run_id)
            events = db.get_events(run_id)
            report = build_performance_report(run_meta, snapshots, trades, events)
            return jsonify(report)

        results = {}
        for subrun_id in subruns:
            ticker = subrun_id.split("_")[1]
            db = _get_run_db(subrun_id)
            run_meta = db.get_run(subrun_id)
            if run_meta:
                snapshots = db.get_snapshots(subrun_id)
                trades = db.get_trades(subrun_id)
                events = db.get_events(subrun_id)
                report = build_performance_report(run_meta, snapshots, trades, events)
                results[ticker] = report
        
        first_subrun = subruns[0]
        db = _get_run_db(first_subrun)
        run_meta = db.get_run(first_subrun)
        
        return jsonify({
            "run_id": run_id,
            "is_multi": True,
            "strategy_name": run_meta["Strategy_Name"],
            "start_date": run_meta["Start_Timestamp"][:10] if run_meta["Start_Timestamp"] else None,
            "end_date": run_meta["End_Timestamp"][:10] if run_meta["End_Timestamp"] else None,
            "initial_capital": run_meta["Initial_Capital"],
            "tickers": list(results.keys()),
            "results": results
        })
    except Exception as e:
        traceback.print_exc()  # Log server-side only
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/runs/<run_id>/status", methods=["GET"])
@require_auth
def run_status(run_id: str):
    """Quick status check for a running or completed backtest."""
    with _run_lock:
        if run_id in _active_runs:
            return jsonify(_active_runs[run_id])

    try:
        subruns = []
        for fname in os.listdir(RUNS_DIR):
            if fname.startswith(f"{run_id}_") and fname.endswith(".db"):
                subruns.append(fname.replace(".db", ""))

        if not subruns:
            db = _get_run_db(run_id)
            run_meta = db.get_run(run_id)
            if not run_meta:
                return jsonify({"status": "NOT_FOUND"}), 404
            snapshots = db.get_snapshots(run_id)
            trades = db.get_trades(run_id)
            return jsonify({
                "run_id": run_id,
                "status": run_meta["Status"],
                "snapshots_count": len(snapshots),
                "trades_count": len(trades),
            })

        all_completed = True
        any_failed = False
        snapshots_count = 0
        trades_count = 0
        
        for subrun_id in subruns:
            db = _get_run_db(subrun_id)
            run_meta = db.get_run(subrun_id)
            if run_meta:
                if run_meta["Status"] != "COMPLETED":
                    all_completed = False
                if run_meta["Status"] == "FAILED":
                    any_failed = True
                snapshots_count += len(db.get_snapshots(subrun_id))
                trades_count += len(db.get_trades(subrun_id))

        status = "COMPLETED" if all_completed else ("FAILED" if any_failed else "RUNNING")
        return jsonify({
            "run_id": run_id,
            "status": status,
            "snapshots_count": snapshots_count,
            "trades_count": trades_count,
            "tickers_count": len(subruns)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Backtest Execution ────────────────────────────────────────────────────────

def _run_backtest_thread(
    run_id: str, strategy_path: str, tickers: list, start: str, end: str,
    capital: float, timeout_ms: int,
    commission_model: dict = None, lot_sizes: dict = None, benchmark_ticker: str = "SPY",
):
    """Background thread for non-blocking backtest execution."""
    with _run_lock:
        _active_runs[run_id] = {
            "run_id": run_id,
            "status": "RUNNING",
            "progress": 0,
            "tickers": tickers,
            "completed_tickers": {},
            "failed_tickers": {}
        }

    try:
        results = {}
        for i, ticker in enumerate(tickers):
            try:
                subrun_id = f"{run_id}_{ticker}"
                db_path = os.path.join(RUNS_DIR, f"{subrun_id}.db")
                engine = BacktestEngine(
                    strategy_path=strategy_path,
                    tickers=[ticker],
                    start_date=start,
                    end_date=end,
                    initial_capital=capital,
                    db_path=db_path,
                    timeout_ms=timeout_ms,
                    verbose=True,
                    commission_model=commission_model,
                    lot_sizes=lot_sizes,
                    benchmark_ticker=benchmark_ticker,
                )
                engine.run_id = subrun_id
                report = engine.run()
                results[ticker] = report["performance"]
                with _run_lock:
                    _active_runs[run_id]["completed_tickers"][ticker] = report["performance"]
            except Exception as ex:
                with _run_lock:
                    _active_runs[run_id]["failed_tickers"][ticker] = str(ex)
            
            with _run_lock:
                progress = int((i + 1) / len(tickers) * 100)
                _active_runs[run_id]["progress"] = progress

        with _run_lock:
            completed = _active_runs[run_id]["completed_tickers"]
            failed = _active_runs[run_id]["failed_tickers"]
            if not completed:
                raise ValueError(f"All backtest runs failed. Errors: {failed}")
            
            _active_runs[run_id] = {
                "run_id": run_id,
                "status": "COMPLETED",
                "progress": 100,
                "summary": completed,
            }
    except Exception as e:
        with _run_lock:
            _active_runs[run_id] = {
                "run_id": run_id,
                "status": "FAILED",
                "error": str(e),
                "traceback": traceback.format_exc(),
            }
    finally:
        if strategy_path.startswith(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sandbox"))):
            try:
                if os.path.exists(strategy_path):
                    os.remove(strategy_path)
            except Exception:
                pass

        # Auto-prune _active_runs after 10 minutes to prevent memory leak
        def _prune_run():
            time.sleep(600)
            with _run_lock:
                _active_runs.pop(run_id, None)
        threading.Thread(target=_prune_run, daemon=True).start()



@app.route("/api/backtest/run", methods=["POST", "OPTIONS"])
@require_auth
def start_backtest():
    """
    Start a new backtest run (async).
    Enforces daily quota for free-tier users.
    Body:
        strategy: 'ma_crossover' | 'rsi_reversion' | path to custom .py
        tickers: ['AAPL', 'MSFT', ...]
        start_date: 'YYYY-MM-DD'
        end_date: 'YYYY-MM-DD'
        initial_capital: float
        timeout_ms: int (optional, default 5000)
    """
    if request.method == "OPTIONS":
        return jsonify({}), 200

    # ── Quota enforcement for free-tier (atomic check-and-increment) ──
    if g.plan == "free":
        today = _today_utc()
        if not user_db.try_increment_usage(g.user_id, today, FREE_DAILY_BACKTEST_LIMIT):
            usage = user_db.get_daily_usage(g.user_id, today)
            return jsonify({
                "error": "Daily backtest limit reached (3/3). Upgrade to Pro for unlimited backtests.",
                "code": "QUOTA_EXCEEDED",
                "usage": usage,
                "limit": FREE_DAILY_BACKTEST_LIMIT,
            }), 429

    data = request.json or {}
    code = data.get("code", "")
    tickers = data.get("tickers", ["AAPL", "MSFT"])
    start = data.get("start_date", "2022-01-01")
    end = data.get("end_date", "2023-12-31")
    capital = float(data.get("initial_capital", 100_000))
    timeout_ms = int(data.get("timeout_ms", 5000))

    # Commission model: {"type": "flat"|"per_share"|"pct", "value": float}
    commission_model = data.get("commission_model") or {}
    # Lot sizes: {"TICKER": lot_size_int, ...}
    lot_sizes = data.get("lot_sizes") or {}
    # Benchmark ticker for overlay (default SPY; use NIFTY50.NS for Indian strategies)
    benchmark_ticker = data.get("benchmark_ticker", "SPY")

    if not code.strip():
        return jsonify({"error": "Strategy code is required"}), 400

    # Validate commission_model shape
    if commission_model:
        if commission_model.get("type") not in ("flat", "per_share", "pct"):
            return jsonify({"error": "commission_model.type must be 'flat', 'per_share', or 'pct'"}), 400
        try:
            float(commission_model["value"])
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "commission_model.value must be a number"}), 400

    run_id = str(uuid.uuid4())[:12].upper()

    sandbox_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sandbox"))
    os.makedirs(sandbox_dir, exist_ok=True)
    strategy_path = os.path.join(sandbox_dir, f"temp_{run_id}.py")
    with open(strategy_path, "w", encoding="utf-8") as f:
        f.write(code)

    thread = threading.Thread(
        target=_run_backtest_thread,
        args=(run_id, strategy_path, tickers, start, end, capital, timeout_ms),
        kwargs={"commission_model": commission_model, "lot_sizes": lot_sizes, "benchmark_ticker": benchmark_ticker},
        daemon=True,
    )
    thread.start()

    return jsonify({
        "run_id": run_id,
        "status": "STARTED",
        "message": f"Backtest {run_id} started. Poll /api/runs/{run_id}/status for updates.",
    }), 202





@app.route("/api/backtest/walk-forward", methods=["POST", "OPTIONS"])
@require_auth
def start_walk_forward():
    """
    Run a walk-forward optimization (synchronous — runs in foreground).
    Body: same as /api/backtest/run, plus:
      n_splits:  int  (default 3)
      oos_ratio: float (default 0.3)
    Returns the full walk-forward result immediately.
    """
    if request.method == "OPTIONS":
        return jsonify({}), 200

    if g.plan == "free":
        return jsonify({
            "error": "Walk-forward optimization requires a Pro plan.",
            "code": "PRO_REQUIRED",
        }), 403

    data = request.json or {}
    code = data.get("code", "")
    tickers = data.get("tickers", ["AAPL"])
    start = data.get("start_date", "2020-01-01")
    end = data.get("end_date", "2023-12-31")
    capital = float(data.get("initial_capital", 100_000))
    timeout_ms = int(data.get("timeout_ms", 5000))
    commission_model = data.get("commission_model") or {}
    lot_sizes = data.get("lot_sizes") or {}
    benchmark_ticker = data.get("benchmark_ticker", "SPY")
    n_splits = min(int(data.get("n_splits", 3)), 6)
    oos_ratio = max(0.1, min(float(data.get("oos_ratio", 0.3)), 0.5))

    if not code.strip():
        return jsonify({"error": "Strategy code is required"}), 400

    run_id = str(uuid.uuid4())[:12].upper()
    sandbox_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sandbox"))
    os.makedirs(sandbox_dir, exist_ok=True)
    strategy_path = os.path.join(sandbox_dir, f"temp_wf_{run_id}.py")
    with open(strategy_path, "w", encoding="utf-8") as f:
        f.write(code)

    try:
        result = run_walk_forward(
            strategy_path=strategy_path,
            tickers=tickers,
            start_date=start,
            end_date=end,
            initial_capital=capital,
            n_splits=n_splits,
            oos_ratio=oos_ratio,
            commission_model=commission_model,
            lot_sizes=lot_sizes,
            benchmark_ticker=benchmark_ticker,
            timeout_ms=timeout_ms,
            verbose=False,
        )
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            if os.path.exists(strategy_path):
                os.remove(strategy_path)
        except Exception:
            pass


@app.route("/api/strategy/generate", methods=["POST", "OPTIONS"])
@require_auth
def strategy_generate():
    """
    Generate a Strategy class from a plain-English description using Claude.
    Body: { "description": str, "model": str (optional) }
    Returns: { "code": str } or { "error": str }
    """
    if request.method == "OPTIONS":
        return jsonify({}), 200

    data = request.json or {}
    description = (data.get("description") or "").strip()
    if not description:
        return jsonify({"error": "description is required"}), 400
    if len(description) > 2000:
        return jsonify({"error": "description too long (max 2000 chars)"}), 400

    model = data.get("model", "claude-haiku-4-5-20251001")
    result = generate_strategy(description, model=model)

    if result["error"]:
        return jsonify({"error": result["error"]}), 500
    return jsonify({"code": result["code"]})


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"getABG API Server starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
