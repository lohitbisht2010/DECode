"""Backtester for discrete pattern trades (entry + stop-loss + optional
target/exit-signal), as opposed to engine.Backtester's continuous
hold-a-position-per-signal model.

Execution model:
  - A signal on bar i (known from data up to and including bar i) is
    filled at bar i+1's open - no lookahead.
  - Once in a trade, every subsequent bar's high/low is checked against
    the stop and (if set) the target. If both would be hit within the
    same bar, the stop is assumed to trigger first (the conservative
    assumption, since intrabar order isn't known from OHLC alone).
  - Strategies with no fixed target (e.g. "hold until the trend flips")
    leave target_price as NaN - only the stop is checked against price,
    and setups may supply an `exit_signal` column instead: True on a bar
    schedules a close at the *next* bar's open (same no-lookahead
    convention as entries), unless the stop fires first.
  - Only one position at a time; new signals while already in a trade are
    ignored (matches the single-position constraint of engine.Backtester).
  - A position still open at the end of the data is force-closed at the
    final bar's close.
"""
import math
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from sol_backtest.backtest.engine import BacktestResult, Trade
from sol_backtest.fees import FeeModel


@dataclass
class PatternTrade(Trade):
    stop_price: float = 0.0
    target_price: float = float("nan")
    exit_reason: str = ""
    tag: str = ""


