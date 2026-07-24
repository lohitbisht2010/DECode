"""Combine multiple strategies' independent backtest results into a
comparison and a shared-capital portfolio view.

Every strategy in this project sizes positions as a percentage of current
equity (fixed allocation or risk-based), so every dollar figure in a trade
scales linearly with starting capital. That means running strategy i alone
with `weight_i * capital` produces exactly `weight_i * equity_curve_i(t)`
at every bar - there's no need to re-run each backtest at a smaller
capital allocation; scaling and summing each strategy's full-capital
result is mathematically equivalent to actually splitting capital between
them upfront. All strategies here run over the same OHLCV dataframe, so
their equity curves share an identical bar index.
"""
import copy
from typing import Dict, List

import pandas as pd

from sol_backtest.backtest.engine import Trade


def scale_trade(trade: Trade, weight: float) -> Trade:
    """Copy of trade with qty/fees scaled by weight (prices unchanged).
    gross_pnl/net_pnl are computed properties derived from qty, so they
    come out correctly scaled too."""
    scaled = copy.copy(trade)
    scaled.qty = trade.qty * weight
    scaled.entry_fee = trade.entry_fee * weight
    scaled.exit_fee = trade.exit_fee * weight
    return scaled


def combine_equity_curves(curves: Dict[str, pd.Series], weights: Dict[str, float]) -> pd.Series:
    """Weighted sum of equity curves. Weights must sum to 1.0."""
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > 1e-6:
        raise ValueError(f"weights must sum to 1.0, got {total_weight}")

    combined = None
    for name, curve in curves.items():
        contribution = curve * weights[name]
        combined = contribution if combined is None else combined.add(contribution, fill_value=0)
    return combined


def combine_trades(trades_by_strategy: Dict[str, List[Trade]], weights: Dict[str, float]) -> List[Trade]:
    """Scale each strategy's trades by its portfolio weight and merge them
    into one chronological list, for computing portfolio-level trade stats
    (win rate, profit factor, fees) alongside the combined equity curve."""
    combined: List[Trade] = []
    for name, trades in trades_by_strategy.items():
        combined.extend(scale_trade(t, weights[name]) for t in trades)
    combined.sort(key=lambda t: t.entry_time)
    return combined


def compute_return_correlation(curves: Dict[str, pd.Series]) -> pd.DataFrame:
    """Pairwise correlation of each strategy's daily returns, computed from
    its own equity curve resampled to 1-day steps (so results reflect
    day-to-day P&L movement rather than the many flat, no-trade bars
    between signals). NaN where a strategy has zero variance (e.g. no
    trades at all)."""
    returns = {}
    for name, curve in curves.items():
        daily = curve.resample("1D").last().ffill()
        returns[name] = daily.pct_change().dropna()
    return pd.DataFrame(returns).corr()
