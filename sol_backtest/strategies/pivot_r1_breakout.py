"""Bullish breakout continuation through the previous day's R1 pivot.

The opposite thesis to pivot_r1_rejection.py: instead of fading a poke
through R1 that fails, this trades *with* momentum once R1 is broken with
conviction. Pattern (all on the 15m timeframe, comparing the current bar
to the one immediately before it):
  1. previous.close <= R1                  (R1 not yet broken as of the prior close)
  2. current.close   >  R1                  (breakout confirmed by close, not just a wick through)
  3. current.open    <  current.close       (bullish/strength candle)
  4. current.high    >  previous.high       (making a new high - momentum continuing)

Condition 1 restricts signals to the *first* bar that closes through R1,
so the pattern doesn't keep re-firing on every bar while price simply
holds above it.

R1 comes from the previous UTC day's daily pivot (pivots.py). Trade plan:
long at the next bar's open, stop at the breakout bar's own low
(invalidated if price falls back below it), target at a configurable
pivot level - defaults to R2, the natural next resistance above a broken
R1 (unlike the rejection strategy, PP/S1 sit *behind* a long entry here
and wouldn't make sense as a default target).
"""
import pandas as pd

from sol_backtest.pivots import VALID_PIVOT_LEVELS, attach_previous_day_pivots
from sol_backtest.strategies.pattern_base import PatternStrategy


class PivotR1BreakoutStrategy(PatternStrategy):
    def __init__(self, daily_df: pd.DataFrame, target_level: str = "r2"):
        if target_level not in VALID_PIVOT_LEVELS:
            raise ValueError(f"target_level must be one of {sorted(VALID_PIVOT_LEVELS)}, got {target_level!r}")
        self.daily_df = daily_df
        self.target_level = target_level

    def generate_setups(self, df: pd.DataFrame) -> pd.DataFrame:
        merged = attach_previous_day_pivots(df, self.daily_df)

        prev_high = merged["high"].shift(1)
        prev_close = merged["close"].shift(1)

        pattern = (
            (prev_close <= merged["pivot_r1"])
            & (merged["close"] > merged["pivot_r1"])
            & (merged["open"] < merged["close"])
            & (merged["high"] > prev_high)
        )

        out = pd.DataFrame(index=df.index)
        out["entry_signal"] = pattern.fillna(False)
        out["direction"] = 1
        out["stop_price"] = merged["low"]
        out["target_price"] = merged[f"pivot_{self.target_level}"]
        return out
