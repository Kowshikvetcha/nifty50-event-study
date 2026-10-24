"""Event-study engine: Day-0 alignment (15:30 IST rule), pre-event drift, abnormal volume, post drift.

Window layout around Day 0 (index i in the trading calendar):

    |<----- baseline: 30 days ----->|<- pre [t-5,t-1] ->| t0 |<- post [t+1,t+5] ->|
     i-35                      i-6   i-5            i-1    i    i+1           i+5

Returns are market-adjusted against Nifty 50 (AR = r_stock - r_nifty) so a broad market
rally is not mistaken for leakage. Raw cumulative returns are reported alongside.
"""
import re

import numpy as np
import pandas as pd
from scipy import stats

import config


def assign_day0(ts: pd.Timestamp, trading_days: pd.DatetimeIndex) -> tuple[pd.Timestamp | None, str]:
    """Map an IST announcement timestamp to its Day 0 trading session.

    - after 15:30:00             -> next trading day (market could only react then)
    - 09:15:00 .. 15:30:00       -> same day; pre-event window ends at close of t-1
    - before 09:15:00 (pre-open) -> same day (first session that can react)
    - weekends / holidays        -> next trading day
    """
    day = ts.normalize()
    t = ts.time()
    if t > config.MARKET_CLOSE:
        session, pos = "Post-close", trading_days.searchsorted(day, side="right")
    else:
        session = "Intraday" if t >= config.MARKET_OPEN else "Pre-open"
        pos = trading_days.searchsorted(day, side="left")
    if pos >= len(trading_days):
        return None, session
    day0 = trading_days[pos]
    if day0 != day and session != "Post-close":
        session = "Non-trading day"
    return day0, session


_GENERIC_SUBJECT = re.compile(r"^(announcement under regulation 30|disclosure under regulation 30|"
                              r"media release|press release|statement)", re.IGNORECASE)


def short_title(subject: str, headline: str) -> str:
    """Prefer a quoted release title, then a specific subject, then the headline."""
    quoted = re.search(r'titled\s+"+([^"]+)', headline)
    if quoted:
        return quoted.group(1).strip().title()
    return headline if (not subject or _GENERIC_SUBJECT.match(subject)) else subject


def earliest_exchange_time(bse: pd.DataFrame, nse: pd.DataFrame) -> pd.DataFrame:
    """Move each BSE filing to the NSE broadcast time when NSE carried the same disclosure earlier.

    Companies file on both exchanges within minutes; the market can react to whichever lands first. The
    nearest NSE filing within EXCHANGE_MATCH_MINUTES is taken as the same disclosure (nearest, not
    earliest, because results days bundle several filings a few minutes apart).
    """
    out = bse.copy()
    out["public_source"] = "BSE"
    out["nse_lead_sec"] = np.nan
    if nse.empty or out.empty:
        return out
    tol = pd.Timedelta(minutes=config.EXCHANGE_MATCH_MINUTES)
    nse_ts = pd.DatetimeIndex(nse["timestamp"].sort_values())
    for idx, ts in out["timestamp"].items():
        near = nse_ts[(nse_ts >= ts - tol) & (nse_ts <= ts + tol)]
        if near.empty:
            continue
        match = near[np.abs((near - ts).total_seconds()).argmin()]
        lead = (ts - match).total_seconds()
        out.at[idx, "nse_lead_sec"] = lead
        if lead > 0:
            out.at[idx, "timestamp"] = match
            out.at[idx, "public_source"] = "NSE"
    return out


_STOPWORDS = set(
    "limited ltd company india indian shares share stock stocks disclosure regulation regulations sebi "
    "announcement update updates intimation under with from into that this their about after over news "
    "said says will report reports group business market markets price today year crore".split())


def keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in _STOPWORDS}


def generic_words(titles: pd.Series) -> set[str]:
    """Words in more than MEDIA_MAX_DOC_FREQ of a company's headlines (e.g. 'consumer', 'products' for
    Reliance's subsidiaries): they match unrelated stories, so they don't count towards a match."""
    if titles.empty:
        return set()
    df = pd.Series([w for t in titles.drop_duplicates() for w in keywords(t)]).value_counts()
    return set(df[df / titles.nunique() > config.MEDIA_MAX_DOC_FREQ].index)


def media_lead(articles: pd.DataFrame, company: str, headline: str, filing_ts: pd.Timestamp,
               generic: set[str] = frozenset()) -> dict:
    """Did press coverage of this story appear on a day before the filing?

    articles: date / source / title from a company-name search. A match must share MEDIA_MIN_KEYWORDS
    distinctive headline keywords (company-name and generic words excluded). Dates only: same-day coverage
    cannot be ordered against the filing.
    """
    keys = keywords(headline) - keywords(company) - generic
    if not keys or articles.empty:
        return {"media_prior_n": 0, "media_lead_days": 0, "media_prior": False}
    hits = articles[articles["title"].map(lambda t: len(keywords(t) & keys) >= config.MEDIA_MIN_KEYWORDS)]
    prior = hits[hits["date"] < filing_ts.normalize()]
    lead = (filing_ts.normalize() - prior["date"].min()).days if len(prior) else 0
    return {"media_prior_n": len(prior), "media_lead_days": lead, "media_prior": len(prior) > 0}


