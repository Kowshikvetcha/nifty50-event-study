"""Central configuration: credentials, endpoints and study constants."""
import os
from datetime import time
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# --- Credentials (.env) ------------------------------------------------------
UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
UPSTOX_API_KEY = os.getenv("UPSTOX_API_KEY", "").strip()
UPSTOX_API_SECRET = os.getenv("UPSTOX_API_SECRET", "").strip()

# --- Paths ---------------------------------------------------------------------
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
DATA_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)
INSTRUMENT_MASTER_PATH = DATA_DIR / "complete.csv.gz"
INSTRUMENT_MASTER_MAX_AGE_HOURS = 24

# --- Upstox endpoints ---------------------------------------------------------
UPSTOX_BASE_URL = "https://api.upstox.com/v2"
UPSTOX_INSTRUMENT_MASTER_URL = (
    "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
)
UPSTOX_HISTORICAL_CANDLE_URL = UPSTOX_BASE_URL + "/historical-candle/{key}/{interval}/{to_date}/{from_date}"
UPSTOX_EXPIRED_EXPIRIES_URL = UPSTOX_BASE_URL + "/expired-instruments/expiries"
UPSTOX_EXPIRED_FUTURES_URL = UPSTOX_BASE_URL + "/expired-instruments/future/contract"
UPSTOX_EXPIRED_CANDLE_URL = (
    UPSTOX_BASE_URL + "/expired-instruments/historical-candle/{key}/{interval}/{to_date}/{from_date}"
)
# v3 intraday candles (1-minute bars, at most one calendar month per request).
UPSTOX_V3_CANDLE_URL = "https://api.upstox.com/v3/historical-candle/{key}/{unit}/{interval}/{to_date}/{from_date}"
UPSTOX_REQUEST_PAUSE_SEC = 0.15
# Max span per daily-candle request; longer ranges are chunked.
UPSTOX_MAX_DAYS_PER_REQUEST = 365
MARKET_INDEX_KEY = "NSE_INDEX|Nifty 50"

# --- NSE endpoints (F&O bhavcopy, UDiFF format, available from Jul-2024) --------
NSE_FO_BHAVCOPY_URL = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{yyyymmdd}_F_0000.csv.zip"
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
NSE_REQUEST_PAUSE_SEC = 0.3
NIFTY50_LIST_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
NSE_HOME_URL = "https://www.nseindia.com/"  # visited first: /api endpoints need its Akamai cookies
# /api/historical/bulk-deals returns 503; this is what the NSE website itself calls.
NSE_DEALS_URL = "https://www.nseindia.com/api/historicalOR/bulk-block-short-deals"
NSE_DEALS_ROW_CAP = 70     # the endpoint silently truncates at 70 rows; full pages trigger a range split
NSE_DEALS_MAX_DAYS = 365  # also used to chunk announcement requests
NSE_ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements"
# A BSE filing and an NSE filing this close together are treated as the same disclosure.
EXCHANGE_MATCH_MINUTES = 10

# --- Media (Google News RSS) -----------------------------------------------------
# Historical items carry only a date (time is a placeholder), so media lead is measured in days.
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
MEDIA_LOOKBACK_DAYS = 7     # calendar days before the filing searched for matching coverage
MEDIA_MIN_KEYWORDS = 2      # title must share this many distinctive headline keywords
MEDIA_MAX_DOC_FREQ = 0.02   # words in more of a company's headlines than this are generic, not evidence
MEDIA_PAUSE_SEC = 1.0

# --- SEBI enforcement orders (drill-down cross-check) ---------------------------------
SEBI_ORDERS_LISTING_URL = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=2&s=0&smid=0&ssid=9"
SEBI_ORDERS_AJAX_URL = "https://www.sebi.gov.in/sebiweb/ajax/home/getnewslistinfo.jsp"
SEBI_MAX_PAGES = 8          # 25 orders per page
# Titles that point at leaked information rather than other enforcement (registration, fees, appeals).
SEBI_RELEVANT_PATTERN = r"insider|unpublished price sensitive|upsi|front.?running"

# --- BSE endpoints ------------------------------------------------------------
BSE_ANNOUNCEMENTS_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
BSE_ATTACHMENT_URL = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{name}"
# SEBI PIT system-driven disclosures (insider trades); found in the BSE site's JS bundle (Getquote "SDD PIT" tab).
BSE_PIT_URL = "https://api.bseindia.com/BseIndiaAPI/api/sddpit/w"
BSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}
BSE_PAGE_SIZE = 50
BSE_MAX_DAYS_PER_REQUEST = 365  # longer ranges return no rows at all (no error), so requests are chunked
BSE_REQUEST_PAUSE_SEC = 0.5

# --- Market session (IST) -----------------------------------------------------
MARKET_OPEN = time(9, 15, 0)
MARKET_CLOSE = time(15, 30, 0)  # 15:30 IST market-close rule cutoff

# --- Event-study windows (trading days relative to Day 0) ---------------------
PRE_WINDOW = (-5, -1)      # leakage / pre-event drift window
POST_WINDOW = (1, 5)       # post-announcement drift window
BASELINE_DAYS = 30         # trailing baseline, ends just before PRE_WINDOW starts
SIGNIFICANCE_Z = 1.96      # |z| threshold for flagging abnormal moves
CAR_PATH_WINDOW = (-10, 5) # per-day ARs stored for the report's average cumulative-AR path
PRICE_BREAK_THRESHOLD = 0.20  # |daily return| treated as an unadjusted split/demerger
LOOKBACK_BUFFER_DAYS = 70  # calendar days of history fetched before the first event

