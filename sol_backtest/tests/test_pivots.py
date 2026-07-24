import pandas as pd

from sol_backtest.pivots import (
    attach_pivots,
    attach_previous_day_pivots,
    attach_previous_month_pivots,
    compute_daily_pivots,
    compute_monthly_pivots,
)


def _daily_df():
    # day0: H=110, L=90, C=100 -> PP=100, R1=110, S1=90, R2=120, S2=80, R3=130, S3=70
    # day1: H=108, L=98, C=104 -> PP=103.333..., R1=108.666..., S1=98.666...
    return pd.DataFrame({
        "time": [0, 86400],
        "open": [95.0, 100.0],
        "high": [110.0, 108.0],
        "low": [90.0, 98.0],
        "close": [100.0, 104.0],
        "volume": [1, 1],
    })


def test_compute_daily_pivots_matches_floor_trader_formula():
    pivots = compute_daily_pivots(_daily_df())
    day0 = pivots.iloc[0]
    assert abs(day0["pp"] - 100.0) < 1e-9
    assert abs(day0["r1"] - 110.0) < 1e-9
    assert abs(day0["s1"] - 90.0) < 1e-9
    assert abs(day0["r2"] - 120.0) < 1e-9
    assert abs(day0["s2"] - 80.0) < 1e-9
    assert abs(day0["r3"] - 130.0) < 1e-9
    assert abs(day0["s3"] - 70.0) < 1e-9


def test_attach_previous_day_pivots_uses_prior_day_and_nans_first_day():
    daily = _daily_df()
    intraday = pd.DataFrame({
        "time": [0, 43200, 86400 + 3600],  # bar0: day0 (no prior day); bar2: day1, should use day0's pivots
        "open": [1, 1, 1], "high": [1, 1, 1], "low": [1, 1, 1], "close": [1, 1, 1], "volume": [1, 1, 1],
    })
    out = attach_previous_day_pivots(intraday, daily)
    assert pd.isna(out.loc[0, "pivot_pp"])
    assert pd.isna(out.loc[1, "pivot_pp"])
    assert abs(out.loc[2, "pivot_r1"] - 110.0) < 1e-9
    assert abs(out.loc[2, "pivot_pp"] - 100.0) < 1e-9


def _monthly_daily_df():
    # January 2025: open=100 (day1's open), high=130 (day15), low=70 (day31), close=100 (day31's close)
    # -> PP=100, R1=130, S1=70, R2=160, S2=40, R3=190, S3=10
    jan1 = 1735689600     # 2025-01-01 00:00:00 UTC
    jan15 = jan1 + 14 * 86400
    jan31 = jan1 + 30 * 86400
    return pd.DataFrame({
        "time": [jan1, jan15, jan31],
        "open": [100.0, 102.0, 110.0],
        "high": [105.0, 130.0, 112.0],
        "low": [95.0, 101.0, 70.0],
        "close": [102.0, 110.0, 100.0],
        "volume": [1, 1, 1],
    })


def test_compute_monthly_pivots_aggregates_open_high_low_close_across_the_month():
    pivots = compute_monthly_pivots(_monthly_daily_df())
    january = pivots.iloc[0]
    assert abs(january["pp"] - 100.0) < 1e-9
    assert abs(january["r1"] - 130.0) < 1e-9
    assert abs(january["s1"] - 70.0) < 1e-9
    assert abs(january["r2"] - 160.0) < 1e-9
    assert abs(january["s2"] - 40.0) < 1e-9
    assert abs(january["r3"] - 190.0) < 1e-9
    assert abs(january["s3"] - 10.0) < 1e-9


def test_attach_previous_month_pivots_uses_prior_month_for_every_bar_in_the_current_month():
    daily = _monthly_daily_df()
    jan1 = 1735689600
    feb1 = jan1 + 31 * 86400
    feb5 = feb1 + 4 * 86400 + 1800
    feb20 = feb1 + 19 * 86400
    intraday = pd.DataFrame({
        "time": [jan1 + 3600, feb5, feb20],  # bar0: still January (no prior month); bar1/2: February
        "open": [1, 1, 1], "high": [1, 1, 1], "low": [1, 1, 1], "close": [1, 1, 1], "volume": [1, 1, 1],
    })
    out = attach_previous_month_pivots(intraday, daily)

    assert pd.isna(out.loc[0, "pivot_pp"])
    assert abs(out.loc[1, "pivot_r1"] - 130.0) < 1e-9
    assert abs(out.loc[2, "pivot_r1"] - 130.0) < 1e-9  # same month -> same (January) pivots regardless of day


def test_attach_pivots_dispatches_by_period_name():
    daily = _monthly_daily_df()
    feb5 = 1735689600 + 35 * 86400
    intraday = pd.DataFrame({
        "time": [feb5], "open": [1], "high": [1], "low": [1], "close": [1], "volume": [1],
    })
    monthly_result = attach_pivots(intraday, daily, period="monthly")
    assert abs(monthly_result.loc[0, "pivot_r1"] - 130.0) < 1e-9

    import pytest
    with pytest.raises(ValueError):
        attach_pivots(intraday, daily, period="weekly")
