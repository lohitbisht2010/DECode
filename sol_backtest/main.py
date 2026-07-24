"""CLI: fetch SOLUSD history from Delta Exchange India, run a strategy
through the backtester (with Delta's maker/taker + GST fee model applied),
and print a performance report.

Examples:
    python -m sol_backtest.main --start 2025-01-01 --end 2026-01-01 \
        --resolution 1h --strategy sma_crossover --fast 10 --slow 30

    python -m sol_backtest.main --start 2025-01-01 --end 2026-01-01 \
        --resolution 15m --strategy pivot_r1_rejection

    python -m sol_backtest.main --start 2025-01-01 --end 2026-01-01 \
        --resolution 15m --strategy pivot_r1_breakout

    python -m sol_backtest.main --start 2025-01-01 --end 2026-01-01 \
        --resolution 15m --strategy pivot_ladder_rejection

    python -m sol_backtest.main --start 2025-01-01 --end 2026-01-01 \
        --resolution 15m --strategy supertrend_rejection
"""
import argparse
from collections import Counter
from datetime import datetime, timezone

from sol_backtest.backtest.engine import Backtester
from sol_backtest.backtest.metrics import compute_metrics
from sol_backtest.backtest.pattern_engine import PatternBacktester, PatternTrade
from sol_backtest.config import RESOLUTION_SECONDS, base_url_for, settings
from sol_backtest.data.fetcher import fetch_candles
from sol_backtest.fees import FeeModel
from sol_backtest.reporting import save_trades_csv
from sol_backtest.strategies.pivot_ladder_rejection import PivotLadderRejectionStrategy
from sol_backtest.strategies.pivot_r1_breakout import PivotR1BreakoutStrategy
from sol_backtest.strategies.pivot_r1_rejection import PivotR1RejectionStrategy
from sol_backtest.strategies.sma_crossover import SmaCrossoverStrategy
from sol_backtest.strategies.supertrend_rejection import SupertrendRejectionStrategy

# kind: "signal" strategies implement generate_signals + run through Backtester.
#       "pattern" strategies implement generate_setups (entry/stop/target) and
#       run through PatternBacktester.
# needs_daily_data: pivot-based strategies need daily OHLC to compute pivot
#       levels; Supertrend is computed directly on the trading timeframe and
#       doesn't need it.
# default_target_level: used to fill in --target-level when the user didn't
#       pass one explicitly (rejection fades back down to PP; breakout's
#       next target is naturally above R1, so PP/S1 wouldn't make sense).
#       None for strategies where --target-level doesn't apply at all.
STRATEGIES = {
    "sma_crossover": {
        "kind": "signal",
        "factory": lambda args, daily_df: SmaCrossoverStrategy(fast=args.fast, slow=args.slow),
        "needs_daily_data": False,
        "default_target_level": None,
    },
    "pivot_r1_rejection": {
        "kind": "pattern",
        "factory": lambda args, daily_df: PivotR1RejectionStrategy(daily_df, target_level=args.target_level),
        "needs_daily_data": True,
        "default_target_level": "pp",
    },
    "pivot_r1_breakout": {
        "kind": "pattern",
        "factory": lambda args, daily_df: PivotR1BreakoutStrategy(daily_df, target_level=args.target_level),
        "needs_daily_data": True,
        "default_target_level": "r2",
    },
    "pivot_ladder_rejection": {
        "kind": "pattern",
        "factory": lambda args, daily_df: PivotLadderRejectionStrategy(daily_df),
        "needs_daily_data": True,
        "default_target_level": None,  # target is fixed by the ladder rung, not configurable
    },
    "supertrend_rejection": {
        "kind": "pattern",
        "factory": lambda args, daily_df: SupertrendRejectionStrategy(
            atr_period=args.atr_period, multiplier=args.supertrend_multiplier,
        ),
        "needs_daily_data": False,
        "default_target_level": None,  # no fixed target - exits on trend flip
    },
}

DAILY_PIVOT_LOOKBACK_DAYS = 2  # extra days of daily data fetched before `start` so the first bar has a prior-day pivot


