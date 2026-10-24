"""Google News RSS search: dated press coverage of a company, for the media-before-filing check."""
import re
import time
import xml.etree.ElementTree as ET
from datetime import date

import pandas as pd
import requests

import config


class MediaError(RuntimeError):
    pass


def company_query(name: str) -> str:
    """'Reliance Industries Ltd.' -> 'Reliance Industries' (the form the press uses)."""
    return re.sub(r"\b(ltd|limited|corporation|corp|co)\b\.?|\.$", "", name, flags=re.IGNORECASE).strip(" .,")


class MediaClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.NSE_HEADERS["User-Agent"]})

    def search(self, company: str, from_date: date, to_date: date) -> pd.DataFrame:
        """Articles mentioning the company published in [from_date, to_date], cached per query.

        Google News returns at most ~100 items per query, so keep ranges short.
        """
        return self._search(f'"{company}"', "gnews_", company, from_date, to_date)

    def search_broker(self, company: str, from_date: date, to_date: date) -> pd.DataFrame:
        """Articles about broker rating changes or target revisions for the company (config.BROKER_QUERY)."""
        return self._search(config.BROKER_QUERY.format(company=company), "gnews_broker_", company, from_date, to_date)

    def _search(self, query: str, prefix: str, company: str, from_date: date, to_date: date) -> pd.DataFrame:
        slug = re.sub(r"\W+", "_", company.lower()).strip("_")
        cache_file = config.CACHE_DIR / f"{prefix}{slug}_{from_date}_{to_date}.csv"
        if cache_file.exists():
            return pd.read_csv(cache_file, parse_dates=["date"], keep_default_na=False)
        # before: is exclusive in Google's operator syntax
        q = f'{query} after:{from_date:%Y-%m-%d} before:{(pd.Timestamp(to_date) + pd.Timedelta(days=1)):%Y-%m-%d}'
        for attempt in range(3):  # long runs make ~1,000 searches; Google drops the odd connection
            try:
                resp = self.session.get(config.GOOGLE_NEWS_RSS_URL, timeout=30,
                                        params={"q": q, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
                break
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 2:
                    raise
                time.sleep(5 * 2 ** attempt)
        time.sleep(config.MEDIA_PAUSE_SEC)
        if resp.status_code != 200:
            raise MediaError(f"{resp.status_code} from Google News for {company!r}")
        rows = [{
            # pubDate is RFC 822 in GMT; historical items carry a placeholder time, so keep the IST date only.
            "date": (pd.to_datetime(it.findtext("pubDate"), format="%a, %d %b %Y %H:%M:%S %Z")
                     + pd.Timedelta(hours=5, minutes=30)).tz_localize(None).normalize(),
            "source": it.findtext("source") or "",
            # Google appends " - <publisher>" to every title; drop it so publisher names aren't keywords.
            "title": (it.findtext("title") or "").removesuffix(f" - {it.findtext('source') or ''}"),
        } for it in ET.fromstring(resp.content).findall("./channel/item")]
        df = pd.DataFrame(rows, columns=["date", "source", "title"])
        df.to_csv(cache_file, index=False)
        return df
