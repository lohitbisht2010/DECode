# BTC Short Strangle Backtester (Delta Exchange India)

Backtests a short strangle (sell an OTM call + OTM put, collect premium)
against **real historical option premium data** from Delta Exchange India -
not a synthetic Black-Scholes simulation. Built after `sol_backtest`'s
futures-based strategies (pivot rejections, Donchian breakout) showed that
Delta's futures fee schedule (0.05% taker / 0.02% maker) eats most of the
edge in high-frequency mean-reversion trading; options are charged a much
lower rate (0.01% maker *and* taker) on the underlying notional, which
changes the economics enough to be worth backtesting directly.

## Why real historical option data, not synthetic

Delta lists a fresh BTC call+put chain **every day**, settling at 12:00 UTC,
~30 strikes per side. Two things made a real backtest possible instead of
a Black-Scholes approximation:

1. `GET /v2/products?states=expired&contract_types=call_options,put_options&underlying_asset_symbols=BTC`
   (paginated) enumerates every option that's ever settled, back to
   2023-12-28 - the same start date as `sol_backtest`'s BTCUSD futures data.
2. `GET /v2/history/candles?symbol=C-BTC-<strike>-<DDMMYY>` returns real
   OHLCV premium candles for those expired contracts, same endpoint
   `sol_backtest` uses for futures.

The one real gap versus a live bot: historical candles carry no Greeks
(no delta/IV history), so strike selection here is by **moneyness**
(`--target-otm-pct`, e.g. 5% away from spot) instead of `delta_option_algo`'s
live ~0.16-delta selection. That's a genuine simplification - moneyness
ignores how delta compresses/expands with realized vol, so the strangle's
actual probability of expiring ITM drifts across cycles at a fixed
`target_otm_pct`.

## Premium quoting convention

Option premiums on Delta are quoted **per 1 BTC of underlying**, not
per-contract - confirmed by checking a deep ITM put against its intrinsic
value directly (`mark_price` for a put struck $3000 above spot came back
as ~$3001, matching `strike - spot` unscaled). The actual dollar premium
per contract is `quoted_price * contract_value` (contract_value = 0.001 BTC
for BTC options, read live from the product data rather than hardcoded).
Fees are charged on `spot_price * contract_value * qty`, the underlying
notional - matching futures' fee convention, just at 0.01% instead of
0.05%/0.02%.

## Strategy: short strangle (`main.py`)

Each expiry cycle:

1. **Entry** (`--entry-hours-before-expiry`, default 6h before the day's
   12:00 UTC settlement): look up spot via the `.DEXBTUSD` index, pick the
   call strike nearest `spot * (1 + target_otm_pct/100)` and the put strike
   nearest `spot * (1 - target_otm_pct/100)` from that day's listed
   strikes, sell one contract of each.
2. **Per-leg stop-loss** (`--stop-loss-multiple`, default 3x): if a leg's
   premium (candle high) reaches this many times its entry premium, buy it
   back immediately - the other leg keeps running independently.
3. **Combined take-profit** (`--take-profit-pct`, default 50%): once the
   remaining open legs' combined current premium has decayed to
   `(100 - take_profit_pct)%` of the cycle's total entry credit, close
   everything at that bar's close.
4. **Settlement**: anything still open at 12:00 UTC settles to intrinsic
   value against the spot index - `max(spot - strike, 0)` for a call,
   `max(strike - spot, 0)` for a put.

Position sizing (`--risk-pct-per-trade`, default 1%): sized so that *both*
legs stopping out simultaneously (the conservative worst case) would lose
exactly that % of equity, `qty = (equity * risk% ) / worst_case_loss`,
capped by `--max-notional-leverage` (default 5x equity notional) as a
backstop - **this backtest does not model Delta's real options margin
(SPAN-style) requirements**, so the leverage cap is a simplification, not
a guarantee the position would actually be marginable.

## Real backtest results

<!-- filled in after running against real Delta India data -->

## Known limitations

- **Strike selection by moneyness, not delta** - see above. A fixed
  `target_otm_pct` doesn't hold delta (and therefore win probability)
  constant across cycles the way the live bot's delta-targeting does.
- **No margin model** - real options margin on Delta is more restrictive
  than the flat notional-leverage cap used here, especially for naked
  short strangles. Position sizes that pencil out on paper may not be
  marginable for real.
- **No fee cap verification** - Delta's fees page returned 403 to
  automated fetches while building this; the 0.01% maker/taker rate comes
  from the live `/v2/products` `taker_commission_rate`/`maker_commission_rate`
  fields, not the docs page, and this project doesn't model any
  premium-based fee cap (common on other crypto options exchanges) since
  none is visible in the product schema. Re-verify before real capital.
- **Legs assumed independently fillable at the modeled price** - stop-outs
  fill exactly at the stop threshold and target exits fill at that bar's
  close; real fills would face slippage, especially on wide-strike,
  lower-volume daily options.
- **Sequential cycles, single equity pool** - cycles don't overlap in time
  (entry sits only hours before each daily expiry) so this is a reasonable
  simplification, but it does mean the backtest can't explore running
  multiple simultaneous expiries' strangles concurrently.

## Setup

Uses the same environment as `sol_backtest` (project root `requirements.txt`,
no separate install needed - `pandas`, `requests`).

## Running a backtest

```bash
# Default: 6h before expiry, 5% OTM each leg, 1% risk per cycle, 3x stop, 50% take-profit
python -m option_backtest.main --start 2024-01-01 --end 2026-07-01

# Tighter strikes, closer to the money (higher premium, higher win rate needed to profit)
python -m option_backtest.main --start 2024-01-01 --end 2026-07-01 --target-otm-pct 2

# Wider strikes, sold further out, held longer
python -m option_backtest.main --start 2024-01-01 --end 2026-07-01 \
    --entry-hours-before-expiry 12 --target-otm-pct 8
```

## Tests

```bash
python -m pytest option_backtest/tests/ -v
```

Engine tests mock `fetch_candles` with synthetic premium data so they don't
hit the live API - covers settlement-to-intrinsic-value exits, per-leg
stop-loss, combined take-profit, position sizing, and fee application.
Strike-selection tests cover moneyness-based nearest-strike picking and the
no-data skip paths.