# Pre-announced by a board-meeting notice, so the market knows the date in advance; leakage
# evidence is far stronger for the unscheduled types.
SCHEDULED_TYPES = {"Financial Results", "Dividend", "Board Outcome"}
# Run-up ratio pre_car / (pre_car + day0_ar) is unstable when the total move is tiny.
RUNUP_MIN_MOVE = 0.01

# Placebo: random non-event days per stock, measured exactly like events (empirical null).
PLACEBO_PER_STOCK = 20
PLACEBO_MIN_GAP = 6        # sessions to any event / other placebo day: keeps Day 0s out of [t-5, t+5]
PLACEBO_SEED = 42
PLACEBO_BOOTSTRAP = 2000

# Optional per-event signals tested (mean, t-test) alongside price drift: column -> report label.
EXTRA_SIGNAL_COLUMNS = {
    "fut_oi_chg_pre": "Fut OI chg",
    "opt_vol_z": "Option vol z",
    "opt_oi_chg_pre": "Option OI chg",
    "signed_oi_tilt": "Signed call-put OI tilt",
    "signed_call_skew_z": "Signed call vol skew z",
    "news_side_otm_vol_z": "OTM news-side vol z",
    "wrong_side_otm_vol_z": "OTM wrong-side vol z",
    "deal_any": "Block/bulk deal share",
    "deal_value_cr": "Deal value Rs cr",
    "insider_any": "Insider trade share",
    "insider_net_signed_cr": "Insider net, news-signed Rs cr",
    "sector_signed_pre_car": "Sector-adj signed pre CAR",
    "signed_intra_ar_z": "Signed intraday pre-AR z",
    "intra_vol_z": "Intraday pre-vol z",
}
DEALS_WINDOW = (-30, -1)   # sessions before Day 0 scanned for bulk/block deals
# Options at least this far out of the money (strike vs that day's underlying) count as OTM. Informed
# traders favour cheap short-dated OTM contracts (Augustin, Brenner & Subrahmanyam), so OTM flow is
# measured on each stock's front (nearest) expiry only.
OTM_MIN_MONEYNESS = 0.02
INSIDER_WINDOW = (-30, -1)  # sessions before Day 0 scanned for reported insider (PIT) trades, by trade date

# --- Public catalysts that are not company filings (controls) --------------------
# A pre-window day this big for the market, or for the sector relative to the market, is public news that
# can move the stock without anyone knowing the company's own news.
MACRO_SHOCK_RET = 0.02
SECTOR_SHOCK_RET = 0.02
# Sector benchmark per NSE industry (from the Nifty 50 list); symbols below override it. The stock is part of
# its own sector index, which biases sector-adjusted returns slightly towards zero for the heaviest weights.
SECTOR_INDEX = {
    "Financial Services": "NSE_INDEX|Nifty Fin Service",
    "Healthcare": "NSE_INDEX|NIFTY HEALTHCARE",
    "Automobile and Auto Components": "NSE_INDEX|Nifty Auto",
    "Metals & Mining": "NSE_INDEX|Nifty Metal",
    "Information Technology": "NSE_INDEX|Nifty IT",
    "Fast Moving Consumer Goods": "NSE_INDEX|Nifty FMCG",
    "Oil Gas & Consumable Fuels": "NSE_INDEX|NIFTY OIL AND GAS",
    "Services": "NSE_INDEX|Nifty Trans Logis",
    "Consumer Durables": "NSE_INDEX|NIFTY CONSR DURBL",
    "Consumer Services": "NSE_INDEX|Nifty Consumption",
    "Construction Materials": "NSE_INDEX|Nifty Cement",
    "Power": "NSE_INDEX|Nifty Energy",
    "Capital Goods": "NSE_INDEX|Nifty Ind Defence",
    "Construction": "NSE_INDEX|Nifty Infra",
}
SECTOR_INDEX_OVERRIDES = {s: "NSE_INDEX|Nifty Bank" for s in
                          ("HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK", "SBIN", "INDUSINDBK")}
# Broker research in the press before a filing (with `media`): rating changes and target revisions.
BROKER_QUERY = '"{company}" (upgrade OR downgrade OR "target price" OR "buy rating" OR "sell rating")'
# A rating *change* or target *revision* (not "check target price" explainers or software "upgrades").
BROKER_PATTERN = (r"\b(?:upgrade[sd]?|downgrade[sd]?)\b.{0,60}\b(?:rating|buy|sell|hold|overweight|underweight|"
                  r"neutral|outperform|underperform|add|reduce)\b|\btarget(?: price)?\b.{0,20}\b(?:hike[sd]?|raise[sd]?|"
                  r"cuts?|lower(?:s|ed)?|lifts?|trims?|slashe[sd])\b|\b(?:hike[sd]?|raise[sd]?|cuts?|lower(?:s|ed)?|"
                  r"lifts?|trims?|slashe[sd])\b.{0,30}\btarget\b|\binitiates? coverage\b")

# Intraday test (filings released during market hours): the minutes just before the filing vs the same
# clock window on prior sessions.
INTRADAY_PRE_MINUTES = 60
INTRADAY_MIN_MINUTES = 15  # skip filings so early in the session that the window is shorter than this
INTRADAY_BASELINE_DAYS = 20

# --- Sample universe ------------------------------------------------------------
# NSE symbol -> BSE scrip code. Overrides the ISIN lookup in the Upstox master (BSE_EQ rows).
SAMPLE_STOCKS = {
    "RELIANCE": 500325,
    "TMPV": 500570,  # Tata Motors (renamed Tata Motors Passenger Vehicles after the Oct-2025 demerger)
}
