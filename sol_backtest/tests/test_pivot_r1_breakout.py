import pandas as pd
import pytest

from sol_backtest.strategies.pivot_r1_breakout import PivotR1BreakoutStrategy


def _daily_df():
    # day0 (time=0): H=110, L=90, C=100 -> PP=100, R1=110, R2=120 - these are the
    # pivots that apply to every 15m bar on day1 (time in [86400, 172800)).
    return pd.DataFrame({
        "time": [0, 86400],
        "open": [95.0, 100.0],
        "high": [110.0, 108.0],
        "low": [90.0, 98.0],
        "close": [100.0, 104.0],
        "volume": [1, 1],
    })


def _base_bars():
    day1 = 86400
    return {
        "time": [day1 + 3 * 900, day1 + 4 * 900],
        "prev": dict(open=107.0, high=109.0, low=106.0, close=108.0),   # closed below R1 (110)
        "cur": dict(open=109.0, high=113.0, low=108.0, close=112.0),    # closes above R1, bullish, new high
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
    setups = PivotR1BreakoutStrategy(_daily_df()).generate_setups(df)

    assert not setups.loc[0, "entry_signal"]
    assert setups.loc[1, "entry_signal"]
    assert setups.loc[1, "direction"] == 1
    assert abs(setups.loc[1, "stop_price"] - 108.0) < 1e-9    # the signal bar's own low
    assert abs(setups.loc[1, "target_price"] - 120.0) < 1e-9  # previous day's R2 (default target)


def test_no_signal_when_r1_already_broken_on_previous_bar():
    bars = _base_bars()
    prev = dict(bars["prev"])
    prev["close"] = 111.0  # already closed above R1 - not the *first* breakout bar
    df = _df_from(prev, bars["cur"], bars["time"])
    setups = PivotR1BreakoutStrategy(_daily_df()).generate_setups(df)
    assert not setups.loc[1, "entry_signal"]


def test_no_signal_when_current_bar_does_not_close_above_r1():
    bars = _base_bars()
    cur = dict(bars["cur"])
    cur["close"] = 109.5  # still below R1 (110)
    df = _df_from(bars["prev"], cur, bars["time"])
    setups = PivotR1BreakoutStrategy(_daily_df()).generate_setups(df)
    assert not setups.loc[1, "entry_signal"]


def test_no_signal_when_current_bar_is_bearish():
    bars = _base_bars()
    cur = dict(bars["cur"])
    cur["open"], cur["close"] = cur["close"], cur["open"]  # flip to bearish
    df = _df_from(bars["prev"], cur, bars["time"])
    setups = PivotR1BreakoutStrategy(_daily_df()).generate_setups(df)
    assert not setups.loc[1, "entry_signal"]


def test_no_signal_when_no_new_high():
    bars = _base_bars()
    cur = dict(bars["cur"])
    cur["high"] = 109.0  # doesn't exceed prev.high (109) - no momentum confirmation
    df = _df_from(bars["prev"], cur, bars["time"])
    setups = PivotR1BreakoutStrategy(_daily_df()).generate_setups(df)
    assert not setups.loc[1, "entry_signal"]


def test_target_level_r3_uses_third_resistance_instead_of_r2():
    bars = _base_bars()
    df = _df_from(bars["prev"], bars["cur"], bars["time"])
    setups = PivotR1BreakoutStrategy(_daily_df(), target_level="r3").generate_setups(df)
    # day0: H=110, L=90, PP=100 -> R3 = H + 2*(PP-L) = 110 + 2*(100-90) = 130
    assert abs(setups.loc[1, "target_price"] - 130.0) < 1e-9


def test_invalid_target_level_rejected():
    with pytest.raises(ValueError):
        PivotR1BreakoutStrategy(_daily_df(), target_level="not_a_level")
