"""Enumerate BTC option contracts (symbol, strike, expiry) listed on Delta
Exchange India, across a date range.

Delta lists a fresh call+put chain for BTC every calendar day (daily
expiries, settling at 12:00 UTC), each with ~30 strikes per side. There's
no single endpoint that returns "the chain as of date X" - instead
`/v2/products` returns every product for a `states` filter (`live` for
contracts that haven't settled yet, `expired` for ones that have),
paginated via an opaque cursor. This fetches both, filters to the
underlying and date range requested, and caches the result to a local CSV
so repeat backtests over the same window don't re-paginate the whole
product catalogue.
"""
import os
import time
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd
import requests

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")


class ProductFetchError(RuntimeError):
    pass


def _cache_path(underlying: str, start: int, end: int) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"options_{underlying}_{start}_{end}.csv")


def _fetch_page(base_url: str, underlying: str, states: str, after: Optional[str],
                 retries: int = 3, backoff: float = 1.0) -> dict:
    params = {
        "contract_types": "call_options,put_options",
        "underlying_asset_symbols": underlying,
        "states": states,
    }
    if after:
        params["after"] = after
    last_error = None
    for attempt in range(retries):
        try:
            resp = requests.get(f"{base_url}/v2/products", params=params, timeout=20)
            payload = resp.json()
            if not resp.ok or payload.get("success") is False:
                raise ProductFetchError(f"Delta API error [{resp.status_code}]: {payload}")
            return payload
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            time.sleep(backoff * (2 ** attempt))
    raise ProductFetchError(f"Failed to fetch products after {retries} attempts: {last_error}")


def _fetch_all(base_url: str, underlying: str, states: str) -> List[dict]:
    rows: List[dict] = []
    after = None
    while True:
        payload = _fetch_page(base_url, underlying, states, after)
        data = payload.get("result", [])
        rows.extend(data)
        after = (payload.get("meta") or {}).get("after")
        if not after or not data:
            break
    return rows


def fetch_option_products(
    base_url: str, underlying: str, start: int, end: int, use_cache: bool = True,
) -> pd.DataFrame:
    """Return every call/put product settling in [start, end) (unix seconds),
    with columns: symbol, contract_type, strike_price, settlement_time
    (unix), contract_value. `states=live` covers contracts still trading
    (recent/future expiries); `states=expired` covers everything already
    settled - both are needed to cover a backtest window that runs up to
    "now"."""
    cache_file = _cache_path(underlying, start, end)
    if use_cache and os.path.exists(cache_file):
        return pd.read_csv(cache_file)

    raw = _fetch_all(base_url, underlying, "expired") + _fetch_all(base_url, underlying, "live")

    rows = []
    for p in raw:
        settlement_dt = datetime.strptime(p["settlement_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        settlement_unix = int(settlement_dt.timestamp())
        if not (start <= settlement_unix < end):
            continue
        rows.append({
            "symbol": p["symbol"],
            "contract_type": p["contract_type"],
            "strike_price": float(p["strike_price"]),
            "settlement_time": settlement_unix,
            "contract_value": float(p["contract_value"]),
        })

    if not rows:
        raise ProductFetchError(f"No {underlying} option products found settling between {start} and {end}")

    df = pd.DataFrame(rows).drop_duplicates(subset="symbol").sort_values(["settlement_time", "strike_price"])
    df = df.reset_index(drop=True)

    if use_cache:
        df.to_csv(cache_file, index=False)
    return df
