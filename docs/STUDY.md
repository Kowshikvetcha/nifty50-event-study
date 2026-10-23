# Does the market know before the news? A Nifty 50 information-leakage study

This document explains the study: what we are trying to find out, how we test it, which data sources we use, and what we have found so far. It is written for readers who know markets but not this codebase. For the code itself, see [ARCHITECTURE.md](ARCHITECTURE.md); for setup and commands, see the [README](../README.md).

## 1. The question

When a listed company has material news (an acquisition, a big order, a partnership, a regulatory problem), it must disclose it to the stock exchanges. In theory, nobody can trade on that news before the disclosure. In practice, the information passes through many hands first: executives, bankers, lawyers, auditors, counterparties and journalists.

**Hypothesis:** for Nifty 50 stocks, some of the market's reaction to material news happens *before* the news is public. If so, we should see unusual activity in the days and hours before the disclosure:

- the price drifting in the direction the news will later push it;
- trading volume above normal;
- futures and options positioning on the side that would profit;
- trading concentrated in the hour before a filing made during market hours.

**What this can and cannot show.** It is a statistical study of market data. It can show that markets behave as if *someone* knew before the disclosure. It cannot say who traded or whether anything illegal happened. Pre-disclosure moves can also have legitimate causes: good analysis, rumours, press reports, or news about the sector or the economy. Much of the design below exists to separate those causes from genuine leakage.

## 2. Prior research

The idea is well studied, mostly for US takeovers:

- **Keown & Pinkerton (1981):** target stocks earn abnormal returns before merger announcements. The "run-up ratio" used here is named after them.
- **Meulbroek (1992):** in 320 SEC insider-trading cases, almost half of the pre-takeover run-up happened on the days insiders traded.
- **Augustin, Brenner & Subrahmanyam (2014–2017):** about a quarter of US takeover targets show abnormal options volume beforehand, concentrated in short-dated out-of-the-money calls.
- **Kacperczyk & Pagnotta (2019):** in 3,586 documented illegal insider trades, volume and options reveal private information much more than stock prices do.
- **India:** NSE research found run-ups before mergers in the late 1990s, and a 2025 study found run-ups before share buybacks. SEBI's 2017–18 WhatsApp case showed that quarterly results of about a dozen large companies leaked before release.

What is new here is a current, Nifty 50-wide test with second-level filing timestamps, minute-level prices, options data and a placebo control.

## 3. How the study works

### Step 1: Find the news and its exact public time

- We take every corporate announcement filed by each Nifty 50 company over the last 12 months, from **both BSE and NSE**.
- A keyword classifier keeps **material** news (results, dividends, board outcomes, M&A, order wins, restructuring, strategic deals, exchange clarifications) and drops routine compliance filings (trading-window notices, analyst meets, shareholding disclosures and similar).
- The **public time** is the earlier of the BSE and NSE broadcast timestamps, to the second.
- **Day 0** is the first trading session that could react. A filing up to 15:30:00 IST counts for the same day; after that, the next session. Weekend and holiday filings move to the next session.
- Filings on the same Day 0 are merged into one event.

### Step 2: Separate scheduled from unscheduled news

- **Scheduled news** (results, dividends, board outcomes) has a date announced in advance. The market knows something is coming, so heavy positioning beforehand is normal and is not leakage.
- **Unscheduled news** (M&A, orders, deals, restructuring, clarifications) arrives without notice. Unusual activity before it is much harder to explain innocently. **The headline verdicts use unscheduled news only.**

We also drop events whose windows overlap another event of the same stock, so one event's reaction doesn't leak into another's "before" window.

### Step 3: Measure what happened before the news

For each event, we compare the **pre-window** (the 5 sessions before Day 0) with the stock's own **baseline** (30 sessions ending a week before). The two never overlap.

| What | How it's measured |
|---|---|
| **Price drift** | Stock return minus the Nifty 50 return each day (the abnormal return), summed over the pre-window. It is then **signed by the direction of the news**: if the news turned out good, an upward drift counts as positive; if bad, a downward drift does. Without this, leaks before good and bad news would cancel out. |
| **Share volume** | Pre-window average volume against the baseline (z-score) |
| **Option volume** | Total stock-option volume against its baseline |
| **Short-dated OTM options, by side** | Volume in the nearest-expiry options at least 2% out of the money. It is split into the **news side** (calls before good news, puts before bad) and the **wrong side**, which is the control. Informed traders favour these cheap, leveraged contracts. |
| **Open interest** | Change in futures and option OI over the pre-window, call vs put. The one-day drop when a monthly series expires is removed, because it's a calendar effect, not trading. |
| **The last hour** | For filings made *during* market hours, the abnormal return and volume in the 60 minutes before the filing minute, against the same clock time on the previous 20 sessions (1-minute data) |
| **Bulk/block deals** | Large disclosed trades in the 30 sessions before |

