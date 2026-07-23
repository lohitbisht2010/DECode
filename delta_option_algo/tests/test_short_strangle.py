from delta_option_algo.strategy.short_strangle import select_strangle


def _ticker(symbol, product_id, contract_type, strike, delta, mark, bid, ask):
    return {
        "symbol": symbol,
        "product_id": product_id,
        "contract_type": contract_type,
        "strike_price": strike,
        "mark_price": mark,
        "greeks": {"delta": delta},
        "quotes": {"best_bid": bid, "best_ask": ask},
    }


def _sample_chain():
    calls = [
        _ticker("C-BTC-60000", 1, "call_options", 60000, 0.35, 500, 490, 510),
        _ticker("C-BTC-62000", 2, "call_options", 62000, 0.16, 250, 245, 255),
        _ticker("C-BTC-64000", 3, "call_options", 64000, 0.05, 90, 85, 95),
    ]
    puts = [
        _ticker("P-BTC-58000", 4, "put_options", 58000, -0.34, 480, 470, 490),
        _ticker("P-BTC-56000", 5, "put_options", 56000, -0.16, 240, 235, 245),
        _ticker("P-BTC-54000", 6, "put_options", 54000, -0.05, 80, 75, 85),
    ]
    return calls + puts


def test_select_strangle_picks_target_delta_strikes():
    result = select_strangle(
        _sample_chain(), target_leg_delta=0.16, delta_tolerance=0.05, max_spread_pct=10
    )
    assert result is not None
    assert result["call"].symbol == "C-BTC-62000"
    assert result["put"].symbol == "P-BTC-56000"


def test_select_strangle_filters_wide_spreads():
    chain = _sample_chain()
    # Blow out the spread on the target-delta call so it should be skipped.
    for t in chain:
        if t["symbol"] == "C-BTC-62000":
            t["quotes"] = {"best_bid": 100, "best_ask": 400}  # ~120% spread vs mark

    result = select_strangle(chain, target_leg_delta=0.16, delta_tolerance=0.05, max_spread_pct=10)
    assert result is not None
    # falls back to the next closest liquid call since 62000 strike got filtered out
    assert result["call"].symbol != "C-BTC-62000"


def test_select_strangle_returns_none_on_empty_chain():
    assert select_strangle([], target_leg_delta=0.16, delta_tolerance=0.05, max_spread_pct=10) is None
