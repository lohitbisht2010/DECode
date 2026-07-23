"""Delta Exchange India trading fee model.

Delta charges a maker or taker fee as a percentage of a trade's notional
value (price x quantity), then applies 18% GST on top of that fee amount
(India-specific). This mirrors the schedule published at
https://www.delta.exchange/fees for perpetual futures (SOLUSD is a
perpetual future, not spot or an option), so options-specific premium
caps don't apply here.
"""
from dataclasses import dataclass


@dataclass
class FeeModel:
    maker_fee_pct: float
    taker_fee_pct: float
    gst_pct: float

    def fee_for_trade(self, notional_value: float, is_maker: bool) -> float:
        """Return the total fee (including GST) charged for one fill."""
        base_rate = self.maker_fee_pct if is_maker else self.taker_fee_pct
        base_fee = abs(notional_value) * (base_rate / 100.0)
        return base_fee * (1 + self.gst_pct / 100.0)

    def round_trip_fee(self, entry_notional: float, exit_notional: float, is_maker: bool) -> float:
        """Fee for opening and closing a position (two fills)."""
        return self.fee_for_trade(entry_notional, is_maker) + self.fee_for_trade(exit_notional, is_maker)
