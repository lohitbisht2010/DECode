"""Signal-driven long/short backtester with Delta Exchange fee modelling.

Convention: `signals[i]` is the position (1 long, -1 short, 0 flat) the
strategy wants held *during* bar i. Whenever it differs from the currently
held position, the engine closes the old position and opens the new one at
bar i's open price — so a strategy computing signals from bar i-1's closed
data (the normal, non-lookahead way) gets executed on the next bar's open,
same as a real order placed after the prior candle closed.
"""
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from sol_backtest.fees import FeeModel


@dataclass
class Trade:
    direction: int  # 1 = long, -1 = short
    entry_time: int
    entry_price: float
    qty: float
    entry_fee: float
    exit_time: Optional[int] = None
    exit_price: Optional[float] = None
    exit_fee: float = 0.0

    @property
    def gross_pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry_price) * self.qty * self.direction

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.entry_fee - self.exit_fee


@dataclass
class BacktestResult:
    trades: List[Trade]
    equity_curve: pd.Series
    initial_capital: float

    @property
    def final_equity(self) -> float:
        return float(self.equity_curve.iloc[-1])


class Backtester:
    def __init__(
        self,
        fee_model: FeeModel,
        initial_capital: float,
        leverage: float = 1.0,
        allocation_pct: float = 100.0,
        assume_maker_fees: bool = False,
    ):
        self.fee_model = fee_model
        self.initial_capital = initial_capital
        self.leverage = leverage
        self.allocation_pct = allocation_pct
        self.is_maker = assume_maker_fees

    def _open(self, equity: float, price: float, direction: int, time: int) -> Trade:
        margin = equity * (self.allocation_pct / 100.0)
        notional = margin * self.leverage
        qty = notional / price
        fee = self.fee_model.fee_for_trade(notional, self.is_maker)
        return Trade(direction=direction, entry_time=time, entry_price=price, qty=qty, entry_fee=fee)

    def _close(self, trade: Trade, price: float, time: int) -> float:
        """Close the trade and return its impact on equity.

        Entry fee was already deducted from equity when the trade was
        opened, so only the exit fee gets subtracted here — using
        `trade.net_pnl` (which subtracts both fees) would double-count
        the entry fee.
        """
        notional = price * trade.qty
        fee = self.fee_model.fee_for_trade(notional, self.is_maker)
        trade.exit_time = time
        trade.exit_price = price
        trade.exit_fee = fee
        return trade.gross_pnl - fee

    def run(self, df: pd.DataFrame, signals: pd.Series) -> BacktestResult:
        if len(df) != len(signals):
            raise ValueError("df and signals must have the same length")

        equity = self.initial_capital
        position = 0
        open_trade: Optional[Trade] = None
        trades: List[Trade] = []
        equity_curve = []

        times = df["time"].to_numpy()
        opens = df["open"].to_numpy()
        closes = df["close"].to_numpy()
        sig = signals.to_numpy()

        for i in range(len(df)):
            desired = int(sig[i])
            if desired != position:
                if open_trade is not None:
                    equity += self._close(open_trade, opens[i], times[i])
                    trades.append(open_trade)
                    open_trade = None
                if desired != 0:
                    open_trade = self._open(equity, opens[i], desired, times[i])
                    equity -= open_trade.entry_fee
                position = desired

            unrealized = 0.0
            if open_trade is not None:
                unrealized = (closes[i] - open_trade.entry_price) * open_trade.qty * open_trade.direction
            equity_curve.append(equity + unrealized)

        if open_trade is not None:
            equity += self._close(open_trade, closes[-1], times[-1])
            trades.append(open_trade)
            equity_curve[-1] = equity

        curve = pd.Series(equity_curve, index=pd.to_datetime(times, unit="s"), name="equity")
        return BacktestResult(trades=trades, equity_curve=curve, initial_capital=self.initial_capital)
