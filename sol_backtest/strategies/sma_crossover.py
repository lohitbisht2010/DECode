"""Placeholder demo strategy: simple/fast moving-average crossover.

This exists only to exercise the data-fetch -> backtest -> report pipeline
end to end. Swap it out for the real pattern by adding a new file in this
package that implements `Strategy.generate_signals` and pointing main.py's
STRATEGIES registry at it.
"""
import pandas as pd

from sol_backtest.strategies.base import Strategy


class SmaCrossoverStrategy(Strategy):
    def __init__(self, fast: int = 10, slow: int = 30):
        if fast >= slow:
            raise ValueError("fast period must be smaller than slow period")
        self.fast = fast
        self.slow = slow

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        fast_ma = df["close"].rolling(self.fast).mean()
        slow_ma = df["close"].rolling(self.slow).mean()
        signal = pd.Series(0, index=df.index)
        signal[fast_ma > slow_ma] = 1
        signal[fast_ma < slow_ma] = -1
        signal[fast_ma.isna() | slow_ma.isna()] = 0
        return signal
