# SOLUSD Strategy Backtester (Delta Exchange India)

Pulls historical SOLUSD perpetual futures candles from Delta Exchange
India, runs a pluggable strategy against them, and reports performance
including Delta's actual trading fees (maker/taker + GST).

## Architecture

```
config.py                Settings: symbol, resolution, fee schedule, backtest defaults
fees.py                  FeeModel: maker/taker % of notional + 18% GST, per Delta's fee schedule
data/fetcher.py          Paginated /v2/history/candles fetcher with local CSV caching
backtest/engine.py       Signal-driven long/short backtester, applies fees on every fill
backtest/metrics.py      Total return, CAGR, Sharpe, max drawdown, win rate, profit factor,
                          gross vs net P&L, fees as % of gross P&L
strategies/base.py        Strategy interface: generate_signals(df) -> Series of {1, 0, -1}
strategies/sma_crossover.py  Placeholder demo strategy (swap this out for the real pattern)
main.py                   CLI: fetch -> backtest -> report
tests/                     Unit tests for fees, engine fee accounting, and fetcher pagination/caching
```

## Fee model

Sourced from https://www.delta.exchange/fees and Delta's support article on
options/futures fee calculation, for **perpetual futures** (SOLUSD is a
perpetual, not spot or an option):

- Maker: 0.02% of notional
- Taker: 0.05% of notional
- 18% GST charged on top of the fee amount (India-specific)

Delta's fees page returned an automated-fetch block (403) while building
this, so these numbers were cross-checked against multiple secondary
sources rather than read directly off the page — **re-verify against
https://www.delta.exchange/fees before trusting results for real capital
decisions.** The fee schedule also has volume-based discount tiers that
aren't modelled here; `config.py`'s `maker_fee_pct`/`taker_fee_pct` are the
base retail tier and can be edited directly if you trade at a discounted
tier.

Every trade pays a fee on both legs (entry and exit), computed on that
leg's notional value at the fill price — the same way Delta actually
charges it — not a flat round-trip estimate.

## Plugging in your pattern

`strategies/sma_crossover.py` is a placeholder just to exercise the
pipeline end to end. To backtest your actual pattern:

1. Add a new file in `strategies/`, e.g. `strategies/my_pattern.py`,
   implementing `Strategy.generate_signals(df) -> pd.Series` (1 = long,
   -1 = short, 0 = flat, one value per bar).
2. Register it in `main.py`'s `STRATEGIES` dict.
3. Run it via `--strategy my_pattern`.

The engine executes on the *next* bar's open after a signal changes, so
write `generate_signals` using only data available up to and including the
current bar — no lookahead.

## Setup

```bash
pip install -r requirements.txt
```

## Running a backtest

```bash
python -m sol_backtest.main \
  --start 2025-01-01 --end 2026-01-01 \
  --resolution 1h \
  --strategy sma_crossover --fast 10 --slow 30 \
  --capital 10000 --leverage 1 --allocation-pct 100
```

Use `--maker` to assume maker (limit, liquidity-adding) fees instead of
the taker default. `--env testnet` points at Delta's testnet instead of
production. Candle data is cached under `sol_backtest/data/cache/` keyed
by symbol/resolution/date-range, so re-running the same window doesn't
re-hit the API.

## Tests

```bash
pip install pytest
python -m pytest sol_backtest/tests -v
```

11 tests covering: fee calculation (GST, maker vs taker, absolute
notional), backtest engine fee accounting (hand-verified against manually
computed equity, including a regression test for a double-fee-counting
bug caught during development), and fetcher pagination/caching — all
against synthetic data, no live API access required.

## Known limitations

- Position sizing recomputes on every entry as a fixed % of *current*
  equity (compounding), not a fixed dollar/contract size — pass
  `--allocation-pct` accordingly.
- No funding-rate simulation for the perpetual (only trading fees), no
  slippage model, and no partial fills — a real fill will differ somewhat
  from the open-price assumption used here, especially on illiquid bars.
- Single position at a time; the engine doesn't support scaling in/out.
