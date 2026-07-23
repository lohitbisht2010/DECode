"""Strategy plug-in interface.

Implement `generate_signals` to turn OHLCV data into a target-position
series and drop the file in this package. The engine executes on the next
bar's open after a signal changes, so implementations should only look at
data available up to and including the current bar (no lookahead).
"""
from abc import ABC, abstractmethod

import pandas as pd


class Strategy(ABC):
    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """df has columns [time, open, high, low, close, volume], ascending by time.

        Return a Series the same length as df, one of {1, 0, -1} per bar:
        1 = hold long, -1 = hold short, 0 = flat.
        """
        raise NotImplementedError
