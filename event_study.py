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
            "session": first["session"],
            "event_type": " + ".join(dict.fromkeys(group["event_type"])),
            "headline": short_title(first["subject"], first["headline"]),
            "n_filings": len(group),
        })

    return df.groupby("day0").apply(merge, include_groups=False).reset_index()


def prepare_prices(stock: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    px = pd.DataFrame({"close": stock["close"], "volume": stock["volume"]}).join(
        market["close"].rename("mkt_close"), how="inner")
    px["ret"] = px["close"].pct_change()
    px["mkt_ret"] = px["mkt_close"].pct_change()
    px["ar"] = px["ret"] - px["mkt_ret"]
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

    out["day0_ar"] = px["ar"].iloc[i]
    out["day0_vol_ratio"] = px["volume"].iloc[i] / vol_mu
    if post is not None:
        out["post_ret"] = (1 + post["ret"]).prod() - 1
        out["post_car"] = post["ar"].sum()
        out["post_car_z"] = out["post_car"] / (ar_sd * np.sqrt(len(post))) if ar_sd > 0 else np.nan
    return out


def classify_outcome(pre_car: float, post_car: float, flat: float = 0.005) -> str:
    if pd.isna(post_car):
        return "Pending (<5d)"
    if pd.isna(pre_car) or abs(post_car) < flat:
        return "Flat"
    if np.sign(post_car) == np.sign(pre_car):
        return "Continuation"
    return "Reversal (sell-news)" if pre_car > 0 else "Reversal (rebound)"


def run_event_study(events: pd.DataFrame, stock: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    px = prepare_prices(stock, market)
    rows = []
    day0s = list(events["day0"]) if not events.empty else []
    for ev in events.itertuples(index=False):
        m = measure_event(px, ev.day0)
        if not m:
            continue
        if m.get("price_break"):
            print(f"  skipped {ev.day0:%Y-%m-%d} ({ev.event_type}): unadjusted corporate-action price break in window")
            continue
        # Another event's Day 0 inside [t-5, t+5] contaminates this event's windows.
        i = px.index.get_loc(ev.day0)
        lo = px.index[max(i + config.PRE_WINDOW[0], 0)]
        hi = px.index[min(i + config.POST_WINDOW[1], len(px) - 1)]
        overlap = any(lo <= d <= hi and d != ev.day0 for d in day0s)
        rows.append({**ev._asdict(), **m, "overlap": overlap})

    res = pd.DataFrame(rows)
    if res.empty:
        return res
    for c in ("post_ret", "post_car", "post_car_z"):
        if c not in res:
            res[c] = np.nan
    z = config.SIGNIFICANCE_Z
    res["leakage_flag"] = (res["pre_car_z"].abs() >= z) | (res["vol_z"] >= z)
    res["outcome"] = [classify_outcome(a, b) for a, b in zip(res["pre_car"], res["post_car"])]
    return res


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
