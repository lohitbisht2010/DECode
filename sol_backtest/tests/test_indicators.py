import pandas as pd

from sol_backtest.indicators import compute_atr, compute_supertrend


def test_compute_atr_matches_hand_calculation():
    # period=1 -> Wilder-smoothed ATR degenerates to each bar's own True Range.
    df = pd.DataFrame({
        "high": [10.0, 12.0, 11.0, 15.0],
        "low": [8.0, 9.0, 10.0, 10.0],
        "close": [9.0, 11.0, 10.0, 14.0],
    })
    atr = compute_atr(df, period=1)
    # TR0 = max(10-8, |10-9|, |8-9|) = 2; TR1 = max(12-9,|12-9|,|9-9|) = 3
    # TR2 = max(11-10,|11-11|,|10-11|) = 1; TR3 = max(15-10,|15-10|,|10-10|) = 5
    expected = [2.0, 3.0, 1.0, 5.0]
    for i in range(len(df)):
        assert abs(atr.iloc[i] - expected[i]) < 1e-9


def test_compute_atr_warmup_period_is_nan():
    df = pd.DataFrame({
        "high": [10.0, 12.0, 11.0],
        "low": [8.0, 9.0, 10.0],
        "close": [9.0, 11.0, 10.0],
    })
    atr = compute_atr(df, period=10)
    assert atr.isna().all()


def test_compute_supertrend_matches_hand_calculation():
    # period=1 makes Wilder-smoothed ATR degenerate to the bar's own True
    # Range, so every value here is hand-traceable through the sticky-band
    # recursion (see the derivation in the PR/commit description).
    df = pd.DataFrame({
        "high": [10.0, 12.0, 11.0, 15.0],
        "low": [8.0, 9.0, 10.0, 10.0],
        "close": [9.0, 11.0, 10.0, 14.0],
    })
    result = compute_supertrend(df, period=1, multiplier=1.0)

    expected_supertrend = [11.0, 11.0, 11.0, 9.5]
    expected_trend = [-1, -1, -1, 1]

    for i in range(len(df)):
        assert abs(result["supertrend"].iloc[i] - expected_supertrend[i]) < 1e-9
        assert result["trend"].iloc[i] == expected_trend[i]


def test_supertrend_warmup_period_is_nan():
    df = pd.DataFrame({
        "high": [10.0, 12.0, 11.0],
        "low": [8.0, 9.0, 10.0],
        "close": [9.0, 11.0, 10.0],
    })
    result = compute_supertrend(df, period=10, multiplier=3.0)
    assert result["supertrend"].isna().all()
    assert (result["trend"] == 0).all()


def test_supertrend_downtrend_line_sits_above_price():
    # A steadily falling series should settle into trend=-1 with the
    # supertrend line above the closes it's resisting.
    closes = [100 - i for i in range(30)]
    df = pd.DataFrame({
        "high": [c + 1 for c in closes],
        "low": [c - 1 for c in closes],
        "close": closes,
    })
    result = compute_supertrend(df, period=5, multiplier=2.0)
    tail = result.iloc[-5:]
    assert (tail["trend"] == -1).all()
    assert (tail["supertrend"] > df["close"].iloc[-5:]).all()
