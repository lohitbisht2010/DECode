import pandas as pd

from option_backtest.strategy.short_strangle import build_cycles, spot_at_or_before


def _products_df():
    # One expiry cycle, settlement_time=100000, strikes 200 apart on each side.
    rows = []
    for strike in range(63000, 67001, 200):
        rows.append({"symbol": f"C-BTC-{strike}-X", "contract_type": "call_options",
                      "strike_price": float(strike), "settlement_time": 100000, "contract_value": 0.001})
        rows.append({"symbol": f"P-BTC-{strike}-X", "contract_type": "put_options",
                      "strike_price": float(strike), "settlement_time": 100000, "contract_value": 0.001})
    return pd.DataFrame(rows)


def _spot_df():
    # entry_time will be 100000 - 6*3600 = 78400; spot flat at 65000 throughout.
    return pd.DataFrame({"time": [0, 50000, 78400, 90000, 100000], "close": [65000.0] * 5})


def test_build_cycles_picks_nearest_strike_to_target_otm_pct():
    cycles = build_cycles(_products_df(), _spot_df(), entry_hours_before_expiry=6.0, target_otm_pct=5.0)
    assert len(cycles) == 1
    c = cycles[0]
    # 5% OTM of 65000 -> call target 68250 (clamped to max listed 67000), put target 61750 (clamped to min 63000)
    assert c.call_strike == 67000.0
    assert c.put_strike == 63000.0
    assert c.entry_time == 100000 - 6 * 3600
    assert c.spot_at_entry == 65000.0


def test_build_cycles_uses_closer_strikes_for_smaller_otm_pct():
    cycles = build_cycles(_products_df(), _spot_df(), entry_hours_before_expiry=6.0, target_otm_pct=2.0)
    c = cycles[0]
    # 2% OTM of 65000 -> call target 66300 -> nearest listed strike is 66200 or 66400; put target 63700 -> nearest is 63600 or 63800
    assert abs(c.call_strike - 66300.0) <= 100.0
    assert abs(c.put_strike - 63700.0) <= 100.0


def test_build_cycles_skips_expiry_with_no_spot_data_before_entry():
    spot_df = pd.DataFrame({"time": [100000], "close": [65000.0]})  # nothing before entry_time
    cycles = build_cycles(_products_df(), spot_df, entry_hours_before_expiry=6.0, target_otm_pct=5.0)
    assert cycles == []


def test_build_cycles_skips_expiry_missing_one_side():
    products = _products_df()
    products = products[products["contract_type"] == "call_options"]  # no puts at all
    cycles = build_cycles(products, _spot_df(), entry_hours_before_expiry=6.0, target_otm_pct=5.0)
    assert cycles == []


def test_spot_at_or_before_returns_none_when_nothing_precedes_t():
    import numpy as np
    times = np.array([100, 200, 300])
    closes = np.array([1.0, 2.0, 3.0])
    assert spot_at_or_before(times, closes, 50) is None
    assert spot_at_or_before(times, closes, 100) == 1.0
    assert spot_at_or_before(times, closes, 250) == 2.0
