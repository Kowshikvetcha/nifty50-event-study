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

- We take every corporate announcement filed by each Nifty 50 company since August 2024 (26 months, back to the start of the current F&O data format), from **both BSE and NSE**.
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
| **Price drift** | Stock return minus the Nifty 50 return each day (the abnormal return), summed over the pre-window. It is then **signed by the direction of the news**: if the news turned out good, an upward drift counts as positive; if bad, a downward drift does. Without this, leaks before good and bad news would cancel out. A second version uses the stock's **sector index** instead of the Nifty, so sector news doesn't count. |
| **Share volume** | Pre-window average volume against the baseline (z-score) |
| **Option volume** | Total stock-option volume against its baseline |
| **Short-dated OTM options, by side** | Volume in the nearest-expiry options at least 2% out of the money. It is split into the **news side** (calls before good news, puts before bad) and the **wrong side**, which is the control. Informed traders favour these cheap, leveraged contracts. |
| **Open interest** | Change in futures and option OI over the pre-window, call vs put. The one-day drop when a monthly series expires is removed, because it's a calendar effect, not trading. |
| **The last hour** | For filings made *during* market hours, the abnormal return and volume in the 60 minutes before the filing minute, against the same clock time on the previous 20 sessions (1-minute data) |
| **Insider trades** | Trades reported by company insiders (promoters, directors, designated employees) under SEBI's insider-trading rules, dated in the 30 sessions before. We record whether there were any, and their net buying or selling signed by the news direction. |
| **Bulk/block deals** | Large disclosed trades in the 30 sessions before |

### Step 4: Rule out public catalysts

Most of what looks like leakage turns out to be public information that isn't a company filing. We flag four kinds:

