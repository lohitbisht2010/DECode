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


def test_risk_based_sizing_matches_hand_calculation():
    df = pd.DataFrame({
        "time": [0, 900, 1800],
        "open": [100.0, 100.0, 105.0],
        "high": [100.0, 101.0, 106.0],
        "low": [100.0, 99.0, 104.0],
        "close": [100.0, 100.0, 105.0],
        "volume": [1, 1, 1],
    })
    # entry at 100, stop at 105 -> risk 5/unit. 1% of 10000 = 100 risk -> qty = 100/5 = 20
    setups = _setups(3, signal_index=0, stop=105.0, target=90.0)
    bt = PatternBacktester(fee_model=_zero_fee(), initial_capital=10000, leverage=10,
                            allocation_pct=100, risk_pct_per_trade=1.0)
    result = bt.run(df, setups)

    trade = result.trades[0]
    assert abs(trade.qty - 20.0) < 1e-9
    # stopped out -> loss should be exactly 1% of starting equity (100), before fees
    assert abs(trade.gross_pnl - (-100.0)) < 1e-6
    assert abs(result.final_equity - 9900.0) < 1e-6


def test_risk_based_sizing_capped_by_leverage_buying_power():
    df = pd.DataFrame({
        "time": [0, 900, 1800],
        "open": [100.0, 100.0, 100.1],
        "high": [100.0, 101.0, 100.2],
        "low": [100.0, 99.0, 99.0],
        "close": [100.0, 100.0, 99.5],
        "volume": [1, 1, 1],
    })
    # stop only 0.01 away -> uncapped qty would be (100 * 0.01) / 0.01 = 100 -> notional 10,000
    # but leverage=1 caps buying power at equity (10000), so qty should cap at 10000/100=100...
    # use a tighter risk to force the cap: 10% risk with a 0.01 stop distance -> huge desired qty.
    setups = _setups(3, signal_index=0, stop=100.01, target=90.0)
    bt = PatternBacktester(fee_model=_zero_fee(), initial_capital=10000, leverage=1,
                            allocation_pct=100, risk_pct_per_trade=10.0)
    result = bt.run(df, setups)

    trade = result.trades[0]
    max_qty = (10000 * 1) / 100.0  # equity * leverage / price
    assert abs(trade.qty - max_qty) < 1e-6


def test_risk_based_sizing_skips_trade_when_stop_equals_entry():
    df = pd.DataFrame({
        "time": [0, 900, 1800],
        "open": [100.0, 100.0, 100.0],
        "high": [100.0, 101.0, 101.0],
        "low": [100.0, 99.0, 99.0],
        "close": [100.0, 100.0, 100.0],
        "volume": [1, 1, 1],
    })
    # stop == entry price -> zero stop distance, undefined risk sizing
    setups = _setups(3, signal_index=0, stop=100.0, target=90.0)
    bt = PatternBacktester(fee_model=_zero_fee(), initial_capital=10000, leverage=1,
                            allocation_pct=100, risk_pct_per_trade=1.0)
    result = bt.run(df, setups)
    assert result.trades == []
    assert result.final_equity == 10000


def test_reward_multiple_overrides_setup_target_for_short():
    df = pd.DataFrame({
        "time": [0, 900, 1800],
        "open": [100.0, 100.0, 80.0],
        "high": [100.0, 101.0, 81.0],
        "low": [100.0, 99.0, 79.0],
        "close": [100.0, 100.0, 80.0],
        "volume": [1, 1, 1],
    })
    # entry 100, stop 105 -> risk 5/unit; reward_multiple=4 -> target should be 100 - 4*5 = 80,
    # NOT the setup's own target_price (90).
    setups = _setups(3, signal_index=0, stop=105.0, target=90.0)
    bt = PatternBacktester(fee_model=_zero_fee(), initial_capital=10000, leverage=10,
                            allocation_pct=100, reward_multiple=4.0)
    result = bt.run(df, setups)

    trade = result.trades[0]
    assert abs(trade.target_price - 80.0) < 1e-9


def test_reward_multiple_overrides_setup_target_for_long():
    df = pd.DataFrame({
        "time": [0, 900, 1800],
        "open": [100.0, 100.0, 120.0],
        "high": [100.0, 101.0, 121.0],
        "low": [100.0, 99.0, 119.0],
        "close": [100.0, 100.0, 120.0],
        "volume": [1, 1, 1],
    })
    # entry 100, stop 95 -> risk 5/unit; reward_multiple=4 -> target should be 100 + 4*5 = 120
    setups = _setups(3, signal_index=0, stop=95.0, target=110.0, direction=1)
    bt = PatternBacktester(fee_model=_zero_fee(), initial_capital=10000, leverage=10,
                            allocation_pct=100, reward_multiple=4.0)
    result = bt.run(df, setups)

    trade = result.trades[0]
    assert abs(trade.target_price - 120.0) < 1e-9


