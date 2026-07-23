"""CLI: fetch SOLUSD history from Delta Exchange India, run a strategy
through the backtester (with Delta's maker/taker + GST fee model applied),
and print a performance report.

Examples:
    python -m sol_backtest.main --start 2025-01-01 --end 2026-01-01 \
        --resolution 1h --strategy sma_crossover --fast 10 --slow 30

    python -m sol_backtest.main --start 2025-01-01 --end 2026-01-01 \
        --resolution 15m --strategy pivot_r1_rejection
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
from sol_backtest.strategies.pivot_r1_rejection import PivotR1RejectionStrategy
from sol_backtest.strategies.sma_crossover import SmaCrossoverStrategy

# kind: "signal" strategies implement generate_signals + run through Backtester.
#       "pattern" strategies implement generate_setups (entry/stop/target) and
#       run through PatternBacktester, and additionally need daily OHLC to
#       compute pivot levels.
STRATEGIES = {
    "sma_crossover": {
        "kind": "signal",
        "factory": lambda args, daily_df: SmaCrossoverStrategy(fast=args.fast, slow=args.slow),
    },
    "pivot_r1_rejection": {
        "kind": "pattern",
        "factory": lambda args, daily_df: PivotR1RejectionStrategy(daily_df, target_level=args.target_level),
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
    p.add_argument("--target-level", default="pp", choices=["pp", "r1", "r2", "r3", "s1", "s2", "s3"],
                    help="pivot_r1_rejection: which pivot level to use as the take-profit target")
    p.add_argument("--capital", type=float, default=settings.initial_capital)
    p.add_argument("--leverage", type=float, default=settings.leverage)
    p.add_argument("--allocation-pct", type=float, default=settings.allocation_pct)
    p.add_argument("--maker", action="store_true", help="Assume maker fees instead of taker")
    p.add_argument("--no-cache", action="store_true", help="Bypass the local candle cache")
    p.add_argument("--no-csv", action="store_true", help="Skip writing the per-trade CSV to sol_backtest/results/")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    start, end = _to_unix(args.start), _to_unix(args.end)
    strategy_info = STRATEGIES[args.strategy]
    base_url = base_url_for(args.env)

    print(f"Fetching {args.symbol} [{args.resolution}] candles from {args.start} to {args.end} ({args.env})...")
    df = fetch_candles(
        base_url=base_url, symbol=args.symbol, resolution=args.resolution,
        start=start, end=end, use_cache=not args.no_cache,
    )
    print(f"Loaded {len(df)} candles.")

    daily_df = None
    if strategy_info["kind"] == "pattern":
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
              f"target={reasons.get('target', 0)}  eod_forced={reasons.get('eod_forced', 0)}")
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
