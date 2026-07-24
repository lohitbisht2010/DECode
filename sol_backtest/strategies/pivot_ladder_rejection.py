"""The same rejection pattern as pivot_r1_rejection, checked at every rung
of the pivot ladder instead of just R1, each targeting the level one rung
below it:

    R3 -> R2,  R2 -> R1,  R1 -> PP,  PP -> S1,  S1 -> S2,  S2 -> S3

At every rung the trigger is identical (comparing the current 15m bar to
the one immediately before it):
  1. current.high  >  previous.high        (takes out the prior bar's high)
  2. current.close <= previous.open        (closes back below the prior bar's open)
  3. previous.open  <  previous.close      (prior bar was bullish/green)
  4. current.open   >  current.close       (current bar is bearish/red)
  5. current.high   >= level                (pokes at/through that pivot level)
  6. current.close  <  level                (but closes back below it - a rejection)

Levels are checked from R3 down to S2 (highest first); if a bar's high
happens to clear more than one level at once, the *highest* one that was
rejected wins, since that's the more extreme (and more informative) level
to have been rejected at. Stop is always the signal bar's own high,
matching every other rejection variant. There's no rejection *at* S3
(nothing below it to target), so it's excluded from the ladder.

Levels come from the previous period's pivot (pivots.py) - defaults to
the previous UTC day, or the previous calendar month via
pivot_period="monthly" (wider levels, fewer signals, smaller position
size under risk-based sizing since stop distance grows with level
spacing).
"""
import numpy as np
import pandas as pd

from sol_backtest.pivots import VALID_PIVOT_PERIODS, attach_pivots
from sol_backtest.strategies.pattern_base import PatternStrategy

# (trigger level, target level), highest trigger first so it takes priority
# on the rare bar where more than one level's conditions are simultaneously met.
LADDER = [
    ("r3", "r2"),
    ("r2", "r1"),
    ("r1", "pp"),
    ("pp", "s1"),
    ("s1", "s2"),
    ("s2", "s3"),
]


class PivotLadderRejectionStrategy(PatternStrategy):
    def __init__(self, daily_df: pd.DataFrame, pivot_period: str = "daily"):
        if pivot_period not in VALID_PIVOT_PERIODS:
            raise ValueError(f"pivot_period must be one of {sorted(VALID_PIVOT_PERIODS)}, got {pivot_period!r}")
        self.daily_df = daily_df
        self.pivot_period = pivot_period

    def generate_setups(self, df: pd.DataFrame) -> pd.DataFrame:
        merged = attach_pivots(df, self.daily_df, self.pivot_period)

        prev_high = merged["high"].shift(1)
        prev_open = merged["open"].shift(1)
        prev_close = merged["close"].shift(1)

        base_pattern = (
            (merged["high"] > prev_high)
            & (merged["close"] <= prev_open)
            & (prev_open < prev_close)
            & (merged["open"] > merged["close"])
        )

        entry_signal = pd.Series(False, index=df.index)
        target_price = pd.Series(np.nan, index=df.index)
        trigger_level = pd.Series("", index=df.index)

        for level, target_level in LADDER:
            level_col = merged[f"pivot_{level}"]
            match = base_pattern & (merged["high"] >= level_col) & (merged["close"] < level_col) & (~entry_signal)
            target_price = target_price.where(~match, merged[f"pivot_{target_level}"])
            trigger_level = trigger_level.where(~match, level)
            entry_signal = entry_signal | match

        out = pd.DataFrame(index=df.index)
        out["entry_signal"] = entry_signal.fillna(False)
        out["direction"] = -1
        out["stop_price"] = merged["high"]
        out["target_price"] = target_price
        out["tag"] = trigger_level
        return out
