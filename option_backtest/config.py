"""Central configuration for the BTC options (short strangle) backtesting project."""
import os
from dataclasses import dataclass

_ENV_URLS = {
    "production": "https://api.india.delta.exchange",
    "testnet": "https://cdn-ind.testnet.deltaex.org",
}

RESOLUTION_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600,
    "1d": 86400, "7d": 604800, "1w": 604800, "2w": 1209600, "30d": 2592000,
}


@dataclass
class Settings:
    env: str = os.getenv("DELTA_ENV", "production")
    underlying: str = "BTC"
    spot_index_symbol: str = ".DEXBTUSD"

    # --- Fee model (Delta Exchange India, options) ----------------------------
    # Read live from GET /v2/products - a BTC option product's
    # taker_commission_rate and maker_commission_rate were both 0.0001 (0.01%)
    # as of 2026-07, versus 0.05%/0.02% for perpetual futures - options are
    # charged on the *underlying* notional (spot_price * contract_value * qty),
    # same convention as futures, just a lower rate. Delta's fees page
    # returned 403 to automated fetches while building this, so the exact
    # rate here comes from the live products endpoint, not the docs page -
    # re-verify (and check for any premium-based fee cap, which the products
    # schema doesn't expose and this project doesn't model) before relying on
    # it for real capital decisions.
    maker_fee_pct: float = 0.01      # % of underlying notional
    taker_fee_pct: float = 0.01      # % of underlying notional (same as maker for options)
    gst_pct: float = 18.0            # GST charged on top of the fee amount (India)

    # --- Backtest defaults -----------------------------------------------------
    initial_capital: float = 100000.0
    leg_monitor_resolution: str = "15m"   # candle resolution used to watch each leg for a stop/target hit
    spot_resolution: str = "15m"          # candle resolution used to look up spot at entry/settlement

    @property
    def base_url(self) -> str:
        return _ENV_URLS[self.env]


def base_url_for(env: str) -> str:
    return _ENV_URLS[env]


settings = Settings()
