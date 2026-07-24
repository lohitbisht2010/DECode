"""Per-expiry-cycle strike selection for the short strangle strategy.

Delta lists a fresh BTC call+put chain settling every day at 12:00 UTC.
For each expiry, this picks the day's entry time (`entry_hours_before_expiry`
before settlement) and selects the call/put strike closest to
spot * (1 +/- target_otm_pct/100) at that moment.

Unlike the live bot in delta_option_algo (which selects strikes by live
option delta from the ticker's greeks), historical candles only give
OHLCV - no historical delta/IV - so strike selection here is by moneyness
(% away from spot) instead. This is a real simplification versus "pick the
~0.16-delta strike": moneyness ignores how delta compresses/expands with
time-to-expiry and realized vol, so the strangle's actual probability of
expiring ITM will drift across cycles even at a fixed target_otm_pct.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class StrangleSetup:
    settlement_time: int
    entry_time: int
    call_symbol: str
    put_symbol: str
    call_strike: float
    put_strike: float
    contract_value: float
    spot_at_entry: float


def spot_at_or_before(spot_times: np.ndarray, spot_closes: np.ndarray, t: int):
    idx = np.searchsorted(spot_times, t, side="right") - 1
    if idx < 0:
        return None
    return float(spot_closes[idx])


def build_cycles(
    products_df: pd.DataFrame,
    spot_df: pd.DataFrame,
    entry_hours_before_expiry: float,
    target_otm_pct: float,
) -> list:
    """products_df: output of data.products.fetch_option_products.
    spot_df: OHLCV of the underlying spot index, ascending by time."""
    spot_times = spot_df["time"].to_numpy()
    spot_closes = spot_df["close"].to_numpy()

    cycles = []
    for settlement_time, group in products_df.groupby("settlement_time"):
        entry_time = int(settlement_time - entry_hours_before_expiry * 3600)
        spot_at_entry = spot_at_or_before(spot_times, spot_closes, entry_time)
        if spot_at_entry is None:
            continue

        calls = group[group["contract_type"] == "call_options"]
        puts = group[group["contract_type"] == "put_options"]
        if calls.empty or puts.empty:
            continue

        call_target = spot_at_entry * (1 + target_otm_pct / 100.0)
        put_target = spot_at_entry * (1 - target_otm_pct / 100.0)
        call_row = calls.iloc[(calls["strike_price"] - call_target).abs().to_numpy().argmin()]
        put_row = puts.iloc[(puts["strike_price"] - put_target).abs().to_numpy().argmin()]

        cycles.append(StrangleSetup(
            settlement_time=int(settlement_time),
            entry_time=entry_time,
            call_symbol=call_row["symbol"],
            put_symbol=put_row["symbol"],
            call_strike=float(call_row["strike_price"]),
            put_strike=float(put_row["strike_price"]),
            contract_value=float(call_row["contract_value"]),
            spot_at_entry=spot_at_entry,
        ))

    return cycles
