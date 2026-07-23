# Delta Exchange India — Option Algo Trading (Short Strangle)

An automated options-selling algo for **Delta Exchange India**, built on the
approach recommended on Delta's [Algo Trading APIs page](https://www.delta.exchange/algo/delta-exchange-apis):
a signed **REST API** for account/order actions plus a persistent
**WebSocket** feed for real-time market data, combined into a single
strategy loop.

## Strategy: delta-neutral short strangle

Sell an out-of-the-money call and an out-of-the-money put whose option
delta sits close to a target value (default `0.16`, i.e. roughly a
one-standard-deviation strangle on the nearest expiry), collecting premium
on the view that the underlying stays inside that range. Every tick, three
independent risk checks run against the open position:

1. **Per-leg stop loss** — a short leg's premium runs up to
   `stop_loss_multiple × entry credit` (default `2x`).
2. **Take profit** — close once `take_profit_pct` (default `50%`) of the
   total credit collected has been captured.
3. **Daily circuit breaker** — flatten everything and stop for the day if
   account equity drawdown exceeds `max_daily_loss_pct` (default `5%`).

Positions are also force-flattened at `eod_square_off_ist` (default
`23:25` IST) regardless of the above.

This is one concrete strategy, not the only one the architecture supports —
`strategy/short_strangle.py` is intentionally isolated from the
REST/WebSocket/order/risk plumbing so a different options strategy (e.g. an
iron condor, a directional single-leg seller, a calendar spread) can be
dropped in without touching the rest of the codebase.

## Architecture

```
config.py                    Settings (.env-driven), safety switches
core/
  auth.py                    HMAC-SHA256 request signing
  rest_client.py             Signed REST wrapper (products, option chain,
                              orders, positions, balances)
  ws_client.py                Reconnecting WebSocket client for live ticks
  logger.py                   Structured logging
strategy/
  short_strangle.py           Strike selection from option chain + greeks
  order_manager.py             Order placement, dry-run/live gating
  risk_manager.py              Stop loss / take profit / circuit breaker / EOD
main.py                        Orchestrates the loop end to end
tests/                          Unit tests for signing + strike selection
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env with your Delta Exchange India API key/secret
```

Get API credentials from **Delta Exchange India → Account → API Management**.
**Always start on testnet.** Set `DELTA_ENV=testnet` in `.env` (this is the
default) and only switch to `production` once you've watched the bot behave
correctly for multiple full cycles.

## Safety: dry-run by default

The bot **will not place a single real order** unless `LIVE_TRADING=true`
is explicitly set in `.env`. With it unset (or `false`), every "trade" is
logged as `[DRY-RUN]` using live market data, so you can validate the
strike-selection and risk logic against real option chains before risking
capital. Recommended path:

1. `DELTA_ENV=testnet`, `LIVE_TRADING=false` — verify logs make sense.
2. `DELTA_ENV=testnet`, `LIVE_TRADING=true` — verify real (testnet) orders
   fill and risk exits fire correctly.
3. Only then move to `DELTA_ENV=production`, starting with `lots_per_leg=1`
   and conservative `capital_allocation_pct`.

## Running

```bash
python -m delta_option_algo.main
```

## Configuration

All strategy parameters live in `delta_option_algo/config.py` (`Settings`
dataclass): `underlying`, `target_leg_delta`, `delta_tolerance`,
`max_bid_ask_spread_pct`, `lots_per_leg`, `capital_allocation_pct`,
`stop_loss_multiple`, `take_profit_pct`, `max_daily_loss_pct`,
`poll_interval_sec`, `eod_square_off_ist`.

## Tests

```bash
pip install pytest
python -m pytest delta_option_algo/tests -v
```

Covers HMAC signature generation and strangle strike selection
(target-delta matching, liquidity/spread filtering) against synthetic
option chains — no live API access required.

## Important notes / disclaimer

- **This trades real money if `LIVE_TRADING=true` on a production
  environment.** Selling naked/uncovered options carries theoretically
  unbounded risk on the call side and substantial risk on the put side.
  Understand the strategy fully before enabling live trading, and only risk
  capital you can afford to lose.
- The WebSocket authentication handshake (`core/ws_client.py`) follows
  Delta's documented HMAC signing convention applied to the `/live` path;
  verify it against your account on testnet before relying on it, since
  Delta's private channel documentation was not directly accessible while
  building this.
- Order/position field names (e.g. `average_fill_price`, `settlement_time`,
  `mark_price`, `greeks.delta`) follow Delta's public REST documentation and
  the official `delta-rest-client` reference; re-verify against
  `https://docs.delta.exchange` if Delta changes their API.
- Nothing here is financial advice.
