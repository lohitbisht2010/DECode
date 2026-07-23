import pandas as pd

from sol_backtest.pivots import attach_previous_day_pivots, compute_daily_pivots


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
