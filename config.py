"""Contract facts, cost rates and paths for Aureus Lens.

Values are either verified against the bhavcopy files in data/raw/ or listed
in UNVERIFIED_ITEMS. Anything in UNVERIFIED_ITEMS is a placeholder and must
not be presented as fact.
"""

from pathlib import Path
from typing import Any, Dict, Set

PROJECT_ROOT: Path = Path(__file__).resolve().parent
DATA_DIR: Path = PROJECT_ROOT / "data"
RAW_DIR: Path = DATA_DIR / "raw"  # manually downloaded CSVs, not committed

TARGET_SYMBOLS: Set[str] = {"GOLDM", "GOLDTEN", "GOLDGUINEA", "GOLDPETAL"}

# Verified: lot_size_grams and quote_grams reproduce Value(Lacs) to within
# 0.5% for every active gold future on 9 Oct 2026 (tests/test_csv_loader.py).
# purity, tick_size and tender_period_days are UNVERIFIED; see below.
CONTRACT_SPECS: Dict[str, Dict[str, Any]] = {
    "GOLDM": {
        "lot_size_grams": 100,
        "quote_grams": 10,
        "purity": 995,
        "tick_size": 1.0,
        "expiry_rule": "5th of the month, or the preceding working day",
        "tender_period_days": 3,
    },
    "GOLDTEN": {
        "lot_size_grams": 10,
        "quote_grams": 10,
        "purity": 999,
        "tick_size": 1.0,
        "expiry_rule": "last calendar day of the month, or the preceding working day",
        "tender_period_days": 3,
    },
    "GOLDGUINEA": {
        "lot_size_grams": 8,
        "quote_grams": 8,
        "purity": 999,
        "tick_size": 1.0,
        "expiry_rule": "last calendar day of the month, or the preceding working day",
        "tender_period_days": 3,
    },
    "GOLDPETAL": {
        "lot_size_grams": 1,
        "quote_grams": 1,
        "purity": 999,
        "tick_size": 1.0,
        "expiry_rule": "last calendar day of the month, or the preceding working day",
        "tender_period_days": 5,  # conservative placeholder, MCX may use 3
    },
}

# Expiries this many calendar days away or closer are excluded from carry.
STAGGERED_DELIVERY_DAYS: int = 3

# Cost rates. All UNVERIFIED until confirmed from MCX circulars. They are
# set so that Rs 1,000,000 turnover costs 69.56 (buy) and 149.56 (sell).
BROKERAGE_RATE_PCT: float = 0.0003
BROKERAGE_MAX_PER_ORDER: float = 20.0  # rupees
EXCHANGE_TRANSACTION_CHARGE_PCT: float = 0.000021
CTT_SELL_PCT: float = 0.0001
GST_PCT: float = 0.18  # on brokerage + exchange charge + SEBI fee
SEBI_TURNOVER_FEE_PCT: float = 10.0 / 10_000_000.0  # Rs 10 per crore
STAMP_DUTY_BUY_PCT: float = 0.00002

UNVERIFIED_ITEMS: Dict[str, str] = {
    "MCX_POST_21JAN2026_VALUE": (
        "An MCX post gave Rs 5,563 crore for 21 Jan 2026. The bhavcopy file sums "
        "to Rs 8,239.66 crore for GOLDTEN, GOLDGUINEA and GOLDPETAL. The post "
        "figure is not used anywhere."
    ),
    "GOLDPETAL_TENDER_DAYS": (
        "GOLDPETAL tender period may be 3 or 5 days. 5 is used as a "
        "conservative placeholder."
    ),
    "GOLDGUINEA_TENDER_DAYS": (
        "GOLDGUINEA tender period of 3 days comes from a secondary summary of "
        "MCX circular MCX/TRD/456/2025. The circular PDF has not been read."
    ),
    "TENDER_DAYS_OTHERS": (
        "Tender periods of 3 days for GOLDM and GOLDTEN, and the 3-day carry "
        "buffer, are not confirmed from an MCX circular."
    ),
    "HOLIDAYS": (
        "No exchange holiday or festival dates are used. Expiry dates come "
        "from the files, not from a holiday calendar."
    ),
    "COST_RATES": (
        "Exchange charge, CTT, stamp duty, SEBI fee, GST and brokerage rates "
        "are not confirmed from MCX circulars or a broker schedule."
    ),
    "TICK_SIZES": (
        "Tick sizes are set to 1.0 for all four contracts. GOLDTEN, GOLDGUINEA "
        "and GOLDPETAL are explicitly unconfirmed; GOLDM has no source either."
    ),
    "PURITY": (
        "GOLDM purity 995 and 999 for the others are not confirmed from the "
        "contract specification. The 999/995 factor matches the hand-checked "
        "normalization value only."
    ),
}
