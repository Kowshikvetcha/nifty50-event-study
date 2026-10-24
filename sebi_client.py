"""SEBI enforcement orders: title search over sebi.gov.in's Orders listing (drill-down cross-check)."""
import re
import time
from datetime import date

import pandas as pd
import requests

import config

_ROW = re.compile(r"<td>(\w{3} \d{2}, \d{4})</td><td><a href='([^']+)'[^>]*title=\"([^\"]+)\"")


class SebiError(RuntimeError):
    pass


class SebiClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.NSE_HEADERS["User-Agent"], "Accept-Language": "en-US,en"})
        self._ready = False

    def search_orders(self, term: str) -> pd.DataFrame:
        """All enforcement orders whose title matches `term` (date, title, url), cached for the day.

        The listing's AJAX pager only answers after the listing page itself has been visited (session cookie).
        """
        slug = re.sub(r"\W+", "_", term.lower()).strip("_")
        cache_file = config.CACHE_DIR / f"sebi_orders_{slug}_{date.today():%Y%m%d}.csv"
        if cache_file.exists():
            return pd.read_csv(cache_file, parse_dates=["date"], keep_default_na=False)
        if not self._ready:
            self.session.get(config.SEBI_ORDERS_LISTING_URL, timeout=60)
            self._ready = True
        rows = []
        for page in range(config.SEBI_MAX_PAGES):
            data = {"nextValue": str(page), "next": "s" if page == 0 else "n", "search": term, "fromDate": "",
                    "toDate": "", "fromYear": "", "toYear": "", "deptId": "", "sid": "2", "ssid": "9", "smid": "0",
                    "ssidhidden": "9", "intmid": "-1", "sText": "Enforcement", "ssText": "Orders", "smText": "",
                    "doDirect": "-1"}
            resp = self.session.post(config.SEBI_ORDERS_AJAX_URL, data=data, timeout=60, headers={
                "Referer": config.SEBI_ORDERS_LISTING_URL, "X-Requested-With": "XMLHttpRequest"})
            time.sleep(config.MEDIA_PAUSE_SEC)
            if resp.status_code != 200:
                raise SebiError(f"{resp.status_code} from SEBI orders search for {term!r}")
            batch = _ROW.findall(resp.text)
            rows += batch
            if len(batch) < 25:  # last page
                break
        df = pd.DataFrame([{"date": pd.to_datetime(d, format="%b %d, %Y"), "title": t.strip(), "url": u}
                           for d, u, t in rows], columns=["date", "title", "url"]).drop_duplicates("url")
        df.to_csv(cache_file, index=False)
        return df
