"""Bearish-outside-bar rejection at the previous day's R1 pivot.

Pattern (all on the 15m timeframe, comparing the current bar to the one
immediately before it):
  1. current.high  >  previous.high        (takes out the prior bar's high)
  2. current.close <= previous.open        (closes back below the prior bar's open)
  3. previous.open  <  previous.close      (prior bar was bullish/green)
  4. current.open   >  current.close       (current bar is bearish/red)
  5. current.high   >= R1                  (pokes at/through the pivot resistance)
  6. current.close  <  R1                  (but closes back below it - a rejection)

R1 comes from the previous UTC day's daily pivot (pivots.py). Trade plan:
short at the next bar's open, stop at the signal bar's high (pattern
invalidated if price keeps going), target at the daily pivot line (PP) -
the classic "fade back to the pivot" trade.
"""
import pandas as pd

from sol_backtest.pivots import attach_previous_day_pivots
from sol_backtest.strategies.pattern_base import PatternStrategy


class PivotR1RejectionStrategy(PatternStrategy):
    def __init__(self, daily_df: pd.DataFrame):
        self.daily_df = daily_df

    def generate_setups(self, df: pd.DataFrame) -> pd.DataFrame:
        merged = attach_previous_day_pivots(df, self.daily_df)

        prev_high = merged["high"].shift(1)
        prev_open = merged["open"].shift(1)
        prev_close = merged["close"].shift(1)

        pattern = (
            (merged["high"] > prev_high)
            & (merged["close"] <= prev_open)
            & (prev_open < prev_close)
            & (merged["open"] > merged["close"])
            & (merged["high"] >= merged["pivot_r1"])
            & (merged["close"] < merged["pivot_r1"])
        )

        out = pd.DataFrame(index=df.index)
        out["entry_signal"] = pattern.fillna(False)
        out["direction"] = -1
        out["stop_price"] = merged["high"]
        out["target_price"] = merged["pivot_pp"]
        return out