def broker_action(articles: pd.DataFrame, filing_ts: pd.Timestamp, names: tuple[str, ...]) -> dict:
    """Broker rating changes or target revisions in the press on a day before the filing (a public catalyst).

    The title must name the company (`names`: e.g. symbol and first word of the name), since broker-roundup
    searches return calls on other stocks too.
    """
    if articles.empty:
        return {"broker_prior": False, "broker_prior_n": 0}
    named = articles["title"].str.contains("|".join(rf"\b{re.escape(n)}\b" for n in names), case=False, regex=True)
    hit = articles[named & articles["title"].str.contains(config.BROKER_PATTERN, case=False, regex=True)
                   & (articles["date"] < filing_ts.normalize())]
    return {"broker_prior": len(hit) > 0, "broker_prior_n": len(hit)}


def build_events(announcements: pd.DataFrame, trading_days: pd.DatetimeIndex) -> pd.DataFrame:
    """Attach Day 0 to each filing and merge filings that share the same Day 0."""
    if announcements.empty:
        return pd.DataFrame()
    df = announcements.copy()
    mapped = df["timestamp"].apply(lambda ts: assign_day0(ts, trading_days))
    df["day0"] = mapped.str[0]
    df["session"] = mapped.str[1]
    df = df.dropna(subset=["day0"]).sort_values("timestamp")

    def merge(group: pd.DataFrame) -> pd.Series:
        first = group.iloc[0]
        return pd.Series({
            "timestamp": first["timestamp"],  # earliest broadcast drives the clock
            "public_source": first.get("public_source", "BSE"),
            "session": first["session"],
            "event_type": " + ".join(dict.fromkeys(group["event_type"])),
            "headline": short_title(first["subject"], first["headline"]),
            "n_filings": len(group),
        })

    return df.groupby("day0").apply(merge, include_groups=False).reset_index()


def prepare_prices(stock: pd.DataFrame, market: pd.DataFrame, sector: pd.DataFrame | None = None) -> pd.DataFrame:
    """Daily returns and abnormal returns vs Nifty 50; with a sector index also `sec_ar` = stock − sector."""
    px = pd.DataFrame({"close": stock["close"], "volume": stock["volume"]}).join(
        market["close"].rename("mkt_close"), how="inner")
    px["ret"] = px["close"].pct_change()
    px["mkt_ret"] = px["mkt_close"].pct_change()
    px["ar"] = px["ret"] - px["mkt_ret"]
    if sector is not None:
        px = px.join(sector["close"].rename("sec_close"), how="left")
        px["sec_ret"] = px["sec_close"].pct_change()
        px["sec_ar"] = px["ret"] - px["sec_ret"]
    return px


def _window(px: pd.DataFrame, i: int, lo: int, hi: int) -> pd.DataFrame | None:
    a, b = i + lo, i + hi
    if a < 1 or b >= len(px):  # row 0 has no return
        return None
    return px.iloc[a:b + 1]


