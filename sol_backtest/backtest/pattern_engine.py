"""Backtester for discrete pattern trades (entry + stop-loss + target),
as opposed to engine.Backtester's continuous hold-a-position-per-signal
model.

Execution model:
  - A signal on bar i (known from data up to and including bar i) is
    filled at bar i+1's open - no lookahead.
  - Once in a trade, every subsequent bar's high/low is checked against
    the stop and target. If both would be hit within the same bar, the
    stop is assumed to trigger first (the conservative assumption, since
    intrabar order isn't known from OHLC alone).
  - Only one position at a time; new signals while already in a trade are
    ignored (matches the single-position constraint of engine.Backtester).
  - A position still open at the end of the data is force-closed at the
    final bar's close.
"""
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from sol_backtest.backtest.engine import BacktestResult, Trade
from sol_backtest.fees import FeeModel


@dataclass
class PatternTrade(Trade):
    stop_price: float = 0.0
    target_price: float = 0.0
    exit_reason: str = ""


class PatternBacktester:
    def __init__(
        self,
        fee_model: FeeModel,
        initial_capital: float,
        leverage: float = 1.0,
        allocation_pct: float = 100.0,
        assume_maker_fees: bool = False,
        risk_pct_per_trade: Optional[float] = None,
    ):
        """risk_pct_per_trade: if set, position size is derived from the
        stop distance so a stop-out loses exactly this % of current equity
        (before fees/slippage) - qty = (equity * risk_pct/100) / |entry -
        stop|. Capped at the notional `leverage * equity` would otherwise
        allow, so a very tight stop can't imply an unbounded position.
        When None (default), falls back to the old fixed allocation_pct *
        leverage sizing, which ignores the stop distance entirely.
        """
        self.fee_model = fee_model
        self.initial_capital = initial_capital
        self.leverage = leverage
        self.allocation_pct = allocation_pct
        self.is_maker = assume_maker_fees
        self.risk_pct_per_trade = risk_pct_per_trade

    def _open(self, equity: float, price: float, direction: int, time: int,
              stop_price: float, target_price: float) -> Optional[PatternTrade]:
        if self.risk_pct_per_trade is not None:
            stop_distance = abs(price - stop_price)
            if stop_distance <= 0:
                return None  # stop coincides with entry - undefined risk, skip the trade
            risk_amount = equity * (self.risk_pct_per_trade / 100.0)
            qty = risk_amount / stop_distance
            max_notional = equity * self.leverage
            notional = qty * price
            if notional > max_notional:
                qty = max_notional / price
                notional = max_notional
        else:
            margin = equity * (self.allocation_pct / 100.0)
            notional = margin * self.leverage
            qty = notional / price

        fee = self.fee_model.fee_for_trade(notional, self.is_maker)
        return PatternTrade(
            direction=direction, entry_time=time, entry_price=price, qty=qty,
            entry_fee=fee, stop_price=stop_price, target_price=target_price,
        )

    def _close(self, trade: PatternTrade, price: float, time: int, reason: str) -> float:
        notional = price * trade.qty
        fee = self.fee_model.fee_for_trade(notional, self.is_maker)
        trade.exit_time = time
        trade.exit_price = price
        trade.exit_fee = fee
        trade.exit_reason = reason
        return trade.gross_pnl - fee

    def run(self, df: pd.DataFrame, setups: pd.DataFrame) -> BacktestResult:
        if len(df) != len(setups):
            raise ValueError("df and setups must have the same length")

        equity = self.initial_capital
        open_trade: Optional[PatternTrade] = None
        pending_entry = None  # (direction, stop_price, target_price)
        trades: List[PatternTrade] = []
        equity_curve = []

        times = df["time"].to_numpy()
        opens = df["open"].to_numpy()
        highs = df["high"].to_numpy()
        lows = df["low"].to_numpy()
        closes = df["close"].to_numpy()

        entry_signal = setups["entry_signal"].to_numpy()
        direction_arr = setups["direction"].to_numpy()
        stop_arr = setups["stop_price"].to_numpy()
        target_arr = setups["target_price"].to_numpy()

        for i in range(len(df)):
            if pending_entry is not None and open_trade is None:
                direction, stop_price, target_price = pending_entry
                if not (pd.isna(stop_price) or pd.isna(target_price)):
                    open_trade = self._open(equity, opens[i], direction, times[i], stop_price, target_price)
                    if open_trade is not None:
                        equity -= open_trade.entry_fee
                pending_entry = None

            if open_trade is not None:
                if open_trade.direction == -1:
                    hit_stop = highs[i] >= open_trade.stop_price
                    hit_target = lows[i] <= open_trade.target_price
                else:
                    hit_stop = lows[i] <= open_trade.stop_price
                    hit_target = highs[i] >= open_trade.target_price

                if hit_stop or hit_target:
                    reason = "stop" if hit_stop else "target"
                    exit_price = open_trade.stop_price if hit_stop else open_trade.target_price
                    equity += self._close(open_trade, exit_price, times[i], reason)
                    trades.append(open_trade)
                    open_trade = None

            if open_trade is None and pending_entry is None and bool(entry_signal[i]):
                pending_entry = (int(direction_arr[i]), float(stop_arr[i]), float(target_arr[i]))

            unrealized = 0.0
            if open_trade is not None:
                unrealized = (closes[i] - open_trade.entry_price) * open_trade.qty * open_trade.direction
            equity_curve.append(equity + unrealized)

        if open_trade is not None:
            equity += self._close(open_trade, closes[-1], times[-1], "eod_forced")
            trades.append(open_trade)
            equity_curve[-1] = equity

        curve = pd.Series(equity_curve, index=pd.to_datetime(times, unit="s"), name="equity")
        return BacktestResult(trades=trades, equity_curve=curve, initial_capital=self.initial_capital)
