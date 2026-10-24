# Nifty 50 Event Study — Pre-Event Drift & Information Leakage

A Python research pipeline that tests whether Nifty 50 stocks move **before** material corporate news is public. Such moves would point to informed or insider trading. It takes timestamped filings from BSE and NSE, and aligns each one to the first session that could react (the 15:30 IST rule). It then checks the days and minutes before the news for:

- abnormal returns and volume;
- futures and options positioning;
- large deals;
- (optionally) earlier press coverage.

Events are compared against their own baselines and against random non-event days (placebo).

**New here?** Start with [docs/STUDY.md](docs/STUDY.md): the question, the method, the data sources and the findings so far, in plain language.

## Features

- **Universe:** a single stock or all of today's Nifty 50 (`--universe nifty50`), with every event pooled into one test. BSE scrip codes are resolved automatically by ISIN.
- **Filings:** BSE announcements are classified by a keyword filter that drops routine compliance filings. Each filing's public time is the earlier of its BSE and NSE broadcasts, to the second.
- **Directional tests:** the pre-window [t-5, t-1] Nifty-adjusted CAR is signed by the news direction and tested four ways: t-test, BMP standardised test, sign test, and a placebo bootstrap. Results are split into scheduled news (results, dividends, board outcomes) and unscheduled news, where leakage evidence matters most.
- **Signals:**
  - `fno`: futures and option OI build-up (call vs put, adjusted for monthly expiries), option volume, and short-dated out-of-the-money volume on the side that would profit from the news (NSE bhavcopy, free).
  - `deals`: bulk/block deals in the 30 sessions before (NSE).
  - `insider`: SEBI PIT insider trades (promoters, directors, designated persons) in the 30 sessions before, by trade date, net value signed by the news direction (BSE system-driven disclosures).
  - `intraday`: for filings released during market hours, the abnormal return and volume in the hour before the filing minute (Upstox 1-minute candles).
  - `media` (opt-in, experimental): whether matching press coverage, or a broker rating or target change, appeared on a day before the filing (Google News RSS).
- **Public-catalyst controls:**
  - a sector-adjusted re-test of the price drift, using each stock's NSE sector index;
  - flags for a big market day or a big sector day in the pre-window;
  - the broker and press flags above.

  The "Unsched, no public catalyst" group keeps only unscheduled news with none of these: the cleanest leakage test.
- **Report:** a self-contained HTML report. It contains verdicts for unscheduled news, the average signed CAR path, drift by event type, the test tables, the strongest individual price moves, and a ranked list of directional option-flow **leads**. Per-event, placebo, test and lead CSVs are written alongside it.
- **Drill-down** (`drilldown.py`): for each lead it shows:
  - the day-by-day option flow;
  - the actual contracts bought, with their Day-0 premium change (did the buyers profit?);
  - **when** they were bought, minute by minute (Upstox expired-option data);
  - reported insider trades before the event;
  - SEBI enforcement orders mentioning the company;
  - the filings around the event and earlier press coverage.

## Prerequisites

- Python 3.12. It was developed on 3.12.3.
- Internet access to:
  - `api.upstox.com` and `assets.upstox.com`;
  - `api.bseindia.com`;
  - `www.nseindia.com` and `nsearchives.nseindia.com`;
  - `news.google.com` (only for `media`);
  - `www.sebi.gov.in` (only for the drill-down).
- An Upstox access token for the `intraday` signal. Daily candles work without one. The Upstox Plus plan is needed for `--oi-source upstox` and for the drill-down's 1-minute option data.

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
| `UPSTOX_ACCESS_TOKEN` | For `intraday`, `--oi-source upstox` and the drill-down's option minutes | Sent as a Bearer token on Upstox requests. Tokens expire daily (about 3:30 AM IST). Regenerate after a plan upgrade. |
| `UPSTOX_API_KEY` / `UPSTOX_API_SECRET` | No | Used in the OAuth login flow to obtain a token; not used by any request |

Study parameters (windows, baselines, placebo size, signal settings) are constants in [config.py](config.py).

## Running

```bash
.venv/Scripts/python main.py                                  # RELIANCE, 12 months, per-event table
.venv/Scripts/python main.py --symbol TMPV                    # Tata Motors (exercises the price-break skip)
.venv/Scripts/python main.py --universe nifty50               # all Nifty 50, pooled tests + report
.venv/Scripts/python main.py --universe TCS,INFY,HCLTECH      # any list of NSE symbols
.venv/Scripts/python main.py --universe nifty50 --months 26 --signals fno,deals,intraday,insider,media  # full study (Aug 2024 on)
.venv/Scripts/python drilldown.py                            # drill into the top 8 option-flow leads
.venv/Scripts/python drilldown.py --symbol ONGC --day0 2026-01-06   # any single event
```