def measure_event(px: pd.DataFrame, day0: pd.Timestamp) -> dict:
    i = px.index.get_loc(day0)
    pre_lo, pre_hi = config.PRE_WINDOW
    base = _window(px, i, pre_lo - config.BASELINE_DAYS, pre_lo - 1)
    pre = _window(px, i, pre_lo, pre_hi)
    post = _window(px, i, *config.POST_WINDOW)
    out = {}
    if base is None or pre is None:
        return out
    # Upstox daily candles are not adjusted for demergers/splits; a single-day move beyond
    # the threshold anywhere in the study span would swamp the baseline volatility.
    span = px["ret"].iloc[i + pre_lo - config.BASELINE_DAYS: i + config.POST_WINDOW[1] + 1]
    if (span.abs() > config.PRICE_BREAK_THRESHOLD).any():
        return {"price_break": True}

    ar_sd = base["ar"].std(ddof=1)
    vol_mu, vol_sd = base["volume"].mean(), base["volume"].std(ddof=1)
    n_pre = len(pre)

    out["pre_ret"] = (1 + pre["ret"]).prod() - 1
    out["pre_car"] = pre["ar"].sum()
    out["pre_car_z"] = out["pre_car"] / (ar_sd * np.sqrt(n_pre)) if ar_sd > 0 else np.nan
    out["vol_ratio"] = pre["volume"].mean() / vol_mu
    out["vol_z"] = (pre["volume"].mean() - vol_mu) / vol_sd if vol_sd > 0 else np.nan
    out["vol_peak_z"] = ((pre["volume"] - vol_mu) / vol_sd).max() if vol_sd > 0 else np.nan
    # Public catalysts that are not company filings: a big market day, or a big sector-only day, inside the
    # pre-window would move the stock without anyone knowing the company news.
    out["macro_shock"] = bool((pre["mkt_ret"].abs() >= config.MACRO_SHOCK_RET).any())
    if "sec_ar" in px and pre["sec_ret"].notna().all():
        out["sector_shock"] = bool(((pre["sec_ret"] - pre["mkt_ret"]).abs() >= config.SECTOR_SHOCK_RET).any())
        sec_sd = base["sec_ar"].std(ddof=1)
        out["sector_pre_car"] = pre["sec_ar"].sum()
        out["sector_pre_car_z"] = out["sector_pre_car"] / (sec_sd * np.sqrt(n_pre)) if sec_sd > 0 else np.nan

    out["day0_ar"] = px["ar"].iloc[i]
    out["day0_z"] = out["day0_ar"] / ar_sd if ar_sd > 0 else np.nan
    out["day0_vol_ratio"] = px["volume"].iloc[i] / vol_mu
    lo, hi = config.CAR_PATH_WINDOW  # daily ARs around Day 0, for the report's average CAR path
    for k in range(lo, hi + 1):
        out[f"ar_{k:+d}"] = px["ar"].iloc[i + k] if 1 <= i + k < len(px) else np.nan
    if post is not None:
        out["post_ret"] = (1 + post["ret"]).prod() - 1
        out["post_car"] = post["ar"].sum()
        out["post_car_z"] = out["post_car"] / (ar_sd * np.sqrt(len(post))) if ar_sd > 0 else np.nan
    return out


def fo_daily(long: pd.DataFrame) -> pd.DataFrame:
    """Per-session totals from long-format F&O rows: fut/ce/pe volume and OI, plus front-month OTM volume."""
    vol = long.pivot_table(index="date", columns="kind", values="vol", aggfunc="sum")
    oi = long.pivot_table(index="date", columns="kind", values="oi", aggfunc="sum")
    out = pd.concat([vol.add_suffix("_vol"), oi.add_suffix("_oi")], axis=1)
    out.columns = out.columns.str.lower()
    otm = long[long["otm"] & long["front"]].pivot_table(index="date", columns="kind", values="vol", aggfunc="sum")
    for side in ("CE", "PE"):
        out[f"otm_{side.lower()}_vol"] = otm[side] if side in otm else 0.0
    return out.fillna(0).sort_index()


def _oi_chg_ex_expiry(total: pd.Series, expiries: pd.DatetimeIndex, i0: int, i1: int) -> float:
    """Total-OI change from session i0 to i1, skipping the step in which an expired series drops out.

    Rollover moves OI from the front month into the next and leaves the total unchanged, but the unrolled
    remainder vanishes in the session after expiry (the bhavcopy still lists it on expiry day). Measuring only
    the contract set alive at the end does not work: it books the whole rollover inflow as new positions.
    """
    s = total.iloc[i0:i1 + 1]
    if len(s) < 2 or s.iloc[0] <= 0:
        return np.nan
    steps = s.diff().iloc[1:]
    prev = s.index[:-1]
    expired = [((expiries >= p) & (expiries < d)).any() for p, d in zip(prev, s.index[1:])]
    return steps[~np.array(expired)].sum() / s.iloc[0]


def _side_z(series: pd.Series, a: int, b: int, pre: slice) -> float:
    mu, sd = series.iloc[a:b + 1].mean(), series.iloc[a:b + 1].std(ddof=1)
    return (series.iloc[pre].mean() - mu) / sd if sd > 0 else np.nan


