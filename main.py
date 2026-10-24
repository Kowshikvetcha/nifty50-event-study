"""Pre-event drift & information leakage study for Nifty 50 equities.

Usage:
    python main.py                               # Reliance, last 12 months, per-event table
    python main.py --symbol TMPV --scrip 500570  # Tata Motors
    python main.py --months 24 --oi              # longer window + futures OI (NSE bhavcopy)
    python main.py --universe nifty50            # all Nifty 50 stocks, pooled tests + placebo
"""
import argparse
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

import config
import report
from event_study import (broker_action, build_events, earliest_exchange_time, generic_words, leakage_tests,
                         media_lead, placebo_events, rank_directional_otm, run_event_study, summarise)
from media_client import MediaClient, MediaError, company_query
from news_scraper import BSEScraper
from nse_client import NSEClient, NSEError
from upstox_client import UpstoxClient, UpstoxError

OUTPUT_DIR = config.BASE_DIR / "output"
SIGNALS = ("fno", "deals", "intraday", "insider", "media")  # optional per-event signal families
# media (press and broker-action searches) is opt-in: Google News returns different result sets for the
# same query between runs.
DEFAULT_SIGNALS = ("fno", "deals", "intraday", "insider")


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


def tests_table(results: pd.DataFrame, placebo: pd.DataFrame) -> pd.DataFrame:
    """Directional leakage tests per group; the placebo row is the empirical null."""
    clean = results[~results["overlap"]]
    groups = {
        "All events": results,
        "Non-overlapping": clean,
        "Unscheduled (non-ovl)": clean[~clean["scheduled"]],
        "Scheduled (non-ovl)": clean[clean["scheduled"]],
    }
    # The cleanest test: unscheduled news with no public catalyst we can see in the pre-window (no big market
    # or sector day, no exchange query about a media report, and with `media` no earlier press or broker call).
    unsched = clean[~clean["scheduled"]]
    # Merged events keep one label, so a same-day clarification can hide behind another type: check both.
    clarif = unsched["event_type"].str.contains("Media Clarification") | \
        unsched["headline"].str.contains("clarification sought", case=False)
    quiet = ~unsched["macro_shock"].astype(bool) & ~clarif
    if "sector_shock" in unsched:  # missing = no sector index for the stock, not a shock
        quiet &= ~unsched["sector_shock"].fillna(False).astype(bool)
    for col in ("media_prior", "broker_prior"):  # missing = search failed, so the event can't count as quiet
        if col in unsched:
            quiet &= unsched[col].astype(str) == "False"
    groups["Unsched, no public catalyst"] = unsched[quiet]
    if "media_prior" in clean:
        # Leakage through the press vs no public trace before the filing (the stronger insider signal).
        unsched = clean[~clean["scheduled"]]
        groups["Unsched, media first"] = unsched[unsched["media_prior"] == True]  # noqa: E712 (object dtype)
        groups["Unsched, no prior media"] = unsched[unsched["media_prior"] == False]  # noqa: E712
    rng = np.random.default_rng(config.PLACEBO_SEED)
    rows = {g: leakage_tests(df, placebo, rng) for g, df in groups.items() if len(df)}
    if len(placebo):
        rows["Placebo days"] = leakage_tests(placebo)
    return pd.DataFrame(rows).T


def print_tests(t: pd.DataFrame) -> None:
    def p(x):
        return "" if pd.isna(x) else f"{x:.3f}"

    def share(x):
        return "" if pd.isna(x) else f"{x:.0%}"

    view = pd.DataFrame({
        "N": t["n"].astype(int),
        "Signed pre CAR": t["signed_pre_car"].map(pct),
        "t-test p": t["signed_p"].map(p),
        "BMP p": t["bmp_p"].map(p),
        "Right way": t["share_right_way"].map(share),
        "Sign p": t["sign_p"].map(p),
        "Placebo p": t["placebo_p"].map(p),
        "Run-up med": t["runup_median"].map(share),
        "Vol z": t["vol_z"].map(num),
        "Vol p": t["vol_p"].map(p),
        "|D0 AR|": t["day0_abs_ar"].map(pct),
    })
    print("\nLeakage hypothesis tests (pre-window [t-5,t-1], signed by the news direction)")
    print(view.to_string())
    print("Signed pre CAR > 0 = prices moved the news' way before it was public. p-values are two-sided except"
          "\nPlacebo p (one-sided, vs random non-event days). Run-up = share of the [t-5,t0] move before Day 0.")

    extra = [c for c in config.EXTRA_SIGNAL_COLUMNS if c in t]
    if extra:
        cols = {}
        for c in extra:
            fmt = pct if c.endswith("_chg_pre") or c == "signed_oi_tilt" else share if c == "deal_any" else num
            cols[config.EXTRA_SIGNAL_COLUMNS[c]] = t[c].map(fmt)
            cols[config.EXTRA_SIGNAL_COLUMNS[c] + " p"] = t[c + "_p"].map(p)
        print("\nPositioning signals before Day 0 (mean per event; Welch p vs placebo days, placebo row vs 0)")
        print(pd.DataFrame({"N": t["n"].astype(int), **cols}).to_string())


