"""Performance metrics for a completed backtest."""
import math
from typing import List

import pandas as pd

from sol_backtest.backtest.engine import Trade


def compute_metrics(
    equity_curve: pd.Series,
    trades: List[Trade],
    initial_capital: float,
    periods_per_year: float,
) -> dict:
    final_equity = float(equity_curve.iloc[-1])
    total_return_pct = (final_equity / initial_capital - 1) * 100

    years = max((equity_curve.index[-1] - equity_curve.index[0]).total_seconds() / (365 * 86400), 1e-9)
    cagr_pct = ((final_equity / initial_capital) ** (1 / years) - 1) * 100 if final_equity > 0 else -100.0

    returns = equity_curve.pct_change().dropna()
    sharpe_ratio = (
        (returns.mean() / returns.std()) * math.sqrt(periods_per_year)
        if returns.std() > 0
        else 0.0
    )

    running_max = equity_curve.cummax()
    drawdown_pct = (equity_curve - running_max) / running_max * 100
    max_drawdown_pct = float(drawdown_pct.min())

    closed_trades = [t for t in trades if t.exit_price is not None]
    wins = [t for t in closed_trades if t.net_pnl > 0]
    losses = [t for t in closed_trades if t.net_pnl <= 0]
    win_rate_pct = (len(wins) / len(closed_trades) * 100) if closed_trades else 0.0

    gross_profit = sum(t.net_pnl for t in wins)
    gross_loss = -sum(t.net_pnl for t in losses)
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = float("inf") if gross_profit > 0 else 0.0

    total_fees = sum(t.entry_fee + t.exit_fee for t in closed_trades)
    gross_pnl = sum(t.gross_pnl for t in closed_trades)
    net_pnl = sum(t.net_pnl for t in closed_trades)

    return {
        "initial_capital": initial_capital,
        "final_equity": final_equity,
        "total_return_pct": total_return_pct,
        "cagr_pct": cagr_pct,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown_pct": max_drawdown_pct,
        "num_trades": len(closed_trades),
        "win_rate_pct": win_rate_pct,
        "profit_factor": profit_factor,
        "gross_pnl": gross_pnl,
        "total_fees_paid": total_fees,
        "net_pnl": net_pnl,
        "fees_as_pct_of_gross_pnl": (total_fees / abs(gross_pnl) * 100) if gross_pnl != 0 else float("inf") if total_fees > 0 else 0.0,
    }