def measure_fno(long: pd.DataFrame, daily: pd.DataFrame, day0: pd.Timestamp) -> dict:
    """Pre-window F&O positioning vs the same [t-35, t-6] baseline as prices.

    long: rows (date, kind, expiry, otm, front, vol, oi); daily: fo_daily(long). OI changes run from t-6 to
    t-1 on contracts alive throughout. Option volume has a monthly expiry cycle; the 30-session baseline
    spans at least one full cycle. Upstox-sourced data has futures only, so only fut_oi_chg_pre is set.
    """
    if day0 not in daily.index:
        return {}
    i = daily.index.get_loc(day0)
    pre_lo, pre_hi = config.PRE_WINDOW
    a, b = i + pre_lo - config.BASELINE_DAYS, i + pre_lo - 1
    if a < 0:
        return {}
    i0, i1 = i + pre_lo - 1, i + pre_hi  # OI change from close of t-6 to close of t-1
    pre = slice(i + pre_lo, i + pre_hi + 1)
    expiries = pd.DatetimeIndex(long["expiry"].unique())
    out = {"fut_oi_chg_pre": _oi_chg_ex_expiry(daily["fut_oi"], expiries, i0, i1)}
    if "ce_vol" not in daily:
        return out
    fo = daily
    opt_vol = fo["ce_vol"] + fo["pe_vol"]
    mu, sd = opt_vol.iloc[a:b + 1].mean(), opt_vol.iloc[a:b + 1].std(ddof=1)
    out["opt_vol_ratio"] = opt_vol.iloc[i + pre_lo:i + pre_hi + 1].mean() / mu if mu > 0 else np.nan
    out["opt_vol_z"] = (opt_vol.iloc[i + pre_lo:i + pre_hi + 1].mean() - mu) / sd if sd > 0 else np.nan
    # Call share of option volume: informed buyers ahead of good news skew it towards calls.
    share = fo["ce_vol"] / opt_vol.where(opt_vol > 0)
    b_share, p_share = share.iloc[a:b + 1].dropna(), share.iloc[i + pre_lo:i + pre_hi + 1].dropna()
    if len(b_share) > 2 and len(p_share):
        out["call_skew"] = p_share.mean() - b_share.mean()
        se = b_share.std(ddof=1) / np.sqrt(len(p_share))
        out["call_skew_z"] = out["call_skew"] / se if se > 0 else np.nan
    out["opt_oi_chg_pre"] = _oi_chg_ex_expiry(fo["ce_oi"] + fo["pe_oi"], expiries, i0, i1)
    out["call_oi_chg_pre"] = _oi_chg_ex_expiry(fo["ce_oi"], expiries, i0, i1)
    out["put_oi_chg_pre"] = _oi_chg_ex_expiry(fo["pe_oi"], expiries, i0, i1)
    # Front-month OTM flow per side, each against its own baseline; signed into news/wrong side later.
    out["otm_ce_vol_z"] = _side_z(fo["otm_ce_vol"], a, b, pre)
    out["otm_pe_vol_z"] = _side_z(fo["otm_pe_vol"], a, b, pre)
    return out


def measure_deals(deals: pd.DataFrame, trading_days: pd.DatetimeIndex, day0: pd.Timestamp) -> dict:
    """Bulk/block deals in the DEALS_WINDOW sessions before Day 0 (large, disclosed trades by one party)."""
    i = trading_days.get_loc(day0)
    lo, hi = config.DEALS_WINDOW
    if i + lo < 0:
        return {}
    hit = deals[(deals["date"] >= trading_days[i + lo]) & (deals["date"] <= trading_days[i + hi])]
    # Buyer and seller of one trade are usually both listed, so count one side of the value.
    value = (hit["qty"] * hit["price"]).sum() / 2
    return {"deal_any": float(len(hit) > 0), "deal_count": len(hit), "deal_value_cr": value / 1e7}


def _clock_window(bars: pd.DataFrame, day: pd.Timestamp, start: pd.Timedelta, end: pd.Timedelta):
    """Bars of one session whose start minute falls in [day+start, day+end)."""
    return bars.loc[day + start: day + end - pd.Timedelta(minutes=1)]


def _window_ar(stock_w: pd.DataFrame, mkt_w: pd.DataFrame) -> float:
    if stock_w.empty or mkt_w.empty:
        return np.nan
    r_s = stock_w["close"].iloc[-1] / stock_w["open"].iloc[0] - 1
    r_m = mkt_w["close"].iloc[-1] / mkt_w["open"].iloc[0] - 1
    return r_s - r_m


