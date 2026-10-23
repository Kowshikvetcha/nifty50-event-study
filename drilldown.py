"""Drill into directional option-flow leads: timeline, day-by-day flow, the contracts traded, press.

Usage:
    python drilldown.py                                  # top 8 from the latest output/otm_leads_*.csv
    python drilldown.py --top 3
    python drilldown.py --symbol ONGC --day0 2026-01-06  # any event in the latest results CSV
"""
import argparse
import sys
from datetime import timedelta

import pandas as pd
import requests

import config
import report
from event_study import keywords, option_flow_by_day, prepare_prices, top_contracts
from media_client import MediaClient, MediaError, company_query
from news_scraper import BSEScraper
from nse_client import NSEClient, NSEError
from upstox_client import UpstoxClient, UpstoxError

OUTPUT_DIR = config.BASE_DIR / "output"
PRESS_LOOKBACK_DAYS = 10
PRESS_OTHER_ROWS = 15


def _latest(pattern: str):
    files = sorted(OUTPUT_DIR.glob(pattern), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def load_leads(args) -> tuple[pd.DataFrame, str]:
    if args.symbol:
        src = _latest("panel_events_*.csv") or _latest(f"event_study_{args.symbol.upper()}_*.csv")
        if src is None:
            sys.exit("No results CSV in output/; run main.py first.")
        df = pd.read_csv(src, parse_dates=["day0", "timestamp"])
        df = df[(df["symbol"] == args.symbol.upper()) & (df["day0"] == pd.Timestamp(args.day0))]
        if df.empty:
            sys.exit(f"{args.symbol} {args.day0} is not an event in {src.name}")
    else:
        src = _latest("otm_leads_*.csv")
        if src is None:
            sys.exit("No otm_leads_*.csv in output/; run main.py --universe nifty50 first.")
        df = pd.read_csv(src, parse_dates=["day0", "timestamp"]).head(args.top)
    return df, src.name


def press_timeline(media: MediaClient, company: str, ev: pd.Series) -> pd.DataFrame:
    day = ev["timestamp"].date()
    arts = media.search(company, day - timedelta(days=PRESS_LOOKBACK_DAYS), day)
    keys = keywords(str(ev["headline"])) - keywords(company)
    arts = arts.assign(
        match=arts["title"].map(lambda t: len(keywords(t) & keys) >= config.MEDIA_MIN_KEYWORDS),
        before=arts["date"] < ev["timestamp"].normalize())
    # Story matches first, then only the most recent other items (company searches return a lot of noise).
    others = arts[~arts["match"]].sort_values("date", ascending=False).head(PRESS_OTHER_ROWS)
    return pd.concat([arts[arts["match"]].sort_values("date"), others])


def drill(ev: pd.Series, upstox: UpstoxClient, nse: NSEClient, media: MediaClient) -> dict:
    sym, day0 = ev["symbol"], ev["day0"]
    key = upstox.get_instrument_key(sym)
    span_from = (day0 - timedelta(days=config.LOOKBACK_BUFFER_DAYS)).date()
    span_to = (day0 + timedelta(days=14)).date()
    px = prepare_prices(upstox.get_daily_candles(key, span_from, span_to),
                        upstox.get_daily_candles(config.MARKET_INDEX_KEY, span_from, span_to))
    sessions = px.index
    i = sessions.get_loc(day0)
    window = sessions[max(i + config.PRE_WINDOW[0] - config.BASELINE_DAYS, 0):i + 3]

    lead = {"event": ev, "anchor": f"{sym}-{day0:%Y%m%d}", "days": pd.DataFrame(), "contracts": pd.DataFrame(),
            "filings": pd.DataFrame(), "press": pd.DataFrame()}
    try:
        strikes = nse.get_option_strikes(sym, window)
        lead["days"] = option_flow_by_day(strikes, px, day0, ev["direction"])
        lead["contracts"] = top_contracts(strikes, sessions, day0, ev["direction"])
    except NSEError as e:
        print(f"  {sym}: options skipped: {e}")

    scrip = config.SAMPLE_STOCKS.get(sym) or upstox.get_bse_scrip(key)
    scraper = BSEScraper()
    filings = scraper.fetch_announcements(scrip, (day0 - timedelta(days=PRESS_LOOKBACK_DAYS)).date(),
                                          (day0 + timedelta(days=1)).date())
    if len(filings):
        filings["event_type"] = filings.apply(scraper.classify, axis=1)
    lead["filings"] = filings
    company = company_query(filings["company"].iloc[0]) if len(filings) else sym
    try:
        lead["press"] = press_timeline(media, company, ev)
    except (MediaError, requests.RequestException) as e:
        lead["press_error"] = str(e)
    return lead


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", type=int, default=8, help="number of leads from the latest otm_leads CSV")
    ap.add_argument("--symbol", help="drill into one event instead (needs --day0)")
    ap.add_argument("--day0", help="Day 0 of that event, YYYY-MM-DD")
    args = ap.parse_args()
    if bool(args.symbol) != bool(args.day0):
        ap.error("--symbol and --day0 go together")

    events, source = load_leads(args)
    upstox, nse, media = UpstoxClient(), NSEClient(), MediaClient()
    leads = []
    for n, (_, ev) in enumerate(events.iterrows(), 1):
        print(f"[{n}/{len(events)}] {ev['symbol']} {ev['day0']:%Y-%m-%d}")
        try:
            leads.append(drill(ev, upstox, nse, media))
        except (UpstoxError, NSEError, RuntimeError, requests.RequestException) as e:
            print(f"  FAILED: {e}")
    if not leads:
        return 1

    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = pd.Timestamp.today().strftime("%Y%m%d")
    contracts = pd.concat([l["contracts"].assign(symbol=l["event"]["symbol"], day0=l["event"]["day0"])
                           for l in leads if len(l["contracts"])], ignore_index=True) \
        if any(len(l["contracts"]) for l in leads) else pd.DataFrame()
    if len(contracts):
        contracts.to_csv(OUTPUT_DIR / f"drilldown_contracts_{stamp}.csv", index=False)
    page = OUTPUT_DIR / f"drilldown_{stamp}.html"
    page.write_text(report.build_drilldown(leads, {"source": source}), encoding="utf-8")
    print(f"Drill-down: {page.relative_to(config.BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
