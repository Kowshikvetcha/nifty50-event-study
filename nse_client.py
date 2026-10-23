"""NSE client: Nifty 50 constituents and daily stock F&O activity from the bhavcopy archive."""
import io
import time
from datetime import date, timedelta

import pandas as pd
import requests

import config


class NSEError(RuntimeError):
    pass


class NSEClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(config.NSE_HEADERS)
        self._fo_mem: dict[date, pd.DataFrame | None] = {}
        self._raw_mem: dict[date, pd.DataFrame] = {}
        self._api_ready = False

    def _get(self, url: str, params: dict | None = None, timeout: int = 60, retries: int = 3) -> requests.Response:
        """session.get that retries dropped connections (long panel runs see a few)."""
        for attempt in range(retries):
            try:
                return self.session.get(url, params=params, timeout=timeout)
            except (requests.ConnectionError, requests.Timeout):
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)

    def _api_get(self, url: str, params: dict) -> dict:
        """GET an nseindia.com/api JSON endpoint. These need Akamai cookies from a homepage visit first."""
        for attempt in range(2):
            if not self._api_ready:
                self._get(config.NSE_HOME_URL, timeout=30)
                self._api_ready = True
            resp = self._get(url, params=params, timeout=90)
            time.sleep(config.NSE_REQUEST_PAUSE_SEC)
            if resp.status_code == 200 and resp.headers.get("Content-Type", "").startswith("application/json"):
                return resp.json()
            self._api_ready = False  # cookies expired or blocked: re-warm once
        raise NSEError(f"{resp.status_code} from {url}: {resp.text[:120]!r}")

    def get_announcements(self, symbol: str, from_date: date, to_date: date) -> pd.DataFrame:
        """NSE corporate announcements for one symbol with second-precision broadcast time, cached."""
        cache_file = config.CACHE_DIR / f"nse_ann_{symbol.replace('&', '_')}_{from_date}_{to_date}.csv"
        if cache_file.exists():
            return pd.read_csv(cache_file, parse_dates=["timestamp"], keep_default_na=False)
        frames, start = [], from_date
        while start <= to_date:
            end = min(to_date, start + timedelta(days=config.NSE_DEALS_MAX_DAYS - 1))
            payload = self._api_get(config.NSE_ANNOUNCEMENTS_URL, {
                "index": "equities", "symbol": symbol, "from_date": f"{start:%d-%m-%Y}", "to_date": f"{end:%d-%m-%Y}"})
            frames.append(pd.DataFrame(payload if isinstance(payload, list) else payload.get("data", [])))
            start = end + timedelta(days=1)
        raw = pd.concat(frames, ignore_index=True)
        cols = ["timestamp", "subject", "headline", "attachment"]
        if raw.empty:
            df = pd.DataFrame(columns=cols)
        else:
            df = pd.DataFrame({
                "timestamp": pd.to_datetime(raw["an_dt"], format="%d-%b-%Y %H:%M:%S"),
                "subject": raw["desc"].fillna("").str.strip(),
                "headline": raw["attchmntText"].fillna("").str.strip(),
                "attachment": raw["attchmntFile"].fillna(""),
            }).drop_duplicates().sort_values("timestamp").reset_index(drop=True)
        df.to_csv(cache_file, index=False)
        return df

    def get_large_deals(self, symbol: str, from_date: date, to_date: date) -> pd.DataFrame:
        """Bulk and block deals for one symbol (both sides of each trade are listed), cached per range."""
        cache_file = config.CACHE_DIR / f"nse_deals_{symbol.replace('&', '_')}_{from_date}_{to_date}.csv"
        if cache_file.exists():
            return pd.read_csv(cache_file, parse_dates=["date"])
        frames, start = [], from_date
        while start <= to_date:  # ranges over a year fail with a 500
            end = min(to_date, start + timedelta(days=config.NSE_DEALS_MAX_DAYS - 1))
            frames += [self._deals(kind, symbol, start, end) for kind in ("bulk_deals", "block_deals")]
            start = end + timedelta(days=1)
        df = pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True)
        df.to_csv(cache_file, index=False)
        return df

    def _deals(self, kind: str, symbol: str, f: date, t: date) -> pd.DataFrame:
        rows = self._api_get(config.NSE_DEALS_URL, {"optionType": kind, "symbol": symbol,
                                                     "from": f"{f:%d-%m-%Y}", "to": f"{t:%d-%m-%Y}"}).get("data", [])
        if len(rows) >= config.NSE_DEALS_ROW_CAP and f < t:  # response truncated: split the range
            mid = f + (t - f) / 2
            return pd.concat([self._deals(kind, symbol, f, mid),
                              self._deals(kind, symbol, mid + timedelta(days=1), t)])
        cols = ["date", "symbol", "client", "side", "qty", "price", "kind"]
        if not rows:
            return pd.DataFrame(columns=cols)
        d = pd.DataFrame(rows)
        return pd.DataFrame({
            "date": pd.to_datetime(d["BD_DT_DATE"], format="%d-%b-%Y"),
            "symbol": d["BD_SYMBOL"], "client": d["BD_CLIENT_NAME"], "side": d["BD_BUY_SELL"].str.upper(),
            "qty": pd.to_numeric(d["BD_QTY_TRD"]), "price": pd.to_numeric(d["BD_TP_WATP"]),
            "kind": kind.split("_")[0],
        })[cols]

    def get_nifty50(self) -> pd.DataFrame:
        """Current Nifty 50 constituents (symbol, company, industry, isin), cached for the day."""
        cache_file = config.CACHE_DIR / f"nifty50_{date.today():%Y%m%d}.csv"
        if cache_file.exists():
            return pd.read_csv(cache_file)
        resp = self._get(config.NIFTY50_LIST_URL, timeout=30)
        if resp.status_code != 200:
            raise NSEError(f"{resp.status_code} from NSE Nifty 50 list")
        raw = pd.read_csv(io.StringIO(resp.text))
        df = pd.DataFrame({"symbol": raw["Symbol"], "company": raw["Company Name"],
                           "industry": raw["Industry"], "isin": raw["ISIN Code"]})
        df.to_csv(cache_file, index=False)
        return df

    def _bhavcopy(self, day: date) -> pd.DataFrame | None:
        """The full F&O bhavcopy for one session (not cached on disk: ~1 MB zipped). None on 404."""
        if day in self._raw_mem:
            return self._raw_mem[day]
        resp = self._get(config.NSE_FO_BHAVCOPY_URL.format(yyyymmdd=f"{day:%Y%m%d}"))
        time.sleep(config.NSE_REQUEST_PAUSE_SEC)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise NSEError(f"{resp.status_code} from NSE bhavcopy for {day}")
        df = pd.read_csv(io.BytesIO(resp.content), compression="zip")
        if len(self._raw_mem) >= 5:  # a drill-down asks several symbols for the same few days
            self._raw_mem.pop(next(iter(self._raw_mem)))
        self._raw_mem[day] = df
        return df

    def get_option_strikes(self, symbol: str, sessions: pd.DatetimeIndex) -> pd.DataFrame:
        """Per-contract stock-option rows (expiry, strike, side, close, oi, vol, underlying) for one symbol.

        Used by the drill-down only; cached per symbol and day under data/cache/strikes/.
        """
        folder = config.CACHE_DIR / "strikes"
        folder.mkdir(exist_ok=True)
        frames = []
        for ts in sessions:
            cache_file = folder / f"{symbol.replace('&', '_')}_{ts:%Y%m%d}.csv"
            if cache_file.exists():
                df = pd.read_csv(cache_file, parse_dates=["expiry"])
            else:
                raw = self._bhavcopy(ts.date())
                if raw is None:
                    continue
                r = raw[(raw["FinInstrmTp"] == "STO") & (raw["TckrSymb"] == symbol.upper())]
                df = pd.DataFrame({"expiry": pd.to_datetime(r["XpryDt"]), "strike": r["StrkPric"],
                                   "side": r["OptnTp"], "close": r["ClsPric"], "oi": r["OpnIntrst"],
                                   "vol": r["TtlTradgVol"], "underlying": r["UndrlygPric"]})
                df.to_csv(cache_file, index=False)
            frames.append(df.assign(date=ts))
        if not frames:
            raise NSEError(f"No NSE option data for {symbol} in the requested sessions")
        return pd.concat(frames, ignore_index=True)

    def _fo_day(self, day: date) -> pd.DataFrame | None:
        """Stock F&O activity for one session, aggregated per (symbol, kind, expiry, otm). Cached per day;
        None if there is no file (holiday / not out yet).

        kind is FUT / CE / PE. Expiry is kept so OI changes can be measured on contracts alive for the whole
        window (OI of an expiring series vanishes on expiry day). otm marks options at least OTM_MIN_MONEYNESS
        out of the money against that day's underlying price; front marks each symbol's nearest expiry.
        """
        if day in self._fo_mem:
            return self._fo_mem[day]
        cache_file = config.CACHE_DIR / f"nse_fo2_{day:%Y%m%d}.csv"
        if cache_file.exists():
            agg = pd.read_csv(cache_file, parse_dates=["expiry"]).set_index("symbol")
        else:
            df = self._bhavcopy(day)
            if df is None:
                self._fo_mem[day] = None
                return None
            df = df[df["FinInstrmTp"].isin(["STF", "STO"])]
            kind = df["OptnTp"].where(df["FinInstrmTp"] == "STO", "FUT")
            m = config.OTM_MIN_MONEYNESS
            otm = ((kind == "CE") & (df["StrkPric"] >= df["UndrlygPric"] * (1 + m))) | \
                  ((kind == "PE") & (df["StrkPric"] <= df["UndrlygPric"] * (1 - m)))
            long = pd.DataFrame({"symbol": df["TckrSymb"], "kind": kind,
                                 "expiry": pd.to_datetime(df["XpryDt"]), "otm": otm,
                                 "vol": df["TtlTradgVol"], "oi": df["OpnIntrst"]})
            agg = long.groupby(["symbol", "kind", "expiry", "otm"], as_index=False)[["vol", "oi"]].sum()
            agg["front"] = agg["expiry"] == agg.groupby("symbol")["expiry"].transform("min")
            agg.to_csv(cache_file, index=False)
            agg = agg.set_index("symbol")
        self._fo_mem[day] = agg
        return agg

    def get_fo_activity(self, symbol: str, sessions: pd.DatetimeIndex) -> pd.DataFrame:
        """Long-format F&O rows (date, kind, expiry, otm, front, vol, oi) for one symbol.

        Sessions without a file are skipped.
        """
        frames = []
        for ts in sessions:
            agg = self._fo_day(ts.date())
            if agg is not None and symbol.upper() in agg.index:
                frames.append(agg.loc[[symbol.upper()]].assign(date=ts))
        if not frames:
            raise NSEError(f"No NSE F&O data for {symbol} (bhavcopy UDiFF format starts Jul-2024)")
        return pd.concat(frames).reset_index(drop=True)

    def get_futures_oi(self, symbol: str, sessions: pd.DatetimeIndex) -> pd.DataFrame:
        """Total futures OI (summed over live expiries) per session."""
        fo = self.get_fo_activity(symbol, sessions)
        fut = fo[fo["kind"] == "FUT"].groupby("date")
        return pd.DataFrame({"oi": fut["oi"].sum(), "n_expiries": fut["oi"].size()})
