# Nifty 50 Event Study — Pre-Event Drift & Information Leakage

A Python research pipeline that tests whether Nifty 50 stocks move abnormally **before** material corporate announcements, which would suggest information is leaking. It pulls timestamped filings from the BSE Corporate Announcements API and daily price/volume from Upstox API v2. Each filing is aligned to the first trading session that could react to it (the 15:30 IST rule). For each event, the pipeline measures pre-event drift, abnormal volume and post-event drift.

## Features

- Maps NSE symbols to Upstox `instrument_key`s using the cached Upstox instrument master (`complete.csv.gz`).
- Fetches every page of BSE filings for a scrip and keeps the broadcast timestamp (`DT_TM`) to the second.
- Filters out routine compliance filings. It keeps results, dividends, board outcomes, M&A, order wins, restructuring/IPOs, strategic deals and exchange clarifications.
- Assigns Day 0 under the 15:30 IST market-close rule and merges filings that share the same Day 0 into one event.
- For each event, computes Nifty-50-adjusted CAR, the raw return, and the abnormal-volume ratio and z-score over [t-5, t-1] against a 30-day baseline, plus Day-0 AR and post-event drift over [t+1, t+5].
- Labels outcomes (Continuation / Reversal "sell-the-news" / Rebound / Flat), flags possible leakage, and runs cross-sectional t-tests. The tests are run on all events and again on events whose windows don't overlap.
- Optionally adds a pre-event stock-futures open-interest change from the NSE F&O bhavcopy (no token needed; Upstox expired contracts need a Plus plan).

## Prerequisites

- Python 3.12. It was developed on 3.12.3; the code uses 3.10+ type syntax and 3.12 f-string quoting.
- Internet access to `api.upstox.com`, `assets.upstox.com` and `api.bseindia.com`, plus `nsearchives.nseindia.com` for `--oi`.
- An Upstox access token is **optional** and is not needed for `--oi` (NSE bhavcopy). Only `--oi-source upstox` needs one, plus a Plus plan.

## Installation

```bash
cd nifty50-event-study
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # macOS/Linux
cp .env.example .env
```

## Configuration

Credentials are read from `.env` in the project root by `config.py`. `.env` is git-ignored; `.env.example` is the template.

| Variable | Required | Purpose |
|---|---|---|
| `UPSTOX_ACCESS_TOKEN` | No (only `--oi-source upstox`) | Sent as a Bearer token on Upstox requests |
| `UPSTOX_API_KEY` | No | Loaded for future OAuth use; not currently used by any request |
| `UPSTOX_API_SECRET` | No | Loaded for future OAuth use; not currently used by any request |

Study parameters (windows, baseline length, significance threshold, market-close cutoff, sample stocks) are constants in [config.py](config.py).

## Running

```bash
.venv/Scripts/python main.py                               # Reliance, last 12 months
.venv/Scripts/python main.py --symbol TMPV --scrip 500570  # Tata Motors
.venv/Scripts/python main.py --months 24 --oi              # 24 months + FUTSTK OI (NSE bhavcopy OI)
```

| Flag | Default | Meaning |
|---|---|---|
| `--symbol` | `RELIANCE` | NSE trading symbol |
| `--scrip` | from `config.SAMPLE_STOCKS` | BSE scrip code (required for symbols not in that map) |
| `--months` | `12` | Look-back period for announcements |
| `--oi` | off | Add a pre-event futures open-interest change column |
| `--oi-source` | `nse` | `nse` (free bhavcopy, Jul-2024 onward) or `upstox` (Plus plan) |

On Windows consoles, set `PYTHONIOENCODING=utf-8` if a headline contains characters the console code page can't print.

**Output**
- A formatted event table and a cross-sectional summary are printed to stdout.
- `output/event_study_<SYMBOL>_<YYYYMMDD>.csv` holds the per-event metrics.
- `output/bse_filings_<SYMBOL>_<YYYYMMDD>.csv` holds every fetched filing with its `event_type` (empty = filtered out). Use it to audit the filter.

### Reading the table

| Column | Meaning |
|---|---|
| Day 0 / Filed (IST) / Session | Reaction day, earliest filing timestamp, and how Day 0 was derived (Intraday, Post-close, Pre-open, Non-trading day) |
| Pre Ret | Raw stock return over [t-5, t-1] |
| Pre CAR / CAR z | Nifty-adjusted cumulative abnormal return over [t-5, t-1], and its z-score against baseline AR volatility |
| Vol x / Vol z | Mean volume over [t-5, t-1] ÷ baseline mean, and its z-score |
| D0 AR | Day-0 abnormal return (includes the announcement reaction) |
| Post CAR | Nifty-adjusted CAR over [t+1, t+5]; blank if fewer than 5 sessions have elapsed |
| Leak? | `YES` if \|CAR z\| ≥ 1.96 or Vol z ≥ 1.96 |
| OI chg | (only with `--oi`) Change in total stock-futures open interest from t-6 to t-1, from the NSE F&O bhavcopy |
| Ovl | `*` if another event's Day 0 falls within [t-5, t+5] |

## Testing

There is no automated test suite. Two manual checks were used during development: the 15:30 boundary cases in `event_study.assign_day0`, and auditing `output/bse_filings_*.csv`. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#verifying-changes).

## Project structure

```
config.py          credentials, endpoints, study constants
upstox_client.py   instrument master, daily candles, expired-futures OI
nse_client.py      stock-futures OI from NSE F&O bhavcopy (cached per day)
news_scraper.py    BSE announcements fetch + material-event classifier
event_study.py     Day-0 alignment, window metrics, outcome labels, t-tests
main.py            CLI orchestrator, table formatting, CSV export
data/              instrument master + candle cache (generated, git-ignored)
output/            per-run CSV results (generated, git-ignored)
docs/              architecture and methodology
```

## Further documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): data flow, methodology, a file-by-file reference and known limitations.
- [CLAUDE.md](CLAUDE.md): working notes for AI-assisted development in this repo.