def _to_unix(date_str: str) -> int:
    return int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol", default=settings.symbol)
    p.add_argument("--resolution", default=settings.resolution, choices=sorted(RESOLUTION_SECONDS))
    p.add_argument("--start", required=True, help="YYYY-MM-DD (UTC)")
    p.add_argument("--end", required=True, help="YYYY-MM-DD (UTC)")
    p.add_argument("--env", default=settings.env, choices=["production", "testnet"])
    p.add_argument("--strategy", default="sma_crossover", choices=sorted(STRATEGIES))
    p.add_argument("--fast", type=int, default=10, help="SMA crossover: fast period")
    p.add_argument("--slow", type=int, default=30, help="SMA crossover: slow period")
    p.add_argument("--target-level", default=None, choices=["pp", "r1", "r2", "r3", "s1", "s2", "s3"],
                    help="pivot strategies: which pivot level to use as the take-profit target. "
                         "Defaults to PP for pivot_r1_rejection, R2 for pivot_r1_breakout. Not used by "
                         "pivot_ladder_rejection (target is fixed by the ladder rung) or supertrend_rejection "
                         "(no fixed target - exits on trend flip).")
    p.add_argument("--atr-period", type=int, default=10, help="supertrend_rejection: ATR period")
    p.add_argument("--supertrend-multiplier", type=float, default=3.0, help="supertrend_rejection: ATR multiplier")
    p.add_argument("--capital", type=float, default=settings.initial_capital)
    p.add_argument("--leverage", type=float, default=settings.leverage)
    p.add_argument("--allocation-pct", type=float, default=settings.allocation_pct,
                    help="Fixed sizing: %% of equity used as margin per trade. Ignored if --risk-pct-per-trade is set.")
    p.add_argument("--risk-pct-per-trade", type=float, default=None,
                    help="Pattern strategies only (pivot_r1_rejection, pivot_r1_breakout): size each trade so "
                         "a stop-out loses exactly this %% of current equity, e.g. 1 for 1%% risk. Position size "
                         "= (equity * risk%%) / |entry - stop|, capped by --leverage's buying power. Overrides "
                         "--allocation-pct when set.")
    p.add_argument("--reward-multiple", type=float, default=None,
                    help="Pattern strategies only: place the take-profit target this many multiples of the "
                         "stop distance from the actual entry price, overriding --target-level's pivot-based "
                         "target. E.g. with --risk-pct-per-trade 1, --reward-multiple 4 means a stop-out loses "
                         "1%% of equity and hitting target gains 4%% - a 1:4 risk:reward setup.")
    p.add_argument("--maker", action="store_true", help="Assume maker fees instead of taker")
    p.add_argument("--no-cache", action="store_true", help="Bypass the local candle cache")
    p.add_argument("--no-csv", action="store_true", help="Skip writing the per-trade CSV to sol_backtest/results/")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    start, end = _to_unix(args.start), _to_unix(args.end)
    strategy_info = STRATEGIES[args.strategy]
    base_url = base_url_for(args.env)

    if args.target_level is None:
        args.target_level = strategy_info["default_target_level"]

    print(f"Fetching {args.symbol} [{args.resolution}] candles from {args.start} to {args.end} ({args.env})...")
    df = fetch_candles(
        base_url=base_url, symbol=args.symbol, resolution=args.resolution,
        start=start, end=end, use_cache=not args.no_cache,
    )
    print(f"Loaded {len(df)} candles.")

    daily_df = None
    if strategy_info["needs_daily_data"]:
        daily_start = start - DAILY_PIVOT_LOOKBACK_DAYS * 86400
        print(f"Fetching {args.symbol} [1d] candles for pivot calculation ({DAILY_PIVOT_LOOKBACK_DAYS} day lookback)...")
        daily_df = fetch_candles(
            base_url=base_url, symbol=args.symbol, resolution="1d",
            start=daily_start, end=end, use_cache=not args.no_cache,
        )

    strategy = strategy_info["factory"](args, daily_df)

    fee_model = FeeModel(
        maker_fee_pct=settings.maker_fee_pct,
        taker_fee_pct=settings.taker_fee_pct,
        gst_pct=settings.gst_pct,
    )

    if strategy_info["kind"] == "signal":
        if args.risk_pct_per_trade is not None or args.reward_multiple is not None:
            print("Warning: --risk-pct-per-trade/--reward-multiple have no effect on signal-kind "
                  "strategies (no stop level to size or target against) - ignoring them.")
        signals = strategy.generate_signals(df)
        backtester = Backtester(
            fee_model=fee_model, initial_capital=args.capital, leverage=args.leverage,
            allocation_pct=args.allocation_pct, assume_maker_fees=args.maker,
        )
        result = backtester.run(df, signals)
    else:
        setups = strategy.generate_setups(df)
        print(f"Pattern triggered on {int(setups['entry_signal'].sum())} bars.")
        backtester = PatternBacktester(
            fee_model=fee_model, initial_capital=args.capital, leverage=args.leverage,
            allocation_pct=args.allocation_pct, assume_maker_fees=args.maker,
            risk_pct_per_trade=args.risk_pct_per_trade, reward_multiple=args.reward_multiple,
        )
        result = backtester.run(df, setups)

    periods_per_year = (365 * 86400) / RESOLUTION_SECONDS[args.resolution]
    metrics = compute_metrics(result.equity_curve, result.trades, args.capital, periods_per_year)

    fee_side = "maker" if args.maker else "taker"
    fee_pct = settings.maker_fee_pct if args.maker else settings.taker_fee_pct
    print("\n" + "=" * 60)
    print(f"Strategy: {args.strategy}  |  {args.symbol} {args.resolution}  |  {args.start} -> {args.end}")
    print(f"Fees assumed: {fee_side} {fee_pct}% + {settings.gst_pct}% GST on the fee "
          f"(source: delta.exchange/fees, perpetual futures schedule)")
    if strategy_info["kind"] == "pattern" and args.risk_pct_per_trade is not None:
        print(f"Position sizing: {args.risk_pct_per_trade}% equity risk per trade "
              f"(capped at {args.leverage}x equity buying power)")
    else:
        print(f"Position sizing: {args.allocation_pct}% of equity as margin, {args.leverage}x leverage")
    if strategy_info["kind"] == "pattern" and args.reward_multiple is not None:
        print(f"Target: {args.reward_multiple}x the stop distance from entry (overrides --target-level)")
    print("=" * 60)
    print(f"Initial capital:      {metrics['initial_capital']:,.2f}")
    print(f"Final equity:         {metrics['final_equity']:,.2f}")
    print(f"Total return:         {metrics['total_return_pct']:.2f}%")
    print(f"CAGR:                 {metrics['cagr_pct']:.2f}%")
    print(f"Sharpe ratio:         {metrics['sharpe_ratio']:.2f}")
    print(f"Max drawdown:         {metrics['max_drawdown_pct']:.2f}%")
    print(f"Number of trades:     {metrics['num_trades']}")
    print(f"Win rate:             {metrics['win_rate_pct']:.2f}%")
    print(f"Profit factor:        {metrics['profit_factor']:.2f}")
    if result.trades and isinstance(result.trades[0], PatternTrade):
        reasons = Counter(t.exit_reason for t in result.trades)
        print(f"Exit breakdown:       stop={reasons.get('stop', 0)}  "
              f"target={reasons.get('target', 0)}  signal_exit={reasons.get('signal_exit', 0)}  "
              f"eod_forced={reasons.get('eod_forced', 0)}")
        tags = Counter(t.tag for t in result.trades if t.tag)
        if tags:
            tag_str = "  ".join(f"{k}={v}" for k, v in sorted(tags.items()))
            print(f"Trigger levels:       {tag_str}")
    print("-" * 60)
    print(f"Gross P&L (no fees):  {metrics['gross_pnl']:,.2f}")
    print(f"Total fees paid:      {metrics['total_fees_paid']:,.2f}")
    print(f"Net P&L (after fees): {metrics['net_pnl']:,.2f}")
    print(f"Fees as % of gross P&L: {metrics['fees_as_pct_of_gross_pnl']:.2f}%")
    print("=" * 60)

    if not args.no_csv and result.trades:
        filename = f"{args.strategy}_{args.symbol}_{args.resolution}_{args.start}_{args.end}.csv"
        path = save_trades_csv(result.trades, filename)
        print(f"\nPer-trade log written to: {path}")


if __name__ == "__main__":
    main()
