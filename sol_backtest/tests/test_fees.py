from sol_backtest.fees import FeeModel


def _model():
    return FeeModel(maker_fee_pct=0.02, taker_fee_pct=0.05, gst_pct=18.0)


def test_taker_fee_includes_gst():
    fee = _model().fee_for_trade(notional_value=10000, is_maker=False)
    base = 10000 * 0.05 / 100  # 5.0
    expected = base * 1.18
    assert abs(fee - expected) < 1e-9


def test_maker_fee_cheaper_than_taker():
    model = _model()
    maker_fee = model.fee_for_trade(10000, is_maker=True)
    taker_fee = model.fee_for_trade(10000, is_maker=False)
    assert maker_fee < taker_fee


def test_round_trip_fee_sums_both_legs():
    model = _model()
    entry_fee = model.fee_for_trade(10000, is_maker=False)
    exit_fee = model.fee_for_trade(10500, is_maker=False)
    assert model.round_trip_fee(10000, 10500, is_maker=False) == entry_fee + exit_fee


def test_fee_uses_absolute_notional():
    fee = _model().fee_for_trade(-10000, is_maker=False)
    assert fee == _model().fee_for_trade(10000, is_maker=False)
