"""
scraper.py — Web Scraper Module
Smart Automated Notification & Alerts System
"""

import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# User-Agent pool — rotated on every request to reduce bot-detection risk
# ---------------------------------------------------------------------------
_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
]


@dataclass
class ProductSnapshot:
    """Immutable snapshot of a product's scraped state."""

    url: str
    title: Optional[str]
    price: Optional[float]          # None when price is unavailable
    in_stock: bool
    raw_price_text: Optional[str]   # Kept for debugging / display
    timestamp: float                # Unix epoch


class ScraperError(Exception):
    """Raised when the scraper cannot retrieve or parse the page."""


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def _pick_headers() -> dict[str, str]:
    """Return browser-like headers with a randomly chosen User-Agent."""
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    }


def _parse_price(text: str) -> Optional[float]:
    """
    Extract the first decimal number from a price string.

    Examples
    --------
    "$1,299.99"  → 1299.99
    "Price: ₹89,999"  → 89999.0
    "Out of stock"   → None
    """
    cleaned = re.sub(r"[^\d.,]", "", text)          # strip currency symbols
    cleaned = cleaned.replace(",", "")              # remove thousands separator
    match = re.search(r"\d+(\.\d+)?", cleaned)
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None


def fetch_product_snapshot(
    url: str,
    *,
    price_selector: str,
    title_selector: str,
    stock_selector: str,
    in_stock_text: str = "in stock",
    timeout: int = 15,
    retries: int = 3,
    retry_delay: float = 2.0,
) -> ProductSnapshot:
    """
    Fetch *url* and return a :class:`ProductSnapshot`.

    Parameters
    ----------
    url:
        Target product page URL.
    price_selector:
        CSS selector for the price element (e.g. ``"span.a-price-whole"``).
    title_selector:
        CSS selector for the product title.
    stock_selector:
        CSS selector for the availability / stock element.
    in_stock_text:
        Substring (case-insensitive) that indicates the item is available.
    timeout:
        HTTP request timeout in seconds.
    retries:
        Number of retry attempts on transient network errors.
    retry_delay:
        Base delay (seconds) between retries — doubled on each attempt.

    Raises
    ------
    ScraperError
        On unrecoverable HTTP errors or HTML parsing failures.
    """
    last_exc: Optional[Exception] = None

    for attempt in range(1, retries + 1):
        try:
            logger.info("Fetching %s (attempt %d/%d)", url, attempt, retries)
            response = requests.get(url, headers=_pick_headers(), timeout=timeout)
            response.raise_for_status()
            break
        except requests.exceptions.HTTPError as exc:
            # 4xx errors won't recover on retry
            if exc.response is not None and exc.response.status_code < 500:
                raise ScraperError(
                    f"HTTP {exc.response.status_code} fetching {url}: {exc}"
                ) from exc
            last_exc = exc
        except requests.exceptions.ConnectionError as exc:
            logger.warning("Connection error on attempt %d: %s", attempt, exc)
            last_exc = exc
        except requests.exceptions.Timeout as exc:
            logger.warning("Timeout on attempt %d after %ds", attempt, timeout)
            last_exc = exc
        except requests.exceptions.RequestException as exc:
            last_exc = exc

        if attempt < retries:
            sleep_for = retry_delay * (2 ** (attempt - 1))
            logger.info("Retrying in %.1f seconds…", sleep_for)
            time.sleep(sleep_for)
    else:
        raise ScraperError(
            f"Failed to fetch {url} after {retries} attempts. "
            f"Last error: {last_exc}"
        ) from last_exc

    # --- Parse HTML --------------------------------------------------------
    try:
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as exc:
        raise ScraperError(f"HTML parsing failed: {exc}") from exc

    # Title
    title: Optional[str] = None
    title_el = soup.select_one(title_selector)
    if title_el:
        title = title_el.get_text(strip=True)
    else:
        logger.warning("Title element not found with selector: %s", title_selector)

    # Price
    raw_price_text: Optional[str] = None
    price: Optional[float] = None
    price_el = soup.select_one(price_selector)
    if price_el:
        raw_price_text = price_el.get_text(strip=True)
        price = _parse_price(raw_price_text)
        if price is None:
            logger.warning(
                "Could not parse a numeric price from: %r", raw_price_text
            )
    else:
        logger.warning("Price element not found with selector: %s", price_selector)

    # Stock
    in_stock = False
    stock_el = soup.select_one(stock_selector)
    if stock_el:
        stock_text = stock_el.get_text(strip=True).lower()
        in_stock = in_stock_text.lower() in stock_text
    else:
        logger.warning("Stock element not found with selector: %s", stock_selector)

    snapshot = ProductSnapshot(
        url=url,
        title=title,
        price=price,
        in_stock=in_stock,
        raw_price_text=raw_price_text,
        timestamp=time.time(),
    )
    logger.info(
        "Snapshot — title=%r  price=%s  in_stock=%s",
        snapshot.title,
        snapshot.price,
        snapshot.in_stock,
    )
    return snapshot
