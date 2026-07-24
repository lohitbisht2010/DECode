"""Turn a strangle backtest's cycle list into a human-checkable CSV."""
import os
from typing import List

import pandas as pd

from option_backtest.backtest.engine import StrangleCycle

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def cycles_to_dataframe(cycles: List[StrangleCycle]) -> pd.DataFrame:
    rows = []
    for c in cycles:
        rows.append({
            "entry_time": pd.to_datetime(c.entry_time, unit="s"),
            "settlement_time": pd.to_datetime(c.settlement_time, unit="s"),
            "exit_time": pd.to_datetime(c.exit_time, unit="s"),
            "call_strike": c.call_strike, "put_strike": c.put_strike,
            "qty": c.qty,
            "call_entry_premium": c.call_entry_premium, "put_entry_premium": c.put_entry_premium,
            "call_exit_premium": c.call_exit_premium, "put_exit_premium": c.put_exit_premium,
            "call_exit_reason": c.call_exit_reason, "put_exit_reason": c.put_exit_reason,
            "entry_fee": c.entry_fee, "exit_fee": c.exit_fee,
            "gross_pnl": c.gross_pnl, "net_pnl": c.net_pnl,
        })
    return pd.DataFrame(rows)


def save_cycles_csv(cycles: List[StrangleCycle], filename: str) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, filename)
    cycles_to_dataframe(cycles).to_csv(path, index=False)
    return path
