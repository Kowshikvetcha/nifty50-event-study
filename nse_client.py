"""NSE client: daily stock-futures open interest from the F&O bhavcopy archive."""
import io
import time
from datetime import date

import pandas as pd
import requests

import config

_KEEP = ["TckrSymb", "XpryDt", "ClsPric", "OpnIntrst", "TtlTradgVol"]


class NSEError(RuntimeError):
    pass


class NSEClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(config.NSE_HEADERS)

    def _stock_futures(self, day: date) -> pd.DataFrame | None:
        """All stock-futures (STF) rows for one session, cached per day. None if no file (holiday/not yet out)."""
        cache_file = config.CACHE_DIR / f"nse_stf_{day:%Y%m%d}.csv"
        if cache_file.exists():
            return pd.read_csv(cache_file)
        resp = self.session.get(config.NSE_FO_BHAVCOPY_URL.format(yyyymmdd=f"{day:%Y%m%d}"), timeout=60)
        time.sleep(config.NSE_REQUEST_PAUSE_SEC)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise NSEError(f"{resp.status_code} from NSE bhavcopy for {day}")
        df = pd.read_csv(io.BytesIO(resp.content), compression="zip")
        df = df.loc[df["FinInstrmTp"] == "STF", _KEEP]
        df.to_csv(cache_file, index=False)
        return df

    def get_futures_oi(self, symbol: str, sessions: pd.DatetimeIndex) -> pd.DataFrame:
        """Total futures OI (summed over live expiries) per session; sessions without a file are skipped.

        Summing across expiries avoids the artificial OI drop when the near contract rolls.
        """
        rows = {}
        for ts in sessions:
            df = self._stock_futures(ts.date())
            if df is None:
                continue
            sym = df[df["TckrSymb"] == symbol.upper()]
            if not sym.empty:
                rows[ts] = {"oi": sym["OpnIntrst"].sum(), "n_expiries": len(sym)}
        if not rows:
            raise NSEError(f"No NSE futures OI for {symbol} (bhavcopy UDiFF format starts Jul-2024)")
        return pd.DataFrame.from_dict(rows, orient="index").rename_axis("date").sort_index()
