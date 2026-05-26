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
    else:
        # If origin not explicitly allowed, default to the first one (or allow wildcard for dev)
        response.headers["Access-Control-Allow-Origin"] = origin if origin else ALLOWED_ORIGINS[0]
    
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


# ══════════════════════════════════════════════════════════════════════════════
# AUTH ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/auth/register", methods=["POST", "OPTIONS"])
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
    user_id = user_db.create_user(email, password_hash)

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
    webhook_secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", RAZORPAY_KEY_SECRET)
    webhook_signature = request.headers.get("X-Razorpay-Signature", "")
    webhook_body = request.get_data(as_text=True)

    # Verify webhook signature
    expected = hmac.new(
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
            user_db.set_plan(user_id, "pro", subscription_id=payment.get("id"))
            print(f"[getABG] Webhook: User {user_id} upgraded to Pro via payment {payment.get('id')}")

    return jsonify({"status": "ok"}), 200


# ══════════════════════════════════════════════════════════════════════════════
# RUN MANAGEMENT (unchanged logic, now with auth context)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/runs", methods=["GET"])
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


@app.route("/api/runs/<run_id>", methods=["GET"])
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
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@app.route("/api/runs/<run_id>/status", methods=["GET"])
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
    capital: float, timeout_ms: int
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

    # ── Quota enforcement for free-tier ──
    if g.plan == "free":
        today = _today_utc()
        usage = user_db.get_daily_usage(g.user_id, today)
        if usage >= FREE_DAILY_BACKTEST_LIMIT:
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

    if not code.strip():
        return jsonify({"error": "Strategy code is required"}), 400

    run_id = str(uuid.uuid4())[:12].upper()

    sandbox_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sandbox"))
    os.makedirs(sandbox_dir, exist_ok=True)
    strategy_path = os.path.join(sandbox_dir, f"temp_{run_id}.py")
    with open(strategy_path, "w", encoding="utf-8") as f:
        f.write(code)

    # Increment usage AFTER validation passes (before thread starts)
    if g.plan == "free":
        user_db.increment_usage(g.user_id, _today_utc())

    thread = threading.Thread(
        target=_run_backtest_thread,
        args=(run_id, strategy_path, tickers, start, end, capital, timeout_ms),
        daemon=True,
    )
    thread.start()

    return jsonify({
        "run_id": run_id,
        "status": "STARTED",
        "message": f"Backtest {run_id} started. Poll /api/runs/{run_id}/status for updates.",
    }), 202





@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    print("getABG API Server starting on http://localhost:5050")
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)
