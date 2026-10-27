"""Aureus Lens - Central Configuration.

Contract-Native Relative-Value Engine for MCX Gold Futures.
Hack in Hills '26 - Problem Statement 03 (Commodity Derivatives Intelligence)
"""

from pathlib import Path
from typing import Any, Dict, Set

# --- Project Paths ---
PROJECT_ROOT: Path = Path(__file__).resolve().parent
DATA_DIR: Path = PROJECT_ROOT / "data"
CACHE_DIR: Path = DATA_DIR / "raw"

# --- API Endpoints ---
BHAVCOPY_PAGE_URL: str = "https://www.mcxindia.com/market-data/bhavcopy"
BHAVCOPY_API_URL: str = "https://www.mcxindia.com/market-data/bhavcopy/GetDateWiseBhavCopy"

# --- HTTP Headers ---
DEFAULT_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": BHAVCOPY_PAGE_URL,
    "Origin": "https://www.mcxindia.com",
}

# --- Contract Symbols ---
# Confirmed target contracts for relative-value analysis.
# Note: "GOLD" (1kg) is deliberately EXCLUDED unless explicitly verified.
TARGET_SYMBOLS: Set[str] = {"GOLDM", "GOLDTEN", "GOLDGUINEA", "GOLDPETAL"}

# --- Contract Lifecycle & Specifications (MCX Circulars) ---
CONTRACT_SPECS: Dict[str, Dict[str, Any]] = {
    "GOLDM": {
        "description": "Gold Mini",
        "lot_size_grams": 100,
        "purity": 995,
        "price_quote_unit": "10 g",
        "tick_size": 1.0,  # Re. 1 / 10g
        "expiry_rule": "5th of expiry month (preceding working day if holiday)",
        "tender_period_days": 3,  # Last 3 trading days including expiry day
    },
    "GOLDTEN": {
        "description": "Gold Ten",
        "lot_size_grams": 10,
        "purity": 999,
        "price_quote_unit": "10 g",
        "tick_size": 1.0,
        "expiry_rule": "Last calendar day of expiry month",
        "tender_period_days": 3,  # Last 3 trading days including expiry day
    },
    "GOLDGUINEA": {
        "description": "Gold Guinea",
        "lot_size_grams": 8,
        "purity": 999,
        "price_quote_unit": "8 g",
        "tick_size": 1.0,
        "expiry_rule": "Last calendar day of expiry month",
        "tender_period_days": 3,  # Verified 3-day tender window
    },
    "GOLDPETAL": {
        "description": "Gold Petal",
        "lot_size_grams": 1,
        "purity": 999,
        "price_quote_unit": "1 g",
        "tick_size": 1.0,
        "expiry_rule": "Last calendar day of expiry month",
        "tender_period_days": 5,  # Conservative unknown value (5 days) until confirmed by MCX circular
        "verified": False,
    },
}

# Common tender period window (staggered delivery tender period)
STAGGERED_DELIVERY_DAYS: int = 3

# --- Transaction Cost Model (MCX Circulars & Statutory) ---
# Standard discount broker commodity rate: min(0.03% of turnover, Rs 20 per executed order)
BROKERAGE_RATE_PCT: float = 0.0003  # 0.03%
BROKERAGE_MAX_PER_ORDER: float = 20.0  # ₹20 cap

# Exchange transaction charge: 0.0021% of turnover
EXCHANGE_TRANSACTION_CHARGE_PCT: float = 0.000021

# Commodities Transaction Tax (CTT): 0.01% on sell side (non-agri)
CTT_SELL_PCT: float = 0.0001

# Goods and Services Tax (GST): 18% on (brokerage + exchange charges + SEBI fee)
GST_PCT: float = 0.18

# SEBI Turnover Fee: ₹10 per crore (10 / 10,000,000 = 1e-6)
SEBI_TURNOVER_FEE_PCT: float = 10.0 / 10_000_000.0

# Stamp Duty: 0.002% on buy side
STAMP_DUTY_BUY_PCT: float = 0.00002

# --- Unverified Facts Registry (Displayed prominently on Dashboard) ---
UNVERIFIED_ITEMS: Dict[str, str] = {
    "GOLDPETAL_TENDER_DAYS": (
        "GOLDPETAL tender period is set to conservative default of 5 days pending "
        "direct MCX physical delivery circular confirmation."
    ),
}

