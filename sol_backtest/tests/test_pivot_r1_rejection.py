import pandas as pd
import pytest

from sol_backtest.strategies.pivot_r1_rejection import PivotR1RejectionStrategy


def _daily_df():
    # day0 (time=0): H=110, L=90, C=100 -> PP=100, R1=110 - these are the pivots
    # that apply to every 15m bar on day1 (time in [86400, 172800)).
    return pd.DataFrame({
        "time": [0, 86400],
        "open": [95.0, 100.0],
        "high": [110.0, 108.0],
        "low": [90.0, 98.0],
        "close": [100.0, 104.0],
        "volume": [1, 1],
    })


def _base_bars():
    # Both bars fall on day1 -> pivots R1=110, PP=100 (from day0) apply.
    day1 = 86400
    return {
        "time": [day1 + 3 * 900, day1 + 4 * 900],
        "prev": dict(open=105.0, high=109.0, low=104.0, close=108.0),   # bullish, high < R1
        "cur": dict(open=106.0, high=111.0, low=103.0, close=104.0),    # bearish, engulfs prev, pokes R1, closes back below
    }


def _df_from(prev: dict, cur: dict, times):
    return pd.DataFrame({
        "time": times,
        "open": [prev["open"], cur["open"]],
        "high": [prev["high"], cur["high"]],
        "low": [prev["low"], cur["low"]],
        "close": [prev["close"], cur["close"]],
        "volume": [1, 1],
    })


def test_pattern_triggers_on_matching_bars():
    bars = _base_bars()
    df = _df_from(bars["prev"], bars["cur"], bars["time"])
    setups = PivotR1RejectionStrategy(_daily_df()).generate_setups(df)

    assert not setups.loc[0, "entry_signal"]
    assert setups.loc[1, "entry_signal"]
    assert setups.loc[1, "direction"] == -1
    assert abs(setups.loc[1, "stop_price"] - 111.0) < 1e-9   # the signal bar's own high
    assert abs(setups.loc[1, "target_price"] - 100.0) < 1e-9  # previous day's PP


def test_no_signal_when_previous_bar_is_bearish():
    bars = _base_bars()
    prev = dict(bars["prev"])
    prev["open"], prev["close"] = prev["close"], prev["open"]  # flip to bearish
    df = _df_from(prev, bars["cur"], bars["time"])
    setups = PivotR1RejectionStrategy(_daily_df()).generate_setups(df)
    assert not setups.loc[1, "entry_signal"]


def test_no_signal_when_current_bar_does_not_reach_r1():
    bars = _base_bars()
    cur = dict(bars["cur"])
    cur["high"] = 109.5  # below R1 (110)
    df = _df_from(bars["prev"], cur, bars["time"])
    setups = PivotR1RejectionStrategy(_daily_df()).generate_setups(df)
    assert not setups.loc[1, "entry_signal"]


def test_no_signal_when_current_bar_closes_above_r1():
    bars = _base_bars()
    cur = dict(bars["cur"])
    cur["close"] = 110.5  # closes above R1, no rejection
    df = _df_from(bars["prev"], cur, bars["time"])
    setups = PivotR1RejectionStrategy(_daily_df()).generate_setups(df)
    assert not setups.loc[1, "entry_signal"]


def test_no_signal_when_current_bar_is_bullish():
    bars = _base_bars()
    cur = dict(bars["cur"])
    cur["open"], cur["close"] = cur["close"], cur["open"]  # flip to bullish (open < close)
    df = _df_from(bars["prev"], cur, bars["time"])
    setups = PivotR1RejectionStrategy(_daily_df()).generate_setups(df)
    assert not setups.loc[1, "entry_signal"]


def test_target_level_s1_uses_support_one_instead_of_pivot():
    bars = _base_bars()
    df = _df_from(bars["prev"], bars["cur"], bars["time"])
    setups = PivotR1RejectionStrategy(_daily_df(), target_level="s1").generate_setups(df)
    # day0: H=110, L=90, PP=100 -> S1 = 2*100 - 110 = 90
    assert abs(setups.loc[1, "target_price"] - 90.0) < 1e-9


def test_invalid_target_level_rejected():
    with pytest.raises(ValueError):
        PivotR1RejectionStrategy(_daily_df(), target_level="not_a_level")
