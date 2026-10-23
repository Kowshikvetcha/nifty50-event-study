# CLAUDE.md

Research pipeline testing pre-event drift / information leakage in Nifty 50 stocks. It uses BSE filings (timestamps) and Upstox v2 daily candles. Full design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Commands

```bash
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python main.py                               # RELIANCE, 12 months
.venv/Scripts/python main.py --symbol TMPV --scrip 500570  # Tata Motors (exercises price-break skip)
.venv/Scripts/python main.py --oi                          # needs UPSTOX_ACCESS_TOKEN
```

- Windows dev box: always use `.venv/Scripts/python`, and prefix with `PYTHONIOENCODING=utf-8` when running from bash.
- There is no test suite. Verify changes as described in ARCHITECTURE.md → "Verifying changes".

## Layout

Flat modules, with `config.py` imported by everything:
`upstox_client.py` (prices) · `nse_client.py` (futures OI from F&O bhavcopy) · `news_scraper.py` (filings + classifier) · `event_study.py` (pure computation) · `main.py` (CLI/report).

## Conventions

- Put every tunable (windows, thresholds, URLs, headers, sample stocks) in `config.py`, never inline in other modules.
- `event_study.py` stays free of I/O. Network access belongs in the two client modules.
- Data flows as pandas DataFrames; prices are indexed by a naive `date`, and filing timestamps are naive IST `Timestamp`s.
- Style: type hints, short docstrings, sparse comments that explain *why*. Code is formatted at ~110 columns.
- Python 3.12 / pandas 3.x. Nested-quote f-strings (PEP 701) are already used in `main.py`.

## Gotchas

- **BSE blocks curl** (Akamai). Use `requests` with `config.BSE_HEADERS`. Don't "simplify" those headers away.
- **Upstox daily candles need no token**, but they are **not adjusted** for splits or demergers. The `PRICE_BREAK_THRESHOLD` guard in `measure_event` exists for this; don't remove it.
- **The 15:30 rule boundary is inclusive**: 15:30:00 is same-day, 15:30:01 is next session. Preserve this exactly if you touch `assign_day0`.
- **Filter changes** (`MATERIAL_RULES`, `ROUTINE_PATTERNS`, `ROUTINE_SUBCATEGORIES` in `news_scraper.py`) must be audited against `output/bse_filings_*.csv` for false positives and negatives. Rule order matters: the first match wins.
- **Baseline = [t-35, t-6]**, deliberately disjoint from the pre-window. Don't let it overlap.
- **`--oi` defaults to NSE bhavcopy** (`nse_client.py`, free, UDiFF format from Jul-2024 only; total OI summed over expiries). `--oi-source upstox` needs an Upstox Plus plan (UDAPI1149) and is untested against the live API.
- `data/`, `output/`, `.env` and `.venv/` are generated or secret and git-ignored. Never commit `.env`.
- Tata Motors trades as `TMPV` after the Oct-2025 demerger (BSE 500570 unchanged).
