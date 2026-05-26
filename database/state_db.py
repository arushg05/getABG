"""
getABG Database Layer - SQLite state-machine logger
"""

import sqlite3
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS Run_Metadata (
    Run_ID          TEXT PRIMARY KEY,
    Strategy_Name   TEXT NOT NULL,
    Start_Timestamp TEXT NOT NULL,
    End_Timestamp   TEXT,
    Initial_Capital REAL NOT NULL,
    Market_Universe TEXT NOT NULL,
    Status          TEXT DEFAULT 'RUNNING',
    Parameters      TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS Execution_Events (
    Event_ID        INTEGER PRIMARY KEY AUTOINCREMENT,
    Run_ID          TEXT NOT NULL,
    Simulation_Time TEXT NOT NULL,
    Event_Type      TEXT NOT NULL,
    Ticker          TEXT,
    Direction       TEXT,
    Quantity        REAL,
    Price           REAL,
    Slippage        REAL DEFAULT 0.0,
    Notes           TEXT
);

CREATE TABLE IF NOT EXISTS Portfolio_Snapshots (
    Snapshot_ID         INTEGER PRIMARY KEY AUTOINCREMENT,
    Run_ID              TEXT NOT NULL,
    Simulation_Time     TEXT NOT NULL,
    Available_Cash      REAL NOT NULL,
    Allocated_Margin    REAL NOT NULL,
    Total_Equity_Value  REAL NOT NULL,
    Open_Positions      TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS Trade_Log (
    Trade_ID        INTEGER PRIMARY KEY AUTOINCREMENT,
    Run_ID          TEXT NOT NULL,
    Ticker          TEXT NOT NULL,
    Direction       TEXT NOT NULL,
    Entry_Time      TEXT NOT NULL,
    Exit_Time       TEXT,
    Entry_Price     REAL NOT NULL,
    Exit_Price      REAL,
    Quantity        REAL NOT NULL,
    Slippage_In     REAL DEFAULT 0.0,
    Slippage_Out    REAL DEFAULT 0.0,
    Gross_PnL       REAL,
    Net_PnL         REAL,
    Status          TEXT DEFAULT 'OPEN'
);
"""


class StateDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_schema()

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        conn = self._conn()
        conn.executescript(SCHEMA_SQL)
        conn.close()

    def _exec(self, sql, params=None):
        conn = self._conn()
        try:
            cur = conn.execute(sql, params or [])
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def _fetch(self, sql, params=None):
        conn = self._conn()
        try:
            return [dict(r) for r in conn.execute(sql, params or []).fetchall()]
        finally:
            conn.close()

    def create_run(self, run_id, strategy_name, initial_capital, tickers, parameters=None):
        self._exec(
            "INSERT INTO Run_Metadata (Run_ID,Strategy_Name,Start_Timestamp,Initial_Capital,Market_Universe,Parameters) VALUES (?,?,?,?,?,?)",
            (run_id, strategy_name, datetime.now(timezone.utc).isoformat(), initial_capital, json.dumps(tickers), json.dumps(parameters or {}))
        )
        return run_id

    def finalize_run(self, run_id, status="COMPLETED", metrics=None):
        if metrics is None:
            metrics = {}
        rows = self._fetch("SELECT Parameters FROM Run_Metadata WHERE Run_ID=?", (run_id,))
        if rows:
            try:
                params = json.loads(rows[0]["Parameters"] or "{}")
            except Exception:
                params = {}
            params.update(metrics)
            self._exec("UPDATE Run_Metadata SET End_Timestamp=?, Status=?, Parameters=? WHERE Run_ID=?",
                       (datetime.now(timezone.utc).isoformat(), status, json.dumps(params), run_id))
        else:
            self._exec("UPDATE Run_Metadata SET End_Timestamp=?, Status=? WHERE Run_ID=?",
                       (datetime.now(timezone.utc).isoformat(), status, run_id))

    def get_run(self, run_id):
        rows = self._fetch("SELECT * FROM Run_Metadata WHERE Run_ID=?", (run_id,))
        return rows[0] if rows else None

    def list_runs(self):
        return self._fetch("SELECT * FROM Run_Metadata ORDER BY Start_Timestamp DESC")

    def log_event(self, run_id, sim_time, event_type, ticker=None, direction=None,
                  quantity=None, price=None, slippage=0.0, notes=None):
        self._exec(
            "INSERT INTO Execution_Events (Run_ID,Simulation_Time,Event_Type,Ticker,Direction,Quantity,Price,Slippage,Notes) VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, sim_time, event_type, ticker, direction, quantity, price, slippage, notes)
        )

    def get_events(self, run_id):
        return self._fetch("SELECT * FROM Execution_Events WHERE Run_ID=? ORDER BY Event_ID", (run_id,))

    def snapshot_portfolio(self, run_id, sim_time, cash, margin, equity, open_positions):
        self._exec(
            "INSERT INTO Portfolio_Snapshots (Run_ID,Simulation_Time,Available_Cash,Allocated_Margin,Total_Equity_Value,Open_Positions) VALUES (?,?,?,?,?,?)",
            (run_id, sim_time, cash, margin, equity, json.dumps(open_positions))
        )

    def get_snapshots(self, run_id):
        return self._fetch("SELECT * FROM Portfolio_Snapshots WHERE Run_ID=? ORDER BY Snapshot_ID", (run_id,))

    def open_trade(self, run_id, ticker, direction, entry_time, entry_price, quantity, slippage_in=0.0):
        return self._exec(
            "INSERT INTO Trade_Log (Run_ID,Ticker,Direction,Entry_Time,Entry_Price,Quantity,Slippage_In) VALUES (?,?,?,?,?,?,?)",
            (run_id, ticker, direction, entry_time, entry_price, quantity, slippage_in)
        )

    def close_trade(self, trade_id, exit_time, exit_price, slippage_out=0.0):
        conn = self._conn()
        try:
            row = conn.execute("SELECT Entry_Price, Quantity, Slippage_In, Direction FROM Trade_Log WHERE Trade_ID=?", (trade_id,)).fetchone()
            if row:
                entry_price, quantity, slippage_in, direction = row
                if direction == "SHORT":
                    gross_pnl = (entry_price - exit_price) * quantity
                else:
                    gross_pnl = (exit_price - entry_price) * quantity
                net_pnl = gross_pnl - (slippage_in + slippage_out) * quantity
                conn.execute(
                    "UPDATE Trade_Log SET Exit_Time=?,Exit_Price=?,Slippage_Out=?,Gross_PnL=?,Net_PnL=?,Status='CLOSED' WHERE Trade_ID=?",
                    (exit_time, exit_price, slippage_out, gross_pnl, net_pnl, trade_id)
                )
                conn.commit()
        finally:
            conn.close()

    def get_trades(self, run_id, status=None):
        if status:
            return self._fetch("SELECT * FROM Trade_Log WHERE Run_ID=? AND Status=? ORDER BY Trade_ID", (run_id, status))
        return self._fetch("SELECT * FROM Trade_Log WHERE Run_ID=? ORDER BY Trade_ID", (run_id,))
