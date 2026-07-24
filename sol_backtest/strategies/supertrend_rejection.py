"""The same rejection pattern again, this time triggered against the
Supertrend line instead of a daily pivot: price is in a downtrend
(Supertrend red, sitting above price as dynamic resistance), rallies up
into it, and gets rejected - trading with the trend's continuation.

Pattern (all on the trading timeframe, comparing the current bar to the
one immediately before it):
  1. trend == -1 (downtrend)                (Supertrend currently red)
  2. current.high  >  previous.high         (takes out the prior bar's high)
  3. current.close <= previous.open         (closes back below the prior bar's open)
  4. previous.open  <  previous.close       (prior bar was bullish/green)
  5. current.open   >  current.close        (current bar is bearish/red)
  6. current.high   >= supertrend            (pokes at/through the Supertrend line)
  7. current.close  <  supertrend            (but closes back below it - a rejection)

Unlike the pivot-based rejection strategies, there's no fixed take-profit
target here: short at the next bar's open, stop at the signal bar's own
high, and hold until the Supertrend itself flips bullish (price closes
above it) - i.e. exit_signal = trend == 1. This runs through
`PatternBacktester`'s NaN-target + exit_signal machinery rather than a
fixed target level.
"""
import pandas as pd

from sol_backtest.indicators import compute_supertrend
from sol_backtest.strategies.pattern_base import PatternStrategy


class SupertrendRejectionStrategy(PatternStrategy):
    def __init__(self, atr_period: int = 10, multiplier: float = 3.0):
        self.atr_period = atr_period
        self.multiplier = multiplier

    def generate_setups(self, df: pd.DataFrame) -> pd.DataFrame:
        st = compute_supertrend(df, period=self.atr_period, multiplier=self.multiplier)

        prev_high = df["high"].shift(1)
        prev_open = df["open"].shift(1)
        prev_close = df["close"].shift(1)

        pattern = (
            (st["trend"] == -1)
            & (df["high"] > prev_high)
            & (df["close"] <= prev_open)
            & (prev_open < prev_close)
            & (df["open"] > df["close"])
            & (df["high"] >= st["supertrend"])
            & (df["close"] < st["supertrend"])
        )

        out = pd.DataFrame(index=df.index)
        out["entry_signal"] = pattern.fillna(False)
        out["direction"] = -1
        out["stop_price"] = df["high"]
        out["target_price"] = float("nan")
        out["exit_signal"] = st["trend"] == 1
        return out