def test_risk_1pct_reward_4x_hits_target_for_4pct_equity_gain():
    df = pd.DataFrame({
        "time": [0, 900, 1800],
        "open": [100.0, 100.0, 80.0],
        "high": [100.0, 101.0, 81.0],
        "low": [100.0, 99.0, 79.0],
        "close": [100.0, 100.0, 80.0],
        "volume": [1, 1, 1],
    })
    # 1% risk sizing (qty = 100/5 = 20) + reward_multiple=4 (target=80) -> hitting target
    # should gain exactly 4% of starting equity, before fees.
    setups = _setups(3, signal_index=0, stop=105.0, target=999.0)  # setup target ignored
    bt = PatternBacktester(fee_model=_zero_fee(), initial_capital=10000, leverage=10,
                            risk_pct_per_trade=1.0, reward_multiple=4.0)
    result = bt.run(df, setups)

    trade = result.trades[0]
    assert trade.exit_reason == "target"
    assert abs(trade.gross_pnl - 400.0) < 1e-6  # 4% of 10000
    assert abs(result.final_equity - 10400.0) < 1e-6


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


def test_exit_signal_closes_at_next_bar_open():
    df = pd.DataFrame({
        "time": [0, 900, 1800, 2700],
        "open": [100.0, 100.0, 95.0, 90.0],
        "high": [100.0, 101.0, 96.0, 91.0],
        "low": [100.0, 99.0, 94.0, 89.0],
        "close": [100.0, 100.0, 95.0, 90.0],
        "volume": [1, 1, 1, 1],
    })
    setups = pd.DataFrame({
        "entry_signal": [True, False, False, False],
        "direction": [-1] * 4,
        "stop_price": [999.0] * 4,       # never hit
        "target_price": [float("nan")] * 4,  # no fixed target
        "exit_signal": [False, False, True, False],
    })
    bt = PatternBacktester(fee_model=_zero_fee(), initial_capital=10000, leverage=1, allocation_pct=100)
    result = bt.run(df, setups)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "signal_exit"
    assert trade.exit_price == 90.0  # filled at the bar *after* exit_signal fired
    assert abs(trade.gross_pnl - 1000.0) < 1e-9  # short 100 units 100->90
    assert abs(result.final_equity - 11000.0) < 1e-9


def test_stop_takes_priority_over_exit_signal_same_bar():
    df = pd.DataFrame({
        "time": [0, 900, 1800],
        "open": [100.0, 100.0, 107.0],
        "high": [100.0, 101.0, 108.0],
        "low": [100.0, 99.0, 104.0],
        "close": [100.0, 100.0, 105.0],
        "volume": [1, 1, 1],
    })
    setups = pd.DataFrame({
        "entry_signal": [True, False, False],
        "direction": [-1] * 3,
        "stop_price": [105.0] * 3,
        "target_price": [float("nan")] * 3,
        "exit_signal": [False, False, True],  # fires the same bar the stop is hit
    })
    bt = PatternBacktester(fee_model=_zero_fee(), initial_capital=10000, leverage=1, allocation_pct=100)
    result = bt.run(df, setups)
    assert result.trades[0].exit_reason == "stop"


def test_nan_target_never_triggers_a_target_exit():
    df = pd.DataFrame({
        "time": [0, 900, 1800, 2700, 3600],
        "open": [100.0, 100.0, 80.0, 60.0, 50.0],
        "high": [100.0, 101.0, 81.0, 61.0, 51.0],
        "low": [100.0, 99.0, 59.0, 49.0, 49.0],
        "close": [100.0, 100.0, 60.0, 50.0, 50.0],
        "volume": [1, 1, 1, 1, 1],
    })
    setups = _setups(5, signal_index=0, stop=999.0, target=float("nan"))
    bt = PatternBacktester(fee_model=_zero_fee(), initial_capital=10000, leverage=1, allocation_pct=100)
    result = bt.run(df, setups)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "eod_forced"  # never a "target" exit despite the huge favorable move
    assert trade.exit_price == 50.0


def _loss_cycle(entry_price=100.0, stop=101.0, target=float("nan")):
    """(signal_row, resolution_row) for a losing trade: entry then an
    immediate stop-out on the very next bar."""
    signal = dict(open=entry_price, high=entry_price, low=entry_price, close=entry_price,
                   entry_signal=True, stop=stop, target=target)
    resolve = dict(open=entry_price, high=stop + 1, low=entry_price - 1, close=entry_price,
                    entry_signal=False, stop=stop, target=target)
    return signal, resolve


def _win_cycle(entry_price=100.0, stop=105.0, target=95.0):
    """(signal_row, resolution_row) for a winning trade: entry then an
    immediate target-hit on the very next bar."""
    signal = dict(open=entry_price, high=entry_price, low=entry_price, close=entry_price,
                   entry_signal=True, stop=stop, target=target)
    resolve = dict(open=entry_price, high=entry_price + 1, low=target - 1, close=entry_price - 3,
                    entry_signal=False, stop=stop, target=target)
    return signal, resolve