def measure_intraday(bars: pd.DataFrame, mkt_bars: pd.DataFrame, ts: pd.Timestamp) -> dict:
    """Abnormal return and volume in the minutes just before an in-session filing.

    Pre window = [ts - INTRADAY_PRE_MINUTES, ts), clipped to the 09:15 open; only bars that finished
    before the filing minute are used. Baseline = the same clock window on the prior INTRADAY_BASELINE_DAYS
    sessions. intra_post_ar (filing minute -> close) gives the reaction used to sign the pre-move.
    """
    day, t = ts.normalize(), ts.floor("min")
    if not (config.MARKET_OPEN <= ts.time() <= config.MARKET_CLOSE):
        return {}
    open_td = pd.Timedelta(hours=config.MARKET_OPEN.hour, minutes=config.MARKET_OPEN.minute)
    close_td = pd.Timedelta(hours=config.MARKET_CLOSE.hour, minutes=config.MARKET_CLOSE.minute)
    end = t - day
    start = max(open_td, end - pd.Timedelta(minutes=config.INTRADAY_PRE_MINUTES))
    minutes = int((end - start).total_seconds() // 60)
    if minutes < config.INTRADAY_MIN_MINUTES:
        return {}
    sessions = bars.index.normalize().unique()
    prior = sessions[sessions < day][-config.INTRADAY_BASELINE_DAYS:]
    if day not in sessions or len(prior) < config.INTRADAY_BASELINE_DAYS // 2:
        return {}

    pre_s, pre_m = _clock_window(bars, day, start, end), _clock_window(mkt_bars, day, start, end)
    base_ar = np.array([_window_ar(_clock_window(bars, d, start, end), _clock_window(mkt_bars, d, start, end))
                        for d in prior])
    base_vol = np.array([_clock_window(bars, d, start, end)["volume"].sum() for d in prior])
    base_ar = base_ar[~np.isnan(base_ar)]
    ar, vol = _window_ar(pre_s, pre_m), pre_s["volume"].sum()
    ar_sd, vol_mu, vol_sd = base_ar.std(ddof=1), base_vol.mean(), base_vol.std(ddof=1)
    return {
        "intra_minutes": minutes,
        "intra_pre_ar": ar,
        "intra_pre_ar_z": (ar - base_ar.mean()) / ar_sd if ar_sd > 0 else np.nan,
        "intra_vol_ratio": vol / vol_mu if vol_mu > 0 else np.nan,
        "intra_vol_z": (vol - vol_mu) / vol_sd if vol_sd > 0 else np.nan,
        "intra_post_ar": _window_ar(_clock_window(bars, day, end, close_td), _clock_window(mkt_bars, day, end, close_td)),
    }


def measure_insider(pit: pd.DataFrame, trading_days: pd.DatetimeIndex, day0: pd.Timestamp) -> dict:
    """Reported insider (SEBI PIT) trades whose trade date falls in INSIDER_WINDOW sessions before Day 0.

    Disclosures are filed days after the trade (median ~6 in testing), so this uses the trade date, which
    is what matters for "did insiders trade before the news". Net value is signed by news direction later.
    """
    i = trading_days.get_loc(day0)
    lo, hi = config.INSIDER_WINDOW
    if i + lo < 0:
        return {}
    hit = pit[(pit["trade_from"] >= trading_days[i + lo]) & (pit["trade_from"] <= trading_days[i + hi])]
    buy = hit.loc[hit["kind"] == "buy", "value"].sum()
    sell = hit.loc[hit["kind"] == "sell", "value"].sum()
    return {"insider_any": float(len(hit) > 0), "insider_trades": len(hit), "insider_net_cr": (buy - sell) / 1e7}


def classify_outcome(pre_car: float, post_car: float, flat: float = 0.005) -> str:
    if pd.isna(post_car):
        return "Pending (<5d)"
    if pd.isna(pre_car) or abs(post_car) < flat:
        return "Flat"
    if np.sign(post_car) == np.sign(pre_car):
        return "Continuation"
    return "Reversal (sell-news)" if pre_car > 0 else "Reversal (rebound)"


def is_scheduled(event_type: str) -> bool:
    """True if any merged label is a pre-announced (board-meeting-notice) type."""
    return any(t in config.SCHEDULED_TYPES for t in event_type.split(" + "))


def add_direction_metrics(res: pd.DataFrame) -> pd.DataFrame:
    """Sign every pre-window metric by the direction of the news itself.

    Direction = sign of the reaction (Day 0 + post window, Day 0 alone if post is pending). Without this,
    leakage on good news (+) and bad news (-) cancels in a plain mean of pre_car.
    """
    reaction = res["day0_ar"] + res["post_car"].fillna(0)
    res["direction"] = np.sign(reaction)
    res["signed_pre_car"] = res["direction"] * res["pre_car"]
    res["signed_pre_car_z"] = res["direction"] * res["pre_car_z"]
    total = res["pre_car"] + res["day0_ar"]
    # Keown-Pinkerton run-up: share of the [t-5, t0] move that happened before Day 0.
    res["runup_ratio"] = np.where(total.abs() >= config.RUNUP_MIN_MOVE, res["pre_car"] / total, np.nan)
    if "call_skew_z" in res:
        res["signed_call_skew_z"] = res["direction"] * res["call_skew_z"]
    if "call_oi_chg_pre" in res:
        # Calls building faster than puts before good news (and the reverse before bad news) is > 0.
        res["signed_oi_tilt"] = res["direction"] * (res["call_oi_chg_pre"] - res["put_oi_chg_pre"])
        good = res["direction"] > 0
        res["news_side_otm_vol_z"] = res["otm_ce_vol_z"].where(good, res["otm_pe_vol_z"])
        res["wrong_side_otm_vol_z"] = res["otm_pe_vol_z"].where(good, res["otm_ce_vol_z"])
        res.loc[res["direction"] == 0, ["signed_oi_tilt", "news_side_otm_vol_z", "wrong_side_otm_vol_z"]] = np.nan
    if "sector_pre_car" in res:
        # Same news direction (from the Nifty-adjusted reaction); only the benchmark changes.
        res["sector_signed_pre_car"] = res["direction"] * res["sector_pre_car"]
    if "insider_net_cr" in res:
        # Insiders net-buying before good news (or net-selling before bad) is > 0.
        res["insider_net_signed_cr"] = res["direction"] * res["insider_net_cr"]
    if "intra_pre_ar_z" in res:
        # Day-0 AR would include the pre-filing minutes themselves; sign by the reaction after the filing.
        intra_dir = np.sign(res["intra_post_ar"] + res["post_car"].fillna(0))
        res["signed_intra_ar_z"] = intra_dir * res["intra_pre_ar_z"]
    return res


def rank_directional_otm(results: pd.DataFrame) -> pd.DataFrame:
    """Unscheduled, non-overlapping events with significant short-dated OTM flow on the side that profits
    from the news, ranked by how far it exceeds the wrong side.

    Both sides elevated is a volatility bet; only a news-side excess is the informed-trading footprint
    (Augustin, Brenner & Subrahmanyam). These are leads to check against filings, press and SEBI orders.
    """
    if "news_side_otm_vol_z" not in results:
        return pd.DataFrame()
    u = results[~results["overlap"] & ~results["scheduled"]].copy()
    u["otm_side_gap"] = u["news_side_otm_vol_z"] - u["wrong_side_otm_vol_z"]
    u = u[(u["news_side_otm_vol_z"] >= config.SIGNIFICANCE_Z) & (u["otm_side_gap"] > 0)]
    return u.sort_values("otm_side_gap", ascending=False).reset_index(drop=True)


def _flag_contracts(strikes: pd.DataFrame) -> pd.DataFrame:
    """Add moneyness, otm and front (nearest live expiry that day) to per-contract option rows."""
    s = strikes.copy()
    s["moneyness"] = s["strike"] / s["underlying"] - 1
    m = config.OTM_MIN_MONEYNESS
    s["otm"] = ((s["side"] == "CE") & (s["moneyness"] >= m)) | ((s["side"] == "PE") & (s["moneyness"] <= -m))
    s["front"] = s["expiry"] == s.groupby("date")["expiry"].transform("min")
    return s


def option_flow_by_day(strikes: pd.DataFrame, px: pd.DataFrame, day0: pd.Timestamp, direction: float,
                       lo: int = -10, hi: int = 1) -> pd.DataFrame:
    """Drill-down day table t+lo..t+hi: stock AR and volume, front-month OTM volume on the news and wrong
    side, and total call / put OI. direction > 0 makes calls the news side."""
    s = _flag_contracts(strikes)
    news, wrong = ("CE", "PE") if direction > 0 else ("PE", "CE")
    fo = s[s["otm"] & s["front"]].pivot_table(index="date", columns="side", values="vol", aggfunc="sum")
    oi = s.pivot_table(index="date", columns="side", values="oi", aggfunc="sum")
    i = px.index.get_loc(day0)
    base_vol = px["volume"].iloc[max(i - 35, 0):i - 5].mean()
    rows = []
    for k in range(lo, hi + 1):
        if not 0 <= i + k < len(px):
            continue
        d = px.index[i + k]
        rows.append({"k": k, "date": d, "ar": px["ar"].iloc[i + k], "vol_x": px["volume"].iloc[i + k] / base_vol,
                     "news_otm_vol": fo[news].get(d, np.nan) if news in fo else np.nan,
                     "wrong_otm_vol": fo[wrong].get(d, np.nan) if wrong in fo else np.nan,
                     "call_oi": oi["CE"].get(d, np.nan) if "CE" in oi else np.nan,
                     "put_oi": oi["PE"].get(d, np.nan) if "PE" in oi else np.nan})
    return pd.DataFrame(rows)


def top_contracts(strikes: pd.DataFrame, sessions: pd.DatetimeIndex, day0: pd.Timestamp, direction: float,
                  n: int = 8) -> pd.DataFrame:
    """News-side OTM contracts with the most pre-window volume, against their own baseline.

    For each (expiry, strike) on the news side that was OTM at t-1: pre-window [t-5, t-1] volume and its
    ratio to the contract's mean daily volume over [t-35, t-6] (missing days count as zero), OI change
    t-6 -> t-1, and the premium at t-1 vs Day 0 close (what a pre-news buyer would have made).
    """
    side = "CE" if direction > 0 else "PE"
    s = _flag_contracts(strikes)
    s = s[s["side"] == side]
    i = sessions.get_loc(day0)
    pre_lo, pre_hi = config.PRE_WINDOW
    t1, t6 = sessions[i + pre_hi], sessions[i + pre_lo - 1]
    base_days = sessions[max(i + pre_lo - config.BASELINE_DAYS, 0):i + pre_lo]
    pre_days = sessions[i + pre_lo:i + pre_hi + 1]
    at_t1 = s[(s["date"] == t1) & s["otm"]].set_index(["expiry", "strike"])
    if at_t1.empty:
        return pd.DataFrame()
    key = ["expiry", "strike"]
    pre = s[s["date"].isin(pre_days)].groupby(key)["vol"].sum()
    base = s[s["date"].isin(base_days)].groupby(key)["vol"].sum() / max(len(base_days), 1)
    by_day = s.set_index(["date", *key])

    def val(d, k, col):
        return by_day[col].get((d, *k), np.nan)

    rows = []
    for k, r in at_t1.iterrows():
        pv = pre.get(k, 0)
        if pv <= 0:
            continue
        b = base.get(k, 0)
        p1, p0 = val(t1, k, "close"), val(day0, k, "close")
        rows.append({"expiry": k[0], "strike": k[1], "moneyness_t1": r["moneyness"], "pre_vol": pv,
                     "base_daily_vol": b, "pre_vs_base": (pv / len(pre_days)) / b if b > 0 else np.inf,
                     "oi_t6": val(t6, k, "oi"), "oi_t1": val(t1, k, "oi"),
                     "premium_t1": p1, "premium_day0": p0,
                     "premium_chg": p0 / p1 - 1 if p1 and p1 > 0 and not pd.isna(p0) else np.nan})
    out = pd.DataFrame(rows)
    return out.sort_values("pre_vol", ascending=False).head(n).reset_index(drop=True) if len(out) else out


def minute_profile(minutes: pd.DataFrame, lot: float, public_ts: pd.Timestamp, n_top: int = 5) -> dict:
    """When were a contract's pre-news lots bought? 1-minute bars up to the public time.

    Returns contracts per session, the share bought in the last 60 trading minutes before the news and in the
    first 15 minutes of each session (a gap-open reaction to overnight public news), and the busiest minutes.
    """
    before = minutes[minutes.index < public_ts.floor("min")]
    if before.empty or before["volume"].sum() <= 0:
        return {}
    lots = before["volume"] / lot
    total = lots.sum()
    t = before.index
    opening = (t.hour == config.MARKET_OPEN.hour) & (t.minute < config.MARKET_OPEN.minute + 15)
    top = before.assign(contracts=lots).nlargest(n_top, "volume")[["contracts", "close"]]
    return {
        "by_session": lots.groupby(t.normalize()).sum(),
        "last_hour_share": lots.iloc[-60:].sum() / total,
        "opening_share": lots[opening].sum() / total,
        "top_minutes": top,
        "total_contracts": total,
    }


def placebo_events(trading_days: pd.DatetimeIndex, event_day0s: list, n: int,
                   rng: np.random.Generator) -> pd.DataFrame:
    """Random non-event sessions, at least PLACEBO_MIN_GAP sessions from any event and from each other."""
    gap = config.PLACEBO_MIN_GAP
    first = config.BASELINE_DAYS - config.PRE_WINDOW[0] + 1   # enough history for the baseline
    last = len(trading_days) - config.POST_WINDOW[1] - 1      # complete post window
    taken = [trading_days.get_loc(d) for d in event_day0s if d in trading_days]
    picked = []
    for i in rng.permutation(np.arange(first, max(first, last))):
        if all(abs(i - j) >= gap for j in taken):
            picked.append(i)
            taken.append(i)
            if len(picked) == n:
                break
    days = trading_days[sorted(picked)]
    return pd.DataFrame({"day0": days, "timestamp": days + pd.Timedelta(hours=12), "session": "Placebo",
                         "event_type": "Placebo", "headline": "", "n_filings": 0})


def run_event_study(events: pd.DataFrame, stock: pd.DataFrame, market: pd.DataFrame,
                    verbose: bool = True, fo: pd.DataFrame | None = None,
                    deals: pd.DataFrame | None = None,
                    intraday: tuple[pd.DataFrame, pd.DataFrame] | None = None,
                    insider: pd.DataFrame | None = None,
                    sector: pd.DataFrame | None = None) -> pd.DataFrame:
    px = prepare_prices(stock, market, sector)
    fo_d = fo_daily(fo) if fo is not None else None  # fo is long-format (see measure_fno)
    rows = []
    day0s = list(events["day0"]) if not events.empty else []
    for ev in events.itertuples(index=False):
        m = measure_event(px, ev.day0)
        if not m:
            continue
        if m.get("price_break"):
            if verbose:
                print(f"  skipped {ev.day0:%Y-%m-%d} ({ev.event_type}): "
                      f"unadjusted corporate-action price break in window")
            continue
        # Another event's Day 0 inside [t-5, t+5] contaminates this event's windows.
        i = px.index.get_loc(ev.day0)
        lo = px.index[max(i + config.PRE_WINDOW[0], 0)]
        hi = px.index[min(i + config.POST_WINDOW[1], len(px) - 1)]
        overlap = any(lo <= d <= hi and d != ev.day0 for d in day0s)
        fno = measure_fno(fo, fo_d, ev.day0) if fo is not None else {}
        dl = measure_deals(deals, px.index, ev.day0) if deals is not None else {}
        ins = measure_insider(insider, px.index, ev.day0) if insider is not None else {}
        # Only filings released in-session on Day 0 itself have a well-defined "minutes before".
        intra = (measure_intraday(*intraday, ev.timestamp)
                 if intraday is not None and ev.timestamp.normalize() == ev.day0 else {})
        rows.append({**ev._asdict(), **m, **fno, **dl, **ins, **intra, "overlap": overlap})

    res = pd.DataFrame(rows)
    if res.empty:
        return res
    for c in ("post_ret", "post_car", "post_car_z"):
        if c not in res:
            res[c] = np.nan
    z = config.SIGNIFICANCE_Z
    res["leakage_flag"] = (res["pre_car_z"].abs() >= z) | (res["vol_z"] >= z)
    res["outcome"] = [classify_outcome(a, b) for a, b in zip(res["pre_car"], res["post_car"])]
    res["scheduled"] = res["event_type"].map(is_scheduled)
    return add_direction_metrics(res)


def summarise(results: pd.DataFrame) -> dict:
    """Cross-sectional tests: is mean pre-event / post-event CAR different from zero?"""
    out = {"n_events": len(results)}
    for col in ("pre_car", "day0_ar", "post_car"):
        x = results[col].dropna()
        out[f"{col}_mean"] = x.mean() if len(x) else np.nan
        out[f"{col}_abs_mean"] = x.abs().mean() if len(x) else np.nan
        out[f"{col}_t"], out[f"{col}_p"] = (
            stats.ttest_1samp(x, 0.0) if len(x) >= 3 else (np.nan, np.nan))
    v = results["vol_z"].dropna()
    out["vol_z_mean"] = v.mean()
    out["vol_z_t"], out["vol_z_p"] = stats.ttest_1samp(v, 0.0) if len(v) >= 3 else (np.nan, np.nan)
    out["leakage_share"] = results["leakage_flag"].mean()
    # Does the pre-event drift predict the direction of the Day-0 reaction?
    both = results.dropna(subset=["pre_car", "day0_ar"])
    out["pre_day0_same_sign"] = (np.sign(both["pre_car"]) == np.sign(both["day0_ar"])).mean()
    return out


def _ttest(x: pd.Series) -> tuple[float, float]:
    x = x.dropna()
    return tuple(stats.ttest_1samp(x, 0.0)) if len(x) >= 3 else (np.nan, np.nan)


def leakage_tests(res: pd.DataFrame, placebo: pd.DataFrame | None = None,
                  rng: np.random.Generator | None = None) -> dict:
    """Directional leakage tests on one group of events.

    - signed_pre_car t-test: did prices move in the news' direction before Day 0?
    - BMP: the same on signed_pre_car_z (each event standardised by its own baseline volatility)
    - sign test: share of events whose pre-drift points the right way, vs 50%
    - placebo p: share of same-size random draws of placebo days with a mean signed_pre_car at
      least as large (empirical one-sided null that needs no distributional assumption)
    """
    out = {"n": len(res)}
    out["signed_pre_car"] = res["signed_pre_car"].mean()
    out["signed_t"], out["signed_p"] = _ttest(res["signed_pre_car"])
    out["bmp_t"], out["bmp_p"] = _ttest(res["signed_pre_car_z"])
    s = res["signed_pre_car"].dropna()
    s = s[s != 0]
    out["share_right_way"] = (s > 0).mean() if len(s) else np.nan
    out["sign_p"] = stats.binomtest(int((s > 0).sum()), len(s), 0.5).pvalue if len(s) >= 3 else np.nan
    out["runup_median"] = res["runup_ratio"].median()
    out["vol_z"] = res["vol_z"].mean()
    out["vol_t"], out["vol_p"] = _ttest(res["vol_z"])
    out["leak_share"] = res["leakage_flag"].mean()
    out["day0_abs_ar"] = res["day0_ar"].abs().mean()
    out["placebo_p"] = np.nan
    if placebo is not None and len(placebo) and len(s) >= 3:
        rng = rng or np.random.default_rng(config.PLACEBO_SEED)
        pool = placebo["signed_pre_car"].dropna().to_numpy()
        n = int(res["signed_pre_car"].notna().sum())
        draws = rng.choice(pool, size=(config.PLACEBO_BOOTSTRAP, n), replace=True).mean(axis=1)
        out["placebo_p"] = (draws >= out["signed_pre_car"]).mean()
    # Optional signals: mean, and two-sided Welch p vs placebo days (vs 0 for the placebo group itself).
    # Placebo is the right null here: option volume, OI and deal frequency all have non-zero baselines.
    for col in config.EXTRA_SIGNAL_COLUMNS:
        if col in res:
            out[col] = res[col].mean()
            x = res[col].dropna()
            if placebo is not None and col in placebo and len(x) >= 3:
                out[col + "_p"] = stats.ttest_ind(x, placebo[col].dropna(), equal_var=False).pvalue
            else:
                out[col + "_p"] = _ttest(x)[1]
    return out
