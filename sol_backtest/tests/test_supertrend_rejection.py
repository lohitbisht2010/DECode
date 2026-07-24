from unittest.mock import patch

import pandas as pd

from sol_backtest.strategies.supertrend_rejection import SupertrendRejectionStrategy


def _df():
    # bar0: prev (bullish, high 99.5). bar1: rejection candle vs a
    # supertrend value of 100 injected via the mocked indicator below.
    return pd.DataFrame({
        "time": [0, 900],
        "open": [95.0, 96.0],
        "high": [99.5, 101.0],
        "low": [94.0, 93.0],
        "close": [99.0, 94.0],
        "volume": [1, 1],
    })


def _fake_supertrend(trend_at_bar1: int, supertrend_at_bar1: float = 100.0):
    return pd.DataFrame({
        "supertrend": [105.0, supertrend_at_bar1],
        "trend": [-1, trend_at_bar1],
    })


def test_pattern_triggers_in_downtrend_with_rejection_at_supertrend():
    with patch(
        "sol_backtest.strategies.supertrend_rejection.compute_supertrend",
        return_value=_fake_supertrend(trend_at_bar1=-1),
    ):
        setups = SupertrendRejectionStrategy().generate_setups(_df())

    assert setups.loc[1, "entry_signal"]
    assert setups.loc[1, "direction"] == -1
    assert abs(setups.loc[1, "stop_price"] - 101.0) < 1e-9  # signal bar's own high
    assert pd.isna(setups.loc[1, "target_price"])            # no fixed target
    assert not setups.loc[1, "exit_signal"]                  # still downtrend


def test_no_signal_when_trend_is_up_despite_matching_candle_shape():
    with patch(
        "sol_backtest.strategies.supertrend_rejection.compute_supertrend",
        return_value=_fake_supertrend(trend_at_bar1=1),
    ):
        setups = SupertrendRejectionStrategy().generate_setups(_df())
    assert not setups.loc[1, "entry_signal"]


def test_no_signal_when_price_does_not_reach_supertrend_line():
    with patch(
        "sol_backtest.strategies.supertrend_rejection.compute_supertrend",
        return_value=_fake_supertrend(trend_at_bar1=-1, supertrend_at_bar1=150.0),
    ):
        setups = SupertrendRejectionStrategy().generate_setups(_df())
    assert not setups.loc[1, "entry_signal"]  # bar1 high (101) never reaches 150


def test_exit_signal_flags_every_bar_where_trend_flips_bullish():
    fake = pd.DataFrame({
        "supertrend": [105.0, 104.0, 103.0, 102.0],
        "trend": [-1, -1, 1, 1],
    })
    df = pd.DataFrame({
        "time": [0, 900, 1800, 2700],
        "open": [100.0, 99.0, 98.0, 103.0],
        "high": [101.0, 100.0, 105.0, 106.0],
        "low": [98.0, 97.0, 97.0, 102.0],
        "close": [99.0, 98.0, 104.0, 105.0],
        "volume": [1, 1, 1, 1],
    })
    with patch("sol_backtest.strategies.supertrend_rejection.compute_supertrend", return_value=fake):
        setups = SupertrendRejectionStrategy().generate_setups(df)

    assert list(setups["exit_signal"]) == [False, False, True, True]
