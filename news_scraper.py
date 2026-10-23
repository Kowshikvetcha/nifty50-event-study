"""BSE corporate announcements: fetch, timestamp-parse and filter for material catalysts."""
import re
import time
from datetime import date

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
    r"postal ballot|change in (director|kmp|auditor)|book closure|shareholding pattern",
    re.IGNORECASE,
)
ROUTINE_SUBCATEGORIES = {
    "Closure of Trading Window", "Analyst / Investor Meet", "Credit Rating", "Earnings Call Transcript",
    "Board Meeting", "AGM", "Postal Ballot", "Record Date", "Allotment of ESOP / ESPS",
    "Reg. 34 (1) Annual Report", "Reg.24(A)-Annual Secretarial Compliance",
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
        rows, page, total = [], 1, None
        while True:
            params = {
                "pageno": page, "strCat": -1, "subcategory": -1, "strType": "C", "strSearch": "P",
                "strScrip": scrip_code,
                "strPrevDate": from_date.strftime("%Y%m%d"), "strToDate": to_date.strftime("%Y%m%d"),
            }
            for attempt in range(3):  # retry dropped connections; panel runs make hundreds of calls
                try:
                    resp = self.session.get(config.BSE_ANNOUNCEMENTS_URL, params=params, timeout=30)
                    break
                except (requests.ConnectionError, requests.Timeout):
                    if attempt == 2:
                        raise
                    time.sleep(2 ** attempt)
            if resp.status_code != 200 or not resp.headers.get("Content-Type", "").startswith("application/json"):
                raise RuntimeError(f"BSE API returned {resp.status_code}: {resp.text[:200]}")
            payload = resp.json()
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
        df = self._normalise(rows)
        df.to_csv(cache_file, index=False)
        return df

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
