"""Technical indicators computed directly on the trading timeframe (as
opposed to pivots.py, which is computed on the daily timeframe and mapped
down onto intraday bars)."""
import numpy as np
import pandas as pd


def compute_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """Standard ATR-based Supertrend (Wilder-smoothed ATR, sticky bands).

    Returns a DataFrame aligned with df.index with columns:
      supertrend: the indicator line's value at each bar
      trend:      -1 (downtrend, supertrend sits above price as resistance)
                   or 1 (uptrend, supertrend sits below price as support)
    Both are NaN/0 for the warmup period before `period` bars of data exist.
    """
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    n = len(df)

    prev_close = np.concatenate(([close[0]], close[:-1])) if n else close
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))

    atr = np.full(n, np.nan)
    if n >= period:
        atr[period - 1] = tr[:period].mean()
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    hl2 = (high + low) / 2
    basic_upper = hl2 + multiplier * atr
    basic_lower = hl2 - multiplier * atr

    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    supertrend = np.full(n, np.nan)
    trend = np.zeros(n, dtype=int)

    start = period - 1
    for i in range(start, n):
        if i == start:
            final_upper[i] = basic_upper[i]
            final_lower[i] = basic_lower[i]
            if close[i] <= final_upper[i]:
                supertrend[i] = final_upper[i]
                trend[i] = -1
            else:
                supertrend[i] = final_lower[i]
                trend[i] = 1
            continue

        if basic_upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]:
            final_upper[i] = basic_upper[i]
        else:
            final_upper[i] = final_upper[i - 1]

        if basic_lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]:
            final_lower[i] = basic_lower[i]
        else:
            final_lower[i] = final_lower[i - 1]

        if supertrend[i - 1] == final_upper[i - 1]:
            if close[i] <= final_upper[i]:
                supertrend[i] = final_upper[i]
                trend[i] = -1
            else:
                supertrend[i] = final_lower[i]
                trend[i] = 1
        else:
            if close[i] >= final_lower[i]:
                supertrend[i] = final_lower[i]
                trend[i] = 1
            else:
                supertrend[i] = final_upper[i]
                trend[i] = -1

    return pd.DataFrame({"supertrend": supertrend, "trend": trend}, index=df.index)
