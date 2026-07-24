"""Backtester for the short strangle strategy: sell a call + put each expiry
cycle, manage each leg independently against a stop-loss, close the whole
position early on a combined take-profit, else let unclosed legs settle to
intrinsic value at expiry.

Cycles are processed sequentially in settlement-time order against a single
running equity value - position size for cycle N is derived from equity as
of the start of cycle N. Since entries sit only a few hours before each
daily expiry, cycles' entry-to-settlement windows don't overlap (matches
how the discrete pattern engines in sol_backtest treat trades), so this
doesn't need true concurrent-position accounting.

Fee convention: Delta charges options fees on the *underlying* notional
(spot_price * contract_value * qty) at the prevailing spot price when each
fill happens, not on the option premium - see option_backtest/fees.py.
"""
import math
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from sol_backtest.data.fetcher import DataFetchError, fetch_candles

from option_backtest.fees import OptionFeeModel
from option_backtest.strategy.short_strangle import StrangleSetup, spot_at_or_before


@dataclass
class StrangleCycle:
    settlement_time: int
    entry_time: int
    exit_time: int
    call_strike: float
    put_strike: float
    qty: float
    contract_value: float
    call_entry_premium: float
    put_entry_premium: float
    call_exit_premium: float
    put_exit_premium: float
    call_exit_time: int
    put_exit_time: int
    call_exit_reason: str
    put_exit_reason: str
    call_entry_fee: float
    put_entry_fee: float
    call_exit_fee: float
    put_exit_fee: float

    @property
    def entry_fee(self) -> float:
        return self.call_entry_fee + self.put_entry_fee

    @property
    def exit_fee(self) -> float:
        return self.call_exit_fee + self.put_exit_fee

    @property
    def exit_price(self) -> float:
        # No single "exit price" for a two-leg position - this only exists so
        # backtest.metrics.compute_metrics's "is not None" closed-trade filter
        # (written for single-instrument Trade objects) works unmodified.
        return self.call_exit_premium + self.put_exit_premium

    @property
    def gross_pnl(self) -> float:
        call_pnl = (self.call_entry_premium - self.call_exit_premium) * self.contract_value * self.qty
        put_pnl = (self.put_entry_premium - self.put_exit_premium) * self.contract_value * self.qty
        return call_pnl + put_pnl

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.entry_fee - self.exit_fee


@dataclass
class StrangleBacktestResult:
    cycles: List[StrangleCycle]
    equity_curve: pd.Series
    initial_capital: float
    skipped_no_data: int = 0
    skipped_risk_too_small: int = 0

    @property
    def trades(self):
        return self.cycles  # alias so backtest.metrics.compute_metrics (written for `trades`) works as-is


