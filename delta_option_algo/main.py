"""Entry point: runs the short-strangle option-selling algo against Delta
Exchange India.

Flow:
  1. Find the nearest expiry for the configured underlying and pull its
     option chain (REST, public).
  2. Pick a call/put pair near the target leg delta (strategy/short_strangle.py).
  3. Sell both legs to open (strategy/order_manager.py).
  4. Start a WebSocket feed for live mark-price ticks on the two legs, used
     to keep risk checks responsive between REST polls.
  5. On every tick: check per-leg stop loss, trade take-profit, the daily
     equity circuit breaker, and the end-of-day square-off time
     (strategy/risk_manager.py). Flatten and stop when any of them trips.

Defaults to dry-run (paper) mode. Set LIVE_TRADING=true in .env only once
you've validated behaviour on testnet.
"""
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from delta_option_algo.config import settings
from delta_option_algo.core.logger import get_logger
from delta_option_algo.core.rest_client import DeltaApiError, DeltaRestClient
from delta_option_algo.core.ws_client import DeltaWebSocketClient
from delta_option_algo.strategy.order_manager import OrderManager, StrangleTrade
from delta_option_algo.strategy.risk_manager import RiskManager
from delta_option_algo.strategy.short_strangle import select_strangle

log = get_logger("main")


def nearest_expiry_ddmmyyyy(client: DeltaRestClient, underlying: str) -> Optional[str]:
    products = client.get_products(contract_types="call_options,put_options")
    upcoming = []
    for p in products:
        if p.get("underlying_asset", {}).get("symbol") != underlying:
            continue
        settlement_time = p.get("settlement_time")
        if not settlement_time:
            continue
        try:
            dt = datetime.fromisoformat(settlement_time.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt > datetime.now(timezone.utc):
            upcoming.append(dt)
    if not upcoming:
        return None
    return min(upcoming).strftime("%d-%m-%Y")


def get_account_equity(client: DeltaRestClient) -> float:
    try:
        balances = client.get_balances()
    except DeltaApiError:
        log.exception("Could not fetch balances; treating equity as 0")
        return 0.0
    total = 0.0
    for b in balances:
        total += float(b.get("balance", 0) or 0)
    return total


def refresh_leg_mark_prices(client: DeltaRestClient, trade: StrangleTrade) -> Dict[str, float]:
    marks = {}
    for open_leg in (trade.call, trade.put):
        try:
            ticker = client.get_ticker(open_leg.leg.symbol)
            mark = float(ticker.get("mark_price", open_leg.leg.mark_price))
        except DeltaApiError:
            log.exception("Failed to refresh ticker for %s, using last known mark", open_leg.leg.symbol)
            mark = open_leg.leg.mark_price
        open_leg.leg.mark_price = mark
        marks[open_leg.leg.symbol] = mark
    return marks


def run() -> None:
    if not settings.api_key or not settings.api_secret:
        log.error("DELTA_API_KEY / DELTA_API_SECRET are not set. Copy .env.example to .env and fill them in.")
        sys.exit(1)

    dry_run = not settings.live_trading
    log.info("Starting delta-option-algo | env=%s | dry_run=%s | underlying=%s",
              settings.env, dry_run, settings.underlying)

    client = DeltaRestClient(settings.base_url, settings.api_key, settings.api_secret)

    expiry = nearest_expiry_ddmmyyyy(client, settings.underlying)
    if not expiry:
        log.error("No upcoming %s option expiry found", settings.underlying)
        sys.exit(1)
    log.info("Using expiry %s", expiry)

    chain = client.get_option_chain(settings.underlying, expiry)
    picked = select_strangle(
        chain,
        target_leg_delta=settings.target_leg_delta,
        delta_tolerance=settings.delta_tolerance,
        max_spread_pct=settings.max_bid_ask_spread_pct,
    )
    if not picked:
        log.error("No suitable strangle found in the current chain, exiting")
        sys.exit(1)

    equity = get_account_equity(client) if not dry_run else 100000.0  # nominal paper equity
    order_manager = OrderManager(client, dry_run=dry_run)
    risk_manager = RiskManager(
        stop_loss_multiple=settings.stop_loss_multiple,
        take_profit_pct=settings.take_profit_pct,
        max_daily_loss_pct=settings.max_daily_loss_pct,
        eod_square_off_ist=settings.eod_square_off_ist,
        starting_equity=equity,
    )

    trade = order_manager.open_strangle(picked["call"], picked["put"], size=settings.lots_per_leg)
    log.info("Opened strangle | entry credit/contract = %.4f", trade.entry_credit)

    ws_client = DeltaWebSocketClient(settings.ws_url, settings.api_key, settings.api_secret)
    ws_client.start()
    if ws_client.wait_until_connected(timeout=10):
        ws_client.subscribe("v2/ticker", [trade.call.leg.symbol, trade.put.leg.symbol])
    else:
        log.warning("WebSocket did not connect in time; continuing on REST polling only")

    try:
        while True:
            time.sleep(settings.poll_interval_sec)

            marks = refresh_leg_mark_prices(client, trade)
            current_equity = get_account_equity(client) if not dry_run else equity

            stop_loss_tripped = risk_manager.check_leg_stop_loss(trade)
            take_profit_tripped = risk_manager.check_take_profit(
                trade, marks[trade.call.leg.symbol], marks[trade.put.leg.symbol]
            )
            circuit_breaker_tripped = risk_manager.check_daily_circuit_breaker(current_equity)
            eod = risk_manager.should_square_off_eod()

            if stop_loss_tripped or take_profit_tripped or circuit_breaker_tripped or eod:
                reason = (
                    "stop-loss" if stop_loss_tripped else
                    "take-profit" if take_profit_tripped else
                    "daily-circuit-breaker" if circuit_breaker_tripped else
                    "end-of-day"
                )
                log.info("Closing strangle: reason=%s", reason)
                risk_manager.flatten(order_manager, trade)
                break
    except KeyboardInterrupt:
        log.info("Interrupted by user, flattening position before exit")
        risk_manager.flatten(order_manager, trade)
    finally:
        ws_client.stop()

    log.info("Run complete")


if __name__ == "__main__":
    run()
