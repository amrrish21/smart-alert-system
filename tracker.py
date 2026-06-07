"""
tracker.py — Main Orchestration Script
Smart Automated Notification & Alerts System

Entry point for both local runs and GitHub Actions scheduled jobs.

Usage
-----
    python tracker.py               # single check (default)
    python tracker.py --loop        # poll continuously (uses POLL_INTERVAL_SECONDS)
    python tracker.py --dry-run     # scrape & evaluate but do NOT send any alerts

Environment variables (required)
---------------------------------
    TARGET_URL          — Product page to monitor
    PRICE_THRESHOLD     — Float; alert when price drops at or below this value
    ALERT_ON_STOCK      — "true" / "false"; also alert when item comes back in stock

Environment variables (optional)
---------------------------------
    POLL_INTERVAL_SECONDS   — Seconds between checks in --loop mode (default 3600)
    STATE_FILE              — Path to JSON file tracking previous state (default .state.json)
    LOG_LEVEL               — DEBUG / INFO / WARNING / ERROR (default INFO)

Notification credentials are read by notifier.py — see that module for details.
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from notifier import AlertPayload, Notifier, NotificationError
from scraper import ProductSnapshot, ScraperError, fetch_product_snapshot

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

load_dotenv()  # loads .env when running locally; a no-op in CI

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("tracker")


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        logger.critical("Required environment variable %r is not set.", name)
        sys.exit(1)
    return value


def _optional_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# ---------------------------------------------------------------------------
# CSS Selector profiles
# ---------------------------------------------------------------------------

# Add profiles for other retailers here as needed.
# Each profile maps to the CSS selectors used by that site.
SELECTOR_PROFILES: dict[str, dict[str, str]] = {
    "amazon": {
        "price_selector": "span.a-price span.a-offscreen",
        "title_selector": "span#productTitle",
        "stock_selector": "#availability span",
        "in_stock_text": "in stock",
    },
    "bestbuy": {
        "price_selector": "div.priceView-customer-price span[aria-hidden]",
        "title_selector": "div.sku-title h1",
        "stock_selector": "button.add-to-cart-button",
        "in_stock_text": "add to cart",
    },
    # Default: generic fallback — works on the bundled mock page
    "generic": {
        "price_selector": "[data-price], .price, #price, span.price",
        "title_selector": "h1, [data-title], .product-title",
        "stock_selector": "[data-stock], .stock-status, #availability",
        "in_stock_text": "in stock",
    },
}


def _detect_profile(url: str) -> dict[str, str]:
    """Auto-select a selector profile from the target URL."""
    url_lower = url.lower()
    if "amazon." in url_lower:
        profile = "amazon"
    elif "bestbuy." in url_lower:
        profile = "bestbuy"
    else:
        profile = "generic"
    logger.info("Using selector profile: %r", profile)
    return SELECTOR_PROFILES[profile]


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

class StateManager:
    """
    Persists the last-known price and stock status to a local JSON file
    so the tracker can detect *changes* across separate runs.
    """

    def __init__(self, path: str = ".state.json") -> None:
        self._path = Path(path)

    def load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not read state file: %s — starting fresh.", exc)
        return {}

    def save(self, state: dict) -> None:
        try:
            self._path.write_text(json.dumps(state, indent=2))
        except OSError as exc:
            logger.warning("Could not write state file: %s", exc)


# ---------------------------------------------------------------------------
# Alert evaluation
# ---------------------------------------------------------------------------

def _should_alert(
    snapshot: ProductSnapshot,
    previous: dict,
    *,
    price_threshold: Optional[float],
    alert_on_stock: bool,
) -> tuple[bool, str]:
    """
    Evaluate whether the current snapshot warrants an alert.

    Returns
    -------
    (trigger, reason)
        ``trigger`` — True when an alert should fire.
        ``reason``  — Human-readable sentence to include in the notification.
    """
    reasons: list[str] = []

    # --- Price drop alert ---------------------------------------------------
    if price_threshold is not None and snapshot.price is not None:
        prev_price: Optional[float] = previous.get("price")
        if snapshot.price <= price_threshold:
            if prev_price is None or snapshot.price < prev_price:
                reasons.append(
                    f"Price dropped to ${snapshot.price:.2f} "
                    f"(threshold: ${price_threshold:.2f})."
                )

    # --- Back-in-stock alert ------------------------------------------------
    if alert_on_stock and snapshot.in_stock:
        was_in_stock: Optional[bool] = previous.get("in_stock")
        if was_in_stock is False:
            reasons.append("Item is back in stock!")

    trigger = bool(reasons)
    reason = " ".join(reasons) if reasons else "Monitoring — no threshold crossed yet."
    return trigger, reason


# ---------------------------------------------------------------------------
# Core run function
# ---------------------------------------------------------------------------

def run_check(*, dry_run: bool = False) -> None:
    """Perform one full scrape → evaluate → notify cycle."""

    # --- Load config --------------------------------------------------------
    target_url = _require_env("TARGET_URL")

    raw_threshold = _optional_env("PRICE_THRESHOLD")
    price_threshold: Optional[float] = None
    if raw_threshold:
        try:
            price_threshold = float(raw_threshold)
        except ValueError:
            logger.error(
                "PRICE_THRESHOLD=%r is not a valid float — price alerting disabled.",
                raw_threshold,
            )

    alert_on_stock = _optional_env("ALERT_ON_STOCK", "false").lower() == "true"
    state_file = _optional_env("STATE_FILE", ".state.json")

    selectors = _detect_profile(target_url)
    state_mgr = StateManager(state_file)
    previous_state = state_mgr.load()

    # --- Scrape -------------------------------------------------------------
    logger.info("Starting scrape: %s", target_url)
    try:
        snapshot: ProductSnapshot = fetch_product_snapshot(
            target_url,
            **selectors,
        )
    except ScraperError as exc:
        logger.error("Scrape failed: %s", exc)
        return   # Do not clear previous state; try again next run

    # --- Evaluate -----------------------------------------------------------
    trigger, reason = _should_alert(
        snapshot,
        previous_state,
        price_threshold=price_threshold,
        alert_on_stock=alert_on_stock,
    )
    logger.info("Alert trigger: %s — %s", trigger, reason)

    # --- Persist new state --------------------------------------------------
    new_state = {
        "price": snapshot.price,
        "in_stock": snapshot.in_stock,
        "last_checked": snapshot.timestamp,
        "title": snapshot.title,
    }
    state_mgr.save(new_state)

    # --- Notify -------------------------------------------------------------
    if trigger:
        payload = AlertPayload(
            product_title=snapshot.title or "Unknown Product",
            product_url=snapshot.url,
            current_price=snapshot.price,
            threshold_price=price_threshold,
            in_stock=snapshot.in_stock,
            trigger_reason=reason,
        )

        if dry_run:
            logger.info("[DRY-RUN] Would send alert:\n%s", payload)
            return

        notifier = Notifier()
        results = notifier.broadcast(payload)

        successes = [ch for ch, ok in results.items() if ok]
        failures  = [ch for ch, ok in results.items() if not ok]

        if successes:
            logger.info("Alert delivered via: %s", ", ".join(successes))
        if failures:
            logger.error("Alert failed on: %s", ", ".join(failures))

        # Non-zero exit when ALL channels fail — useful for CI failure detection
        if results and not successes:
            sys.exit(2)

    else:
        logger.info("No alert criteria met — nothing to send.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smart Automated Notification & Alerts System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously, polling every POLL_INTERVAL_SECONDS (default 3600).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and evaluate but do NOT send any notifications.",
    )
    args = parser.parse_args()

    if args.loop:
        interval = int(_optional_env("POLL_INTERVAL_SECONDS", "3600"))
        logger.info("Running in loop mode — interval: %ds", interval)
        while True:
            run_check(dry_run=args.dry_run)
            logger.info("Next check in %ds. Sleeping…", interval)
            time.sleep(interval)
    else:
        run_check(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