- **A big market day** (Nifty moves 2% or more) in the pre-window.
- **A big sector day** (the stock's sector index moves 2% or more relative to the Nifty).
- **An exchange clarification:** the exchange asked the company about a media report, so the story was already in the press.
- **Broker calls and press** (optional): a rating change or target revision, or matching press coverage, on a day before the filing.

The group **"unscheduled news with no public catalyst"** keeps only events with none of these. It is the cleanest test of leakage.

### Step 5: Compare against random days (placebo)

A small positive number means nothing until you know what "normal" looks like. For every stock, we pick up to 20 **random non-event days** and measure them in exactly the same way. Every result is compared with these placebo days. On the placebo days the signed price drift averages about 0 and points the "right way" about 50% of the time, which is what a fair test should show.

We use several tests, because each has blind spots:

| Test | What it checks |
|---|---|
| t-test | Is the average signed drift above zero? |
| BMP test | The same, with each event scaled by its own volatility |
| Sign test | Does the drift point the right way more than 50% of the time? |
| Placebo bootstrap | How often would random days produce an average this large? |

Positioning signals (volume, options, OI, insider trades) are compared with the placebo days directly.

### Step 6: Screen individual events, then drill down

Pooled statistics say whether leakage happens *on average*. To find specific cases, we rank unscheduled events with **significant news-side OTM option buying that exceeds the wrong side**. These are **leads**. For each lead, the drill-down shows:

- the day-by-day flow;
- the contracts traded, how unusual they were, and whether their premium jumped on Day 0 (did the buyers profit?);
- **when** they were bought, minute by minute. Buying at the open after weekend news points to a public catalyst; buying in the last hour before the filing points to positioning.
- reported insider trades before the event;
- SEBI enforcement orders mentioning the company;
- the exchange filings around the event and the press coverage in the 10 days before.

A lead only becomes interesting when the buyers profited **and** no public explanation exists.

## 4. Data sources

| Source | What we take | Access | Notes |
|---|---|---|---|
| **BSE Corporate Announcements API** | Every filing with its broadcast timestamp to the second, category and subject | Free; needs browser-like request headers | The main event list. It returns nothing for ranges over a year, so requests are split by year. |
| **NSE Corporate Announcements** | NSE broadcast times for the same filings | Free; needs a session cookie from the NSE homepage | Used to take the earlier of the two exchange times. In testing they differed by 17 s to 8 min. |
| **BSE SEBI insider-trade disclosures** (`sddpit`) | Insider trades: person category, buy/sell, shares, value, trade dates | Free | Complete where NSE's equivalent feed returns nothing (e.g. about 1,500 HDFC Bank trades a year vs zero). Names are discarded. |
| **NSE Nifty 50 constituent list** | Current symbols, ISINs and industries | Free | Today's constituents only (see limitations) |
| **Upstox API** | Daily prices for stocks, the Nifty 50 and sector indices; 1-minute stock prices; the instrument master; 1-minute prices of expired option contracts | Daily prices free; 1-minute data needs a free token (expires daily); expired-contract data needs the paid Plus plan | Prices are not adjusted for splits or demergers; events near such breaks are skipped |
| **NSE F&O bhavcopy** | Daily volume, open interest, strike, expiry and underlying price for every stock future and option | Free daily files | Basis of all options and OI measures. Available in this format from July 2024. |
| **NSE bulk & block deals** | Large disclosed trades | Free | For Nifty 50 stocks, mostly institutional crossings |
| **Google News RSS** | Dated headlines: company coverage, and broker rating or target news | Free | Optional. Dates only, and results vary between runs. |
| **SEBI enforcement orders** (sebi.gov.in) | Order titles, dates and links | Free | Used in the drill-down. Title search is literal, so spelling variants can miss orders. |

## 5. Findings so far (26 months, 23 Aug 2024 – 24 Oct 2026)

**Sample:**
- 49 of the 50 Nifty stocks. BSE Ltd has no BSE listing for its own shares, so it is excluded.
- 1,840 material events, 705 of them non-overlapping: 379 unscheduled and 326 scheduled.
- 234 unscheduled events with no detectable public catalyst.
- 938 placebo days.

| Signal (vs random days) | Unscheduled news (379) | No public catalyst (234) | Scheduled news (326) |
|---|---|---|---|
| Price drift in the news' direction, t-5..t-1 | +0.18%, p 0.27 | 0.00%, p 0.99 | +0.07%, p 0.65 |
| Same, sector-adjusted | +0.14%, p 0.65 | +0.01%, p 0.71 | +0.02%, p 0.74 |
| Share volume | +0.05 z, p 0.20 | −0.03 z, p 0.46 | −0.01 z, p 0.82 |
| Option volume | +0.07 z, p 0.02 | −0.07 z, p 0.96 | +0.10 z, p 0.003 |
| Short-dated OTM options, news side | +0.06 z, p 0.02 | −0.10 z, p 0.66 | +0.22 z, p < 0.001 |
| Short-dated OTM options, wrong side | +0.02 z, p 0.15 | −0.12 z, p 0.18 | +0.13 z, p 0.001 |
| Option OI build-up | +19% vs +16%, p 0.33 | +13%, p 0.20 | +29%, p < 0.001 |
| Any insider trade in the 30 sessions before | 73% vs 74%, p 0.81 | 71%, p 0.43 | **61%, p < 0.001** |
| Insiders' net trading, signed by news | p 0.99 | p 0.48 | p 0.38 |
| **Volume in the hour before in-session filings** | **+0.64 z, p < 0.001** | **+0.40 z, p 0.04** | +0.45 z, p 0.002 |
| Price move in that hour | p 0.62 | p 0.31 | p 0.97 |

**What changed with more data.** The first 12-month run showed a marginal price drift before unscheduled news (+0.43%, placebo p 0.007). With twice the sample it disappears (+0.18%, p 0.27), and so does the elevated share volume. That earlier result was most likely noise.

**Interpretation:**

- **No evidence of systematic leakage in prices, share volume or insider trading.** Before unscheduled news, prices don't drift the news' way, and insiders trade about as often as on random days without favouring the profitable side.
- **The option activity before unscheduled news is explained by public catalysts.** It is visible across all unscheduled news, but disappears entirely in the no-catalyst group. Big market or sector days, media reports and broker calls account for it.
- **One robust anomaly: volume in the hour before filings made during market hours.** It survives the controls (no-catalyst group: +0.40 z, p 0.04). About 12% of these filings show a significant spike, against 5% of random hours. The price does not move the news' way in that hour, so it looks like *activity* without a *directional bet*: consistent with the story circulating (rumour, or the company preparing a release), not with traders positioning on the outcome. These events are the best candidates for case-by-case review.
- **Scheduled news behaves as expected for known dates:** option OI and volume build up openly. Insiders trade much less (61% vs 74% of random days), which is the mandatory trading-window closure before results. That is also a useful check that the insider data is correct.
- **No option-flow lead has held up.** Of the 10 leads, 8 carry a public catalyst (clarification, macro or sector day, broker call). The two without one (ONGC, Reliance) are explained on inspection. ONGC's call buying happened at the open after weekend Venezuela news, and those buyers lost money by Day 0. Reliance's option buyers lost money (−19%). No SEBI order concerns any lead event; every match is from earlier years.

**Bottom line:** in this sample, Nifty 50 stocks show no daily-horizon leakage that survives controls for public news. The remaining signal is a short-lived volume spike just before some in-session filings.

## 6. Limitations

- **Survivorship:** the universe is today's Nifty 50.
- **Event filter:** classification uses keywords. It is audited against the raw filings, but errors remain possible. One example fixed: shareholding (SAST) disclosures were being counted as M&A.
- **Catalyst detection is incomplete.** Broker and press checks rely on Google News, which gives dates only and varies between runs. A catalyst it misses can make a public-news event look "quiet".
- **Unadjusted prices:** events near splits and demergers are skipped rather than corrected.
- **Insider trades are as reported.** Late or missing disclosures, and trades through relatives or other accounts, are invisible. ESOP-related buys count as buys.
- **Multiple testing:** many signals and groups are tested, so about 1 in 20 p-values below 0.05 is expected by chance. The last-hour volume result (p < 0.001 for all unscheduled news) is well beyond that; the rest of the borderline results are not.
- **Large caps only:** most published run-ups are in smaller takeover targets.

## 7. Next steps

1. **Review the in-session volume spikes case by case.** List the in-session filings with a significant last-hour spike. Pull each one's minute-by-minute price, volume and option trades, and any press from the same morning.
2. **Better catalyst data:** a paid news feed with timestamps would replace Google News and make the "no public catalyst" group more reliable.
3. **Re-run the SEBI cross-check periodically** as orders covering 2024–26 are published.
4. **Widen the universe** to the Nifty Next 50 or midcaps, closer to where published run-ups are found.

## 8. References

- Keown, A. & Pinkerton, J. (1981). Merger Announcements and Insider Trading Activity. *Journal of Finance* 36(4). [IDEAS](https://ideas.repec.org/r/bla/jfinan/v36y1981i4p855-69.html)
- Meulbroek, L. (1992). An Empirical Analysis of Illegal Insider Trading. *Journal of Finance* 47(5). [IDEAS](https://ideas.repec.org/a/bla/jfinan/v47y1992i5p1661-99.html)
- Augustin, P., Brenner, M. & Subrahmanyam, M. Informed Options Trading prior to M&A Announcements: Insider Trading? [Working paper](https://weinberg.udel.edu/files/2022/08/Informed-Options-Trading_June-12-20141.pdf)
- Kacperczyk, M. & Pagnotta, E. (2019). Chasing Private Information. *Review of Financial Studies* 32(12). [Abstract](https://rmi.nus.edu.sg/events/nus-quantitative-finance-joint-seminar-series-webinar-14-may-2021)
- NSE Research Initiative, merger announcements and insider trading in India. [PDF](https://nsearchives.nseindia.com/content/research/Paper48.pdf)
- Share buybacks and insider trading in India (2025). [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S1544612325018483)
- SEBI WhatsApp results-leak case. [Business Standard](https://www.business-standard.com/amp/article/markets/sebi-asks-hdfc-bank-to-probe-whatsapp-earnings-leak-118022400028_1.html)

Most of the figures above were taken from abstracts and secondary citations. Check the original papers before quoting them.
