from unittest.mock import patch

import pandas as pd

from option_backtest.backtest.engine import StrangleBacktester
from option_backtest.fees import OptionFeeModel
from option_backtest.strategy.short_strangle import StrangleSetup


def _zero_fee():
    return OptionFeeModel(maker_fee_pct=0.0, taker_fee_pct=0.0, gst_pct=0.0)


def _setup(entry_time=0, settlement_time=21600, call_strike=68000.0, put_strike=62000.0,
           contract_value=0.001, spot_at_entry=65000.0):
    return StrangleSetup(
        settlement_time=settlement_time, entry_time=entry_time,
        call_symbol="C-BTC-68000-X", put_symbol="P-BTC-62000-X",
        call_strike=call_strike, put_strike=put_strike,
        contract_value=contract_value, spot_at_entry=spot_at_entry,
    )


def _candles(rows):
    # rows: list of (time, open, high, close)
    return pd.DataFrame(rows, columns=["time", "open", "high", "close"])


def _run(setup, call_rows, put_rows, spot_rows, fee_model=None, **kwargs):
    call_df = _candles(call_rows)
    put_df = _candles(put_rows)
    spot_df = pd.DataFrame(spot_rows, columns=["time", "close"])

    bt = StrangleBacktester(
        fee_model=fee_model or _zero_fee(), initial_capital=100000,
        risk_pct_per_trade=kwargs.get("risk_pct_per_trade", 1.0),
        stop_loss_multiple=kwargs.get("stop_loss_multiple", 3.0),
        take_profit_pct=kwargs.get("take_profit_pct", 50.0),
        max_notional_leverage=kwargs.get("max_notional_leverage", 5.0),
    )

    def fake_fetch(base_url, symbol, resolution, start, end, use_cache):
        return call_df if symbol == setup.call_symbol else put_df

    with patch("option_backtest.backtest.engine.fetch_candles", side_effect=fake_fetch):
        return bt.run(base_url="https://x", cycles=[setup], spot_df=spot_df, leg_resolution="15m")


def test_both_legs_expire_worthless_out_of_the_money():
    setup = _setup()
    call_rows = [(0, 100.0, 110.0, 90.0)]
    put_rows = [(0, 90.0, 95.0, 80.0)]
    spot_rows = [(0, 65000.0), (21600, 66000.0)]  # settles between the strikes -> both OTM
    result = _run(setup, call_rows, put_rows, spot_rows)

    assert len(result.cycles) == 1
    cycle = result.cycles[0]
    assert cycle.call_exit_reason == "settlement"
    assert cycle.put_exit_reason == "settlement"
    assert cycle.call_exit_premium == 0.0
    assert cycle.put_exit_premium == 0.0
    assert cycle.gross_pnl > 0  # kept the full entry credit
    assert cycle.net_pnl == cycle.gross_pnl  # zero-fee model


def test_call_leg_stops_out_when_premium_spikes():
    setup = _setup()
    call_rows = [
        (0, 100.0, 110.0, 90.0),
        (900, 250.0, 350.0, 300.0),  # high 350 >= stop (100*3=300) -> stopped at 300
    ]
    put_rows = [
        (0, 90.0, 95.0, 80.0),
        (900, 70.0, 75.0, 65.0),
    ]
    spot_rows = [(0, 65000.0), (900, 68500.0), (21600, 68500.0)]
    result = _run(setup, call_rows, put_rows, spot_rows, stop_loss_multiple=3.0)

    cycle = result.cycles[0]
    assert cycle.call_exit_reason == "stop"
    assert cycle.call_exit_premium == 300.0  # 100 * stop_loss_multiple
    assert cycle.call_exit_time == 900
    # put leg wasn't stopped and spot (68500) is below its strike (62000)... wait spot > put strike means put OTM
    assert cycle.put_exit_reason == "settlement"


def test_take_profit_closes_remaining_open_legs():
    setup = _setup()
    # combined entry premium = 100+90=190; take_profit_pct=50 -> target = 95
    call_rows = [
        (0, 100.0, 110.0, 90.0),
        (900, 40.0, 45.0, 35.0),
    ]
    put_rows = [
        (0, 90.0, 95.0, 80.0),
        (900, 30.0, 35.0, 25.0),
    ]
    # combined close at t=900: 35+25=60 <= target 95 -> both close at their close price
    spot_rows = [(0, 65000.0), (900, 65000.0)]
    result = _run(setup, call_rows, put_rows, spot_rows, take_profit_pct=50.0, stop_loss_multiple=10.0)

    cycle = result.cycles[0]
    assert cycle.call_exit_reason == "target"
    assert cycle.put_exit_reason == "target"
    assert cycle.call_exit_premium == 35.0
    assert cycle.put_exit_premium == 25.0
    assert cycle.exit_time == 900


def test_position_sizing_from_risk_pct_and_stop_loss_multiple():
    setup = _setup()
    call_rows = [(0, 100.0, 110.0, 90.0)]
    put_rows = [(0, 90.0, 95.0, 80.0)]
    spot_rows = [(0, 65000.0), (21600, 65000.0)]
    result = _run(setup, call_rows, put_rows, spot_rows, risk_pct_per_trade=1.0, stop_loss_multiple=3.0)

    # risk_amount = 100000 * 1% = 1000; worst_case_loss_per_contract =
    # 0.001 * (3-1) * (100+90) = 0.38 -> qty = floor(1000/0.38) = 2631
    assert result.cycles[0].qty == 2631


def test_nonzero_fees_reduce_net_pnl_below_gross_pnl():
    setup = _setup()
    call_rows = [(0, 100.0, 110.0, 90.0)]
    put_rows = [(0, 90.0, 95.0, 80.0)]
    spot_rows = [(0, 65000.0), (21600, 66000.0)]
    fee_model = OptionFeeModel(maker_fee_pct=0.01, taker_fee_pct=0.01, gst_pct=18.0)
    result = _run(setup, call_rows, put_rows, spot_rows, fee_model=fee_model)

    cycle = result.cycles[0]
    assert cycle.entry_fee > 0
    assert cycle.exit_fee > 0
    assert cycle.net_pnl < cycle.gross_pnl


def test_skips_cycle_when_risk_budget_below_one_contract():
    setup = _setup()
    call_rows = [(0, 100.0, 110.0, 90.0)]
    put_rows = [(0, 90.0, 95.0, 80.0)]
    spot_rows = [(0, 65000.0), (21600, 66000.0)]
    result = _run(setup, call_rows, put_rows, spot_rows, risk_pct_per_trade=0.0001, stop_loss_multiple=3.0)

    assert len(result.cycles) == 0
    assert result.skipped_risk_too_small == 1