def _build_from_cycles(cycles, start_time=0, step=900):
    """cycles: list of (signal_row, resolve_row) dict pairs -> (df, setups) with
    one bar per row, `step` seconds apart starting at `start_time`."""
    rows = [row for cycle in cycles for row in cycle]
    n = len(rows)
    times = [start_time + i * step for i in range(n)]
    df = pd.DataFrame({
        "time": times,
        "open": [r["open"] for r in rows],
        "high": [r["high"] for r in rows],
        "low": [r["low"] for r in rows],
        "close": [r["close"] for r in rows],
        "volume": [1] * n,
    })
    setups = pd.DataFrame({
        "entry_signal": [r["entry_signal"] for r in rows],
        "direction": [-1] * n,
        "stop_price": [r["stop"] for r in rows],
        "target_price": [r["target"] for r in rows],
    })
    return df, setups


def test_blocks_new_entries_after_n_consecutive_losses_same_day():
    cycles = [_loss_cycle(), _loss_cycle(), _loss_cycle()]
    df, setups = _build_from_cycles(cycles)
    # append one more signal bar (should be blocked) + a flat filler bar, same day
    extra = pd.DataFrame({
        "time": [df["time"].iloc[-1] + 900, df["time"].iloc[-1] + 1800],
        "open": [100.0, 100.0], "high": [100.0, 100.0], "low": [100.0, 100.0], "close": [100.0, 100.0],
        "volume": [1, 1],
    })
    extra_setups = pd.DataFrame({
        "entry_signal": [True, False], "direction": [-1, -1],
        "stop_price": [101.0, 101.0], "target_price": [float("nan"), float("nan")],
    })
    df = pd.concat([df, extra], ignore_index=True)
    setups = pd.concat([setups, extra_setups], ignore_index=True)

    bt = PatternBacktester(fee_model=_zero_fee(), initial_capital=10000, leverage=1,
                            allocation_pct=100, max_consecutive_losses_per_day=3)
    result = bt.run(df, setups)

    assert len(result.trades) == 3  # the 4th signal never opened a trade
    assert all(t.exit_reason == "stop" for t in result.trades)


def test_no_block_without_the_cap_set():
    cycles = [_loss_cycle(), _loss_cycle(), _loss_cycle(), _loss_cycle()]
    df, setups = _build_from_cycles(cycles)
    bt = PatternBacktester(fee_model=_zero_fee(), initial_capital=10000, leverage=1, allocation_pct=100)
    result = bt.run(df, setups)
    assert len(result.trades) == 4  # no cap -> all four losing cycles trade


def test_block_resets_at_next_day_boundary():
    cycles = [_loss_cycle(), _loss_cycle(), _loss_cycle()]
    df, setups = _build_from_cycles(cycles)  # 3 losses, all on day 0

    day1_start = 86400
    day1 = pd.DataFrame({
        "time": [day1_start, day1_start + 900],
        "open": [100.0, 100.0], "high": [100.0, 200.0], "low": [100.0, 100.0], "close": [100.0, 150.0],
        "volume": [1, 1],
    })
    day1_setups = pd.DataFrame({
        "entry_signal": [True, False], "direction": [-1, -1],
        "stop_price": [999.0, 999.0], "target_price": [float("nan"), float("nan")],
    })
    df = pd.concat([df, day1], ignore_index=True)
    setups = pd.concat([setups, day1_setups], ignore_index=True)

    bt = PatternBacktester(fee_model=_zero_fee(), initial_capital=10000, leverage=1,
                            allocation_pct=100, max_consecutive_losses_per_day=3)
    result = bt.run(df, setups)

    assert len(result.trades) == 4  # 3 losses on day 0, then a 4th trade opens fine on day 1


def test_winning_trade_resets_the_streak():
    # L, L, W, L, L - never 3 losses in a row, so a 6th signal should still open.
    cycles = [_loss_cycle(), _loss_cycle(), _win_cycle(), _loss_cycle(), _loss_cycle()]
    df, setups = _build_from_cycles(cycles)
    extra = pd.DataFrame({
        "time": [df["time"].iloc[-1] + 900, df["time"].iloc[-1] + 1800],
        "open": [100.0, 100.0], "high": [100.0, 200.0], "low": [100.0, 100.0], "close": [100.0, 150.0],
        "volume": [1, 1],
    })
    extra_setups = pd.DataFrame({
        "entry_signal": [True, False], "direction": [-1, -1],
        "stop_price": [999.0, 999.0], "target_price": [float("nan"), float("nan")],
    })
    df = pd.concat([df, extra], ignore_index=True)
    setups = pd.concat([setups, extra_setups], ignore_index=True)

    bt = PatternBacktester(fee_model=_zero_fee(), initial_capital=10000, leverage=1,
                            allocation_pct=100, max_consecutive_losses_per_day=3)
    result = bt.run(df, setups)

    assert len(result.trades) == 6  # all 5 cycles plus the 6th signal, never blocked
