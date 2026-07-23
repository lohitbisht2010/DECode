import pandas as pd

from sol_backtest.backtest.engine import Backtester
from sol_backtest.fees import FeeModel


def _zero_fee_model():
    return FeeModel(maker_fee_pct=0.0, taker_fee_pct=0.0, gst_pct=0.0)


def _flat_fee_model():
    # 1% taker fee, no GST, to keep hand-calculated expectations simple.
    return FeeModel(maker_fee_pct=1.0, taker_fee_pct=1.0, gst_pct=0.0)


def _df():
    return pd.DataFrame({
        "time": [0, 3600, 7200, 10800],
        "open": [100.0, 100.0, 104.0, 110.0],
        "high": [100.0, 104.0, 106.0, 111.0],
        "low": [100.0, 99.0, 103.0, 109.0],
        "close": [100.0, 102.0, 105.0, 111.0],
        "volume": [1, 1, 1, 1],
    })


def test_no_fee_long_trade_matches_hand_calculation():
    df = _df()
    signals = pd.Series([0, 1, 1, 0])
    bt = Backtester(fee_model=_zero_fee_model(), initial_capital=10000, leverage=1, allocation_pct=100)
    result = bt.run(df, signals)

    # Enter at bar 1's open (100), exit at bar 3's open (110): qty = 10000/100 = 100
    # gross pnl = (110 - 100) * 100 = 1000, no fees.
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_price == 100.0
    assert trade.exit_price == 110.0
    assert abs(trade.qty - 100.0) < 1e-9
    assert abs(trade.gross_pnl - 1000.0) < 1e-9
    assert abs(result.final_equity - 11000.0) < 1e-9


def test_fees_reduce_equity_by_exactly_both_legs_once():
    df = _df()
    signals = pd.Series([0, 1, 1, 0])
    bt = Backtester(fee_model=_flat_fee_model(), initial_capital=10000, leverage=1, allocation_pct=100)
    result = bt.run(df, signals)

    trade = result.trades[0]
    # entry notional = 10000 -> fee = 100; exit notional = 110*100=11000 -> fee = 110
    assert abs(trade.entry_fee - 100.0) < 1e-9
    assert abs(trade.exit_fee - 110.0) < 1e-9
    # final equity = 10000 - 100 (entry fee) + 1000 (gross pnl) - 110 (exit fee)
    expected_equity = 10000 - 100 + 1000 - 110
    assert abs(result.final_equity - expected_equity) < 1e-6
    # and it should NOT equal the double-counted (buggy) value
    buggy_equity = 10000 - 100 + (1000 - 100 - 110)
    assert abs(result.final_equity - buggy_equity) > 1.0


def test_flat_signal_throughout_keeps_capital_unchanged():
    df = _df()
    signals = pd.Series([0, 0, 0, 0])
    bt = Backtester(fee_model=_flat_fee_model(), initial_capital=10000, leverage=1, allocation_pct=100)
    result = bt.run(df, signals)
    assert result.trades == []
    assert abs(result.final_equity - 10000.0) < 1e-9


def test_short_trade_profits_when_price_falls():
    df = pd.DataFrame({
        "time": [0, 3600, 7200],
        "open": [100.0, 100.0, 90.0],
        "high": [100.0, 100.0, 91.0],
        "low": [100.0, 89.0, 89.0],
        "close": [100.0, 95.0, 90.0],
        "volume": [1, 1, 1],
    })
    signals = pd.Series([0, -1, 0])
    bt = Backtester(fee_model=_zero_fee_model(), initial_capital=10000, leverage=1, allocation_pct=100)
    result = bt.run(df, signals)

    trade = result.trades[0]
    assert trade.direction == -1
    # short 100 units at 100, cover at 90 -> gross pnl = (90-100)*100*(-1) = 1000
    assert abs(trade.gross_pnl - 1000.0) < 1e-9
    assert abs(result.final_equity - 11000.0) < 1e-9
