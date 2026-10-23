# Nifty 50 Event Study — Pre-Event Drift & Information Leakage

A Python research pipeline that tests whether Nifty 50 stocks move **before** material corporate news is public. Such moves would point to informed or insider trading. It takes timestamped filings from BSE and NSE, and aligns each one to the first session that could react (the 15:30 IST rule). It then checks the days and minutes before the news for:

- abnormal returns and volume;
- futures and options positioning;
- large deals;
- (optionally) earlier press coverage.

Events are compared against their own baselines and against random non-event days (placebo).

## Features

- **Universe:** a single stock or all of today's Nifty 50 (`--universe nifty50`), with every event pooled into one test. BSE scrip codes are resolved automatically by ISIN.
- **Filings:** BSE announcements are classified by a keyword filter that drops routine compliance filings. Each filing's public time is the earlier of its BSE and NSE broadcasts, to the second.
- **Directional tests:** the pre-window [t-5, t-1] Nifty-adjusted CAR is signed by the news direction and tested four ways: t-test, BMP standardised test, sign test, and a placebo bootstrap. Results are split into scheduled news (results, dividends, board outcomes) and unscheduled news, where leakage evidence matters most.
- **Signals:**
  - `fno`: futures and option OI build-up (call vs put, adjusted for monthly expiries), option volume, and short-dated out-of-the-money volume on the side that would profit from the news (NSE bhavcopy, free).
  - `deals`: bulk/block deals in the 30 sessions before (NSE).
  - `intraday`: for filings released during market hours, the abnormal return and volume in the hour before the filing minute (Upstox 1-minute candles).
  - `media` (opt-in, experimental): whether matching press coverage appeared on a day before the filing (Google News RSS).
- **Report:** a self-contained HTML report with verdicts, the average signed CAR path, drift by event type, test tables and the strongest individual cases. Per-event, placebo and test CSVs are written alongside it.

## Prerequisites

- Python 3.12. It was developed on 3.12.3.
- Internet access to:
  - `api.upstox.com` and `assets.upstox.com`;
  - `api.bseindia.com`;
  - `www.nseindia.com` and `nsearchives.nseindia.com`;
  - `news.google.com` (only for `media`).
- An Upstox access token for the `intraday` signal. Daily candles work without one. `--oi-source upstox` also needs the Upstox Plus plan.

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
| `UPSTOX_ACCESS_TOKEN` | For `intraday` and `--oi-source upstox` | Sent as a Bearer token on Upstox requests. Tokens expire daily (about 3:30 AM IST). Regenerate after a plan upgrade. |
| `UPSTOX_API_KEY` / `UPSTOX_API_SECRET` | No | Used in the OAuth login flow to obtain a token; not used by any request |

Study parameters (windows, baselines, placebo size, signal settings) are constants in [config.py](config.py).

## Running

```bash
.venv/Scripts/python main.py                                  # RELIANCE, 12 months, per-event table
.venv/Scripts/python main.py --symbol TMPV                    # Tata Motors (exercises the price-break skip)
.venv/Scripts/python main.py --universe nifty50               # all Nifty 50, pooled tests + report
.venv/Scripts/python main.py --universe TCS,INFY,HCLTECH      # any list of NSE symbols
.venv/Scripts/python main.py --universe nifty50 --signals fno,deals,intraday,media
```

| Flag | Default | Meaning |
|---|---|---|
| `--symbol` | `RELIANCE` | Single-stock run (prints the per-event table) |
| `--universe` | – | `nifty50` or comma-separated NSE symbols; pools all events |
| `--scrip` | ISIN lookup | BSE scrip override for a single-stock run |
| `--months` | `12` | Look-back period for announcements |
| `--signals` | `fno,deals,intraday` | Any of `fno`, `deals`, `intraday`, `media`, or `none` |
| `--oi` | off | Shorthand for adding `fno` |
| `--oi-source` | `nse` | `nse` (bhavcopy, includes options) or `upstox` (expired near-month futures only) |

On Windows, prefix commands with `PYTHONIOENCODING=utf-8` when running from bash. The first Nifty 50 run downloads about 1,000 files and takes tens of minutes. Later runs read `data/cache/` and take about a minute.

**Output** (in `output/`, with the run date in each file name)

| File | Contents |
|---|---|
| `report_<SYMBOL\|panel>_<date>.html` | The report; open it in a browser |
| `event_study_<SYMBOL>_<date>.csv` (single-stock run) or `panel_events_<date>.csv` (pooled run) | One row per event with every metric |
| `placebo_*.csv` | The placebo days, measured the same way |
| `tests_*.csv` | The hypothesis-test table |
| `otm_leads_*.csv` | Unscheduled events with significant short-dated OTM option volume on the side that profits from the news, ranked; leads to investigate, not findings |
| `bse_filings_<SYMBOL>_<date>.csv` | Every fetched filing with its `event_type`, for auditing the filter |

### Reading the results

| Measure | Meaning |
|---|---|
| Signed pre CAR | Nifty-adjusted return over [t-5, t-1], multiplied by the sign of the news reaction. **> 0 means the stock moved the news' way before it was public.** |
| t-test / BMP / Sign / Placebo p | Four tests of the same hypothesis. Placebo p compares against random non-event days for the same stocks. |
| Vol z | Pre-window volume against the 30-session baseline |
| Option vol z, Fut OI chg, Signed call skew z | F&O positioning before the event; p-values are against placebo days |
| Intraday pre-AR z / pre-vol z | The hour before in-session filings, against the same clock window on the prior 20 sessions |
| Placebo days row | The null: signed pre-CAR should be about 0 and Right way about 50% |

The single-stock run also prints the original per-event table: Day 0, session, Pre/Post CAR, Vol z, D0 AR, outcome, the leakage flag (`|CAR z|` or `Vol z` ≥ 1.96) and the overlap marker.

## Limitations

- **No SEBI insider-trade (PIT) disclosures.** NSE's feed is incomplete, and the BSE endpoint isn't wired up yet.
- **Media timing is day-level and unstable.** Free news feeds give no minute timestamps, and Google results vary between runs.
- **Coverage and bias:**
  - Prices are unadjusted; events near splits or demergers are skipped.
  - The universe is today's Nifty 50 (survivorship bias).
  - The event filter is keyword-based.
  - Many tests are run, so about 1 in 20 p-values under 0.05 is expected by chance.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full methodology.

## Testing

There is no automated test suite. The checks used during development are listed under [docs/ARCHITECTURE.md → Verifying changes](docs/ARCHITECTURE.md#verifying-changes): the 15:30 boundary cases, the placebo sanity check, per-signal coverage lines, a visual check of the report, and the two sample stocks.

## Project structure

```
config.py          credentials, endpoints, study constants
upstox_client.py   instrument master, daily + 1-minute candles, expired-futures OI
news_scraper.py    BSE announcements fetch + material-event classifier
nse_client.py      Nifty 50 list, NSE announcements, F&O bhavcopy aggregates, bulk/block deals
media_client.py    Google News RSS search (optional media signal)
event_study.py     Day-0 alignment, metrics, signals, placebo, leakage tests (pure)
report.py          HTML report (pure rendering)
main.py            CLI orchestrator, terminal tables, CSV + report export
data/              instrument master + API caches (generated, git-ignored)
output/            per-run CSVs and HTML reports (generated, git-ignored)
docs/              architecture and methodology
```

## Further documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): data flow, methodology, a file-by-file reference and known limitations.
- [CLAUDE.md](CLAUDE.md): working notes for AI-assisted development in this repo.
