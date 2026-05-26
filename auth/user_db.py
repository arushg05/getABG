"""
getABG Auth — User Database Layer
SQLite-backed user store with plan management and daily usage tracking.
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

USER_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS Users (
    user_id                  TEXT PRIMARY KEY,
    email                    TEXT UNIQUE NOT NULL,
    password_hash            TEXT NOT NULL,
    plan                     TEXT DEFAULT 'free',
    razorpay_subscription_id TEXT,
    created_at               TEXT NOT NULL,
    verified                 INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS Backtest_Usage (
    user_id  TEXT NOT NULL,
    date     TEXT NOT NULL,
    count    INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, date)
);

CREATE TABLE IF NOT EXISTS Refresh_Tokens (
    token_id   TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked    INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES Users(user_id)
);
"""


class UserDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_schema()

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self):
        conn = self._conn()
        conn.executescript(USER_SCHEMA_SQL)
        conn.close()

    def _exec(self, sql, params=None):
        conn = self._conn()
        try:
            cur = conn.execute(sql, params or [])
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def _fetch_one(self, sql, params=None) -> Optional[Dict]:
        conn = self._conn()
        try:
            row = conn.execute(sql, params or []).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def _fetch_all(self, sql, params=None):
        conn = self._conn()
        try:
            return [dict(r) for r in conn.execute(sql, params or []).fetchall()]
        finally:
            conn.close()

    # ── User CRUD ─────────────────────────────────────────────────────────────

    def create_user(self, email: str, password_hash: str) -> str:
        """Create a new user. Returns user_id."""
        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self._exec(
            "INSERT INTO Users (user_id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (user_id, email.lower().strip(), password_hash, now),
        )
        return user_id

    def get_user_by_email(self, email: str) -> Optional[Dict]:
        return self._fetch_one(
            "SELECT * FROM Users WHERE email = ?", (email.lower().strip(),)
        )

    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        return self._fetch_one("SELECT * FROM Users WHERE user_id = ?", (user_id,))

    def set_verified(self, user_id: str):
        self._exec("UPDATE Users SET verified = 1 WHERE user_id = ?", (user_id,))

    def set_plan(self, user_id: str, plan: str, subscription_id: str = None):
        self._exec(
            "UPDATE Users SET plan = ?, razorpay_subscription_id = ? WHERE user_id = ?",
            (plan, subscription_id, user_id),
        )

    # ── Daily Usage Tracking ──────────────────────────────────────────────────

    def get_daily_usage(self, user_id: str, date: str) -> int:
        """Get backtest count for a user on a given date (YYYY-MM-DD)."""
        row = self._fetch_one(
            "SELECT count FROM Backtest_Usage WHERE user_id = ? AND date = ?",
            (user_id, date),
        )
        return row["count"] if row else 0

    def increment_usage(self, user_id: str, date: str):
        """Atomically increment the daily usage counter."""
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO Backtest_Usage (user_id, date, count) VALUES (?, ?, 1)
                   ON CONFLICT(user_id, date) DO UPDATE SET count = count + 1""",
                (user_id, date),
            )
            conn.commit()
        finally:
            conn.close()

    def try_increment_usage(self, user_id: str, date: str, limit: int) -> bool:
        """
        Atomically check-and-increment the daily usage counter.
        Returns True if usage was incremented (under limit), False if at/over limit.
        Uses BEGIN IMMEDIATE to prevent TOCTOU race conditions.
        """
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT count FROM Backtest_Usage WHERE user_id = ? AND date = ?",
                (user_id, date),
            ).fetchone()
            current = row["count"] if row else 0
            if current >= limit:
                conn.rollback()
                return False
            conn.execute(
                """INSERT INTO Backtest_Usage (user_id, date, count) VALUES (?, ?, 1)
                   ON CONFLICT(user_id, date) DO UPDATE SET count = count + 1""",
                (user_id, date),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Refresh Tokens ────────────────────────────────────────────────────────

    def store_refresh_token(self, token_id: str, user_id: str, token_hash: str, expires_at: str):
        now = datetime.now(timezone.utc).isoformat()
        self._exec(
            "INSERT INTO Refresh_Tokens (token_id, user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (token_id, user_id, token_hash, expires_at, now),
        )

    def get_refresh_token(self, token_id: str) -> Optional[Dict]:
        return self._fetch_one(
            "SELECT * FROM Refresh_Tokens WHERE token_id = ? AND revoked = 0",
            (token_id,),
        )

    def revoke_refresh_token(self, token_id: str):
        self._exec("UPDATE Refresh_Tokens SET revoked = 1 WHERE token_id = ?", (token_id,))

    def revoke_all_user_tokens(self, user_id: str):
        self._exec("UPDATE Refresh_Tokens SET revoked = 1 WHERE user_id = ?", (user_id,))
