"""CLI: backtest a BTC short strangle against Delta Exchange India's real
historical daily-expiry option premium data.

Each day, sell an OTM call + OTM put (moneyness picked by --target-otm-pct,
since historical candles carry no Greeks) some hours before that day's
12:00 UTC settlement (--entry-hours-before-expiry). Each leg is bought back
early if its premium grows to --stop-loss-multiple x its entry premium;
the whole position closes early if combined premium decays to
(100 - --take-profit-pct)% of the entry credit; otherwise legs ride to
expiry and settle against the spot index.

Example:
    python -m option_backtest.main --start 2024-01-01 --end 2026-07-01 \
        --entry-hours-before-expiry 6 --target-otm-pct 5 --risk-pct-per-trade 1
"""
import argparse
from collections import Counter
from datetime import datetime, timezone

from sol_backtest.backtest.metrics import compute_metrics
from sol_backtest.data.fetcher import fetch_candles

from option_backtest.backtest.engine import StrangleBacktester
from option_backtest.config import base_url_for, settings
from option_backtest.data.products import fetch_option_products
from option_backtest.fees import OptionFeeModel
from option_backtest.reporting import save_cycles_csv
from option_backtest.strategy.short_strangle import build_cycles


def _to_unix(date_str: str) -> int:
    return int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--underlying", default=settings.underlying)
    p.add_argument("--start", required=True, help="YYYY-MM-DD (UTC)")
    p.add_argument("--end", required=True, help="YYYY-MM-DD (UTC)")
    p.add_argument("--env", default=settings.env, choices=["production", "testnet"])
    p.add_argument("--entry-hours-before-expiry", type=float, default=6.0,
                    help="Sell the strangle this many hours before the day's 12:00 UTC settlement.")
    p.add_argument("--target-otm-pct", type=float, default=5.0,
                    help="Pick the call/put strike nearest to spot * (1 +/- this%%) at entry time.")
    p.add_argument("--risk-pct-per-trade", type=float, default=1.0,
                    help="Size each cycle so both legs stopping out simultaneously (the conservative "
                         "worst case) loses this %% of equity.")
    p.add_argument("--stop-loss-multiple", type=float, default=3.0,
                    help="Buy back a leg once its premium grows to this many times its entry premium.")
    p.add_argument("--take-profit-pct", type=float, default=50.0,
                    help="Close all remaining open legs once combined premium has decayed to "
                         "(100 - this)%% of the entry credit.")
    p.add_argument("--max-notional-leverage", type=float, default=5.0,
                    help="Cap position size so both legs' combined underlying notional doesn't exceed "
                         "this multiple of equity (backstop - this backtest doesn't model Delta's real "
                         "options margin requirements).")
    p.add_argument("--capital", type=float, default=settings.initial_capital)
    p.add_argument("--leg-resolution", default=settings.leg_monitor_resolution,
                    help="Candle resolution used to watch each leg for a stop/target hit intraday.")
    p.add_argument("--spot-resolution", default=settings.spot_resolution,
                    help="Candle resolution used to look up the spot index at entry/settlement.")
    p.add_argument("--no-cache", action="store_true", help="Bypass the local candle/product cache")
    p.add_argument("--no-csv", action="store_true", help="Skip writing the per-cycle CSV to option_backtest/results/")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    start, end = _to_unix(args.start), _to_unix(args.end)
    base_url = base_url_for(args.env)
    use_cache = not args.no_cache

    print(f"Fetching {args.underlying} option product listing from {args.start} to {args.end} ({args.env})...")
    products_df = fetch_option_products(base_url, args.underlying, start, end, use_cache=use_cache)
    n_expiries = products_df["settlement_time"].nunique()
    print(f"Loaded {len(products_df)} option products across {n_expiries} expiry cycles.")

    spot_buffer = int(args.entry_hours_before_expiry * 3600) + 3 * 86400
    print(f"Fetching {settings.spot_index_symbol} [{args.spot_resolution}] spot index candles...")
    spot_df = fetch_candles(
        base_url=base_url, symbol=settings.spot_index_symbol, resolution=args.spot_resolution,
        start=start - spot_buffer, end=end, use_cache=use_cache,
    )
    print(f"Loaded {len(spot_df)} spot candles.")

    cycles = build_cycles(products_df, spot_df, args.entry_hours_before_expiry, args.target_otm_pct)
    print(f"Built {len(cycles)} strangle setups (of {n_expiries} expiries seen).")

    fee_model = OptionFeeModel(
        maker_fee_pct=settings.maker_fee_pct, taker_fee_pct=settings.taker_fee_pct, gst_pct=settings.gst_pct,
    )
    backtester = StrangleBacktester(
        fee_model=fee_model, initial_capital=args.capital,
        risk_pct_per_trade=args.risk_pct_per_trade, stop_loss_multiple=args.stop_loss_multiple,
        take_profit_pct=args.take_profit_pct, max_notional_leverage=args.max_notional_leverage,
    )

    print("Fetching per-leg option premium candles and simulating each cycle "
          "(this makes 2 API calls per expiry - the slow part)...")
    result = backtester.run(base_url, cycles, spot_df, args.leg_resolution, use_cache=use_cache)

    metrics = compute_metrics(result.equity_curve, result.trades, args.capital, periods_per_year=365.0)

    print("\n" + "=" * 60)
    print(f"Strategy: short_strangle  |  {args.underlying}  |  {args.start} -> {args.end}")
    print(f"Entry: {args.entry_hours_before_expiry}h before expiry, target {args.target_otm_pct}% OTM each leg")
    print(f"Stop-loss: {args.stop_loss_multiple}x entry premium/leg  |  Take-profit: {args.take_profit_pct}% "
          f"of entry credit")
    print(f"Fees assumed: {settings.taker_fee_pct}% of underlying notional (maker=taker for options) "
          f"+ {settings.gst_pct}% GST on the fee (source: live /v2/products taker/maker_commission_rate, "
          f"2026-07 - no premium-based fee cap is modeled, see config.py)")
    print(f"Position sizing: {args.risk_pct_per_trade}% equity risk per cycle "
          f"(capped at {args.max_notional_leverage}x equity notional)")
    print("=" * 60)
    print(f"Expiry cycles seen:    {n_expiries}")
    print(f"Cycles traded:         {len(result.cycles)}")
    print(f"Skipped (no data):     {result.skipped_no_data}")
    print(f"Skipped (risk < 1 lot):{result.skipped_risk_too_small}")
    print(f"Initial capital:      {metrics['initial_capital']:,.2f}")
    print(f"Final equity:         {metrics['final_equity']:,.2f}")
    print(f"Total return:         {metrics['total_return_pct']:.2f}%")
    print(f"CAGR:                 {metrics['cagr_pct']:.2f}%")
    print(f"Sharpe ratio:         {metrics['sharpe_ratio']:.2f}")
    print(f"Max drawdown:         {metrics['max_drawdown_pct']:.2f}%")
    print(f"Number of cycles:     {metrics['num_trades']}")
    print(f"Win rate:             {metrics['win_rate_pct']:.2f}%")
    print(f"Profit factor:        {metrics['profit_factor']:.2f}")
    if result.cycles:
        call_reasons = Counter(c.call_exit_reason for c in result.cycles)
        put_reasons = Counter(c.put_exit_reason for c in result.cycles)
        print(f"Call exit breakdown:  " + "  ".join(f"{k}={v}" for k, v in sorted(call_reasons.items())))
        print(f"Put exit breakdown:   " + "  ".join(f"{k}={v}" for k, v in sorted(put_reasons.items())))
    print("-" * 60)
    print(f"Gross P&L (no fees):  {metrics['gross_pnl']:,.2f}")
    print(f"Total fees paid:      {metrics['total_fees_paid']:,.2f}")
    print(f"Net P&L (after fees): {metrics['net_pnl']:,.2f}")
    print(f"Fees as % of gross P&L: {metrics['fees_as_pct_of_gross_pnl']:.2f}%")
    print("=" * 60)

    if not args.no_csv and result.cycles:
        filename = f"short_strangle_{args.underlying}_{args.start}_{args.end}.csv"
        path = save_cycles_csv(result.cycles, filename)
        print(f"\nPer-cycle log written to: {path}")


if __name__ == "__main__":
    main()
