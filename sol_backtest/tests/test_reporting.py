import pandas as pd

from sol_backtest.backtest.engine import Trade
from sol_backtest.backtest.pattern_engine import PatternTrade
from sol_backtest.reporting import save_trades_csv, trades_to_dataframe


def _plain_trade():
    t = Trade(direction=1, entry_time=0, entry_price=100.0, qty=10.0, entry_fee=1.0)
    t.exit_time = 900
    t.exit_price = 110.0
    t.exit_fee = 1.1
    return t


def _pattern_trade():
    t = PatternTrade(
        direction=-1, entry_time=0, entry_price=100.0, qty=10.0, entry_fee=1.0,
        stop_price=105.0, target_price=90.0,
    )
    t.exit_time = 900
    t.exit_price = 90.0
    t.exit_fee = 0.9
    t.exit_reason = "target"
    return t


def test_trades_to_dataframe_plain_trade_has_no_pattern_columns():
    df = trades_to_dataframe([_plain_trade()])
    assert list(df["direction"]) == ["long"]
    assert abs(df.loc[0, "gross_pnl"] - 100.0) < 1e-9  # (110-100)*10
    assert "stop_price" not in df.columns


def test_trades_to_dataframe_pattern_trade_includes_stop_target_reason():
    df = trades_to_dataframe([_pattern_trade()])
    assert df.loc[0, "direction"] == "short"
    assert df.loc[0, "exit_reason"] == "target"
    assert abs(df.loc[0, "stop_price"] - 105.0) < 1e-9
    assert abs(df.loc[0, "target_price"] - 90.0) < 1e-9
    assert abs(df.loc[0, "gross_pnl"] - 100.0) < 1e-9  # (90-100)*10*(-1)


def test_save_trades_csv_writes_readable_file(tmp_path, monkeypatch):
    import sol_backtest.reporting as reporting
    monkeypatch.setattr(reporting, "RESULTS_DIR", str(tmp_path))

    path = save_trades_csv([_pattern_trade()], "test.csv")
    assert path == str(tmp_path / "test.csv")

    loaded = pd.read_csv(path)
    assert loaded.loc[0, "exit_reason"] == "target"
    assert abs(loaded.loc[0, "net_pnl"] - (100.0 - 1.0 - 0.9)) < 1e-6
