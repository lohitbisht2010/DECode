import sys
from unittest.mock import patch

import pandas as pd
import pytest

import sol_backtest.compare as compare_mod


def _tiny_df(n=50):
    times = [1700000000 + i * 900 for i in range(n)]
    prices = [100.0 + (i % 5) for i in range(n)]
    return pd.DataFrame({
        "time": times,
        "open": prices, "high": [p + 1 for p in prices], "low": [p - 1 for p in prices],
        "close": prices, "volume": [1] * n,
    })


def _tiny_daily_df(n=5):
    times = [1700000000 + i * 86400 for i in range(n)]
    return pd.DataFrame({
        "time": times, "open": [100.0] * n, "high": [105.0] * n, "low": [95.0] * n,
        "close": [100.0] * n, "volume": [1] * n,
    })


def test_unknown_strategy_name_raises_system_exit(monkeypatch):
    monkeypatch.setattr(
        sys, "argv",
        ["compare.py", "--start", "2025-01-01", "--end", "2025-01-02", "--strategies", "not_a_real_strategy"],
    )
    with pytest.raises(SystemExit):
        compare_mod.main()


def test_weights_count_mismatch_raises_system_exit(monkeypatch):
    monkeypatch.setattr(
        sys, "argv",
        ["compare.py", "--start", "2025-01-01", "--end", "2025-01-02",
         "--strategies", "pivot_r1_rejection,pivot_r1_breakout", "--weights", "0.5"],
    )
    with pytest.raises(SystemExit):
        compare_mod.main()


def test_full_run_with_mocked_data_produces_results_for_each_strategy(monkeypatch, capsys):
    def fake_fetch_candles(base_url, symbol, resolution, start, end, use_cache=True, request_pause_sec=0.2):
        return _tiny_df() if resolution == "15m" else _tiny_daily_df()

    monkeypatch.setattr(
        sys, "argv",
        ["compare.py", "--start", "2025-01-01", "--end", "2025-01-02", "--resolution", "15m",
         "--strategies", "pivot_r1_rejection,pivot_r1_breakout", "--no-csv"],
    )
    with patch.object(compare_mod, "fetch_candles", side_effect=fake_fetch_candles):
        compare_mod.main()

    out = capsys.readouterr().out
    assert "INDEPENDENT COMPARISON" in out
    assert "COMBINED PORTFOLIO" in out
    assert "pivot_r1_rejection" in out
    assert "pivot_r1_breakout" in out
