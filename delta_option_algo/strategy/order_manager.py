"""Order placement and position bookkeeping for the short strangle."""
from dataclasses import dataclass, field
from typing import Dict, Optional

from delta_option_algo.core.logger import get_logger
from delta_option_algo.core.rest_client import DeltaRestClient
from delta_option_algo.strategy.short_strangle import OptionLeg

log = get_logger(__name__)


@dataclass
class OpenLeg:
    leg: OptionLeg
    size: int
    entry_price: float
    order_id: Optional[int] = None
    closed: bool = False


@dataclass
class StrangleTrade:
    call: OpenLeg
    put: OpenLeg

    @property
    def entry_credit(self) -> float:
        """Total premium collected (per contract) across both legs."""
        return self.call.entry_price + self.put.entry_price


class OrderManager:
    """Wraps the REST client with a dry-run mode so the strategy can be
    exercised safely before real capital is at risk."""

    def __init__(self, client: DeltaRestClient, dry_run: bool = True):
        self.client = client
        self.dry_run = dry_run

    def _sell_to_open(self, leg: OptionLeg, size: int) -> OpenLeg:
        if self.dry_run:
            log.info(
                "[DRY-RUN] SELL %s x%s @ mark %.4f (product_id=%s)",
                leg.symbol, size, leg.mark_price, leg.product_id,
            )
            return OpenLeg(leg=leg, size=size, entry_price=leg.mark_price, order_id=None)

        order = self.client.place_order(
            product_id=leg.product_id,
            size=size,
            side="sell",
            order_type="limit_order",
            limit_price=str(leg.best_bid or leg.mark_price),
            time_in_force="ioc",
        )
        fill_price = float(order.get("average_fill_price") or leg.mark_price)
        log.info("SELL order placed: %s x%s id=%s fill=%.4f", leg.symbol, size, order.get("id"), fill_price)
        return OpenLeg(leg=leg, size=size, entry_price=fill_price, order_id=order.get("id"))

    def open_strangle(self, call_leg: OptionLeg, put_leg: OptionLeg, size: int) -> StrangleTrade:
        call = self._sell_to_open(call_leg, size)
        put = self._sell_to_open(put_leg, size)
        return StrangleTrade(call=call, put=put)

    def close_leg(self, open_leg: OpenLeg) -> None:
        if open_leg.closed:
            return
        if self.dry_run:
            log.info("[DRY-RUN] BUY-TO-CLOSE %s x%s", open_leg.leg.symbol, open_leg.size)
        else:
            self.client.close_position(
                product_id=open_leg.leg.product_id, size=open_leg.size, side="buy"
            )
            log.info("Closed position: %s x%s", open_leg.leg.symbol, open_leg.size)
        open_leg.closed = True

    def close_strangle(self, trade: StrangleTrade) -> None:
        self.close_leg(trade.call)
        self.close_leg(trade.put)
