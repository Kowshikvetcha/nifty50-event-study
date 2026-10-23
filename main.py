"""Pre-event drift & information leakage study for Nifty 50 equities.

Usage:
    python main.py                               # Reliance, last 12 months
    python main.py --symbol TMPV --scrip 500570  # Tata Motors
    python main.py --months 24 --oi              # longer window + FUTSTK OI (needs token)
"""
import argparse
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

import config
from event_study import build_events, run_event_study, summarise
from news_scraper import BSEScraper
from nse_client import NSEClient, NSEError
from upstox_client import UpstoxClient, UpstoxError

OUTPUT_DIR = config.BASE_DIR / "output"


def pct(x, nd=2):
    return "" if pd.isna(x) else f"{x * 100:+.{nd}f}%"


def num(x, nd=2):
    return "" if pd.isna(x) else f"{x:+.{nd}f}"


def format_table(res: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Day 0": res["day0"].dt.strftime("%Y-%m-%d"),
        "Filed (IST)": res["timestamp"].dt.strftime("%m-%d %H:%M:%S"),
        "Session": res["session"],
        "Type": res["event_type"],
        "Headline": res["headline"].str.slice(0, 38),
        "Pre Ret": res["pre_ret"].map(pct),
        "Pre CAR": res["pre_car"].map(pct),
        "CAR z": res["pre_car_z"].map(num),
        "Vol x": res["vol_ratio"].map(lambda v: f"{v:.2f}x"),
        "Vol z": res["vol_z"].map(num),
        "D0 AR": res["day0_ar"].map(pct),
        "Post CAR": res["post_car"].map(pct),
        "Outcome": res["outcome"],
        "Leak?": np.where(res["leakage_flag"], "YES", ""),
        "Ovl": np.where(res["overlap"], "*", ""),
    })


def print_summary(s: dict) -> None:
    def line(label, key):
        print(f"  {label:<28}{pct(s[key + '_mean']):>9}   |mean| {pct(s[key + '_abs_mean']):>8}"
              f"   t={num(s[key + '_t'])}  p={'' if pd.isna(s[key + '_p']) else f'{s[key + '_p']:.3f}'}")

    print("\nCross-sectional summary")
    print(f"  Events analysed             {s['n_events']}")
    line("Pre-event CAR [t-5,t-1]", "pre_car")
    line("Day-0 abnormal return", "day0_ar")
    line("Post-event CAR [t+1,t+5]", "post_car")
    print(f"  Mean pre-event volume z     {num(s['vol_z_mean'])}   t={num(s['vol_z_t'])}"
          f"  p={'' if pd.isna(s['vol_z_p']) else f'{s['vol_z_p']:.3f}'}")
    print(f"  Events flagged for leakage  {s['leakage_share']:.0%}  (|CAR z| or Vol z >= {config.SIGNIFICANCE_Z})")
    print(f"  Pre-drift sign == Day-0 sign {s['pre_day0_same_sign']:.0%}  (50% = no predictive drift)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="RELIANCE", help="NSE trading symbol")
    ap.add_argument("--scrip", type=int, default=None, help="BSE scrip code (defaults from config)")
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--oi", action="store_true", help="also pull stock-futures open interest")
    ap.add_argument("--oi-source", choices=["nse", "upstox"], default="nse",
                    help="nse = F&O bhavcopy (free); upstox = expired contracts (needs Plus plan)")
    args = ap.parse_args()

    symbol = args.symbol.upper()
    scrip = args.scrip or config.SAMPLE_STOCKS.get(symbol)
    if scrip is None:
        ap.error(f"No BSE scrip code known for {symbol}; pass --scrip")

    today = date.today()
    news_from = today - timedelta(days=round(args.months * 30.44))
    price_from = news_from - timedelta(days=config.LOOKBACK_BUFFER_DAYS)

    upstox = UpstoxClient()
    print(f"Pre-Event Drift & Information Leakage | {symbol} (BSE {scrip}) | {news_from} -> {today}")
    print(f"Upstox auth: {'token' if upstox.has_token else 'none (public historical endpoint)'}")

    key = upstox.get_instrument_key(symbol)
    stock = upstox.get_daily_candles(key, price_from, today)
    market = upstox.get_daily_candles(config.MARKET_INDEX_KEY, price_from, today)
    print(f"Prices: {key}  {len(stock)} sessions  ({stock.index[0]:%Y-%m-%d} .. {stock.index[-1]:%Y-%m-%d})")

    scraper = BSEScraper()
    filings = scraper.fetch_announcements(scrip, news_from, today)
    filings["event_type"] = filings.apply(scraper.classify, axis=1)
    material = filings[filings["event_type"].notna()]
    print(f"BSE filings: {len(filings)} total, {len(material)} material after compliance filter")

    events = build_events(material, stock.index)
    results = run_event_study(events, stock, market)
    if results.empty:
        print("No events with enough price history to measure.")
        return 1

    if args.oi:
        try:
            if args.oi_source == "nse":
                oi = NSEClient().get_futures_oi(symbol, stock.index[stock.index >= pd.Timestamp(price_from)])
            else:
                oi = upstox.get_expired_futures_oi(key, price_from, today)
            oi_chg = oi["oi"].pct_change(5)
            results["oi_chg_pre"] = [
                oi_chg.shift(1).get(d, np.nan) for d in results["day0"]]  # OI change over t-5..t-1
            print(f"FUTSTK OI ({args.oi_source}): {len(oi)} sessions")
        except (UpstoxError, NSEError) as e:
            print(f"FUTSTK OI skipped: {e}")

    table = format_table(results)
    if "oi_chg_pre" in results:
        table.insert(10, "OI chg", results["oi_chg_pre"].map(pct))

    with pd.option_context("display.max_rows", None, "display.max_columns", None, "display.width", 250):
        print()
        print(table.to_string(index=False))
    print("\nPre/Post CAR = Nifty-50-adjusted cumulative abnormal return; Pre Ret = raw return t-5..t-1;"
          "\nVol x = mean volume t-5..t-1 / 30-day baseline; z-scores vs 30-day baseline [t-35,t-6];"
          "\n* = another event's Day 0 falls inside [t-5, t+5] (overlapping windows).")
    print_summary(summarise(results))
    clean = results[~results["overlap"]]
    if len(clean) >= 3 and len(clean) < len(results):
        print("\nNon-overlapping events only")
        print_summary(summarise(clean))

    OUTPUT_DIR.mkdir(exist_ok=True)
    out = OUTPUT_DIR / f"event_study_{symbol}_{today:%Y%m%d}.csv"
    results.to_csv(out, index=False)
    filings.to_csv(OUTPUT_DIR / f"bse_filings_{symbol}_{today:%Y%m%d}.csv", index=False)
    print(f"\nSaved: {out.relative_to(config.BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
