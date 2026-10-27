"""MCX Bhavcopy Client.

Fetches Bhavcopy market data from MCX with verification token extraction,
retry backoff, politeness delay, and raw JSON disk caching.
"""

from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, Optional, Tuple
import requests

from config import BHAVCOPY_API_URL, BHAVCOPY_PAGE_URL, CACHE_DIR, DEFAULT_HEADERS

logger = logging.getLogger(__name__)

# Module-level session and token cache to avoid re-fetching HTML page repeatedly
_global_session: Optional[requests.Session] = None
_cached_token: Optional[str] = None


def get_session() -> requests.Session:
    """Return a shared requests.Session instance."""
    global _global_session
    if _global_session is None:
        _global_session = requests.Session()
        _global_session.headers.update(DEFAULT_HEADERS)
    return _global_session


def parse_and_format_date(date_str: str) -> Tuple[str, str]:
    """Parse date string and return tuple: (mcx_request_date, iso_cache_date).

    Supports:
        - "DD/MM/YYYY" -> ("DD/MM/YYYY", "YYYY-MM-DD")
        - "YYYY-MM-DD" -> ("DD/MM/YYYY", "YYYY-MM-DD")
    """
    clean_date = date_str.strip()
    dt: Optional[datetime] = None

    if "/" in clean_date:
        parts = clean_date.split("/")
        if len(parts) == 3:
            # If formatted as DD/MM/YYYY
            try:
                dt = datetime.strptime(clean_date, "%d/%m/%Y")
            except ValueError:
                # Fallback to MM/DD/YYYY if invalid day
                dt = datetime.strptime(clean_date, "%m/%d/%Y")
    elif "-" in clean_date:
        dt = datetime.strptime(clean_date, "%Y-%m-%d")

    if dt is None:
        raise ValueError(
            f"Unsupported date format for '{date_str}'. Expected 'DD/MM/YYYY' or 'YYYY-MM-DD'."
        )

    mcx_date_str = dt.strftime("%d/%m/%Y")
    iso_date_str = dt.strftime("%Y-%m-%d")
    return mcx_date_str, iso_date_str


def extract_verification_token(html_text: str) -> str:
    """Extract __RequestVerificationToken value from MCX Bhavcopy HTML page."""
    # Pattern 1: name="__RequestVerificationToken" ... value="TOKEN"
    match = re.search(
        r'name=["\']__RequestVerificationToken["\'][^>]*value=["\']([^"\']+)["\']',
        html_text,
        re.IGNORECASE,
    )
    if not match:
        # Pattern 2: value="TOKEN" ... name="__RequestVerificationToken"
        match = re.search(
            r'value=["\']([^"\']+)["\'][^>]*name=["\']__RequestVerificationToken["\']',
            html_text,
            re.IGNORECASE,
        )

    if not match:
        raise ValueError(
            "Could not extract __RequestVerificationToken from MCX Bhavcopy HTML page."
        )

    token = match.group(1).strip()
    if not token:
        raise ValueError("Found empty __RequestVerificationToken in MCX Bhavcopy HTML.")
    return token


def get_verification_token(
    session: requests.Session,
    force_refresh: bool = False,
) -> str:
    """Retrieve or re-use cached __RequestVerificationToken."""
    global _cached_token
    if _cached_token and not force_refresh:
        return _cached_token

    logger.info("Fetching MCX Bhavcopy landing page to retrieve verification token...")
    resp = session.get(BHAVCOPY_PAGE_URL, timeout=15)
    resp.raise_for_status()

    token = extract_verification_token(resp.text)
    _cached_token = token
    logger.info("Successfully extracted verification token.")
    return token


def fetch_bhavcopy(
    date_str: str,
    session: Optional[requests.Session] = None,
    force_download: bool = False,
    cache_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Fetch MCX Bhavcopy for a given date.

    Args:
        date_str: Date string in "DD/MM/YYYY" or "YYYY-MM-DD" format.
        session: Optional custom requests.Session. Defaults to global shared session.
        force_download: If True, bypasses local file cache.
        cache_dir: Target cache directory. Defaults to config.CACHE_DIR.

    Returns:
        Dict parsed from MCX API JSON response.

    Features:
        - Caches raw JSON to data/raw/YYYY-MM-DD.json
        - Retries up to 3 attempts with exponential backoff (1s, 2s, 4s)
        - Imposes a 0.5s politeness delay between network requests
        - Reuses token across multiple calls to avoid re-fetching HTML page
    """
    mcx_date_str, iso_date_str = parse_and_format_date(date_str)
    target_cache_dir = cache_dir or CACHE_DIR
    target_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = target_cache_dir / f"{iso_date_str}.json"

    # 1. Return from disk cache if present and not force_download
    if cache_file.exists() and not force_download:
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info("Loaded Bhavcopy for %s from local cache %s", iso_date_str, cache_file)
            return data
        except Exception as exc:
            logger.warning(
                "Failed to read existing cache file %s: %s. Re-fetching from API.",
                cache_file,
                exc,
            )

    sess = session or get_session()

    # 2. Politeness delay (0.5s) between requests
    time.sleep(0.5)

    max_attempts = 3
    backoff_delay = 1.0
    last_error: Optional[Exception] = None

    # Check for environment variables MCX_TOKEN and MCX_COOKIE
    env_token = os.environ.get("MCX_TOKEN", "").strip()
    env_cookie = os.environ.get("MCX_COOKIE", "").strip()

    for attempt in range(1, max_attempts + 1):
        try:
            # Use environment token if provided, otherwise extract from landing page
            token = env_token or get_verification_token(sess, force_refresh=(attempt > 1))

            headers = {
                "__requestverificationtoken": token,
                "X-Requested-With": "XMLHttpRequest",
            }
            if env_cookie:
                headers["Cookie"] = env_cookie

            payload = {"Date": mcx_date_str}

            response = sess.post(
                BHAVCOPY_API_URL,
                json=payload,
                headers=headers,
                timeout=20,
            )

            # Check HTTP status
            response.raise_for_status()

            raw_data = response.json()
            if not isinstance(raw_data, (dict, list)):
                raise ValueError(
                    f"Unexpected response format from MCX API: {type(raw_data)}"
                )

            # If response is a list, normalize into dict format {"Data": raw_data}
            result_dict: Dict[str, Any]
            if isinstance(raw_data, list):
                result_dict = {"Data": raw_data}
            else:
                result_dict = raw_data

            # 3. Write to disk cache
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(result_dict, f, indent=2, ensure_ascii=False)
            logger.info("Saved raw Bhavcopy for %s to %s", iso_date_str, cache_file)

            return result_dict

        except Exception as err:
            last_error = err
            # Force token refresh on 401, 403, or 419 (expired session or anti-forgery token)
            if isinstance(err, requests.HTTPError) and err.response is not None:
                if err.response.status_code in (401, 403, 419):
                    global _cached_token
                    _cached_token = None
                    logger.info(
                        "Received HTTP %d: cleared cached token to refresh session on next attempt.",
                        err.response.status_code,
                    )

            logger.warning(
                "Attempt %d/%d to fetch Bhavcopy for %s failed: %s",
                attempt,
                max_attempts,
                mcx_date_str,
                err,
            )
            if attempt < max_attempts:
                time.sleep(backoff_delay)
                backoff_delay *= 2.0

    raise RuntimeError(
        f"Failed to fetch Bhavcopy for {date_str} ({mcx_date_str}) after {max_attempts} attempts: {last_error}"
    )
