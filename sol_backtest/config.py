"""Central configuration for the SOLUSD backtesting project."""
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

# Max candles Delta's /v2/history/candles endpoint returns in one call.
# Not officially documented as a fixed constant; kept conservative and the
# fetcher paginates regardless, so a wrong guess here only affects how many
# HTTP calls are made, not correctness.
MAX_CANDLES_PER_REQUEST = 2000


@dataclass
class Settings:
    env: str = os.getenv("DELTA_ENV", "production")
    symbol: str = "SOLUSD"
    resolution: str = "1h"

    # --- Fee model (Delta Exchange India, perpetual futures) -----------------
    # Sourced from https://www.delta.exchange/fees and
    # https://www.delta.exchange/support/solutions/articles/80001177864-fees-on-options-and-futures-trading
    # as of 2026-07. Delta's fees page returned 403 to automated fetches while
    # building this, so these were cross-checked against multiple secondary
    # sources instead of the page directly — re-verify against the live page
    # before relying on exact numbers for real capital decisions.
    maker_fee_pct: float = 0.02      # % of notional, base retail tier
    taker_fee_pct: float = 0.05      # % of notional, base retail tier
    gst_pct: float = 18.0            # GST charged on top of the fee amount (India)

    # --- Backtest defaults -----------------------------------------------------
    initial_capital: float = 100000.0   # in quote currency (USD)
    leverage: float = 1.0               # perpetuals support up to 100x; default conservative
    allocation_pct: float = 100.0       # % of equity committed as margin per trade
    assume_maker_fees: bool = False     # False = taker fees (market order assumption)

    @property
    def base_url(self) -> str:
        return _ENV_URLS[self.env]


def base_url_for(env: str) -> str:
    return _ENV_URLS[env]


settings = Settings()
