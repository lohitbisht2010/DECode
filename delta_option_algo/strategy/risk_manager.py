"""Position-level and account-level risk controls.

Three independent tripwires, checked every strategy tick:
  1. Per-leg stop loss   - a short leg's premium runs up against you.
  2. Trade take-profit   - enough of the total credit has been captured.
  3. Daily circuit breaker - account equity drawdown exceeds the daily cap,
     which flattens everything and halts new entries for the day.
"""
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from delta_option_algo.core.logger import get_logger
from delta_option_algo.strategy.order_manager import OrderManager, StrangleTrade

log = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")


class RiskManager:
    def __init__(
        self,
        stop_loss_multiple: float,
        take_profit_pct: float,
        max_daily_loss_pct: float,
        eod_square_off_ist: str,
        starting_equity: float,
    ):
        self.stop_loss_multiple = stop_loss_multiple
        self.take_profit_pct = take_profit_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.eod_hh, self.eod_mm = (int(x) for x in eod_square_off_ist.split(":"))
        self.starting_equity = starting_equity
        self.halted = False

    def check_leg_stop_loss(self, trade: StrangleTrade) -> bool:
        """Returns True if either leg breached its stop loss and was closed."""
        tripped = False
        for open_leg in (trade.call, trade.put):
            if open_leg.closed:
                continue
            current_mark = open_leg.leg.mark_price
            if current_mark >= open_leg.entry_price * self.stop_loss_multiple:
                log.warning(
                    "STOP LOSS hit on %s: entry=%.4f current=%.4f (%.1fx)",
                    open_leg.leg.symbol, open_leg.entry_price, current_mark,
                    current_mark / max(open_leg.entry_price, 1e-9),
                )
                tripped = True
        return tripped

    def check_take_profit(self, trade: StrangleTrade, current_call_mark: float, current_put_mark: float) -> bool:
        entry_credit = trade.entry_credit
        current_cost_to_close = current_call_mark + current_put_mark
        captured_pct = (entry_credit - current_cost_to_close) / max(entry_credit, 1e-9) * 100
        if captured_pct >= self.take_profit_pct:
            log.info("TAKE PROFIT hit: captured %.1f%% of entry credit", captured_pct)
            return True
        return False

    def check_daily_circuit_breaker(self, current_equity: float) -> bool:
        if self.starting_equity <= 0:
            return False
        drawdown_pct = (self.starting_equity - current_equity) / self.starting_equity * 100
        if drawdown_pct >= self.max_daily_loss_pct:
            log.error(
                "DAILY LOSS LIMIT hit: drawdown %.2f%% >= cap %.2f%% - halting new entries",
                drawdown_pct, self.max_daily_loss_pct,
            )
            self.halted = True
            return True
        return False

    def should_square_off_eod(self, now: Optional[datetime] = None) -> bool:
        now = (now or datetime.now(IST)).astimezone(IST)
        return (now.hour, now.minute) >= (self.eod_hh, self.eod_mm)

    def flatten(self, order_manager: OrderManager, trade: StrangleTrade) -> None:
        log.warning("Flattening strangle position")
        order_manager.close_strangle(trade)
