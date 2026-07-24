"""CLI: run multiple pattern strategies over the same SOLUSD window and
report (a) each one's standalone performance plus pairwise return
correlation, and (b) a combined equal-weighted (or custom-weighted)
portfolio equity curve and metrics.

Example:
    python -m sol_backtest.compare --start 2025-01-01 --end 2026-07-01 \
        --resolution 15m --risk-pct-per-trade 1

    python -m sol_backtest.compare --start 2025-01-01 --end 2026-07-01 \
        --resolution 15m --strategies pivot_r1_rejection,supertrend_rejection \
        --weights 0.7,0.3
"""
import argparse
from types import SimpleNamespace

from sol_backtest.backtest.metrics import compute_metrics
from sol_backtest.backtest.pattern_engine import PatternBacktester
from sol_backtest.config import RESOLUTION_SECONDS, base_url_for, settings
from sol_backtest.data.fetcher import fetch_candles
from sol_backtest.fees import FeeModel
from sol_backtest.main import STRATEGIES, _daily_lookback_days, _to_unix
from sol_backtest.portfolio import combine_equity_curves, combine_trades, compute_return_correlation
from sol_backtest.reporting import save_trades_csv

DEFAULT_STRATEGIES = ["pivot_r1_rejection", "pivot_r1_breakout", "pivot_ladder_rejection", "supertrend_rejection"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol", default=settings.symbol)
    p.add_argument("--resolution", default=settings.resolution, choices=sorted(RESOLUTION_SECONDS))
    p.add_argument("--start", required=True, help="YYYY-MM-DD (UTC)")
    p.add_argument("--end", required=True, help="YYYY-MM-DD (UTC)")
    p.add_argument("--env", default=settings.env, choices=["production", "testnet"])
    p.add_argument("--strategies", default=",".join(DEFAULT_STRATEGIES),
                    help=f"Comma-separated pattern strategy names. Default: all of {DEFAULT_STRATEGIES}.")
    p.add_argument("--weights", default=None,
                    help="Comma-separated portfolio weights matching --strategies, must sum to 1.0. "
                         "Default: equal weight across all selected strategies.")
    p.add_argument("--pivot-period", default="daily", choices=["daily", "monthly"],
                    help="Applied identically to every pivot-based strategy being compared - see main.py's "
                         "help for details.")
    p.add_argument("--capital", type=float, default=settings.initial_capital)
    p.add_argument("--leverage", type=float, default=settings.leverage)
    p.add_argument("--allocation-pct", type=float, default=settings.allocation_pct)
    p.add_argument("--risk-pct-per-trade", type=float, default=None,
                    help="Applied identically to every strategy being compared - see main.py's help for details.")
    p.add_argument("--reward-multiple", type=float, default=None)
    p.add_argument("--max-consecutive-losses-per-day", type=int, default=None,
                    help="Applied identically to every strategy being compared - see main.py's help for details.")
    p.add_argument("--maker", action="store_true",
                    help="Optimistic: assume maker fees on every fill. See main.py's help for the caveat.")
    p.add_argument("--maker-on-target-only", action="store_true",
                    help="Realistic: maker fee only on target hits, taker on entries/stops/other exits. "
                         "Overrides --maker when both are set.")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--no-csv", action="store_true", help="Skip writing per-trade CSVs for each strategy")
    return p.parse_args()


def _build_strategy(name: str, daily_df, pivot_period: str):
    info = STRATEGIES[name]
    if info["kind"] != "pattern":
        raise ValueError(f"{name} is not a pattern-kind strategy; compare.py only supports pattern strategies")
    ns = SimpleNamespace(
        target_level=info["default_target_level"],
        fast=10, slow=30,
        atr_period=10, supertrend_multiplier=3.0,
        pivot_period=pivot_period,
    )
    return info["factory"](ns, daily_df)


def main() -> None:
    args = parse_args()
    start, end = _to_unix(args.start), _to_unix(args.end)
    strategy_names = [s.strip() for s in args.strategies.split(",") if s.strip()]
    unknown = [s for s in strategy_names if s not in STRATEGIES]
    if unknown:
        raise SystemExit(f"Unknown strategy name(s): {unknown}. Known: {sorted(STRATEGIES)}")

    if args.weights:
        weight_values = [float(w) for w in args.weights.split(",")]
        if len(weight_values) != len(strategy_names):
            raise SystemExit("--weights must have the same number of entries as --strategies")
        weights = dict(zip(strategy_names, weight_values))
    else:
        weights = {name: 1.0 / len(strategy_names) for name in strategy_names}

    base_url = base_url_for(args.env)
    print(f"Fetching {args.symbol} [{args.resolution}] candles from {args.start} to {args.end} ({args.env})...")
    df = fetch_candles(base_url=base_url, symbol=args.symbol, resolution=args.resolution,
                        start=start, end=end, use_cache=not args.no_cache)
    print(f"Loaded {len(df)} candles.")

    daily_df = None
    if any(STRATEGIES[name]["needs_daily_data"] for name in strategy_names):
        daily_start = start - _daily_lookback_days(args.pivot_period) * 86400
        print(f"Fetching {args.symbol} [1d] candles for {args.pivot_period} pivot calculation...")
        daily_df = fetch_candles(base_url=base_url, symbol=args.symbol, resolution="1d",
                                  start=daily_start, end=end, use_cache=not args.no_cache)

    fee_model = FeeModel(maker_fee_pct=settings.maker_fee_pct, taker_fee_pct=settings.taker_fee_pct,
                          gst_pct=settings.gst_pct)
    periods_per_year = (365 * 86400) / RESOLUTION_SECONDS[args.resolution]

    results = {}
    for name in strategy_names:
        strategy = _build_strategy(name, daily_df, args.pivot_period)
        setups = strategy.generate_setups(df)
        backtester = PatternBacktester(
            fee_model=fee_model, initial_capital=args.capital, leverage=args.leverage,
            allocation_pct=args.allocation_pct, assume_maker_fees=args.maker,
            risk_pct_per_trade=args.risk_pct_per_trade, reward_multiple=args.reward_multiple,
            max_consecutive_losses_per_day=args.max_consecutive_losses_per_day,
            maker_on_target_only=args.maker_on_target_only,
        )
        results[name] = backtester.run(df, setups)
        print(f"  {name}: {int(setups['entry_signal'].sum())} signals, {len(results[name].trades)} trades")

        if not args.no_csv and results[name].trades:
            filename = f"{name}_{args.symbol}_{args.resolution}_{args.start}_{args.end}.csv"
            save_trades_csv(results[name].trades, filename)

    metrics_by_strategy = {
        name: compute_metrics(r.equity_curve, r.trades, args.capital, periods_per_year)
        for name, r in results.items()
    }

    print("\n" + "=" * 100)
    print(f"INDEPENDENT COMPARISON  |  {args.symbol} {args.resolution}  |  {args.start} -> {args.end}  "
          f"|  each run alone at {args.capital:,.0f} capital")
    print("=" * 100)
    header = (f"{'strategy':<26}{'trades':>8}{'win%':>8}{'p.factor':>10}{'return%':>10}{'sharpe':>9}{'maxdd%':>9}"
               f"{'gross_pnl':>12}{'fees':>12}{'net_pnl':>12}")
    print(header)
    print("-" * len(header))
    for name, m in metrics_by_strategy.items():
        print(f"{name:<26}{m['num_trades']:>8}{m['win_rate_pct']:>8.1f}{m['profit_factor']:>10.2f}"
              f"{m['total_return_pct']:>10.2f}{m['sharpe_ratio']:>9.2f}{m['max_drawdown_pct']:>9.2f}"
              f"{m['gross_pnl']:>12,.0f}{m['total_fees_paid']:>12,.0f}{m['net_pnl']:>12,.0f}")

    print("\nPairwise correlation of daily returns (1.0 = moves identically, 0 = unrelated, -1.0 = moves oppositely):")
    corr = compute_return_correlation({name: r.equity_curve for name, r in results.items()})
    print(corr.round(2).to_string())

    print("\n" + "=" * 100)
    weight_str = ", ".join(f"{name}={w:.0%}" for name, w in weights.items())
    print(f"COMBINED PORTFOLIO  |  weights: {weight_str}  |  shared capital: {args.capital:,.0f}")
    print("=" * 100)
    combined_curve = combine_equity_curves({name: r.equity_curve for name, r in results.items()}, weights)
    combined_trades = combine_trades({name: r.trades for name, r in results.items()}, weights)
    combined_metrics = compute_metrics(combined_curve, combined_trades, args.capital, periods_per_year)

    print(f"Final equity:         {combined_metrics['final_equity']:,.2f}")
    print(f"Total return:         {combined_metrics['total_return_pct']:.2f}%")
    print(f"CAGR:                 {combined_metrics['cagr_pct']:.2f}%")
    print(f"Sharpe ratio:         {combined_metrics['sharpe_ratio']:.2f}")
    print(f"Max drawdown:         {combined_metrics['max_drawdown_pct']:.2f}%")
    print(f"Total trades:         {combined_metrics['num_trades']} (weighted-scaled across strategies)")
    print(f"Gross P&L (no fees):  {combined_metrics['gross_pnl']:,.2f}")
    print(f"Total fees paid:      {combined_metrics['total_fees_paid']:,.2f}")
    print(f"Net P&L:              {combined_metrics['net_pnl']:,.2f}")
    print("=" * 100)


if __name__ == "__main__":
    main()
