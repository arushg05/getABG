"""
getABG Data Ingestion Layer
Fetches OHLCV data from Yahoo Finance, caches locally as CSV (Parquet-compatible).
Supports US equities and Indian NSE/BSE markets.
"""

import os
import time
import hashlib
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, List, Dict

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache", "ohlcv")
os.makedirs(CACHE_DIR, exist_ok=True)

YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; getABG/1.0)",
    "Accept": "application/json",
}

def _market_type(ticker: str) -> str:
    if ticker.endswith(".NS"):
        return "NSE"
    elif ticker.endswith(".BO"):
        return "BSE"
    return "US"

def _cache_path(ticker: str, start: str, end: str) -> str:
    key = f"{ticker}_{start}_{end}"
    hashed = hashlib.md5(key.encode()).hexdigest()[:8]
    safe = ticker.replace(".", "_").replace("/", "_")
    return os.path.join(CACHE_DIR, f"{safe}_{start}_{end}_{hashed}.csv")

def _fetch_from_yahoo(ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Fetch OHLCV from Yahoo Finance chart API."""
    start_ts = int(start.timestamp())
    end_ts = int(end.timestamp())
    url = f"{YAHOO_BASE}{ticker}"
    params = {
        "period1": start_ts,
        "period2": end_ts,
        "interval": "1d",
        "events": "div,splits",
        "includeAdjustedClose": "true",
    }
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise ConnectionError(f"[DataLayer] Failed to fetch {ticker}: {e}")

    try:
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        q = result["indicators"]["quote"][0]
        adjclose = result["indicators"]["adjclose"][0]["adjclose"]

        df = pd.DataFrame({
            "Date": pd.to_datetime(timestamps, unit="s").normalize(),
            "Open": q["open"],
            "High": q["high"],
            "Low": q["low"],
            "Close": q["close"],
            "Volume": q["volume"],
            "Adj_Close": adjclose,
        })
        df = df.dropna(subset=["Close"])
        df = df.set_index("Date").sort_index()

        # Apply corporate action adjustment
        adj_factor = df["Adj_Close"] / df["Close"]
        for col in ["Open", "High", "Low", "Close"]:
            df[col] = df[col] * adj_factor
        df["Close"] = df["Adj_Close"]
        df = df.drop(columns=["Adj_Close"])
        return df

    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"[DataLayer] Malformed response for {ticker}: {e}")


def get_ohlcv(
    ticker: str,
    start: str,
    end: str,
    use_cache: bool = True,
    verbose: bool = False,
) -> pd.DataFrame:
    """
    Primary data access method. Returns adjusted OHLCV DataFrame.
    Checks local cache first; fetches from Yahoo Finance if missing.

    Args:
        ticker: Yahoo Finance symbol (e.g. 'AAPL', 'RELIANCE.NS', 'TCS.BO')
        start: ISO date string 'YYYY-MM-DD'
        end: ISO date string 'YYYY-MM-DD'
        use_cache: Whether to use/write local cache
    """
    cache_file = _cache_path(ticker, start, end)

    if use_cache and os.path.exists(cache_file):
        if verbose:
            print(f"  [Cache HIT] {ticker} ({start} -> {end})")
        df = pd.read_csv(cache_file, index_col="Date", parse_dates=True)
        return df

    if verbose:
        print(f"  [Cache MISS] Fetching {ticker} from Yahoo Finance...")

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
    df = _fetch_from_yahoo(ticker, start_dt, end_dt)

    # Filter strictly to requested range
    df = df.loc[start:end]

    if df.empty:
        raise ValueError(f"[DataLayer] No data returned for {ticker} in [{start}, {end}]")

    if use_cache:
        df.to_csv(cache_file)
        if verbose:
            print(f"  [Cached]  {ticker} -> {cache_file}")

    return df


def get_universe_data(
    tickers: List[str],
    start: str,
    end: str,
    use_cache: bool = True,
    verbose: bool = True,
) -> Dict[str, pd.DataFrame]:
    """
    Fetch OHLCV for a universe of tickers.
    Returns dict: {ticker: DataFrame}
    """
    universe = {}
    for ticker in tickers:
        market = _market_type(ticker)
        if verbose:
            print(f"  -> {ticker} [{market}]")
        try:
            df = get_ohlcv(ticker, start, end, use_cache=use_cache, verbose=verbose)
            universe[ticker] = df
            time.sleep(0.3)  # Polite rate-limiting
        except Exception as e:
            print(f"  [WARNING] Skipping {ticker}: {e}")
    return universe
