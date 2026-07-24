from option_backtest.fees import OptionFeeModel


def test_fee_for_fill_applies_rate_and_gst():
    model = OptionFeeModel(maker_fee_pct=0.01, taker_fee_pct=0.01, gst_pct=18.0)
    # notional 65000, rate 0.01% -> base fee 6.5, +18% GST -> 7.67
    fee = model.fee_for_fill(65000.0)
    assert abs(fee - 6.5 * 1.18) < 1e-9


def test_fee_for_fill_maker_and_taker_same_rate_for_options():
    model = OptionFeeModel(maker_fee_pct=0.01, taker_fee_pct=0.01, gst_pct=18.0)
    assert model.fee_for_fill(1000.0, is_maker=True) == model.fee_for_fill(1000.0, is_maker=False)


def test_fee_for_fill_uses_absolute_notional():
    model = OptionFeeModel(maker_fee_pct=0.01, taker_fee_pct=0.01, gst_pct=18.0)
    assert model.fee_for_fill(-1000.0) == model.fee_for_fill(1000.0)
