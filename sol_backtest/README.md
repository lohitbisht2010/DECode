# SOLUSD Strategy Backtester (Delta Exchange India)

Pulls historical SOLUSD perpetual futures candles from Delta Exchange
India, runs a pluggable strategy against them, and reports performance
including Delta's actual trading fees (maker/taker + GST).

## Architecture

```
config.py                Settings: symbol, resolution, fee schedule, backtest defaults
fees.py                  FeeModel: maker/taker % of notional + 18% GST, per Delta's fee schedule
pivots.py                Daily pivot points (PP/R1/R2/R3/S1/S2/S3) attached to intraday bars
indicators.py            Supertrend (ATR-based, sticky bands), computed on the trading timeframe
data/fetcher.py          Paginated /v2/history/candles fetcher with local CSV caching
backtest/engine.py       Signal-driven long/short backtester ("hold until next signal")
backtest/pattern_engine.py  Pattern-trade backtester (entry + stop-loss + target/exit-signal,
                          checked bar-by-bar) for strategies whose exit isn't just "next signal"
backtest/metrics.py      Total return, CAGR, Sharpe, max drawdown, win rate, profit factor,
                          gross vs net P&L, fees as % of gross P&L
strategies/base.py            Strategy interface: generate_signals(df) -> Series of {1, 0, -1}
strategies/pattern_base.py     PatternStrategy interface: generate_setups(df) -> entry/stop/target
strategies/sma_crossover.py    Placeholder demo strategy for the signal-based engine
strategies/pivot_r1_rejection.py     R1 rejection outside-bar pattern (see below)
strategies/pivot_r1_breakout.py      R1 breakout continuation pattern (see below)
strategies/pivot_ladder_rejection.py  Same rejection pattern at every pivot rung (see below)
strategies/supertrend_rejection.py    Rejection at the Supertrend line, trend-flip exit (see below)
portfolio.py              Combine multiple strategies' results: return correlation, weighted
                          portfolio equity curve, scaled/merged trade list
main.py                   CLI: fetch -> backtest -> report for a single strategy
compare.py                 CLI: run several strategies over the same window, compare them,
                          and report a combined-capital portfolio (see below)
tests/                     Unit tests for fees, both engines, indicators, pivots, pattern
                          detection, and portfolio combination
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

## Strategy: R1 rejection outside-bar (`pivot_r1_rejection`)

On the 15m timeframe, comparing each bar to the one immediately before it:

1. `current.high  >  previous.high` — takes out the prior bar's high
2. `current.close <= previous.open` — closes back below the prior bar's open
3. `previous.open  <  previous.close` — prior bar was bullish
4. `current.open   >  current.close` — current bar is bearish
5. `current.high   >= R1` — pokes at/through the pivot resistance
6. `current.close  <  R1` — but closes back below it (a rejection)

R1 and PP come from the **previous UTC day's** daily pivot (classic
floor-trader formula: `PP=(H+L+C)/3`, `R1=2*PP-L`, etc. — see `pivots.py`).
Trade plan: **short at the next bar's open**, **stop at the signal bar's
own high** (pattern invalidated if price keeps going), **target at a
pivot level** — defaults to PP (fade back to the pivot), configurable via
`--target-level {pp,r1,r2,r3,s1,s2,s3}` (e.g. `--target-level s1` for a
deeper fade to the first support level). This runs through
`PatternBacktester`, which checks the stop and target against every
subsequent bar's high/low (not just the close) until one is hit; if both
would be hit in the same bar, the stop is assumed to win (the
conservative assumption, since intrabar order isn't knowable from OHLC
data alone).

One thing worth confirming against your own read of the pattern:
*"prev open<close"* was read as "the previous bar's open is below its
close" (i.e. previous bar bullish) — the alternative parse ("previous
open below the *current* close") didn't fit the rest of the pattern. If
that's not what you meant, it's an isolated change in
`strategies/pivot_r1_rejection.py`.

## Strategy: R1 breakout continuation (`pivot_r1_breakout`)

The opposite thesis: instead of fading a failed poke through R1, trade
*with* momentum once R1 breaks with conviction. Same 15m/previous-bar
comparison structure:

1. `previous.close <= R1` — R1 not yet broken as of the prior close
2. `current.close   >  R1` — breakout confirmed by close, not just a wick through
3. `current.open    <  current.close` — bullish/strength candle
4. `current.high    >  previous.high` — making a new high, momentum continuing

Condition 1 restricts signals to the *first* bar that closes through R1,
so the pattern doesn't keep re-firing on every bar price simply holds
above it. Trade plan: **long at the next bar's open**, **stop at the
breakout bar's own low** (invalidated if price falls back below it),
**target at a pivot level** — defaults to **R2** rather than PP, since
PP/S1 sit *behind* a long entry here and wouldn't make sense as a target
(configurable via the same `--target-level`).

This is why fee drag matters for strategy selection: a rejection/fade
trades against the immediate move with a tight target near the pivot
(many round trips, small average win), while a breakout trades with the
move and can target the next resistance level out or run a wider
`--reward-multiple` (fewer, larger wins) — see the "which strategy suits
this fee schedule" discussion this was built to test.

## Strategy: pivot ladder rejection (`pivot_ladder_rejection`)

The same rejection pattern as `pivot_r1_rejection`, but checked at every
rung of the pivot ladder instead of only R1, each targeting the level one
rung below it:

```
R3 -> R2,  R2 -> R1,  R1 -> PP,  PP -> S1,  S1 -> S2,  S2 -> S3
```

The trigger conditions at each rung are identical to the R1 pattern
(substitute "R1" for whichever level is being tested). If a bar's high
happens to clear more than one level at once, the *highest* one rejected
wins (more extreme = more informative) — stop is always the signal bar's
own high, same as every other rejection variant. There's no rung for a
rejection *at* S3 (nothing below it to target).

Each trade's CSV row and the CLI's `Trigger levels:` summary line record
which rung (`tag` column: `r3`, `r2`, `r1`, `pp`, `s1`, or `s2`) fired it,
so you can see whether particular levels perform differently from others.

## Strategy: Supertrend rejection continuation (`supertrend_rejection`)

The same rejection pattern again, this time triggered against the
[Supertrend](https://en.wikipedia.org/wiki/SuperTrend) line (`indicators.py`,
ATR-based with sticky recursive bands, default period 10 / multiplier 3 —
tune with `--atr-period` / `--supertrend-multiplier`) instead of a daily
pivot: price is in a downtrend (Supertrend red, sitting above price as
resistance), rallies up into the line, and gets rejected — trading with
the trend's continuation rather than against it.

1. `trend == -1` (Supertrend currently red/bearish)
2. `current.high  >  previous.high`
3. `current.close <= previous.open`
4. `previous.open  <  previous.close`
5. `current.open   >  current.close`
6. `current.high   >= supertrend`
7. `current.close  <  supertrend`

Unlike every other strategy here, there's **no fixed take-profit target**:
short at the next bar's open, stop at the signal bar's own high, and hold
until the Supertrend itself flips bullish (price closes above it) — exit
at the *next* bar's open once that flip is confirmed, same no-lookahead
convention as entries. This is the first strategy to exercise
`PatternBacktester`'s NaN-target + `exit_signal` machinery instead of a
fixed target level; `main.py`'s exit breakdown reports `signal_exit`
counts alongside `stop`/`target`/`eod_forced` for it.

In the real backtest run against 2025-01-01 through 2026-07-01, 21 of 28
trades were stopped out (75%) versus only 7 signal exits — worth noting
since it points at a structural tension in this exact rule set: a stop
pinned to the signal candle's own high is tight by mean-reversion
standards, but this is nominally a trend-*continuation* trade, so it gets
stopped out before the trend has room to reassert itself more often than
it survives to actually ride the continuation.

## Plugging in a different pattern

Two extension points depending on how your strategy exits a position:

- **Hold until the next signal** (like a moving-average crossover): add a
  file to `strategies/` implementing `Strategy.generate_signals(df) ->
  pd.Series` (1 = long, -1 = short, 0 = flat, one value per bar), and run
  it through `backtest.engine.Backtester`.
- **Discrete entry + stop-loss + target** (like the R1 rejection pattern
  above): implement `PatternStrategy.generate_setups(df) -> pd.DataFrame`
  with `entry_signal`/`direction`/`stop_price`/`target_price` columns, and
  run it through `backtest.pattern_engine.PatternBacktester`.

Either way, register the strategy in `main.py`'s `STRATEGIES` dict (with
`"kind": "signal"` or `"kind": "pattern"`) and run it via `--strategy
<name>`. Both engines execute on the bar *after* a signal, using only data
available up to and including the signal bar — no lookahead.

## Comparing strategies and combining them into a portfolio (`compare.py`)

```bash
python -m sol_backtest.compare \
  --start 2025-01-01 --end 2026-07-01 --resolution 15m \
  --leverage 5 --risk-pct-per-trade 1