### Step 4: Compare against random days (placebo)

A small positive number means nothing until you know what "normal" looks like. For every stock, we pick up to 20 **random non-event days** and measure them in exactly the same way. Every result is compared with these placebo days. If the placebo days show the same pattern, the effect is an artefact. On the placebo days the signed price drift averages about 0 and points the "right way" about 50% of the time, which is what a fair test should show.

We use several tests, because each has blind spots:

| Test | What it checks |
|---|---|
| t-test | Is the average signed drift above zero? |
| BMP test | The same, with each event scaled by its own volatility, so a few volatile stocks can't dominate |
| Sign test | Does the drift point the right way more than 50% of the time? |
| Placebo bootstrap | How often would random days produce an average this large? |

Positioning signals (volume, options, OI) are compared with the placebo days directly, because they have non-zero baselines.

### Step 5: Screen individual events, then drill down

Pooled statistics say whether leakage happens *on average*. To find specific cases, we rank unscheduled events with **significant news-side OTM option buying that exceeds the wrong side**. These are **leads**. For each lead, the drill-down shows:

- the day-by-day flow;
- the actual contracts traded and how unusual they were for those contracts;
- whether their premium jumped on Day 0 (did the buyers profit?);
- the exchange filings around the event;
- the press coverage in the 10 days before.

A lead only becomes interesting when the buyers profited **and** no public explanation exists.

## 4. Data sources

| Source | What we take | Access | Notes |
|---|---|---|---|
| **BSE Corporate Announcements API** (`api.bseindia.com`) | Every filing with its broadcast timestamp to the second, category and subject | Free; needs browser-like request headers (the site blocks scripts that lack them) | The main event list |
| **NSE Corporate Announcements** (`nseindia.com/api`) | NSE broadcast times for the same filings | Free; needs a session cookie from the NSE homepage first | Used to take the earlier of the two exchange times. In testing they differed by 17 s to 8 min. |
| **NSE Nifty 50 constituent list** (`nsearchives.nseindia.com`) | Current symbols and ISINs | Free | Today's constituents only (see limitations) |
| **Upstox API v2/v3** | Daily prices for stocks and the Nifty 50 index; 1-minute prices; the instrument master (maps ISINs to BSE codes) | Daily prices are free with no login. 1-minute data needs a free account token, which expires daily. | Prices are not adjusted for splits or demergers. Events near such breaks are skipped automatically. |
| **NSE F&O bhavcopy** (`nsearchives.nseindia.com`) | Daily volume, open interest, strike, expiry and underlying price for every stock future and option contract | Free daily files | The basis of all options and OI measures. Available in this format from July 2024. |
| **NSE bulk & block deals** (`nseindia.com/api`) | Large disclosed trades with the client name and side | Free | For Nifty 50 stocks these are mostly institutional crossings, not insiders |
| **Google News RSS** | Dated headlines mentioning the company | Free | Used to check for press coverage before a filing. Dates only (no times), and results vary between runs, so it is an optional, experimental signal. |
| **Upstox expired-instruments API** | Historical near-month futures OI | Needs the paid Upstox Plus plan | An alternative futures OI source. NSE's data is preferred. |

**Not used yet:** SEBI insider-trading (PIT) disclosures, i.e. trades reported by company insiders themselves. NSE's feed returned no records all year for stocks like HDFC Bank and TCS, so a missing record can't be read as "no insider trades". BSE publishes the same data through an endpoint we have not yet wired up.

## 5. Findings so far (12 months to 23 Oct 2026)

**Sample:**
- 49 of the 50 Nifty stocks. BSE Ltd has no BSE listing for its own shares, so it is excluded.
- 908 material events, 345 of them non-overlapping: 187 unscheduled and 158 scheduled.
- 809 placebo days.

**Unscheduled news, compared with random days:**

