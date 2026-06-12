"""
getABG Data Ingestion Layer
Fetches OHLCV data from Yahoo Finance with Parquet caching and concurrent fetching.

Cache strategy:
  - One .parquet file per ticker (keyed by ticker symbol, not date range).
    Overlapping date ranges are served as slices — no duplicate network calls.
  - Historical data (requested end > RECENT_DAYS ago) is cached forever.
  - Recent data (requested end within RECENT_DAYS of today) expires after TTL_RECENT_SECONDS.
  - On cache miss, the new data is merged with existing cached rows so the file
    always holds the widest range fetched so far.

Concurrency:
  - get_universe_data() fetches multiple tickers in parallel via ThreadPoolExecutor.
  - A semaphore caps simultaneous Yahoo Finance connections at MAX_CONCURRENT_FETCHES
    to stay polite and avoid rate-limit bans.
  - pyarrow is required for Parquet; if missing, falls back to CSV automatically.
"""

import os
import json
import time
import threading
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Cache config ──────────────────────────────────────────────────────────────

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache", "ohlcv")
os.makedirs(CACHE_DIR, exist_ok=True)

# Data whose end-date is within this many days of today is considered "recent"
# and will be re-fetched if cached copy is older than TTL_RECENT_SECONDS.
RECENT_DAYS = 5
TTL_RECENT_SECONDS = 86_400  # 24 hours

# Yahoo Finance concurrency — semaphore caps simultaneous open connections
MAX_CONCURRENT_FETCHES = 3
_fetch_semaphore = threading.Semaphore(MAX_CONCURRENT_FETCHES)

# Worker threads for get_universe_data
MAX_WORKERS = 5

# Detect pyarrow availability; fall back to CSV if missing
try:
    import pyarrow  # noqa: F401
    _PARQUET_AVAILABLE = True
except ImportError:
    _PARQUET_AVAILABLE = False

YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; getABG/1.0)",
    "Accept": "application/json",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _market_type(ticker: str) -> str:
    if ticker.endswith(".NS"):
        return "NSE"
    elif ticker.endswith(".BO"):
        return "BSE"
    return "US"


def _safe_name(ticker: str) -> str:
    """Filesystem-safe ticker name."""
    return ticker.replace(".", "_").replace("/", "_").replace("^", "_")


def _cache_paths(ticker: str):
    """Return (data_file_path, meta_file_path) for this ticker."""
    base = os.path.join(CACHE_DIR, _safe_name(ticker))
    ext = ".parquet" if _PARQUET_AVAILABLE else ".csv"
    return base + ext, base + ".meta.json"


def _read_meta(ticker: str) -> dict:
    _, meta_path = _cache_paths(ticker)
    if not os.path.exists(meta_path):
        return {}
    try:
        with open(meta_path) as f:
            return json.load(f)
    except Exception:
        return {}


def _write_meta(ticker: str, meta: dict):
    _, meta_path = _cache_paths(ticker)
    with open(meta_path, "w") as f:
        json.dump(meta, f)


def _is_cache_valid(meta: dict, start: str, end: str) -> bool:
    """
    True if cached data covers [start, end] and passes TTL check.
    Historical ranges (end > RECENT_DAYS ago) never expire.
    """
    if not meta:
        return False

    cached_start = meta.get("start", "")
    cached_end = meta.get("end", "")
    fetched_at = meta.get("fetched_at", 0.0)

    # Coverage check — cache must span the full requested range
    if cached_start > start or cached_end < end:
        return False

    # TTL check — only for recent data
    today = datetime.now().date()
    end_date = datetime.strptime(end, "%Y-%m-%d").date()
    if (today - end_date).days <= RECENT_DAYS:
        if time.time() - fetched_at > TTL_RECENT_SECONDS:
            return False

    return True


def _read_cache(ticker: str) -> Optional[pd.DataFrame]:
    """Load cached DataFrame for ticker; returns None on any failure."""
    data_path, _ = _cache_paths(ticker)
    if not os.path.exists(data_path):
        return None
    try:
        if _PARQUET_AVAILABLE and data_path.endswith(".parquet"):
            return pd.read_parquet(data_path)
        return pd.read_csv(data_path, index_col="Date", parse_dates=True)
    except Exception:
        return None  # corrupt cache — will be overwritten on next fetch


def _write_cache(ticker: str, df: pd.DataFrame):
    """Persist DataFrame to cache (Parquet preferred, CSV fallback)."""
    data_path, _ = _cache_paths(ticker)
    if _PARQUET_AVAILABLE:
        df.to_parquet(data_path, engine="pyarrow", compression="snappy")
    else:
        df.to_csv(data_path)


def _migrate_legacy_csv(ticker: str):
    """
    One-time migration: if an old date-range-keyed CSV exists for this ticker,
    ignore it — it will be naturally replaced when the ticker is next requested.
    The old files can be cleaned up manually from cache/ohlcv/.
    """
    pass  # Old CSV files simply won't be read by new logic; they'll expire naturally.


# ── Yahoo Finance fetch ───────────────────────────────────────────────────────

