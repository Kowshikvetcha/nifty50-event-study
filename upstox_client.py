"""Upstox API v2 client: instrument master, daily candles and expired-futures OI."""
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote

import pandas as pd
import requests

import config

_CANDLE_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "oi"]


class UpstoxError(RuntimeError):
    pass


class UpstoxClient:
    def __init__(self, access_token: str = config.UPSTOX_ACCESS_TOKEN):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        if access_token:
            self.session.headers["Authorization"] = f"Bearer {access_token}"
        self.has_token = bool(access_token)
        self._master: pd.DataFrame | None = None

    # ------------------------------------------------------------------ helpers
    def _get(self, url: str, params: dict | None = None, retries: int = 3) -> dict:
        for attempt in range(retries):
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 429:  # rate limited
                time.sleep(2 ** attempt)
                continue
            try:
                payload = resp.json()
            except ValueError:
                raise UpstoxError(f"{resp.status_code} non-JSON response from {url}")
            if resp.status_code != 200 or payload.get("status") != "success":
                errors = payload.get("errors") or payload
                raise UpstoxError(f"{resp.status_code} from {url}: {errors}")
            return payload["data"]
        raise UpstoxError(f"Rate limited repeatedly on {url}")

    @staticmethod
    def _candles_to_frame(candles: list) -> pd.DataFrame:
        df = pd.DataFrame(candles, columns=_CANDLE_COLUMNS[: len(candles[0])] if candles else _CANDLE_COLUMNS)
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["timestamp"].str[:10])
        return df.drop(columns="timestamp").set_index("date").sort_index()

    # --------------------------------------------------------- instrument master
    def load_instrument_master(self, force_refresh: bool = False) -> pd.DataFrame:
        """Download (or reuse the cached) complete.csv.gz instrument master."""
        if self._master is not None and not force_refresh:
            return self._master
        path = config.INSTRUMENT_MASTER_PATH
        stale = (
            not path.exists()
            or (time.time() - path.stat().st_mtime) / 3600 > config.INSTRUMENT_MASTER_MAX_AGE_HOURS
        )
        if force_refresh or stale:
            resp = requests.get(config.UPSTOX_INSTRUMENT_MASTER_URL, timeout=120)
            resp.raise_for_status()
            path.write_bytes(resp.content)
        self._master = pd.read_csv(path, low_memory=False)
        return self._master

    def get_instrument_key(self, symbol: str, exchange: str = "NSE_EQ") -> str:
        """Map an NSE trading symbol (e.g. RELIANCE) to its instrument_key."""
        master = self.load_instrument_master()
        hit = master[(master["exchange"] == exchange) & (master["tradingsymbol"] == symbol.upper())]
        if exchange == "NSE_EQ":
            hit = hit[hit["instrument_type"] == "EQUITY"]
        if hit.empty:
            raise UpstoxError(f"Symbol {symbol!r} not found on {exchange}")
        return hit.iloc[0]["instrument_key"]

    # --------------------------------------------------------- historical candles
    def get_daily_candles(self, instrument_key: str, from_date: date, to_date: date,
                          use_cache: bool = True) -> pd.DataFrame:
        """Daily OHLCV between from_date and to_date (inclusive), chunked and cached."""
        cache_file = config.CACHE_DIR / (
            f"candles_{instrument_key.replace('|', '_').replace(' ', '')}_{from_date}_{to_date}.csv"
        )
        if use_cache and cache_file.exists():
            return pd.read_csv(cache_file, index_col="date", parse_dates=True)

        frames = []
        chunk_end = to_date
        while chunk_end >= from_date:
            chunk_start = max(from_date, chunk_end - timedelta(days=config.UPSTOX_MAX_DAYS_PER_REQUEST - 1))
            url = config.UPSTOX_HISTORICAL_CANDLE_URL.format(
                key=quote(instrument_key, safe=""), interval="day",
                to_date=chunk_end.isoformat(), from_date=chunk_start.isoformat(),
            )
            candles = self._get(url).get("candles", [])
            if candles:
                frames.append(self._candles_to_frame(candles))
            chunk_end = chunk_start - timedelta(days=1)

        if not frames:
            raise UpstoxError(f"No candles for {instrument_key} {from_date}..{to_date}")
        df = pd.concat(frames).sort_index()
        df = df[~df.index.duplicated(keep="last")]
        df.to_csv(cache_file, index_label="date")
        return df

    # ----------------------------------------------- expired FUTSTK (optional OI)
    def get_expired_expiries(self, underlying_key: str) -> list[str]:
        """Expiry dates of expired derivative contracts on an underlying (needs token)."""
        return self._get(config.UPSTOX_EXPIRED_EXPIRIES_URL, {"instrument_key": underlying_key})

    def get_expired_future_contracts(self, underlying_key: str, expiry_date: str) -> list[dict]:
        return self._get(
            config.UPSTOX_EXPIRED_FUTURES_URL,
            {"instrument_key": underlying_key, "expiry_date": expiry_date},
        )

    def get_expired_futures_oi(self, underlying_key: str, from_date: date, to_date: date) -> pd.DataFrame:
        """Stitch near-month expired FUTSTK daily candles into a continuous OI series.

        For every expiry in [from_date, to_date + 1 month], the contract's daily candles
        are pulled and each trading day keeps the nearest-expiry contract.
        Requires a valid UPSTOX_ACCESS_TOKEN.
        """
        if not self.has_token:
            raise UpstoxError("Expired-instrument endpoints require UPSTOX_ACCESS_TOKEN")
        horizon = to_date + timedelta(days=35)
        expiries = sorted(
            e for e in self.get_expired_expiries(underlying_key)
            if from_date.isoformat() <= e <= horizon.isoformat()
        )
        frames = []
        prev_expiry = from_date - timedelta(days=1)
        for expiry in expiries:
            for contract in self.get_expired_future_contracts(underlying_key, expiry):
                url = config.UPSTOX_EXPIRED_CANDLE_URL.format(
                    key=quote(contract["instrument_key"], safe=""), interval="day",
                    to_date=expiry, from_date=max(from_date, prev_expiry - timedelta(days=95)).isoformat(),
                )
                candles = self._get(url).get("candles", [])
                if candles:
                    df = self._candles_to_frame(candles)
                    df["expiry"] = expiry
                    frames.append(df)
            prev_expiry = datetime.strptime(expiry, "%Y-%m-%d").date()
        if not frames:
            return pd.DataFrame(columns=["close", "volume", "oi", "expiry"])
        allc = pd.concat(frames).reset_index().sort_values(["date", "expiry"])
        near = allc.groupby("date").first()  # nearest live expiry each day
        return near.loc[str(from_date):str(to_date), ["close", "volume", "oi", "expiry"]]