class PatternBacktester:
    def __init__(
        self,
        fee_model: FeeModel,
        initial_capital: float,
        leverage: float = 1.0,
        allocation_pct: float = 100.0,
        assume_maker_fees: bool = False,
        risk_pct_per_trade: Optional[float] = None,
        reward_multiple: Optional[float] = None,
        max_consecutive_losses_per_day: Optional[int] = None,
        maker_on_target_only: bool = False,
    ):
        """risk_pct_per_trade: if set, position size is derived from the
        stop distance so a stop-out loses exactly this % of current equity
        (before fees/slippage) - qty = (equity * risk_pct/100) / |entry -
        stop|. Capped at the notional `leverage * equity` would otherwise
        allow, so a very tight stop can't imply an unbounded position.
        When None (default), falls back to the old fixed allocation_pct *
        leverage sizing, which ignores the stop distance entirely.

        reward_multiple: if set, the take-profit target is placed this many
        times the stop distance away from the *actual fill price* (not the
        setup's target_price, which gets ignored) - e.g. 4 means the target
        is 4x further from entry than the stop, so hitting it gains 4x
        whatever hitting the stop would have lost. Combine with
        risk_pct_per_trade=1 and reward_multiple=4 for "risk 1%, target 4%"
        sizing. When None (default), the setup's own target_price is used
        as-is (which may itself be NaN for a no-fixed-target strategy).

        max_consecutive_losses_per_day: if set, once this many trades in a
        row close at a net loss (net_pnl <= 0) *within the same UTC
        calendar day*, no new entries are taken for the rest of that day.
        The streak and the block both reset at the next day boundary,
        independent of whether the prior day ended blocked. A winning
        trade resets the streak immediately, even mid-day.

        maker_on_target_only: a more realistic alternative to
        assume_maker_fees=True (which optimistically assumes every fill,
        including entries and stop-outs, gets the cheaper maker rate).
        Entries and stop/eod_forced/signal_exit closes are immediate,
        urgency-driven fills - realistically taker. Only a target hit is
        genuinely a resting limit order filled by someone else's market
        order, so only target exits get the maker rate here; everything
        else pays taker regardless of assume_maker_fees. Takes priority
        over assume_maker_fees when both are set.
        """
        self.fee_model = fee_model
        self.initial_capital = initial_capital
        self.leverage = leverage
        self.allocation_pct = allocation_pct
        self.is_maker = assume_maker_fees
        self.risk_pct_per_trade = risk_pct_per_trade
        self.reward_multiple = reward_multiple
        self.max_consecutive_losses_per_day = max_consecutive_losses_per_day
        self.maker_on_target_only = maker_on_target_only

    def _is_maker_fill(self, reason: Optional[str]) -> bool:
        """reason=None means an entry fill; otherwise an exit_reason."""
        if self.maker_on_target_only:
            return reason == "target"
        return self.is_maker

    def _open(self, equity: float, price: float, direction: int, time: int,
              stop_price: float, target_price: float, tag: str = "") -> Optional[PatternTrade]:
        risk_per_unit = abs(price - stop_price)

        if self.risk_pct_per_trade is not None:
            if risk_per_unit <= 0:
                return None  # stop coincides with entry - undefined risk, skip the trade
            risk_amount = equity * (self.risk_pct_per_trade / 100.0)
            qty = risk_amount / risk_per_unit
            max_notional = equity * self.leverage
            notional = qty * price
            if notional > max_notional:
                qty = max_notional / price
                notional = max_notional
        else:
            margin = equity * (self.allocation_pct / 100.0)
            notional = margin * self.leverage
            qty = notional / price

        if self.reward_multiple is not None:
            # short (direction=-1): target below entry. long (direction=1): target above entry.
            target_price = price + direction * self.reward_multiple * risk_per_unit

        fee = self.fee_model.fee_for_trade(notional, self._is_maker_fill(None))
        return PatternTrade(
            direction=direction, entry_time=time, entry_price=price, qty=qty,
            entry_fee=fee, stop_price=stop_price, target_price=target_price, tag=tag,
        )

    def _close(self, trade: PatternTrade, price: float, time: int, reason: str) -> float:
        notional = price * trade.qty
        fee = self.fee_model.fee_for_trade(notional, self._is_maker_fill(reason))
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
        pending_entry = None  # (direction, stop_price, target_price, tag)
        pending_exit = False
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
        has_exit_signal = "exit_signal" in setups.columns
        exit_signal_arr = setups["exit_signal"].to_numpy() if has_exit_signal else None
        has_tag = "tag" in setups.columns
        tag_arr = setups["tag"].to_numpy() if has_tag else None

        max_losses = self.max_consecutive_losses_per_day
        consecutive_losses = 0
        loss_streak_day = None
        blocked_day = None

        def record_close_for_loss_streak(trade: PatternTrade, exit_time: int) -> None:
            nonlocal consecutive_losses, loss_streak_day, blocked_day
            if max_losses is None:
                return
            exit_day = int(exit_time) // 86400
            if loss_streak_day != exit_day:
                consecutive_losses = 0
                loss_streak_day = exit_day
            consecutive_losses = consecutive_losses + 1 if trade.net_pnl <= 0 else 0
            if consecutive_losses >= max_losses:
                blocked_day = exit_day

        for i in range(len(df)):
            # A trend-flip-style exit decided from bar i-1's close fills at this bar's open.
            if pending_exit and open_trade is not None:
                equity += self._close(open_trade, opens[i], times[i], "signal_exit")
                trades.append(open_trade)
                record_close_for_loss_streak(open_trade, times[i])
                open_trade = None
                pending_exit = False

            if pending_entry is not None and open_trade is None:
                direction, stop_price, target_price, tag = pending_entry
                if not pd.isna(stop_price):
                    open_trade = self._open(equity, opens[i], direction, times[i], stop_price, target_price, tag)
                    if open_trade is not None:
                        equity -= open_trade.entry_fee
                pending_entry = None

            if open_trade is not None:
                target_price = open_trade.target_price
                has_target = not math.isnan(target_price)
                if open_trade.direction == -1:
                    hit_stop = highs[i] >= open_trade.stop_price
                    hit_target = has_target and lows[i] <= target_price
                else:
                    hit_stop = lows[i] <= open_trade.stop_price
                    hit_target = has_target and highs[i] >= target_price

                if hit_stop or hit_target:
                    reason = "stop" if hit_stop else "target"
                    exit_price = open_trade.stop_price if hit_stop else target_price
                    equity += self._close(open_trade, exit_price, times[i], reason)
                    trades.append(open_trade)
                    record_close_for_loss_streak(open_trade, times[i])
                    open_trade = None
                elif has_exit_signal and bool(exit_signal_arr[i]):
                    pending_exit = True

            bar_day = int(times[i]) // 86400
            day_is_blocked = max_losses is not None and blocked_day == bar_day
            if open_trade is None and pending_entry is None and not day_is_blocked and bool(entry_signal[i]):
                tag = str(tag_arr[i]) if has_tag else ""
                pending_entry = (int(direction_arr[i]), float(stop_arr[i]), float(target_arr[i]), tag)

            unrealized = 0.0
            if open_trade is not None:
                unrealized = (closes[i] - open_trade.entry_price) * open_trade.qty * open_trade.direction
            equity_curve.append(equity + unrealized)

        if open_trade is not None:
            equity += self._close(open_trade, closes[-1], times[-1], "eod_forced")
            trades.append(open_trade)
            record_close_for_loss_streak(open_trade, times[-1])
            equity_curve[-1] = equity

        curve = pd.Series(equity_curve, index=pd.to_datetime(times, unit="s"), name="equity")
        return BacktestResult(trades=trades, equity_curve=curve, initial_capital=self.initial_capital)
