"""Daily pivot points (classic/floor-trader formula), applied to intraday bars.

Each intraday bar gets the pivot levels computed from the *previous* UTC
calendar day's daily OHLC — standard "trade today off yesterday's pivots"
convention. Crypto trades 24/7 so there's a daily candle for every day
(no weekend gaps to worry about); the first day of a data window has no
prior day available and gets NaN pivots, which pattern checks simply treat
as "no signal".
"""
import pandas as pd

VALID_PIVOT_LEVELS = {"pp", "r1", "r2", "r3", "s1", "s2", "s3"}


def compute_daily_pivots(daily_df: pd.DataFrame) -> pd.DataFrame:
    """daily_df: OHLCV with columns [time, open, high, low, close, volume].

    Returns a copy indexed by the (normalized, UTC midnight) day timestamp,
    with columns pp, r1, r2, r3, s1, s2, s3.
    """
    d = daily_df.copy()
    d["_day"] = pd.to_datetime(d["time"], unit="s").dt.normalize()
    d = d.set_index("_day")

    pp = (d["high"] + d["low"] + d["close"]) / 3
    r1 = 2 * pp - d["low"]
    s1 = 2 * pp - d["high"]
    r2 = pp + (d["high"] - d["low"])
    s2 = pp - (d["high"] - d["low"])
    r3 = d["high"] + 2 * (pp - d["low"])
    s3 = d["low"] - 2 * (d["high"] - pp)

    return pd.DataFrame({"pp": pp, "r1": r1, "r2": r2, "r3": r3, "s1": s1, "s2": s2, "s3": s3})


def attach_previous_day_pivots(intraday_df: pd.DataFrame, daily_df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of intraday_df with pivot_pp/pivot_r1/... columns added,
    each row using the pivots computed from the prior calendar day."""
    daily_pivots = compute_daily_pivots(daily_df)

    out = intraday_df.copy()
    bar_day = pd.to_datetime(out["time"], unit="s").dt.normalize()
    prev_day = bar_day - pd.Timedelta(days=1)

    for col in daily_pivots.columns:
        out[f"pivot_{col}"] = prev_day.map(daily_pivots[col])

    return out