```

Runs every pattern strategy (or a `--strategies a,b,c` subset) over the
*same* price data and reports three things:

1. **Independent comparison** — each strategy's own metrics, as if it
   alone had the full capital.
2. **Pairwise return correlation** — daily-return correlation between
   each pair, to see whether they move together or diversify each other.
3. **Combined portfolio** — an equal-weighted (or `--weights
   0.4,0.3,0.2,0.1`-style custom-weighted) blend, using the *same*
   capital split across all of them rather than each getting the full
   amount.

The combined curve is computed by scaling and summing each strategy's
full-capital equity curve rather than re-running every backtest at a
fraction of the capital (`portfolio.py`) — valid because every sizing
mode here (`--allocation-pct` or `--risk-pct-per-trade`) is a percentage
of *current* equity, so every dollar figure in a trade scales linearly
with starting capital. Running strategy *i* alone at `weight_i * capital`
produces exactly `weight_i * equity_curve_i(t)` at every bar; summing the
scaled full-capital curves gives the identical result a real capital-split
portfolio would produce.

**Real result** (2025-01-01 → 2026-07-01, 15m, 1% risk/trade, 5x leverage cap):

| strategy | trades | win% | profit factor | return% | fees paid | net P&L |
|---|---|---|---|---|---|---|
| pivot_r1_rejection | 71 | 28.2 | 0.68 | -19.4% | 15,085 | -19,417 |
| pivot_r1_breakout | 359 | 28.1 | 0.67 | -65.8% | 48,195 | -65,783 |
| pivot_ladder_rejection | 346 | 27.2 | 0.75 | -53.1% | 54,880 | -53,048 |
| supertrend_rejection | 28 | 7.1 | 0.12 | -23.5% | 6,142 | -23,488 |

Pairwise correlation of daily returns, same window:

| | rejection | breakout | ladder | supertrend |
|---|---|---|---|---|
| **rejection** | 1.00 | 0.07 | 0.33 | 0.06 |
| **breakout** | 0.07 | 1.00 | 0.03 | 0.08 |
| **ladder** | 0.33 | 0.03 | 1.00 | 0.07 |
| **supertrend** | 0.06 | 0.08 | 0.07 | 1.00 |

All four are genuinely low-correlated (0.03-0.33) — they lose money via
different mechanisms and timing, not the same one four times over. That's
the technical definition of a diversification benefit, and it's real
here. But **diversification reduces variance, not a negative mean
return** - all four lost money individually over this window, so the
equal-weighted combined portfolio comes out close to the simple average
of their returns (-40.4%, essentially `(-19.4 -65.8 -53.1 -23.5)/4`) — a
smoother decline, not a profitable one. Low correlation between
strategies is a real, useful property to know about *once you have
strategies with positive expectancy* to combine; it doesn't rescue a set
that doesn't have one yet. None of these four would be worth running live
as specified, individually or combined, over this period.

## Verifying individual trades

Every run writes a per-trade CSV to `sol_backtest/results/` (pass
`--no-csv` to skip it), named
`{strategy}_{symbol}_{resolution}_{start}_{end}.csv`, e.g.
`pivot_r1_rejection_SOLUSD_15m_2025-01-01_2026-01-01.csv`. One row per
closed trade:

| column | meaning |
|---|---|
| `entry_time` / `exit_time` | UTC timestamps of the fills |
| `direction` | `long` or `short` |
| `entry_price` / `exit_price` | fill prices used |
| `qty` | position size in the underlying |
| `entry_fee` / `exit_fee` | fee charged on each leg (incl. GST) |
| `gross_pnl` / `net_pnl` | before/after fees |
| `stop_price` / `target_price` / `exit_reason` | pattern strategies only — `exit_reason` is `stop`, `target`, `signal_exit`, or `eod_forced` |
| `tag` | pattern strategies that set one (e.g. `pivot_ladder_rejection` records which rung — `r3`/`r2`/`r1`/`pp`/`s1`/`s2` — triggered the trade) |

Cross-check a row against the source data with, e.g.:

```bash
python -c "
from sol_backtest.data.fetcher import fetch_candles
from sol_backtest.config import base_url_for
df = fetch_candles(base_url_for('production'), 'SOLUSD', '15m', <start_unix>, <end_unix>)
print(df[(df.time >= <entry_unix> - 3600) & (df.time <= <entry_unix> + 3600)])
"
```

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

# R1 rejection pattern (needs 15m bars; daily data for pivots is fetched automatically)
python -m sol_backtest.main \
  --start 2025-01-01 --end 2026-01-01 \
  --resolution 15m --strategy pivot_r1_rejection --target-level pp \
  --capital 10000 --leverage 1 --allocation-pct 100

# same, but fading to S1 instead of the pivot
python -m sol_backtest.main \
  --start 2025-01-01 --end 2026-01-01 \
  --resolution 15m --strategy pivot_r1_rejection --target-level s1 \
  --capital 10000 --leverage 1 --allocation-pct 100

# 1% equity risk per trade instead of fixed allocation (pattern strategies only)
python -m sol_backtest.main \
  --start 2025-01-01 --end 2026-01-01 \
  --resolution 15m --strategy pivot_r1_rejection --target-level s1 \
  --capital 10000 --leverage 5 --risk-pct-per-trade 1

# risk 1%, target 4% (1:4 risk:reward) - target overrides --target-level entirely
python -m sol_backtest.main \
  --start 2025-01-01 --end 2026-01-01 \
  --resolution 15m --strategy pivot_r1_rejection \
  --capital 10000 --leverage 10 --risk-pct-per-trade 1 --reward-multiple 4

# R1 breakout continuation (defaults to targeting R2, not PP)
python -m sol_backtest.main \
  --start 2025-01-01 --end 2026-01-01 \
  --resolution 15m --strategy pivot_r1_breakout \
  --capital 10000 --leverage 5 --risk-pct-per-trade 1
```

