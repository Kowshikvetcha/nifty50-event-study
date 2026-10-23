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
    "Referer": "https://www.nseindia.com/",
}
NSE_REQUEST_PAUSE_SEC = 0.3

# --- BSE endpoints ------------------------------------------------------------
BSE_ANNOUNCEMENTS_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
BSE_ATTACHMENT_URL = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{name}"
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
BSE_REQUEST_PAUSE_SEC = 0.5

# --- Market session (IST) -----------------------------------------------------
MARKET_OPEN = time(9, 15, 0)
MARKET_CLOSE = time(15, 30, 0)  # 15:30 IST market-close rule cutoff

# --- Event-study windows (trading days relative to Day 0) ---------------------
PRE_WINDOW = (-5, -1)      # leakage / pre-event drift window
POST_WINDOW = (1, 5)       # post-announcement drift window
BASELINE_DAYS = 30         # trailing baseline, ends just before PRE_WINDOW starts
SIGNIFICANCE_Z = 1.96      # |z| threshold for flagging abnormal moves
PRICE_BREAK_THRESHOLD = 0.20  # |daily return| treated as an unadjusted split/demerger
LOOKBACK_BUFFER_DAYS = 70  # calendar days of history fetched before the first event

# --- Sample universe ------------------------------------------------------------
# NSE symbol -> BSE scrip code
SAMPLE_STOCKS = {
    "RELIANCE": 500325,
    "TMPV": 500570,  # Tata Motors (renamed Tata Motors Passenger Vehicles after the Oct-2025 demerger)
}