def _fetch_from_yahoo(ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
    """
    Fetch adjusted OHLCV from Yahoo Finance chart API.
    Semaphore-limited to MAX_CONCURRENT_FETCHES simultaneous connections.
    """
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

    with _fetch_semaphore:
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

        # Apply corporate action adjustment to OHLC
        adj_factor = df["Adj_Close"] / df["Close"]
        for col in ["Open", "High", "Low", "Close"]:
            df[col] = df[col] * adj_factor
        df["Close"] = df["Adj_Close"]
        df = df.drop(columns=["Adj_Close"])

        return df

    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"[DataLayer] Malformed Yahoo response for {ticker}: {e}")


# ── Public API ────────────────────────────────────────────────────────────────

def get_ohlcv(
    ticker: str,
    start: str,
    end: str,
    use_cache: bool = True,
    verbose: bool = False,
) -> pd.DataFrame:
    """
    Primary data access method. Returns adjusted OHLCV DataFrame for [start, end].

    Cache behaviour:
      - Cache is keyed per ticker (not per date range). If the cached file already
        covers the requested range, a slice is returned — no network call.
      - New fetches are merged with existing cached rows so the file grows to
        cover all ranges ever requested for that ticker.
      - Historical data: cached forever.
      - Recent data (end within 5 days of today): cached for 24 hours, then
        re-fetched to pick up any late-arriving adjustments.
      - Falls back to CSV if pyarrow is not installed.
    """
    data_path, _ = _cache_paths(ticker)
    meta = _read_meta(ticker) if use_cache else {}

    if use_cache and os.path.exists(data_path) and _is_cache_valid(meta, start, end):
        if verbose:
            fmt = "Parquet" if _PARQUET_AVAILABLE else "CSV"
            print(f"  [Cache HIT ] {ticker} ({start} -> {end}) [{fmt}]")
        cached_df = _read_cache(ticker)
        if cached_df is not None:
            return cached_df.loc[start:end]
        # If read failed, fall through to re-fetch

    if verbose:
        reason = "stale" if meta else "cold"
        print(f"  [Cache MISS] {ticker} ({reason}) — fetching from Yahoo Finance...")

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
    fresh_df = _fetch_from_yahoo(ticker, start_dt, end_dt)

    df_slice = fresh_df.loc[start:end]
    if df_slice.empty:
        raise ValueError(f"[DataLayer] No data returned for {ticker} in [{start}, {end}]")

    if use_cache:
        # Merge fresh data with any existing cached rows (keeps widest range)
        existing = _read_cache(ticker)
        if existing is not None and not existing.empty:
            merged = pd.concat([existing, fresh_df])
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        else:
            merged = fresh_df

        _write_cache(ticker, merged)
        _write_meta(ticker, {
            "start": str(merged.index.min().date()),
            "end": str(merged.index.max().date()),
            "fetched_at": time.time(),
            "format": "parquet" if _PARQUET_AVAILABLE else "csv",
        })

        if verbose:
            fname = os.path.basename(data_path)
            print(f"  [Cached    ] {ticker} -> {fname} "
                  f"({str(merged.index.min().date())} to {str(merged.index.max().date())})")

    return df_slice


def get_universe_data(
    tickers: List[str],
    start: str,
    end: str,
    use_cache: bool = True,
    verbose: bool = True,
    max_workers: int = MAX_WORKERS,
) -> Dict[str, pd.DataFrame]:
    """
    Fetch OHLCV for a universe of tickers — concurrently when multiple tickers
    are requested, sequentially for single-ticker runs.

    Workers are capped at min(len(tickers), max_workers). The Yahoo Finance
    semaphore (_fetch_semaphore) further limits simultaneous open connections
    to MAX_CONCURRENT_FETCHES regardless of worker count.

    Returns:
        {ticker: adjusted OHLCV DataFrame}  — failed tickers are omitted with a warning.
    """
    universe: Dict[str, pd.DataFrame] = {}

    def _fetch_one(ticker: str):
        market = _market_type(ticker)
        if verbose:
            print(f"  -> {ticker} [{market}]")
        df = get_ohlcv(ticker, start, end, use_cache=use_cache, verbose=verbose)
        return ticker, df

    workers = min(len(tickers), max_workers)

    if workers <= 1:
        # Single ticker — skip threading overhead entirely
        for ticker in tickers:
            try:
                _, df = _fetch_one(ticker)
                universe[ticker] = df
            except Exception as e:
                print(f"  [WARNING] Skipping {ticker}: {e}")
        return universe

    # Multi-ticker — concurrent fetch
    if verbose:
        print(f"  [Fetch] Starting {workers} concurrent workers for {len(tickers)} tickers...")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_one, t): t for t in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                _, df = future.result()
                universe[ticker] = df
            except Exception as e:
                print(f"  [WARNING] Skipping {ticker}: {e}")

    return universe


def clear_cache(ticker: str = None):
    """
    Utility: clear cache for a specific ticker or all tickers.
    Useful when you want to force a fresh fetch (e.g. after a data correction).
    """
    if ticker:
        for path in _cache_paths(ticker):
            if os.path.exists(path):
                os.remove(path)
    else:
        for fname in os.listdir(CACHE_DIR):
            os.remove(os.path.join(CACHE_DIR, fname))
