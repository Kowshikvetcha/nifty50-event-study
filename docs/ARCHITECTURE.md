# Architecture

## Overview

This is a flat, single-package Python script pipeline with no framework. Three data-access modules (`upstox_client.py`, `news_scraper.py`, `nse_client.py`) produce pandas DataFrames, and a pure-computation module (`event_study.py`) turns them into per-event metrics. `main.py` wires them together for one stock per run. `config.py` is the single source of constants and credentials; every other module imports it.

## How it fits together

```mermaid
flowchart LR
  ENV[.env] --> CFG[config.py]
  CFG --> UP[upstox_client.py]
  CFG --> BSE[news_scraper.py]
  CFG --> NSE[nse_client.py]
  CFG --> ES[event_study.py]
  UP -- instrument master / candles --> CACHE[(data/)]
  UP -- stock + Nifty 50 daily OHLCV --> MAIN[main.py]
  BSE -- filings + event_type --> MAIN
  NSE -- futures OI per session (optional, --oi) --> MAIN
  NSE -- bhavcopy STF rows --> CACHE
  MAIN -- material filings, trading calendar --> ES
  ES -- results DataFrame + summary --> MAIN
  MAIN --> OUT[(output/*.csv + stdout table)]
```

One run of `python main.py --symbol RELIANCE` works like this:

1. **Dates.** `main.main()` sets `news_from` to today minus N months. `price_from` is `news_from` minus `LOOKBACK_BUFFER_DAYS` (70 calendar days), so the earliest event still has its 35-session baseline.
2. **Prices.** `UpstoxClient.get_instrument_key("RELIANCE")` reads the cached `data/complete.csv.gz`, refreshing it if it's older than 24 h, and returns `NSE_EQ|INE002A01018`. `get_daily_candles()` is then called for the stock and for `NSE_INDEX|Nifty 50`. Ranges are split into 365-day chunks and cached in `data/cache/candles_<key>_<from>_<to>.csv`.
3. **Filings.** `BSEScraper.fetch_announcements()` pages `AnnSubCategoryGetData/w` until it has `Table1[0].ROWCNT` rows. `_normalise()` maps BSE fields to snake_case, parses `DT_TM` to the second and builds the attachment URL. `classify()` then gives each row an `event_type`, or `None` for routine filings.
4. **Events.** `event_study.build_events()` calls `assign_day0()` on every material filing. Filings with the same Day 0 are merged into one event; the earliest timestamp drives the session label and `short_title()` picks a readable headline.
5. **Metrics.** `run_event_study()` calls `prepare_prices()` to inner-join the stock with the Nifty and compute `ret`, `mkt_ret` and `ar`. It then calls `measure_event()` for each Day 0, and adds the `overlap`, `leakage_flag` and `outcome` columns.
6. **Open interest (optional, `--oi`).** `NSEClient.get_futures_oi()` fetches the daily F&O bhavcopy for every session in the price window (see [Open interest](#open-interest---oi)). `main` computes `oi_chg_pre` and merges it into the results before the report.
7. **Report.** `main.format_table()` and `print_summary(summarise(...))` print the results. The summary runs once for all events and once for events without overlap. Both CSVs are written to `output/`.

## Methodology

### Day-0 assignment (`assign_day0`)

All times are IST, as BSE publishes them.

| Filing time | Day 0 | Session label |
|---|---|---|
| > 15:30:00 | next trading day | Post-close |
| 09:15:00 – 15:30:00 (inclusive) | same day | Intraday |
| < 09:15:00 | same day | Pre-open |
| on a weekend/holiday | next trading day | Non-trading day |

The trading calendar is the stock's own candle index, so holidays come straight from the data with no separate holiday list. Filings after the last available candle are dropped.

### Windows (trading-day offsets from Day 0 at index *i*)

```
| baseline: 30 sessions |  pre [t-5, t-1]  | t0 |  post [t+1, t+5]  |
  i-35            i-6     i-5        i-1    i    i+1         i+5
```

The baseline ends before the pre-window starts, so the drift being tested never contaminates its own reference. All offsets come from `config.PRE_WINDOW`, `POST_WINDOW` and `BASELINE_DAYS`.

### Metrics (`measure_event`)

- `ar = r_stock − r_nifty50`. This is a market-adjusted model: 30 days is too short to estimate a market-model beta reliably.
- `pre_ret = Π(1 + r) − 1` over the pre-window (raw); `pre_car = Σ ar` over the pre-window.
- `pre_car_z = pre_car / (σ_baseline(ar) · √5)`.
- `vol_ratio = mean(V_pre) / mean(V_baseline)`; `vol_z = (mean(V_pre) − μ_V) / σ_V`; `vol_peak_z` = the largest single-day volume z in the pre-window.
- `day0_ar`, `day0_vol_ratio`, and `post_ret` / `post_car` / `post_car_z` (computed the same way over [t+1, t+5]).

### Open interest (`--oi`)

- **Source:** NSE's daily F&O bhavcopy in the UDiFF format (`nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_<YYYYMMDD>_F_0000.csv.zip`). No token is needed; a browser User-Agent and an NSE Referer are enough (`config.NSE_HEADERS`).
- **Series:** rows with `FinInstrmTp == "STF"` (stock futures) and `TckrSymb == <symbol>`. `oi` is `OpnIntrst` summed over all live expiries. Summing avoids the artificial OI drop when the near-month contract rolls.
- **Metric:** `oi_chg_pre = oi[t-1] / oi[t-6] − 1`, shown as the `OI chg` column. It is descriptive only and does not feed `leakage_flag`.
- **Sessions:** the requested dates are the stock's own trading calendar. A 404 (holiday, or today's file not published yet) is skipped, not cached and not fatal.
- **Coverage:** the UDiFF files start in July 2024. Earlier dates are skipped, so very long `--months` values will have missing OI.
- **Alternative:** `--oi-source upstox` uses the Upstox expired-futures endpoints, which need a Plus plan.

### Labels

- **leakage_flag:** `|pre_car_z| ≥ SIGNIFICANCE_Z` or `vol_z ≥ SIGNIFICANCE_Z` (1.96).
- **outcome** (`classify_outcome`):
  - Pending if the post-window isn't complete yet.
  - Flat if |post_car| < 0.5%.
  - Continuation if post_car has the same sign as pre_car.
  - Otherwise "Reversal (sell-news)" when pre_car > 0, or "Reversal (rebound)" when pre_car < 0.
- **overlap:** another event's Day 0 falls within [t-5, t+5] of this one.

### Aggregate tests (`summarise`)

- One-sample t-tests (scipy) of mean `pre_car`, `day0_ar`, `post_car` and `vol_z` against zero. Each needs at least 3 events.
- The share of events flagged for leakage.
- The share where sign(pre_car) equals sign(day0_ar). A value near 50% means the drift has no predictive power.

## Directories

| Path | Purpose |
|---|---|
| `/` | All source modules (flat layout, no package) |
| `data/` | `complete.csv.gz` instrument master (~2.6 MB, refreshed every 24 h). Created by `config.py` on import. |
| `data/cache/` | Daily candle CSVs keyed by instrument and exact date range, plus `nse_stf_<YYYYMMDD>.csv` (all stock-futures rows for one session, shared by every symbol). Deleting it forces a re-fetch. |
| `output/` | Per-run results and filing audit CSVs, created by `main.py` |
| `docs/` | This document |
| `.venv/` | Local virtual environment (git-ignored) |

## File reference

| File | Purpose |
|---|---|
| `config.py` | Loads `.env` and defines every endpoint URL (Upstox, NSE bhavcopy, BSE), `NSE_HEADERS`, the BSE browser headers, the market-session times (`MARKET_OPEN` 09:15, `MARKET_CLOSE` 15:30), the window constants, `PRICE_BREAK_THRESHOLD` and the `SAMPLE_STOCKS` NSE→BSE map. Creates `data/` and `data/cache/` on import. |
| `upstox_client.py` | `UpstoxClient`: a `_get()` wrapper that checks for `status == "success"` and backs off on 429s. Provides instrument-master caching and lookup (`get_instrument_key`), chunked and cached daily candles (`get_daily_candles`), and the expired-derivatives helpers `get_expired_expiries`, `get_expired_future_contracts` and `get_expired_futures_oi`. The last of these keeps the nearest-expiry contract for each day. Raises `UpstoxError`. |
| `news_scraper.py` | `BSEScraper`: paginated fetch, normalisation to snake_case columns, and `classify()`. The classifier has three parts: `ROUTINE_SUBCATEGORIES` and `ROUTINE_PATTERNS` (deny-lists), and `MATERIAL_RULES`, an ordered dict of label → (BSE subcategories, regex) where the first match wins. `material_events()` is a fetch-and-filter convenience wrapper (`main.py` calls the two steps separately so it can save the unfiltered audit file). |
| `event_study.py` | Pure functions with no I/O apart from the skip notices it prints: `assign_day0`, `short_title`, `build_events`, `prepare_prices`, `measure_event`, `classify_outcome`, `run_event_study` and `summarise`. |
| `nse_client.py` | `NSEClient.get_futures_oi`: downloads the daily UDiFF F&O bhavcopy zip, keeps `STF` rows (cached per day in `data/cache/nse_stf_*.csv`) and returns total OI summed across live expiries, which avoids roll artefacts. Archive starts Jul-2024; missing days (404) are skipped. |
| `main.py` | argparse CLI. Runs the steps described above, applies the optional OI merge (`oi_chg_pre` = 5-day OI % change ending at t-1), formats the table and writes the CSVs. |
| `requirements.txt` | Unpinned: requests, pandas, numpy, python-dotenv, scipy. Developed against pandas 3.1. |
| `.env.example` | Credential template; copy it to `.env`. |

## Key design decisions / gotchas

- **The BSE API sits behind Akamai.** Plain `curl` gets "Access Denied". Python `requests` with the `config.BSE_HEADERS` browser User-Agent, Referer and Origin gets through. If BSE starts returning HTML, look at the headers first; `fetch_announcements` raises when the Content-Type isn't JSON.
- **The Upstox v2 daily-candle endpoint is public.** No token is needed. The `Authorization` header is sent only when a token is configured. Candles arrive newest-first; `_candles_to_frame` sorts them ascending.
- **Prices are not adjusted for corporate actions.** Tata Motors shows a −40% "return" on 2025-10-14 (the demerger). `measure_event` returns `{"price_break": True}` when any daily |return| exceeds `PRICE_BREAK_THRESHOLD` (20%) anywhere in [t-35, t+5]. `run_event_study` then skips the event and prints a notice. Lower the threshold with care: a genuine 10–15% announcement-day move is legitimate data.
- **Tata Motors' symbol changed.** It is `TMPV` (Tata Motors Passenger Vehicles) after the Oct-2025 demerger. BSE scrip 500570 and ISIN INE155A01022 stayed the same.
- **The filter is a keyword heuristic, not an NLP classifier.** It was tuned against Reliance's 168 filings for 2025-10 → 2026-10. Known loose matches include media releases containing "partner" (e.g. TIME100). The many "This is further to the disclosure dated …" follow-ups are deliberately left unclassified. Always audit `output/bse_filings_*.csv` after changing the rules.
- **Results-day bundling.** Companies file results, a board outcome, a press release and an investor presentation within minutes of each other. These collapse into one event through the Day-0 groupby, with joined labels such as `Financial Results + Board Outcome`.
- **Overlap is common** for an active filer like Reliance (19 of 27 events in the sample run). Prefer the "Non-overlapping events only" summary when drawing conclusions.
- **NSE bhavcopy costs ~1 MB per session on a cold cache.** A 12-month run makes ~290 requests (0.3 s apart, `NSE_REQUEST_PAUSE_SEC`). Each day is cached after the first fetch, so reruns and other symbols are fast. Only `STF` rows are kept. If NSE starts returning non-zip content, check `NSE_HEADERS` first.
- **Cache keys contain exact dates.** Because `to_date` is today, each new day creates a new cache file and re-fetches; old cache files are never pruned.
- **`--oi-source upstox` is blocked by the Plus-plan requirement (UDAPI1149) and has never been run against the live API** because development had no token. Response shapes follow the Upstox v2 expired-instruments docs (expiries as a list of `YYYY-MM-DD` strings; contracts as dicts with `instrument_key`; candles with OI at index 6).

## Verifying changes

There is no test suite. After changing:

- **Day-0 logic:** check the boundaries. 15:30:00 should map to the same day, 15:30:01 to the next session, 09:14:59 to Pre-open on the same day, and a Saturday filing to Monday:
  ```bash
  .venv/Scripts/python -c "import pandas as pd; from event_study import assign_day0; td=pd.DatetimeIndex(['2026-10-15','2026-10-16','2026-10-19']); [print(s, assign_day0(pd.Timestamp(s), td)) for s in ['2026-10-15 15:30:00','2026-10-15 15:30:01','2026-10-15 09:14:59','2026-10-17 10:00:00']]"
  ```
- **Filter rules:** re-run `main.py` and diff the `event_type` column of `output/bse_filings_<SYMBOL>_*.csv`.
- **OI:** run `main.py --oi` and confirm `FUTSTK OI (nse): N sessions` with N close to the price session count, then spot-check one day: the `OpnIntrst` total for the symbol's `STF` rows in `data/cache/nse_stf_<date>.csv` should equal `oi` for that date.
- **Anything else:** run both sample stocks (`RELIANCE`; `TMPV --scrip 500570`). Tata Motors exercises the price-break skip.