Use `--maker` to assume maker (limit, liquidity-adding) fees instead of
the taker default. `--env testnet` points at Delta's testnet instead of
production. Candle data is cached under `sol_backtest/data/cache/` keyed
by symbol/resolution/date-range, so re-running the same window doesn't
re-hit the API.

## Position sizing: fixed allocation vs. risk-based

Two sizing modes for pattern strategies (`PatternBacktester`):

- **Fixed allocation** (default): `notional = equity * allocation_pct/100 *
  leverage`. Position size doesn't depend on the stop distance, so a
  tight-stop trade and a wide-stop trade risk very different amounts.
- **Risk-based** (`--risk-pct-per-trade N`): position size is derived
  *from* the stop distance so a stop-out loses exactly N% of current
  equity (before fees) — `qty = (equity * N/100) / |entry_price -
  stop_price|`. This is the standard "1% risk per trade" sizing rule.
  Capped at the notional `leverage * equity` would otherwise allow the
  position to have, so an unusually tight stop can't imply an absurd
  position size; if the stop exactly equals the entry price (undefined
  risk), that trade is skipped entirely. `--leverage` still matters here —
  it sets the cap, not the size — so give it enough headroom (e.g. `5`)
  that tight-stop trades aren't clipped below their intended risk.
- `--allocation-pct` is ignored once `--risk-pct-per-trade` is set.
- This only applies to pattern strategies (a stop level is required to
  compute risk); it has no effect on `sma_crossover` and prints a warning
  if you set it there anyway.
