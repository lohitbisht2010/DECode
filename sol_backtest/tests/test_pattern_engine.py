import pandas as pd

from sol_backtest.backtest.pattern_engine import PatternBacktester
from sol_backtest.fees import FeeModel


def _zero_fee():
    return FeeModel(maker_fee_pct=0.0, taker_fee_pct=0.0, gst_pct=0.0)


def _flat_fee():
    return FeeModel(maker_fee_pct=1.0, taker_fee_pct=1.0, gst_pct=0.0)  # 1% taker, no GST


def _setups(n, signal_index, stop, target, direction=-1):
    entry_signal = [False] * n
    entry_signal[signal_index] = True
    return pd.DataFrame({
        "entry_signal": entry_signal,
        "direction": [direction] * n,
        "stop_price": [stop] * n,
        "target_price": [target] * n,
    })


def test_short_trade_hits_target():
    df = pd.DataFrame({
        "time": [0, 900, 1800, 2700],
        "open": [100.0, 100.0, 95.0, 92.0],
        "high": [100.0, 101.0, 96.0, 93.0],
        "low": [100.0, 99.0, 93.0, 91.0],   # bar2's low (93) touches target (93)
        "close": [100.0, 100.0, 94.0, 92.0],
        "volume": [1, 1, 1, 1],
    })
    # signal on bar 0 (high=100, this is the pattern bar) -> entry at bar1's open (100)
    setups = _setups(4, signal_index=0, stop=102.0, target=93.0)
    bt = PatternBacktester(fee_model=_zero_fee(), initial_capital=10000, leverage=1, allocation_pct=100)
    result = bt.run(df, setups)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_price == 100.0
    assert trade.exit_reason == "target"
    assert trade.exit_price == 93.0
    # short 100 units (10000/100) at 100, cover at 93 -> gross pnl = (93-100)*100*(-1) = 700
    assert abs(trade.gross_pnl - 700.0) < 1e-9
    assert abs(result.final_equity - 10700.0) < 1e-9


def test_short_trade_hits_stop():
    df = pd.DataFrame({
        "time": [0, 900, 1800],
        "open": [100.0, 100.0, 103.0],
        "high": [100.0, 101.0, 106.0],   # bar2's high (106) touches stop (105)
        "low": [100.0, 99.0, 102.0],
        "close": [100.0, 100.0, 105.0],
        "volume": [1, 1, 1],
    })
    setups = _setups(3, signal_index=0, stop=105.0, target=90.0)
    bt = PatternBacktester(fee_model=_zero_fee(), initial_capital=10000, leverage=1, allocation_pct=100)
    result = bt.run(df, setups)

    trade = result.trades[0]
    assert trade.exit_reason == "stop"
    assert trade.exit_price == 105.0
    # short 100 units at 100, stopped at 105 -> gross pnl = (105-100)*100*(-1) = -500
    assert abs(trade.gross_pnl - (-500.0)) < 1e-9


def test_stop_wins_when_both_stop_and_target_hit_same_bar():
    df = pd.DataFrame({
        "time": [0, 900, 1800],
        "open": [100.0, 100.0, 100.0],
        "high": [100.0, 101.0, 106.0],  # hits stop (105)
        "low": [100.0, 99.0, 89.0],     # also hits target (90) in the same bar
        "close": [100.0, 100.0, 95.0],
        "volume": [1, 1, 1],
    })
    setups = _setups(3, signal_index=0, stop=105.0, target=90.0)
    bt = PatternBacktester(fee_model=_zero_fee(), initial_capital=10000, leverage=1, allocation_pct=100)
    result = bt.run(df, setups)
    assert result.trades[0].exit_reason == "stop"


def test_fees_charged_once_per_leg_no_double_count():
    df = pd.DataFrame({
        "time": [0, 900, 1800],
        "open": [100.0, 100.0, 93.0],
        "high": [100.0, 101.0, 94.0],
        "low": [100.0, 99.0, 93.0],
        "close": [100.0, 100.0, 93.0],
        "volume": [1, 1, 1],
    })
    setups = _setups(3, signal_index=0, stop=110.0, target=93.0)
    bt = PatternBacktester(fee_model=_flat_fee(), initial_capital=10000, leverage=1, allocation_pct=100)
    result = bt.run(df, setups)

    trade = result.trades[0]
    assert abs(trade.entry_fee - 100.0) < 1e-9   # 1% of 10000 notional
    assert abs(trade.exit_fee - 93.0) < 1e-9      # 1% of 93*100=9300 notional
    expected_equity = 10000 - 100 + 700 - 93  # capital - entry_fee + gross_pnl - exit_fee
    assert abs(result.final_equity - expected_equity) < 1e-6


def test_no_signal_never_opens_a_trade():
    df = pd.DataFrame({
        "time": [0, 900, 1800],
        "open": [100.0, 100.0, 100.0],
        "high": [100.0, 100.0, 100.0],
        "low": [100.0, 100.0, 100.0],
        "close": [100.0, 100.0, 100.0],
        "volume": [1, 1, 1],
    })
    setups = pd.DataFrame({
        "entry_signal": [False, False, False],
        "direction": [-1, -1, -1],
        "stop_price": [110.0, 110.0, 110.0],
        "target_price": [90.0, 90.0, 90.0],
    })
    bt = PatternBacktester(fee_model=_flat_fee(), initial_capital=10000, leverage=1, allocation_pct=100)
    result = bt.run(df, setups)
    assert result.trades == []
    assert result.final_equity == 10000


def test_open_trade_force_closed_at_end_of_data():
    df = pd.DataFrame({
        "time": [0, 900, 1800],
        "open": [100.0, 100.0, 98.0],
        "high": [100.0, 101.0, 99.0],
        "low": [100.0, 99.0, 97.0],
        "close": [100.0, 100.0, 97.0],
        "volume": [1, 1, 1],
    })
    # stop/target far away so neither is hit before data ends
    setups = _setups(3, signal_index=0, stop=200.0, target=1.0)
    bt = PatternBacktester(fee_model=_zero_fee(), initial_capital=10000, leverage=1, allocation_pct=100)
    result = bt.run(df, setups)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "eod_forced"
    assert trade.exit_price == 97.0  # last close
