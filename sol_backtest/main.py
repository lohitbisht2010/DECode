"""CLI: fetch SOLUSD history from Delta Exchange India, run a strategy
through the backtester (with Delta's maker/taker + GST fee model applied),
and print a performance report.

Example:
    python -m sol_backtest.main --start 2025-01-01 --end 2026-01-01 \
        --resolution 1h --strategy sma_crossover --fast 10 --slow 30
"""
import argparse
from datetime import datetime, timezone

from sol_backtest.backtest.engine import Backtester
from sol_backtest.backtest.metrics import compute_metrics
from sol_backtest.config import RESOLUTION_SECONDS, base_url_for, settings
from sol_backtest.data.fetcher import fetch_candles
from sol_backtest.fees import FeeModel
from sol_backtest.strategies.sma_crossover import SmaCrossoverStrategy

STRATEGIES = {
    "sma_crossover": lambda args: SmaCrossoverStrategy(fast=args.fast, slow=args.slow),
}


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
    p.add_argument("--capital", type=float, default=settings.initial_capital)
    p.add_argument("--leverage", type=float, default=settings.leverage)
    p.add_argument("--allocation-pct", type=float, default=settings.allocation_pct)
    p.add_argument("--maker", action="store_true", help="Assume maker fees instead of taker")
    p.add_argument("--no-cache", action="store_true", help="Bypass the local candle cache")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    start, end = _to_unix(args.start), _to_unix(args.end)

    print(f"Fetching {args.symbol} [{args.resolution}] candles from {args.start} to {args.end} ({args.env})...")
    df = fetch_candles(
        base_url=base_url_for(args.env),
        symbol=args.symbol,
        resolution=args.resolution,
        start=start,
        end=end,
        use_cache=not args.no_cache,
    )
    print(f"Loaded {len(df)} candles.")

    strategy = STRATEGIES[args.strategy](args)
    signals = strategy.generate_signals(df)

    fee_model = FeeModel(
        maker_fee_pct=settings.maker_fee_pct,
        taker_fee_pct=settings.taker_fee_pct,
        gst_pct=settings.gst_pct,
    )
    backtester = Backtester(
        fee_model=fee_model,
        initial_capital=args.capital,
        leverage=args.leverage,
        allocation_pct=args.allocation_pct,
        assume_maker_fees=args.maker,
    )
    result = backtester.run(df, signals)

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
    print("-" * 60)
    print(f"Gross P&L (no fees):  {metrics['gross_pnl']:,.2f}")
    print(f"Total fees paid:      {metrics['total_fees_paid']:,.2f}")
    print(f"Net P&L (after fees): {metrics['net_pnl']:,.2f}")
    print(f"Fees as % of gross P&L: {metrics['fees_as_pct_of_gross_pnl']:.2f}%")
    print("=" * 60)


if __name__ == "__main__":
    main()
