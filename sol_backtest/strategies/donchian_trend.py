"""Classic Donchian-channel / Turtle-style breakout trend-follower.

Every mean-reversion pattern tried in this project (pivot rejections,
pivot ladder, Supertrend rejection) shares the same structural problem
against Delta's fee schedule: many trades, each with a small average win,
so per-trade fees eat most or all of the gross edge. This strategy is the
classic architectural answer to that problem - trade rarely, cut losses
short, and let winners run for a large average win via a trailing stop
instead of a fixed target. Designed to run on daily bars specifically to
keep trade count low.

Entry: today's close breaks above the prior `entry_period` bars' highest
high (long) or below their lowest low (short) - the breakout is confirmed
by the close, not just an intrabar poke, and "prior" excludes the signal
bar itself (shift(1), no lookahead).

Initial stop: `initial_stop_atr_multiple` * ATR away from the entry side,
tightened bar-by-bar afterward by the engine's chandelier trailing stop
(see PatternBacktester's trailing_stop_atr_multiple) - there is no fixed
target, the position rides until the trailing stop catches it.
"""
import numpy as np
import pandas as pd

from sol_backtest.indicators import compute_atr
from sol_backtest.strategies.pattern_base import PatternStrategy


class DonchianTrendStrategy(PatternStrategy):
    def __init__(
        self,
        entry_period: int = 20,
        atr_period: int = 14,
        initial_stop_atr_multiple: float = 2.0,
        allow_short: bool = True,
    ):
        self.entry_period = entry_period
        self.atr_period = atr_period
        self.initial_stop_atr_multiple = initial_stop_atr_multiple
        self.allow_short = allow_short

    def generate_setups(self, df: pd.DataFrame) -> pd.DataFrame:
        atr = compute_atr(df, self.atr_period)

        rolling_high = df["high"].rolling(self.entry_period).max().shift(1)
        rolling_low = df["low"].rolling(self.entry_period).min().shift(1)

        long_signal = df["close"] > rolling_high
        short_signal = (df["close"] < rolling_low) if self.allow_short else pd.Series(False, index=df.index)

        long_signal = long_signal.fillna(False)
        short_signal = short_signal.fillna(False)
        # a bar can't break both ways - if it somehow did, prefer the long
        short_signal = short_signal & ~long_signal

        entry_signal = long_signal | short_signal
        direction = np.where(long_signal, 1, np.where(short_signal, -1, 0))

        stop_price = np.where(
            long_signal,
            df["close"] - self.initial_stop_atr_multiple * atr,
            np.where(short_signal, df["close"] + self.initial_stop_atr_multiple * atr, np.nan),
        )

        out = pd.DataFrame(index=df.index)
        out["entry_signal"] = entry_signal & ~atr.isna()
        out["direction"] = direction
        out["stop_price"] = stop_price
        out["target_price"] = float("nan")
        out["atr"] = atr
        return out