| Signal | Before the news | p-value | Reading |
|---|---|---|---|
| Price drift in the news' direction (t-5 to t-1) | +0.43% | 0.07 (t-test), 0.007 (placebo) | Weak evidence; the tests disagree |
| Share volume | +0.12 z | 0.04 | Elevated |
| Option volume | +0.12 z | 0.01 | Elevated |
| Short-dated OTM options, news side | +0.15 z | 0.04 | Elevated |
| Short-dated OTM options, wrong side | +0.06 z | 0.06 | Not clearly elevated |
| Volume in the hour before in-session filings (57 events) | +0.93 z | 0.003 | Strongly elevated |
| Price move in that hour | — | 0.42 | No signal |
| Option OI build-up, call/put tilt, futures OI | — | > 0.15 | No signal |

**Scheduled news:** no price drift (−0.08%, p = 0.73). Option OI builds up strongly beforehand (+30% against +15% on random days, p < 0.001), even when matched on position in the monthly expiry cycle. Both call and put buying rise together, which fits traders positioning openly for a known results date, not leakage.

**Interpretation:**
- **The market is more active before unscheduled news than on random days:** volume, option volume, news-side option buying, and a sharp volume rise in the last hour before in-session filings. This matches the international finding that informed trading shows up in volume and options more than in prices.
- **Price drift before the news is small and only marginally significant.** It is not robust across all tests.
- **No individual case has held up as unexplained.** The top 8 option-flow leads were all checked:

  | Lead | Buyers profited? | Explanation |
  |---|---|---|
  | Maruti | Yes | A broker upgrade the day before |
  | ONGC | Yes | Venezuela news the same day |
  | Dr Reddy's | Yes | A media report on the filing day |
  | HDFC Bank, BEL, Kotak, Reliance, UltraTech | No | Their option buyers broke even or lost money |

The aggregate pattern is real but modest, and it is not yet traceable to specific leaks. A large part of it is likely **public information that isn't a company filing**: broker research, macro and sector news, and media reports that come out before the company confirms.

## 6. Limitations

- **Survivorship:** the universe is today's Nifty 50, not the index as it stood through the year.
- **Event filter:** classification uses keywords. It is audited against the raw filings, but errors remain possible. One fixed example: shareholding (SAST) disclosures were being counted as M&A.
- **Unadjusted prices:** events near splits and demergers are skipped rather than corrected.
- **Media timing:** free news sources give only dates, so we can't tell whether an article came out minutes before or after a filing on the same day.
- **No insider-trade records yet** (see section 4).
- **Multiple testing:** many signals and groups are tested, so about 1 in 20 p-values below 0.05 is expected by chance.
- **Large caps only:** most published run-ups are in takeover *targets*, which are typically smaller companies. Nifty 50 stocks are rarely targets themselves.

## 7. Next steps

1. **Add non-filing news as control events:** broker rating changes, plus large macro and sector news. This would separate public catalysts from genuine leaks, the main source of false leads so far.
2. **Wire in SEBI insider-trade disclosures** from BSE and check whether insiders traded before the events.
3. **Cross-check leads against SEBI enforcement orders** as they are published (typically one to three years after the trades).
4. **Extend the period back to July 2024**, when the current F&O data format starts, for more events and more statistical power.
5. **Use intraday option prices** (Upstox 1-minute data on expired contracts) to see the exact minutes when the news-side contracts were bought.

## 8. References

- Keown, A. & Pinkerton, J. (1981). Merger Announcements and Insider Trading Activity. *Journal of Finance* 36(4). [IDEAS](https://ideas.repec.org/r/bla/jfinan/v36y1981i4p855-69.html)
- Meulbroek, L. (1992). An Empirical Analysis of Illegal Insider Trading. *Journal of Finance* 47(5). [IDEAS](https://ideas.repec.org/a/bla/jfinan/v47y1992i5p1661-99.html)
- Augustin, P., Brenner, M. & Subrahmanyam, M. Informed Options Trading prior to M&A Announcements: Insider Trading? [Working paper](https://weinberg.udel.edu/files/2022/08/Informed-Options-Trading_June-12-20141.pdf)
- Kacperczyk, M. & Pagnotta, E. (2019). Chasing Private Information. *Review of Financial Studies* 32(12). [Abstract](https://rmi.nus.edu.sg/events/nus-quantitative-finance-joint-seminar-series-webinar-14-may-2021)
- NSE Research Initiative, merger announcements and insider trading in India. [PDF](https://nsearchives.nseindia.com/content/research/Paper48.pdf)
- Share buybacks and insider trading in India (2025). [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S1544612325018483)
- SEBI WhatsApp results-leak case. [Business Standard](https://www.business-standard.com/amp/article/markets/sebi-asks-hdfc-bank-to-probe-whatsapp-earnings-leak-118022400028_1.html)

Most of the figures above were taken from abstracts and secondary citations. Check the original papers before quoting them.