- Fee cost isn't included in the risk calculation — a stop-out's actual
  loss is the intended risk amount plus entry/exit fees, so realized loss
  will run slightly over N%.

### Fixed risk:reward target (`--reward-multiple`)

Independent of sizing, `--reward-multiple N` replaces the pivot-based
target (`--target-level`) with one placed `N` times the stop distance from
the *actual fill price*: `target = entry ± N * |entry - stop|` (sign
follows direction). Combined with `--risk-pct-per-trade 1
--reward-multiple 4` ("risk 1%, target 4%"), a stop-out loses exactly 1%
of equity and hitting target gains exactly 4% (both before fees) — a
straightforward 1:4 R:R setup, decoupled from wherever the pivot happens
to sit that day. `--reward-multiple` can be used with either sizing mode
(it only changes where the target is, not the position size); like
`--risk-pct-per-trade`, it's ignored (with a warning) for `sma_crossover`.

### Daily loss-streak circuit breaker (`--max-consecutive-losses-per-day`)

`--max-consecutive-losses-per-day N` stops taking new entries for the
rest of the UTC calendar day once N trades in a row have closed at a net
loss. The streak (and any block) resets at the next day boundary; a
winning trade resets the streak immediately, even mid-day. It's a risk
control on a bad *day*, not a fix for a strategy's underlying edge - in
testing, it barely engaged for `pivot_r1_rejection` and
`pivot_ladder_rejection` (their losses aren't clustered within single
days to begin with), so it moved the combined result by under $500 on
either symbol. If a strategy is losing money because of trade *count* and
per-trade fee cost rather than same-day loss clustering, this flag won't
address that - fewer/larger trades (`--reward-multiple`, `--maker`) will.

