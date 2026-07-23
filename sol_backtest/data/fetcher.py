"""Historical OHLCV candle fetcher for Delta Exchange India.

Delta's /v2/history/candles endpoint caps how many candles it returns per
call, so pulling a long backtest window means walking the range in chunks.
Results are cached to a local CSV keyed by (symbol, resolution, start, end)
so re-running a backtest against the same window doesn't re-hit the API.
"""
import os
import time
from typing import List, Optional

import pandas as pd
import requests

from sol_backtest.config import MAX_CANDLES_PER_REQUEST, RESOLUTION_SECONDS

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")

COLUMNS = ["time", "open", "high", "low", "close", "volume"]


class DataFetchError(RuntimeError):
    pass


def _cache_path(symbol: str, resolution: str, start: int, end: int) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{symbol}_{resolution}_{start}_{end}.csv")


def _fetch_chunk(base_url: str, symbol: str, resolution: str, start: int, end: int,
                  retries: int = 3, backoff: float = 1.0) -> List[dict]:
    url = f"{base_url}/v2/history/candles"
    params = {"symbol": symbol, "resolution": resolution, "start": start, "end": end}
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=15)
            payload = resp.json()
            if not resp.ok or payload.get("success") is False:
                raise DataFetchError(f"Delta API error [{resp.status_code}]: {payload}")
            return payload.get("result", [])
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            time.sleep(backoff * (2 ** attempt))
    raise DataFetchError(f"Failed to fetch candles after {retries} attempts: {last_error}")


def fetch_candles(
    base_url: str,
    symbol: str,
    resolution: str,
    start: int,
    end: int,
    use_cache: bool = True,
    request_pause_sec: float = 0.2,
) -> pd.DataFrame:
    """Fetch OHLCV candles for [start, end) (unix seconds), ascending by time."""
    if resolution not in RESOLUTION_SECONDS:
        raise ValueError(f"Unsupported resolution '{resolution}'. Known: {sorted(RESOLUTION_SECONDS)}")
    if start >= end:
        raise ValueError("start must be before end")

    cache_file = _cache_path(symbol, resolution, start, end)
    if use_cache and os.path.exists(cache_file):
        return pd.read_csv(cache_file)

    step = RESOLUTION_SECONDS[resolution] * MAX_CANDLES_PER_REQUEST
    all_rows: List[dict] = []
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + step, end)
        rows = _fetch_chunk(base_url, symbol, resolution, chunk_start, chunk_end)
        all_rows.extend(rows)
        chunk_start = chunk_end
        if chunk_start < end:
            time.sleep(request_pause_sec)

    if not all_rows:
        raise DataFetchError(
            f"No candle data returned for {symbol} [{resolution}] between {start} and {end}"
        )

    df = pd.DataFrame(all_rows)[COLUMNS]
    df = df.drop_duplicates(subset="time").sort_values("time").reset_index(drop=True)
    df["time"] = df["time"].astype(int)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)

    if use_cache:
        df.to_csv(cache_file, index=False)
    return df