| Flag | Default | Meaning |
|---|---|---|
| `--symbol` | `RELIANCE` | Single-stock run (prints the per-event table) |
| `--universe` | – | `nifty50` or comma-separated NSE symbols; pools all events |
| `--scrip` | ISIN lookup | BSE scrip override for a single-stock run |
| `--months` | `12` | Look-back period for announcements. The F&O data format starts in July 2024, so `26` is the longest useful value. |
| `--signals` | `fno,deals,intraday,insider` | Any of `fno`, `deals`, `intraday`, `insider`, `media`, or `none` |
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
| `drilldown_<date>.html`, `drilldown_contracts_<date>.csv` | `drilldown.py` output: for each lead, the day-by-day option flow, the contracts traded with their Day-0 premium change, filings and earlier press |
| `otm_leads_*.csv` | Unscheduled events with significant short-dated OTM option volume on the side that profits from the news, ranked; leads to investigate, not findings |
| `bse_filings_<SYMBOL>_<date>.csv` | Every fetched filing with its `event_type`, for auditing the filter |

### Reading the results

| Measure | Meaning |
|---|---|
| Signed pre CAR | Nifty-adjusted return over [t-5, t-1], multiplied by the sign of the news reaction. **> 0 means the stock moved the news' way before it was public.** |
| t-test / BMP / Sign / Placebo p | Four tests of the same hypothesis. Placebo p compares against random non-event days for the same stocks. |
| Vol z | Pre-window volume against the 30-session baseline |
| Option vol z | Stock-option volume before the event against its baseline |
| OTM news-side / wrong-side vol z | Short-dated out-of-the-money option volume on the side that profits from the news (calls before good news, puts before bad) vs the opposite side. News side > wrong side is the informed-trading footprint. |
| Option OI chg, Fut OI chg, Signed call-put OI tilt | Open-interest build-up from t-6 to t-1, ignoring the drop when a monthly series expires |
| Signed call vol skew z | Call share of option volume, signed by the news direction |
| *(positioning p-values)* | All against placebo days, not against zero |
| Intraday pre-AR z / pre-vol z | The hour before in-session filings, against the same clock window on the prior 20 sessions |
| Insider trade share / Insider net, news-signed | Share of events with a reported insider trade in the 30 sessions before, and insiders' net buying signed by the news direction (> 0 = insiders traded the right way) |
| Sector-adj signed pre CAR | The same price-drift test against the stock's sector index, so sector news doesn't count as leakage |
| Unsched, no public catalyst row | Unscheduled news with no big market or sector day in the pre-window, no exchange query about a media report, and (with `media`) no earlier press or broker call |
| Placebo days row | The null: signed pre-CAR should be about 0 and Right way about 50% |
| Verdict tiles (report) | Unscheduled news only. Scheduled results are pre-announced, so positioning before them is expected. |

The single-stock run also prints the original per-event table: Day 0, session, Pre/Post CAR, Vol z, D0 AR, outcome, the leakage flag (`|CAR z|` or `Vol z` ≥ 1.96) and the overlap marker.

## Limitations

- **Leads are not findings.** On the first 8 leads, every trade that profited had a public explanation (a broker upgrade, macro news, a same-day media report).
- **Insider trades are as reported.** BSE's PIT feed is used because NSE's is incomplete. ESOP-related buys count as buys.
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
media_client.py    Google News RSS search (press and broker actions, optional)
sebi_client.py     SEBI enforcement-order search (drill-down)
event_study.py     Day-0 alignment, metrics, signals, placebo, leakage tests (pure)
report.py          HTML report and drill-down page (pure rendering)
drilldown.py       per-event drill-down CLI for option-flow leads
main.py            CLI orchestrator, terminal tables, CSV + report export
data/              instrument master + API caches (generated, git-ignored)
output/            per-run CSVs and HTML reports (generated, git-ignored)
docs/              STUDY.md (plain-language overview), ARCHITECTURE.md (design)
```

## Further documentation

- [docs/STUDY.md](docs/STUDY.md): what the study is trying to find, how it works, the data sources, and the findings so far.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): data flow, methodology, a file-by-file reference and known limitations.
- [CLAUDE.md](CLAUDE.md): working notes for AI-assisted development in this repo.
