# CLAUDE.md

Research pipeline testing whether Nifty 50 stocks move before material news is public (pre-event drift / information leakage). It uses BSE+NSE filings (timestamps), Upstox daily and 1-minute candles, NSE F&O bhavcopy and deals, with placebo days as the null. Full design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Plain-language goal, sources and findings: [docs/STUDY.md](docs/STUDY.md); update its findings section when results change materially.

## Commands

```bash
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python main.py                          # RELIANCE, 12 months, per-event table + report
.venv/Scripts/python main.py --symbol TMPV            # Tata Motors (exercises price-break skip)
.venv/Scripts/python main.py --universe nifty50       # pooled panel; cold cache = tens of minutes
.venv/Scripts/python main.py --signals none           # price/volume only, fastest
.venv/Scripts/python drilldown.py                     # per-event drill-down of the latest option-flow leads
```

- Windows dev box: always use `.venv/Scripts/python`, and prefix with `PYTHONIOENCODING=utf-8` when running from bash.
- There is no test suite. Verify changes as described in ARCHITECTURE.md → "Verifying changes".

## Layout

Flat modules, with `config.py` imported by everything:
`upstox_client.py` (daily + 1-min prices) · `news_scraper.py` (BSE filings + classifier) · `nse_client.py` (Nifty 50 list, NSE filings, F&O bhavcopy, deals) · `media_client.py` (Google News) · `event_study.py` (pure computation + tests) · `report.py` (HTML rendering) · `drilldown.py` (lead drill-down CLI) · `main.py` (CLI).

## Conventions

- Put every tunable (windows, thresholds, URLs, headers, sample stocks) in `config.py`, never inline in other modules.
- `event_study.py` and `report.py` stay free of I/O. Network access belongs in the client modules; each caches to `data/cache/` and raises its own `*Error`.
- A new per-event signal = a pure `measure_*` in `event_study.py`, an optional frame passed to `run_event_study` (so placebo days get it too), and an entry in `config.EXTRA_SIGNAL_COLUMNS`.
- Pre-window metrics that have a direction are signed by the news reaction (`add_direction_metrics`). Positioning signals are tested against placebo days, not against 0.
- Data flows as pandas DataFrames; prices are indexed by a naive `date`, and filing timestamps are naive IST `Timestamp`s.
- Style: type hints, short docstrings, sparse comments that explain *why*. Code is formatted at ~110 columns.
- Python 3.12 / pandas 3.x. Nested-quote f-strings (PEP 701) are already used in `main.py`.

## Gotchas

- **BSE blocks curl** (Akamai). Use `requests` with `config.BSE_HEADERS`. Don't "simplify" those headers away.
- **Upstox daily candles need no token**, but they are **not adjusted** for splits or demergers. The `PRICE_BREAK_THRESHOLD` guard in `measure_event` exists for this; don't remove it.
- **The 15:30 rule boundary is inclusive**: 15:30:00 is same-day, 15:30:01 is next session. Preserve this exactly if you touch `assign_day0`.
- **Filter changes** (`MATERIAL_RULES`, `ROUTINE_PATTERNS`, `ROUTINE_SUBCATEGORIES` in `news_scraper.py`) must be audited against `output/bse_filings_*.csv` for false positives and negatives. Rule order matters: the first match wins.
- **Baseline = [t-35, t-6]**, deliberately disjoint from the pre-window. Don't let it overlap.
- **NSE `/api` endpoints need homepage cookies first** (`NSEClient._api_get`). The deals endpoint truncates at 70 rows and 500s on ranges over a year; `get_large_deals` handles both.
- **Don't trust NSE PIT (`corporates-pit`)**: it returns zero rows for whole stocks (HDFCBANK, TCS). Insider trades are not wired up for this reason.
- **Google News is non-deterministic** for the same query, so `media` is opt-in and experimental. Its pubDates are date-only.
- **Upstox token**: needed for intraday (v3) and expired futures (also needs the Plus plan). Tokens expire daily; a token issued before a plan upgrade keeps the old entitlements.
- **F&O defaults to the NSE bhavcopy** (UDiFF format, from Jul-2024 only). `--oi-source upstox` gives near-month futures only, which collapse at each expiry.
- **SAST filings ("Substantial Acquisition of Shares") are routine**: shareholder stake and pledge reports, not company M&A. Keep them in `ROUTINE_SUBCATEGORIES` / `ROUTINE_PATTERNS`.
- **Check the placebo row** after any methodology change: signed pre-CAR should be about 0, and Right way about 50%.
- `data/`, `output/`, `.env` and `.venv/` are generated or secret and git-ignored. Never commit `.env`.
- Tata Motors trades as `TMPV` after the Oct-2025 demerger (BSE 500570 unchanged).