def resolve_universe(args, upstox: UpstoxClient, nse: NSEClient) -> list[tuple[str, str, int]]:
    """(symbol, NSE instrument_key, BSE scrip) for every stock in the run."""
    if args.universe and args.universe.lower() == "nifty50":
        stocks = [(r.symbol, "NSE_EQ|" + r.isin) for r in nse.get_nifty50().itertuples()]
    else:
        symbols = [s.strip() for s in (args.universe or args.symbol).upper().split(",")]
        stocks = [(s, upstox.get_instrument_key(s)) for s in symbols]
    out = []
    for sym, key in stocks:
        scrip = (args.scrip if len(stocks) == 1 else None) or config.SAMPLE_STOCKS.get(sym)
        try:
            out.append((sym, key, scrip or upstox.get_bse_scrip(key)))
        except UpstoxError as e:
            print(f"  {sym}: skipped ({e})")
    return out


def study_stock(sym: str, key: str, scrip: int, args, upstox: UpstoxClient, nse: NSEClient,
                media: MediaClient, market: pd.DataFrame, sector_key: str | None,
                news_from: date, price_from: date, today: date, rng: np.random.Generator,
                verbose: bool) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Events, placebo days and raw filings for one stock."""
    stock = upstox.get_daily_candles(key, price_from, today)
    scraper = BSEScraper()
    filings = scraper.fetch_announcements(scrip, news_from, today)
    filings["event_type"] = filings.apply(scraper.classify, axis=1) if len(filings) else None
    material = filings[filings["event_type"].notna()]
    if verbose:
        print(f"Prices: {key}  {len(stock)} sessions  ({stock.index[0]:%Y-%m-%d} .. {stock.index[-1]:%Y-%m-%d})")
        print(f"BSE filings: {len(filings)} total, {len(material)} material after compliance filter")
    try:  # public time = whichever exchange broadcast first
        material = earliest_exchange_time(material, nse.get_announcements(sym, news_from, today))
        if verbose:
            print(f"NSE filings: {(material['public_source'] == 'NSE').sum()} material filings were on NSE first")
    except (NSEError, requests.RequestException) as e:
        print(f"  {sym}: NSE announcements skipped: {e}")

    fo = None
    if "fno" in args.signals:
        try:
            if args.oi_source == "nse":
                fo = nse.get_fo_activity(sym, stock.index)
            else:  # near-month futures only, in the same long format as the NSE rows
                fut = upstox.get_expired_futures_oi(key, price_from, today).reset_index()
                fo = pd.DataFrame({"date": fut["date"], "kind": "FUT", "expiry": pd.to_datetime(fut["expiry"]),
                                   "otm": False, "front": True, "vol": fut["volume"], "oi": fut["oi"]})
            if verbose:
                print(f"F&O ({args.oi_source}): {fo['date'].nunique()} sessions")
        except (UpstoxError, NSEError) as e:
            print(f"  {sym}: F&O skipped: {e}")
    sector = None
    if sector_key:
        try:
            sector = upstox.get_daily_candles(sector_key, price_from, today)
            if verbose:
                print(f"Sector benchmark: {sector_key}")
        except UpstoxError as e:
            print(f"  {sym}: sector index skipped: {e}")
    insider = None
    if "insider" in args.signals:
        try:
            insider = scraper.get_insider_trades(scrip, price_from, today)
            if verbose:
                print(f"Insider trades (SEBI PIT via BSE): {len(insider)}")
        except (RuntimeError, requests.RequestException) as e:
            print(f"  {sym}: insider trades skipped: {e}")
    deals = None
    if "deals" in args.signals:
        try:
            deals = nse.get_large_deals(sym, price_from, today)
            if verbose:
                print(f"Bulk/block deals: {len(deals)} rows")
        except (NSEError, requests.RequestException) as e:
            print(f"  {sym}: deals skipped: {e}")

    events = build_events(material, stock.index)
    pl_events = placebo_events(stock.index, list(events["day0"]) if len(events) else [],
                               config.PLACEBO_PER_STOCK, rng)
    pl_events = pl_events[pl_events["day0"] >= pd.Timestamp(news_from)]  # same calendar span as the events

    intraday = None
    if "intraday" in args.signals:
        in_session = events[events["timestamp"].dt.normalize() == events["day0"]] if len(events) else events
        days = [d for d0 in [*in_session.get("day0", []), *pl_events["day0"]]
                for d in (d0, d0 - pd.Timedelta(days=35))]  # event day + its baseline sessions
        try:
            intraday = (upstox.get_intraday(key, days), upstox.get_intraday(config.MARKET_INDEX_KEY, days))
            if verbose:
                print(f"Intraday: {len(intraday[0])} one-minute bars for {len(in_session)} in-session events")
        except UpstoxError as e:
            print(f"  {sym}: intraday skipped: {e}")

    signals = {"fo": fo, "deals": deals, "intraday": intraday, "insider": insider, "sector": sector}
    results = run_event_study(events, stock, market, verbose=verbose, **signals)
    placebo = run_event_study(pl_events, stock, market, verbose=False, **signals)

    if "media" in args.signals and len(results):
        # Unscheduled news only: a scheduled date is public anyway, and each query costs a request.
        company = company_query(filings["company"].iloc[0]) if len(filings) else sym
        searched = {}
        for ev in results[~results["scheduled"]].itertuples():
            day = ev.timestamp.date()
            try:
                searched[ev.Index] = media.search(company, day - timedelta(days=config.MEDIA_LOOKBACK_DAYS), day)
            except (MediaError, requests.RequestException) as e:
                print(f"  {sym}: media search stopped: {e}")
                break
        # Second pass: words common across all of this company's coverage are not evidence of a match.
        generic = generic_words(pd.concat([a["title"] for a in searched.values()])) if searched else set()
        found = [media_lead(searched[i], company, ev.headline, ev.timestamp, generic) if i in searched else {}
                 for i, ev in zip(results.index, results.itertuples())]
        broker = {}
        for ev in results[~results["scheduled"]].itertuples():
            day = ev.timestamp.date()
            try:
                broker[ev.Index] = broker_action(
                    media.search_broker(company, day - timedelta(days=config.MEDIA_LOOKBACK_DAYS), day), ev.timestamp,
                    (sym, company.split()[0]))
            except (MediaError, requests.RequestException) as e:
                print(f"  {sym}: broker search stopped: {e}")
                break
        media_cols = pd.DataFrame(found, index=results.index,
                                  columns=["media_prior_n", "media_lead_days", "media_prior"])
        broker_cols = pd.DataFrame([broker.get(i, {}) for i in results.index], index=results.index,
                                   columns=["broker_prior", "broker_prior_n"])
        results = pd.concat([results, media_cols, broker_cols], axis=1)
        if verbose:
            print(f"Media: {int(results['media_prior'].fillna(False).sum())} unscheduled events "
                  f"had matching coverage on an earlier day, {int(results['broker_prior'].fillna(False).sum())} "
                  f"a broker rating or target change")

    for df in (results, placebo):
        if len(df):
            df.insert(0, "symbol", sym)
    return results, placebo, filings


def _concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="RELIANCE", help="NSE trading symbol (single-stock run)")
    ap.add_argument("--universe", default=None,
                    help="'nifty50' or comma-separated NSE symbols; pools all events into one test")
    ap.add_argument("--scrip", type=int, default=None, help="BSE scrip code (default: ISIN lookup)")
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--signals", default=",".join(DEFAULT_SIGNALS),
                    help=f"comma-separated subset of {','.join(SIGNALS)}, or 'none' (price/volume only)")
    ap.add_argument("--oi", action="store_true", help="shorthand for adding the fno signal")
    ap.add_argument("--oi-source", choices=["nse", "upstox"], default="nse",
                    help="futures OI source: nse = F&O bhavcopy (also options); upstox = expired futures (Plus plan)")
    args = ap.parse_args()
    args.signals = {s.strip() for s in args.signals.lower().split(",")} - {"none", ""}
    if args.oi:
        args.signals.add("fno")
    if unknown := args.signals - set(SIGNALS):
        ap.error(f"unknown signals: {', '.join(sorted(unknown))}")

    today = date.today()
    news_from = today - timedelta(days=round(args.months * 30.44))
    price_from = news_from - timedelta(days=config.LOOKBACK_BUFFER_DAYS)

    upstox = UpstoxClient()
    nse, media = NSEClient(), MediaClient()
    stocks = resolve_universe(args, upstox, nse)
    if not stocks:
        print("No stocks to study.")
        return 1
    single = len(stocks) == 1
    label = f"{stocks[0][0]} (BSE {stocks[0][2]})" if single else f"{len(stocks)} stocks"
    print(f"Pre-Event Drift & Information Leakage | {label} | {news_from} -> {today}")
    print(f"Upstox auth: {'token' if upstox.has_token else 'none (public historical endpoint)'}")
    market = upstox.get_daily_candles(config.MARKET_INDEX_KEY, price_from, today)
    try:  # industry per symbol picks each stock's sector benchmark
        industry = dict(zip(*nse.get_nifty50()[["symbol", "industry"]].T.values))
    except (NSEError, requests.RequestException):
        industry = {}

    rng = np.random.default_rng(config.PLACEBO_SEED)
    all_res, all_placebo, all_filings = [], [], {}
    for n, (sym, key, scrip) in enumerate(stocks, 1):
        try:
            res, pl, filings = study_stock(sym, key, scrip, args, upstox, nse, media, market,
                                           config.SECTOR_INDEX_OVERRIDES.get(sym)
                                           or config.SECTOR_INDEX.get(industry.get(sym)),
                                           news_from, price_from, today, rng, verbose=single)
        except (RuntimeError, requests.RequestException) as e:
            print(f"[{n}/{len(stocks)}] {sym:<12} FAILED: {e}")
            continue
        all_filings[sym] = filings
        all_res.append(res)
        all_placebo.append(pl)
        if not single:
            print(f"[{n}/{len(stocks)}] {sym:<12} filings {len(filings):>4}  events {len(res):>3}  "
                  f"placebo {len(pl):>3}")

    results, placebo = _concat(all_res), _concat(all_placebo)
    if results.empty:
        print("No events with enough price history to measure.")
        return 1

    if single:
        table = format_table(results)
        if "fut_oi_chg_pre" in results:
            table.insert(10, "OI chg", results["fut_oi_chg_pre"].map(pct))
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

    tests = tests_table(results, placebo)
    with pd.option_context("display.width", 250, "display.max_columns", None):
        print_tests(tests)

    OUTPUT_DIR.mkdir(exist_ok=True)
    stem = stocks[0][0] if single else "panel"
    out = OUTPUT_DIR / (f"event_study_{stem}_{today:%Y%m%d}.csv" if single else f"panel_events_{today:%Y%m%d}.csv")
    results.to_csv(out, index=False)
    placebo.to_csv(OUTPUT_DIR / f"placebo_{stem}_{today:%Y%m%d}.csv", index=False)
    tests.to_csv(OUTPUT_DIR / f"tests_{stem}_{today:%Y%m%d}.csv", index_label="group")
    for sym, filings in all_filings.items():
        filings.to_csv(OUTPUT_DIR / f"bse_filings_{sym}_{today:%Y%m%d}.csv", index=False)
    page = OUTPUT_DIR / f"report_{stem}_{today:%Y%m%d}.html"
    ranked = rank_directional_otm(results)
    if len(ranked):
        ranked.to_csv(OUTPUT_DIR / f"otm_leads_{stem}_{today:%Y%m%d}.csv", index=False)
    page.write_text(report.build(results, placebo, tests, {
        "label": label, "period": f"{news_from} to {today}", "signals": ", ".join(sorted(args.signals)) or "none",
    }, ranked), encoding="utf-8")
    print(f"\nSaved: {out.relative_to(config.BASE_DIR)} (+ placebo, tests and filing audit CSVs)")
    print(f"Report: {page.relative_to(config.BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