class StrangleBacktester:
    def __init__(
        self,
        fee_model: OptionFeeModel,
        initial_capital: float,
        risk_pct_per_trade: float,
        stop_loss_multiple: float,
        take_profit_pct: float,
        max_notional_leverage: float = 5.0,
    ):
        """risk_pct_per_trade: qty is sized so that *both* legs stopping out
        simultaneously (the conservative worst case) loses exactly this % of
        equity - qty = (equity * risk_pct/100) / worst_case_loss_per_contract,
        where worst_case_loss_per_contract = contract_value *
        (stop_loss_multiple - 1) * (call_entry_premium + put_entry_premium).

        stop_loss_multiple: a leg is bought back if its premium grows to this
        many times its entry premium (matches delta_option_algo's live
        strategy config).

        take_profit_pct: once still-open legs' current combined premium has
        decayed to (100 - take_profit_pct)% of the cycle's total entry
        premium, close every remaining open leg at that bar's close.

        max_notional_leverage: qty is also capped so the combined underlying
        notional of both legs (spot * contract_value * qty * 2) doesn't
        exceed this multiple of equity - a backstop against the risk-based
        formula sizing up huge quantity when premiums are tiny, since this
        backtest doesn't model Delta's actual options margin (SPAN-style)
        requirements.
        """
        self.fee_model = fee_model
        self.initial_capital = initial_capital
        self.risk_pct_per_trade = risk_pct_per_trade
        self.stop_loss_multiple = stop_loss_multiple
        self.take_profit_pct = take_profit_pct
        self.max_notional_leverage = max_notional_leverage

    def _fetch_leg(self, base_url, symbol, resolution, entry_time, settlement_time, use_cache):
        step = 900 if resolution not in ("1m", "3m", "5m") else 300
        try:
            df = fetch_candles(
                base_url=base_url, symbol=symbol, resolution=resolution,
                start=entry_time, end=settlement_time + step, use_cache=use_cache,
            )
        except DataFetchError:
            return None
        df = df[df["time"] >= entry_time].reset_index(drop=True)
        return df if len(df) > 0 else None

    def run(
        self,
        base_url: str,
        cycles: List[StrangleSetup],
        spot_df: pd.DataFrame,
        leg_resolution: str,
        use_cache: bool = True,
    ) -> StrangleBacktestResult:
        spot_times = spot_df["time"].to_numpy()
        spot_closes = spot_df["close"].to_numpy()

        equity = self.initial_capital
        results: List[StrangleCycle] = []
        equity_points = []
        skipped_no_data = 0
        skipped_risk_too_small = 0

        for setup in cycles:
            call_df = self._fetch_leg(base_url, setup.call_symbol, leg_resolution,
                                       setup.entry_time, setup.settlement_time, use_cache)
            put_df = self._fetch_leg(base_url, setup.put_symbol, leg_resolution,
                                      setup.entry_time, setup.settlement_time, use_cache)
            if call_df is None or put_df is None:
                skipped_no_data += 1
                continue

            call_entry_premium = float(call_df.iloc[0]["open"])
            put_entry_premium = float(put_df.iloc[0]["open"])
            if call_entry_premium <= 0 or put_entry_premium <= 0:
                skipped_no_data += 1
                continue

            worst_case_loss_per_contract = (
                setup.contract_value * (self.stop_loss_multiple - 1)
                * (call_entry_premium + put_entry_premium)
            )
            if worst_case_loss_per_contract <= 0:
                skipped_no_data += 1
                continue

            risk_amount = equity * (self.risk_pct_per_trade / 100.0)
            qty = math.floor(risk_amount / worst_case_loss_per_contract)

            max_notional_qty = math.floor(
                (equity * self.max_notional_leverage) / (setup.spot_at_entry * setup.contract_value * 2)
            )
            qty = min(qty, max_notional_qty)

            if qty < 1:
                skipped_risk_too_small += 1
                continue

            call_entry_fee = self.fee_model.fee_for_fill(setup.spot_at_entry * setup.contract_value * qty)
            put_entry_fee = self.fee_model.fee_for_fill(setup.spot_at_entry * setup.contract_value * qty)

            call_stop_price = call_entry_premium * self.stop_loss_multiple
            put_stop_price = put_entry_premium * self.stop_loss_multiple
            total_entry_premium = call_entry_premium + put_entry_premium
            target_premium = total_entry_premium * (1 - self.take_profit_pct / 100.0)

            call_open, put_open = True, True
            call_exit_premium = put_exit_premium = None
            call_exit_time = put_exit_time = None
            call_exit_reason = put_exit_reason = ""

            merged = pd.merge(
                call_df[["time", "high", "close"]].rename(columns={"high": "call_high", "close": "call_close"}),
                put_df[["time", "high", "close"]].rename(columns={"high": "put_high", "close": "put_close"}),
                on="time", how="inner",
            ).iloc[1:]  # row 0 was the entry fill, already consumed above

            for row in merged.itertuples(index=False):
                if call_open and row.call_high >= call_stop_price:
                    call_open = False
                    call_exit_premium = call_stop_price
                    call_exit_time = int(row.time)
                    call_exit_reason = "stop"
                if put_open and row.put_high >= put_stop_price:
                    put_open = False
                    put_exit_premium = put_stop_price
                    put_exit_time = int(row.time)
                    put_exit_reason = "stop"

                if call_open or put_open:
                    current_total = (
                        (call_exit_premium if not call_open else row.call_close)
                        + (put_exit_premium if not put_open else row.put_close)
                    )
                    if current_total <= target_premium:
                        if call_open:
                            call_open = False
                            call_exit_premium = row.call_close
                            call_exit_time = int(row.time)
                            call_exit_reason = "target"
                        if put_open:
                            put_open = False
                            put_exit_premium = row.put_close
                            put_exit_time = int(row.time)
                            put_exit_reason = "target"

                if not call_open and not put_open:
                    break

            spot_at_settlement = spot_at_or_before(spot_times, spot_closes, setup.settlement_time)
            if spot_at_settlement is None:
                spot_at_settlement = setup.spot_at_entry  # fallback, shouldn't normally happen

            if call_open:
                call_exit_premium = max(spot_at_settlement - setup.call_strike, 0.0)
                call_exit_time = setup.settlement_time
                call_exit_reason = "settlement"
            if put_open:
                put_exit_premium = max(setup.put_strike - spot_at_settlement, 0.0)
                put_exit_time = setup.settlement_time
                put_exit_reason = "settlement"

            call_exit_spot = spot_at_settlement if call_exit_reason == "settlement" else \
                (spot_at_or_before(spot_times, spot_closes, call_exit_time) or setup.spot_at_entry)
            put_exit_spot = spot_at_settlement if put_exit_reason == "settlement" else \
                (spot_at_or_before(spot_times, spot_closes, put_exit_time) or setup.spot_at_entry)
            call_exit_fee = self.fee_model.fee_for_fill(call_exit_spot * setup.contract_value * qty)
            put_exit_fee = self.fee_model.fee_for_fill(put_exit_spot * setup.contract_value * qty)

            cycle = StrangleCycle(
                settlement_time=setup.settlement_time, entry_time=setup.entry_time,
                exit_time=max(call_exit_time, put_exit_time),
                call_strike=setup.call_strike, put_strike=setup.put_strike,
                qty=qty, contract_value=setup.contract_value,
                call_entry_premium=call_entry_premium, put_entry_premium=put_entry_premium,
                call_exit_premium=call_exit_premium, put_exit_premium=put_exit_premium,
                call_exit_time=call_exit_time, put_exit_time=put_exit_time,
                call_exit_reason=call_exit_reason, put_exit_reason=put_exit_reason,
                call_entry_fee=call_entry_fee, put_entry_fee=put_entry_fee,
                call_exit_fee=call_exit_fee, put_exit_fee=put_exit_fee,
            )
            equity += cycle.net_pnl
            equity_points.append((cycle.exit_time, equity))
            results.append(cycle)

        if not equity_points:
            equity_points = [(cycles[0].entry_time if cycles else 0, equity)]

        times = [t for t, _ in equity_points]
        values = [v for _, v in equity_points]
        curve = pd.Series(values, index=pd.to_datetime(times, unit="s"), name="equity")
        return StrangleBacktestResult(
            cycles=results, equity_curve=curve, initial_capital=self.initial_capital,
            skipped_no_data=skipped_no_data, skipped_risk_too_small=skipped_risk_too_small,
        )
