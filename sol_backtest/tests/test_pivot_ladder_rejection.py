import pandas as pd

from sol_backtest.strategies.pivot_ladder_rejection import PivotLadderRejectionStrategy


def _daily_df():
    # day0 (time=0): H=130, L=70, C=100 -> round-number ladder:
    # R3=190, R2=160, R1=130, PP=100, S1=70, S2=40, S3=10
    # these apply to every 15m bar on day1 (time in [86400, 172800)).
    return pd.DataFrame({
        "time": [0, 86400],
        "open": [95.0, 100.0],
        "high": [130.0, 108.0],
        "low": [70.0, 98.0],
        "close": [100.0, 104.0],
        "volume": [1, 1],
    })


def _bar_pair(prev, cur, day1=86400):
    return pd.DataFrame({
        "time": [day1 + 3 * 900, day1 + 4 * 900],
        "open": [prev["open"], cur["open"]],
        "high": [prev["high"], cur["high"]],
        "low": [prev["low"], cur["low"]],
        "close": [prev["close"], cur["close"]],
        "volume": [1, 1],
    })


def test_rejection_at_pp_targets_s1():
    prev = dict(open=95.0, high=99.5, low=94.0, close=99.0)
    cur = dict(open=96.0, high=101.0, low=93.0, close=94.0)
    df = _bar_pair(prev, cur)
    setups = PivotLadderRejectionStrategy(_daily_df()).generate_setups(df)

    assert setups.loc[1, "entry_signal"]
    assert setups.loc[1, "direction"] == -1
    assert abs(setups.loc[1, "stop_price"] - 101.0) < 1e-9
    assert abs(setups.loc[1, "target_price"] - 70.0) < 1e-9  # S1
    assert setups.loc[1, "tag"] == "pp"


def test_rejection_at_s1_targets_s2():
    prev = dict(open=65.0, high=69.5, low=60.0, close=69.0)
    cur = dict(open=66.0, high=71.0, low=59.0, close=64.0)
    df = _bar_pair(prev, cur)
    setups = PivotLadderRejectionStrategy(_daily_df()).generate_setups(df)

    assert setups.loc[1, "entry_signal"]
    assert abs(setups.loc[1, "target_price"] - 40.0) < 1e-9  # S2
    assert setups.loc[1, "tag"] == "s1"


def test_rejection_at_s2_targets_s3():
    prev = dict(open=35.0, high=39.5, low=30.0, close=39.0)
    cur = dict(open=36.0, high=41.0, low=29.0, close=34.0)
    df = _bar_pair(prev, cur)
    setups = PivotLadderRejectionStrategy(_daily_df()).generate_setups(df)

    assert setups.loc[1, "entry_signal"]
    assert abs(setups.loc[1, "target_price"] - 10.0) < 1e-9  # S3
    assert setups.loc[1, "tag"] == "s2"


def test_rejection_at_r1_targets_pp():
    prev = dict(open=125.0, high=129.5, low=120.0, close=129.0)
    cur = dict(open=126.0, high=131.0, low=119.0, close=124.0)
    df = _bar_pair(prev, cur)
    setups = PivotLadderRejectionStrategy(_daily_df()).generate_setups(df)

    assert setups.loc[1, "entry_signal"]
    assert abs(setups.loc[1, "target_price"] - 100.0) < 1e-9  # PP
    assert setups.loc[1, "tag"] == "r1"


def test_higher_level_takes_priority_when_both_r1_and_r2_conditions_met():
    # high (165) clears both R1 (130) and R2 (160); close (125) is below both.
    prev = dict(open=125.0, high=129.5, low=120.0, close=129.0)
    cur = dict(open=126.0, high=165.0, low=119.0, close=125.0)
    df = _bar_pair(prev, cur)
    setups = PivotLadderRejectionStrategy(_daily_df()).generate_setups(df)

    assert setups.loc[1, "entry_signal"]
    assert setups.loc[1, "tag"] == "r2"                          # not r1
    assert abs(setups.loc[1, "target_price"] - 130.0) < 1e-9      # R1, not PP


def test_no_signal_when_no_level_is_rejected():
    prev = dict(open=101.0, high=102.0, low=100.0, close=101.5)
    cur = dict(open=101.5, high=102.5, low=101.0, close=101.2)  # never near any pivot level
    df = _bar_pair(prev, cur)
    setups = PivotLadderRejectionStrategy(_daily_df()).generate_setups(df)
    assert not setups.loc[1, "entry_signal"]
