"""Delta-neutral short strangle strike selection.

Strategy in one line: sell an out-of-the-money call and an out-of-the-money
put whose absolute option delta sits close to `target_leg_delta` (~0.16 by
default, i.e. roughly a one-standard-deviation strangle), collecting
premium on the view that the underlying stays within that range until
expiry. Strike selection and entry-safety checks live here; order placement
and risk control live in order_manager.py / risk_manager.py.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

from delta_option_algo.core.logger import get_logger

log = get_logger(__name__)


@dataclass
class OptionLeg:
    symbol: str
    product_id: int
    contract_type: str  # "call_options" | "put_options"
    strike_price: float
    delta: float
    mark_price: float
    best_bid: float
    best_ask: float

    @property
    def spread_pct(self) -> float:
        if self.mark_price <= 0:
            return float("inf")
        return abs(self.best_ask - self.best_bid) / self.mark_price * 100


def _parse_leg(ticker: Dict) -> Optional[OptionLeg]:
    try:
        greeks = ticker.get("greeks") or {}
        quotes = ticker.get("quotes") or {}
        delta = float(greeks.get("delta", 0) or 0)
        mark_price = float(ticker.get("mark_price", 0) or 0)
        best_bid = float(quotes.get("best_bid", 0) or 0)
        best_ask = float(quotes.get("best_ask", 0) or mark_price)
        return OptionLeg(
            symbol=ticker["symbol"],
            product_id=ticker["product_id"],
            contract_type=ticker["contract_type"],
            strike_price=float(ticker["strike_price"]),
            delta=delta,
            mark_price=mark_price,
            best_bid=best_bid,
            best_ask=best_ask,
        )
    except (KeyError, TypeError, ValueError):
        log.debug("Skipping malformed ticker entry: %s", ticker)
        return None


def _closest_to_target_delta(
    legs: List[OptionLeg], target_delta: float, tolerance: float
) -> Optional[OptionLeg]:
    candidates = [leg for leg in legs if abs(abs(leg.delta) - target_delta) <= tolerance]
    pool = candidates or legs
    if not pool:
        return None
    return min(pool, key=lambda leg: abs(abs(leg.delta) - target_delta))


def select_strangle(
    option_chain: List[Dict],
    target_leg_delta: float,
    delta_tolerance: float,
    max_spread_pct: float,
) -> Optional[Dict[str, OptionLeg]]:
    """Return {"call": OptionLeg, "put": OptionLeg} for the best strangle, or None
    if the chain doesn't have a liquid enough pair near the target delta."""
    calls, puts = [], []
    for raw in option_chain:
        leg = _parse_leg(raw)
        if leg is None or leg.mark_price <= 0:
            continue
        if leg.spread_pct > max_spread_pct:
            continue
        (calls if leg.contract_type == "call_options" else puts).append(leg)

    call_leg = _closest_to_target_delta(calls, target_leg_delta, delta_tolerance)
    put_leg = _closest_to_target_delta(puts, -target_leg_delta, delta_tolerance)

    if call_leg is None or put_leg is None:
        log.warning("Could not find a liquid strangle near target delta %.2f", target_leg_delta)
        return None

    log.info(
        "Selected strangle: CALL %s (delta=%.3f, strike=%s) / PUT %s (delta=%.3f, strike=%s)",
        call_leg.symbol, call_leg.delta, call_leg.strike_price,
        put_leg.symbol, put_leg.delta, put_leg.strike_price,
    )
    return {"call": call_leg, "put": put_leg}
