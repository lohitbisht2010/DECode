"""Pivot points (classic/floor-trader formula), applied to intraday bars.

Each intraday bar gets the pivot levels computed from the *previous*
completed period's OHLC - daily pivots use yesterday's UTC day, monthly
pivots use last calendar month, both the standard "trade this period off
the last completed period's pivots" convention. Monthly pivots are
aggregated from daily candles (open of the month's first day, high/low
across the whole month, close of the last day) rather than fetched as a
native exchange resolution, since a calendar month isn't a fixed number
of days and Delta has no "1 month" candle resolution.

Crypto trades 24/7 so there's a daily candle for every day (no weekend
gaps); the first period in a data window has no prior period available
and gets NaN pivots, which pattern checks simply treat as "no signal".
"""
import pandas as pd

VALID_PIVOT_LEVELS = {"pp", "r1", "r2", "r3", "s1", "s2", "s3"}
VALID_PIVOT_PERIODS = {"daily", "monthly"}

_FREQ_BY_PERIOD = {"daily": "D", "monthly": "M"}
_OFFSET_BY_PERIOD = {"daily": pd.Timedelta(days=1), "monthly": pd.DateOffset(months=1)}


def _aggregate_ohlc(source_df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Group daily candles into one OHLC row per period (freq='D' is a
    no-op aggregation since source_df is already one row per day)."""
    d = source_df.copy()
    d["_period"] = pd.to_datetime(d["time"], unit="s").dt.to_period(freq).dt.to_timestamp()
    grouped = d.sort_values("time").groupby("_period", sort=True)
    return grouped.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))


def _compute_pivots(agg: pd.DataFrame) -> pd.DataFrame:
    pp = (agg["high"] + agg["low"] + agg["close"]) / 3
    r1 = 2 * pp - agg["low"]
    s1 = 2 * pp - agg["high"]
    r2 = pp + (agg["high"] - agg["low"])
    s2 = pp - (agg["high"] - agg["low"])
    r3 = agg["high"] + 2 * (pp - agg["low"])
    s3 = agg["low"] - 2 * (agg["high"] - pp)
    return pd.DataFrame({"pp": pp, "r1": r1, "r2": r2, "r3": r3, "s1": s1, "s2": s2, "s3": s3})


def compute_daily_pivots(daily_df: pd.DataFrame) -> pd.DataFrame:
    """daily_df: OHLCV with columns [time, open, high, low, close, volume].

    Returns a copy indexed by the (normalized, UTC midnight) day timestamp,
    with columns pp, r1, r2, r3, s1, s2, s3.
    """
    return _compute_pivots(_aggregate_ohlc(daily_df, "D"))


def compute_monthly_pivots(daily_df: pd.DataFrame) -> pd.DataFrame:
    """daily_df: daily OHLCV, aggregated by calendar month (UTC).

    Returns a copy indexed by each month's first-day timestamp, with
    columns pp, r1, r2, r3, s1, s2, s3.
    """
    return _compute_pivots(_aggregate_ohlc(daily_df, "M"))


def _attach_previous_period_pivots(intraday_df: pd.DataFrame, pivots: pd.DataFrame, period: str) -> pd.DataFrame:
    freq = _FREQ_BY_PERIOD[period]
    out = intraday_df.copy()
    bar_period = pd.to_datetime(out["time"], unit="s").dt.to_period(freq).dt.to_timestamp()
    prev_period = bar_period - _OFFSET_BY_PERIOD[period]
    for col in pivots.columns:
        out[f"pivot_{col}"] = prev_period.map(pivots[col])
    return out


def attach_previous_day_pivots(intraday_df: pd.DataFrame, daily_df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of intraday_df with pivot_pp/pivot_r1/... columns added,
    each row using the pivots computed from the prior calendar day."""
    return _attach_previous_period_pivots(intraday_df, compute_daily_pivots(daily_df), "daily")


def attach_previous_month_pivots(intraday_df: pd.DataFrame, daily_df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of intraday_df with pivot_pp/pivot_r1/... columns added,
    each row using the pivots computed from the prior calendar month."""
    return _attach_previous_period_pivots(intraday_df, compute_monthly_pivots(daily_df), "monthly")


def attach_pivots(intraday_df: pd.DataFrame, daily_df: pd.DataFrame, period: str = "daily") -> pd.DataFrame:
    """Dispatch to the daily or monthly attach function by name."""
    if period not in VALID_PIVOT_PERIODS:
        raise ValueError(f"period must be one of {sorted(VALID_PIVOT_PERIODS)}, got {period!r}")
    if period == "daily":
        return attach_previous_day_pivots(intraday_df, daily_df)
    return attach_previous_month_pivots(intraday_df, daily_df)
