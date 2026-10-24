"""BSE corporate announcements: fetch, timestamp-parse and filter for material catalysts."""
import re
import time
from datetime import date, timedelta

import pandas as pd
import requests

import config

# Event-type classification. Checked in order; first match wins.
# Each entry: label -> (subcategory names, headline/subject regex)
MATERIAL_RULES = {
    "Financial Results": (
        {"Financial Results"},
        r"financial results|quarterly results|audited results|unaudited results",
    ),
    "Dividend": (set(), r"\bdividend\b"),
    "Board Outcome": ({"Outcome of Board Meeting"}, r"outcome of (the )?board meeting"),
    "Acquisition/M&A": (
        {"Acquisition", "Amalgamation / Merger", "Joint Venture"},
        r"\bacqui(re|red|res|sition)|\bmerger\b|amalgamation|joint venture|stake (purchase|sale)|\binvest(s|ment) in\b",
    ),
    "Order Win": (
        {"Award of Order / Receipt of Order"},
        r"\border(s)? (win|won|received|worth)|receipt of order|award(ed)? (of )?(a |an )?(order|contract)|bags .*order|letter of (award|intent)",
    ),
    "Restructuring": (
        {"Scheme of Arrangement", "Diversification / Disinvestment", "Demerger", "Buy back"},
        r"demerger|scheme of arrangement|restructur|disinvest|divest|hive[- ]off|slump sale|buy ?back|fund rais|"
        r"\bqip\b|rights issue|initial public offer|\bipo\b|red herring",
    ),
    "Strategic Deal": (
        set(),
        r"\bpartner(s|ship)?\b|strategic (alliance|collaboration)|collaborat|\bmou\b|tie[- ]up|signs .*agreement",
    ),
    # Exchange queries on media reports: the purest signal that news was circulating pre-filing.
    "Media Clarification": ({"Clarification"}, r"sought clarification"),
}

# Routine compliance filings, dropped even if a keyword above matches.
ROUTINE_PATTERNS = re.compile(
    r"trading window|newspaper (publication|advertisement|clipping)|presentation on (item|the resolutions)|analyst|investor meet|con\.? call|"
    r"earnings call|transcript|audio recording|credit rating|loss of share certificate|duplicate share|"
    r"compliance certificate|reg(ulation)?\.? ?(7|13|24|39|40|74)\b|secretarial|annual report|brsr|"
    r"esop|esos|allotment of|record date|intimation of board meeting|prior intimation|"
    r"postal ballot|change in (director|kmp|auditor)|book closure|shareholding pattern|"
    # SAST: a shareholder reporting its own stake change after the fact; "acquisition" in the title is not M&A
    r"substantial acquisition of shares",
    re.IGNORECASE,
)
ROUTINE_SUBCATEGORIES = {
    "Closure of Trading Window", "Analyst / Investor Meet", "Credit Rating", "Earnings Call Transcript",
    "Board Meeting", "AGM", "Postal Ballot", "Record Date", "Allotment of ESOP / ESPS",
    "Reg. 34 (1) Annual Report", "Reg.24(A)-Annual Secretarial Compliance",
    "Disclosures under Reg. 29(1) of SEBI (SAST) Regulations, 2011",
    "Disclosures under Reg. 29(2) of SEBI (SAST) Regulations, 2011",
    "Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011",
    "Disclosures under Reg. 10(6) of SEBI (SAST) Regulations, 2011",
}


class BSEScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(config.BSE_HEADERS)

    def fetch_announcements(self, scrip_code: int, from_date: date, to_date: date,
                            use_cache: bool = True) -> pd.DataFrame:
        """All corporate announcements for a scrip in [from_date, to_date], every page, cached."""
        cache_file = config.CACHE_DIR / f"bse_{scrip_code}_{from_date}_{to_date}.csv"
        if use_cache and cache_file.exists():
            df = pd.read_csv(cache_file, parse_dates=["timestamp"], keep_default_na=False)
            return df.astype({"critical": bool})
        rows, start = [], from_date
        while start <= to_date:  # the API silently returns nothing for ranges longer than a year
            end = min(to_date, start + timedelta(days=config.BSE_MAX_DAYS_PER_REQUEST - 1))
            rows += self._fetch_range(scrip_code, start, end)
            start = end + timedelta(days=1)
        df = self._normalise(rows)
        df.to_csv(cache_file, index=False)
        return df

    def _fetch_range(self, scrip_code: int, from_date: date, to_date: date) -> list[dict]:
        """Every page of announcements for one range of at most a year."""
        rows, page, total = [], 1, None
        while True:
            params = {
                "pageno": page, "strCat": -1, "subcategory": -1, "strType": "C", "strSearch": "P",
                "strScrip": scrip_code,
                "strPrevDate": from_date.strftime("%Y%m%d"), "strToDate": to_date.strftime("%Y%m%d"),
            }
            payload = self._get(config.BSE_ANNOUNCEMENTS_URL, params).json()
            batch = payload.get("Table") or []
            if total is None and payload.get("Table1"):
                total = payload["Table1"][0].get("ROWCNT")
            if not batch:
                break
            rows.extend(batch)
            if total is not None and len(rows) >= total:
                break
            page += 1
            time.sleep(config.BSE_REQUEST_PAUSE_SEC)
        return rows

    def get_insider_trades(self, scrip_code: int, from_date: date, to_date: date) -> pd.DataFrame:
        """SEBI PIT insider trades (system-driven disclosures) for a scrip, cached per range.

        Source: BSE `sddpit`, which is complete where NSE's corporates-pit feed returns nothing (e.g. 1,848
        HDFC Bank rows in a year against NSE's zero). Person names are dropped here and never stored.
        """
        cache_file = config.CACHE_DIR / f"bse_pit_{scrip_code}_{from_date}_{to_date}.csv"
        cols = ["category", "kind", "shares", "value", "trade_from", "trade_to", "reported"]
        if cache_file.exists():
            return pd.read_csv(cache_file, parse_dates=["trade_from", "trade_to", "reported"])
        rows, start = [], from_date
        while start <= to_date:  # ranges are chunked to a year, like the other exchange APIs
            end = min(to_date, start + timedelta(days=364))
            resp = self._get(config.BSE_PIT_URL, {"scripcode": scrip_code, "fromdt": f"{start:%Y%m%d}",
                                                  "todt": f"{end:%Y%m%d}"})
            rows += resp.json().get("Table") or []
            start = end + timedelta(days=1)
            time.sleep(config.BSE_REQUEST_PAUSE_SEC)
        out = []
        for r in rows:
            for kind, n, v in (("buy", r.get("Buy_No_OF_Shares"), r.get("Buy_Value_Securities")),
                               ("sell", r.get("Sell_No_OF_Shares"), r.get("Sell_Value_Securities"))):
                if n:  # pledge-only rows carry neither and are skipped
                    out.append({"category": r.get("Category") or "", "kind": kind, "shares": float(n),
                                "value": float(v or 0), "trade_from": r.get("Transaction_Date_From"),
                                "trade_to": r.get("Transaction_Date_To"), "reported": r.get("Report_Creation_Date")})
        df = pd.DataFrame(out, columns=cols)
        for c in ("trade_from", "trade_to", "reported"):
            df[c] = pd.to_datetime(df[c])
        df.to_csv(cache_file, index=False)
        return df

    def _get(self, url: str, params: dict) -> requests.Response:
        """GET that retries dropped connections and insists on JSON (BSE serves HTML error pages)."""
        for attempt in range(3):
            try:
                resp = self.session.get(url, params=params, timeout=60)
                break
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        if resp.status_code != 200 or not resp.headers.get("Content-Type", "").startswith("application/json"):
            raise RuntimeError(f"BSE API returned {resp.status_code}: {resp.text[:200]}")
        return resp

    @staticmethod
    def _normalise(rows: list[dict]) -> pd.DataFrame:
        cols = ["news_id", "scrip_code", "company", "timestamp", "category", "subcategory",
                "subject", "headline", "critical", "attachment"]
        if not rows:
            return pd.DataFrame(columns=cols)
        df = pd.DataFrame(rows)
        out = pd.DataFrame({
            "news_id": df["NEWSID"],
            "scrip_code": df["SCRIP_CD"],
            "company": df["SLONGNAME"],
            # DT_TM is the exchange broadcast time in IST; keep second precision.
            "timestamp": pd.to_datetime(df["DT_TM"], format="ISO8601").dt.floor("s"),
            "category": df["CATEGORYNAME"].fillna("").str.strip(),
            "subcategory": df["SUBCATNAME"].fillna("").str.strip(),
            "subject": df["NEWSSUB"].fillna("").str.replace("''", "'").str.strip(),
            "headline": df["HEADLINE"].fillna("").str.replace("''", "'").str.strip(),
            "critical": df["CRITICALNEWS"].astype(str) == "1",
            "attachment": df["ATTACHMENTNAME"].fillna("").map(
                lambda n: config.BSE_ATTACHMENT_URL.format(name=n) if n else ""),
        })
        return out.drop_duplicates("news_id").sort_values("timestamp").reset_index(drop=True)

    @staticmethod
    def classify(row: pd.Series) -> str | None:
        """Return a material event label, or None for routine/compliance filings."""
        text = f"{row['subject']} | {row['headline']}"
        if row["subcategory"] in ROUTINE_SUBCATEGORIES or ROUTINE_PATTERNS.search(text):
            # Results/board outcomes are often filed with compliance boilerplate; keep them.
            if row["subcategory"] not in {"Financial Results", "Outcome of Board Meeting"}:
                return None
        for label, (subcats, pattern) in MATERIAL_RULES.items():
            if row["subcategory"] in subcats or re.search(pattern, text, re.IGNORECASE):
                return label
        return None

    def material_events(self, scrip_code: int, from_date: date, to_date: date) -> pd.DataFrame:
        df = self.fetch_announcements(scrip_code, from_date, to_date)
        if df.empty:
            return df.assign(event_type=pd.Series(dtype=str))
        df["event_type"] = df.apply(self.classify, axis=1)
        return df[df["event_type"].notna()].reset_index(drop=True)
