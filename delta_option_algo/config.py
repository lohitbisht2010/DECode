"""Central configuration for the Delta Exchange India option-selling algo."""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

_ENV_URLS = {
    "production": "https://api.india.delta.exchange",
    "testnet": "https://cdn-ind.testnet.deltaex.org",
}

_WS_URLS = {
    "production": "wss://socket.india.delta.exchange",
    "testnet": "wss://socket-ind.testnet.deltaex.org",
}


@dataclass
class Settings:
    api_key: str = os.getenv("DELTA_API_KEY", "")
    api_secret: str = os.getenv("DELTA_API_SECRET", "")
    env: str = os.getenv("DELTA_ENV", "testnet")
    live_trading: bool = os.getenv("LIVE_TRADING", "false").strip().lower() == "true"

    # --- Strategy parameters -------------------------------------------------
    underlying: str = "BTC"                 # underlying asset symbol, e.g. BTC / ETH
    target_leg_delta: float = 0.16          # |delta| target for each short leg (~1 SD strangle)
    delta_tolerance: float = 0.05           # acceptable band around target_leg_delta
    max_bid_ask_spread_pct: float = 3.0     # skip a strike if spread/mark > this %
    lots_per_leg: int = 1                   # order size (in contracts) per leg
    capital_allocation_pct: float = 20.0    # % of available balance risked per trade cycle
    stop_loss_multiple: float = 2.0         # square off a leg if premium grows to N x entry credit
    take_profit_pct: float = 50.0           # close position after capturing this % of total credit
    max_daily_loss_pct: float = 5.0         # hard circuit breaker on account equity
    poll_interval_sec: int = 5              # REST fallback poll interval
    eod_square_off_ist: str = "23:25"       # flatten all positions before expiry/day end (IST, HH:MM)

    @property
    def base_url(self) -> str:
        return _ENV_URLS[self.env]

    @property
    def ws_url(self) -> str:
        return _WS_URLS[self.env]


settings = Settings()
