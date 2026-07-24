import pandas as pd
import pytest

from sol_backtest.backtest.engine import Trade
from sol_backtest.portfolio import combine_equity_curves, combine_trades, compute_return_correlation, scale_trade


def _trade():
    t = Trade(direction=1, entry_time=0, entry_price=100.0, qty=10.0, entry_fee=2.0)
    t.exit_time = 900
    t.exit_price = 110.0
    t.exit_fee = 2.2
    return t


def test_scale_trade_scales_qty_fees_and_pnl_proportionally():
    original = _trade()
    scaled = scale_trade(original, 0.5)

    assert scaled.qty == 5.0
    assert scaled.entry_fee == 1.0
    assert scaled.exit_fee == 1.1
    assert abs(scaled.gross_pnl - original.gross_pnl * 0.5) < 1e-9
    assert abs(scaled.net_pnl - original.net_pnl * 0.5) < 1e-9
    # original is untouched
    assert original.qty == 10.0


def test_combine_equity_curves_equal_weight():
    idx = pd.date_range("2025-01-01", periods=3, freq="1h")
    curve_a = pd.Series([10000.0, 10500.0, 11000.0], index=idx)
    curve_b = pd.Series([10000.0, 9500.0, 9000.0], index=idx)

    combined = combine_equity_curves({"a": curve_a, "b": curve_b}, {"a": 0.5, "b": 0.5})

    assert abs(combined.iloc[0] - 10000.0) < 1e-9  # starts at full capital
    assert abs(combined.iloc[1] - (10500.0 * 0.5 + 9500.0 * 0.5)) < 1e-9
    assert abs(combined.iloc[2] - (11000.0 * 0.5 + 9000.0 * 0.5)) < 1e-9


def test_combine_equity_curves_rejects_bad_weights():
    idx = pd.date_range("2025-01-01", periods=2, freq="1h")
    curve = pd.Series([10000.0, 10100.0], index=idx)
    with pytest.raises(ValueError):
        combine_equity_curves({"a": curve}, {"a": 0.5})  # doesn't sum to 1.0


def test_combine_trades_scales_and_sorts_by_entry_time():
    t1 = _trade()
    t1.entry_time = 900
    t2 = _trade()
    t2.entry_time = 0

    combined = combine_trades({"strat_a": [t1], "strat_b": [t2]}, {"strat_a": 0.5, "strat_b": 0.5})

    assert [t.entry_time for t in combined] == [0, 900]
    assert all(t.qty == 5.0 for t in combined)


def test_return_correlation_identical_curves_is_one():
    idx = pd.date_range("2025-01-01", periods=5, freq="1D")
    curve = pd.Series([10000.0, 10100.0, 10050.0, 10200.0, 10150.0], index=idx)
    corr = compute_return_correlation({"a": curve, "b": curve.copy()})
    assert abs(corr.loc["a", "b"] - 1.0) < 1e-9


def test_return_correlation_inverse_curves_is_negative_one():
    idx = pd.date_range("2025-01-01", periods=5, freq="1D")
    curve_a = pd.Series([10000.0, 10100.0, 10050.0, 10200.0, 10150.0], index=idx)
    curve_b = pd.Series([10000.0, 9900.0, 9950.0, 9800.0, 9850.0], index=idx)  # mirror-image moves
    corr = compute_return_correlation({"a": curve_a, "b": curve_b})
    assert corr.loc["a", "b"] < -0.99
