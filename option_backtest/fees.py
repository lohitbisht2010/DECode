"""Delta Exchange India options fee model.

Same shape as sol_backtest.fees.FeeModel (rate * notional, then 18% GST on
top) but options are charged on the *underlying* notional at the spot price
prevailing at fill time (spot_price * contract_value * qty), not on the
option premium - and Delta's maker/taker rate for options is the same
(0.01%), unlike futures where they differ.
"""
from dataclasses import dataclass


@dataclass
class OptionFeeModel:
    maker_fee_pct: float
    taker_fee_pct: float
    gst_pct: float

    def fee_for_fill(self, underlying_notional: float, is_maker: bool = False) -> float:
        """Total fee (including GST) for one option fill (buy or sell, one leg)."""
        base_rate = self.maker_fee_pct if is_maker else self.taker_fee_pct
        base_fee = abs(underlying_notional) * (base_rate / 100.0)
        return base_fee * (1 + self.gst_pct / 100.0)
