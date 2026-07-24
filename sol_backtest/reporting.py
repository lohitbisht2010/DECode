"""Turn a backtest's trade list into a human-checkable CSV."""
import os
from typing import List

import pandas as pd

from sol_backtest.backtest.engine import Trade
from sol_backtest.backtest.pattern_engine import PatternTrade

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def trades_to_dataframe(trades: List[Trade]) -> pd.DataFrame:
    rows = []
    for t in trades:
        row = {
            "entry_time": pd.to_datetime(t.entry_time, unit="s"),
            "exit_time": pd.to_datetime(t.exit_time, unit="s") if t.exit_time is not None else None,
            "direction": "short" if t.direction == -1 else "long",
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "qty": t.qty,
            "entry_fee": t.entry_fee,
            "exit_fee": t.exit_fee,
            "gross_pnl": t.gross_pnl,
            "net_pnl": t.net_pnl,
        }
        if isinstance(t, PatternTrade):
            row["stop_price"] = t.stop_price
            row["target_price"] = t.target_price
            row["exit_reason"] = t.exit_reason
            if t.tag:
                row["tag"] = t.tag
        rows.append(row)
    return pd.DataFrame(rows)


def save_trades_csv(trades: List[Trade], filename: str) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, filename)
    trades_to_dataframe(trades).to_csv(path, index=False)
    return path
