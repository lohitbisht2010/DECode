import pandas as pd

from sol_backtest.strategies.donchian_trend import DonchianTrendStrategy


def _df():
    return pd.DataFrame({
        "time": [0, 900, 1800, 2700, 3600],
        "open": [9.0, 10.0, 8.0, 16.0, 5.0],
        "high": [10.0, 11.0, 9.0, 20.0, 6.0],
        "low": [8.0, 9.0, 7.0, 15.0, 4.0],
        "close": [9.0, 10.0, 8.0, 19.0, 5.0],
        "volume": [1, 1, 1, 1, 1],
    })


def test_long_signal_on_close_breakout_above_prior_n_bar_high():
    setups = DonchianTrendStrategy(entry_period=3, atr_period=1).generate_setups(_df())
    # rolling_high(3).shift(1) at bar3 = max(high[0:3]) = 11; close3 = 19 > 11
    assert setups.loc[3, "entry_signal"]
    assert setups.loc[3, "direction"] == 1
    assert not pd.isna(setups.loc[3, "stop_price"])
    assert setups.loc[3, "stop_price"] < 19.0  # stop sits below entry for a long


def test_short_signal_on_close_breakdown_below_prior_n_bar_low():
    setups = DonchianTrendStrategy(entry_period=3, atr_period=1).generate_setups(_df())
    # rolling_low(3).shift(1) at bar4 = min(low[1:4]) = 7; close4 = 5 < 7
    assert setups.loc[4, "entry_signal"]
    assert setups.loc[4, "direction"] == -1
    assert setups.loc[4, "stop_price"] > 5.0  # stop sits above entry for a short


def test_short_disabled_when_allow_short_is_false():
    setups = DonchianTrendStrategy(entry_period=3, atr_period=1, allow_short=False).generate_setups(_df())
    assert not setups.loc[4, "entry_signal"]


def test_no_target_price_rides_the_trailing_stop_instead():
    setups = DonchianTrendStrategy(entry_period=3, atr_period=1).generate_setups(_df())
    assert setups["target_price"].isna().all()


def test_atr_column_present_for_engine_trailing_stop():
    setups = DonchianTrendStrategy(entry_period=3, atr_period=1).generate_setups(_df())
    assert "atr" in setups.columns
    assert not setups["atr"].isna().any()


def test_no_entry_signal_during_atr_warmup_even_if_breakout_matches():
    setups = DonchianTrendStrategy(entry_period=3, atr_period=10).generate_setups(_df())
    assert not setups["entry_signal"].any()