## Tests

```bash
pip install pytest
python -m pytest sol_backtest/tests -v
```

71 tests covering: fee calculation (GST, maker vs taker, absolute
notional), both backtest engines' fee accounting (hand-verified against
manually computed equity, including regression tests for a
double-fee-counting bug caught during development), risk-based position
sizing (hand-verified stop-out losses exactly N% of equity, leverage
capping, zero-stop-distance handling), the fixed risk:reward target
(hand-verified against long/short entry prices, and a combined 1%-risk/
4%-target scenario), the NaN-target/`exit_signal` machinery (trend-flip
exits, stop-vs-signal priority), the Supertrend indicator (hand-traced
through its recursive sticky-band logic), fetcher pagination/caching,
pivot point formulas, all four patterns' condition-by-condition detection
(including the ladder's highest-level-wins priority rule), portfolio
combination math (trade scaling, weighted equity curves, return
correlation), and the trade CSV export — all against synthetic data, no
live API access required except for the one real-data validation run
whose results are quoted above.

## Known limitations

- Position sizing recomputes on every entry as a fixed % of *current*
  equity (compounding), not a fixed dollar/contract size — pass
  `--allocation-pct` accordingly.
- No funding-rate simulation for the perpetual (only trading fees), no
  slippage model, and no partial fills — a real fill will differ somewhat
  from the open-price assumption used here, especially on illiquid bars.
- Single position at a time; the engine doesn't support scaling in/out.
