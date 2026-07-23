"""Interface for discrete pattern-trade strategies (entry + stop + target),
as opposed to the continuous position-per-bar `Strategy` interface in
base.py. Use this when a strategy's exit is defined by a stop-loss/target
level rather than "hold until the next signal" — it needs bar-by-bar
intrabar checking, which `backtest.pattern_engine.PatternBacktester`
provides.
"""
from abc import ABC, abstractmethod

import pandas as pd


class PatternStrategy(ABC):
    @abstractmethod
    def generate_setups(self, df: pd.DataFrame) -> pd.DataFrame:
        """df has columns [time, open, high, low, close, volume], ascending by time.

        Return a DataFrame aligned with df.index with columns:
          entry_signal: bool  - True on the bar where the pattern completes
          direction:    int   - 1 (long) or -1 (short), meaningful only where entry_signal is True
          stop_price:   float - stop-loss level for a trade entered off this signal
          target_price: float - take-profit level for a trade entered off this signal

        The signal must be computable from data available up to and
        including the signal bar itself (no lookahead) — the backtester
        executes the entry at the *next* bar's open.
        """
        raise NotImplementedError
